"""The contribution-suitability engine.

Deterministic and fully unit-testable, mirroring the design of
:class:`oss_agent.scoring.engine.ScoringEngine`. It consumes the artifacts the
workflow already produces (issue analysis, repository report, and the raw issue /
repository metadata) and returns a :class:`SuitabilityAssessment` with a
human-readable category and reasoning. Hard blockers (closed issue, archived repo,
an existing PR, an assignee) force ``BLOCKED`` regardless of the weighted score,
so a technically attractive opportunity that would duplicate work is never
recommended.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from oss_agent.config.profile import DeveloperProfile
from oss_agent.domain.enums import SuitabilityCategory
from oss_agent.domain.models import (
    Issue,
    IssueAnalysis,
    Repository,
    RepositoryReport,
    SuitabilityAssessment,
    SuitabilitySignal,
)

# Labels that indicate the issue is a discussion / requires a design decision
# before any code should be written.
_DISCUSSION_LABELS = frozenset(
    {"discussion", "question", "rfc", "proposal", "needs-design", "needs design",
     "design", "help-wanted-discussion", "meta"}
)
# Labels a maintainer uses to signal an open invitation to contribute.
_INVITING_LABELS = frozenset(
    {"good first issue", "good-first-issue", "help wanted", "help-wanted",
     "up-for-grabs", "hacktoberfest", "beginner-friendly"}
)
# Labels that mean "do not implement".
_DISQUALIFYING_LABELS = frozenset({"wontfix", "invalid", "duplicate", "blocked"})

# Phrases in an issue comment that suggest another contributor is already on it.
# Matching any of these caps the recommendation at REVIEW_REQUIRED so a human
# checks for duplicate work before proceeding (prompt-pack §8).
_WORKING_ON_IT = re.compile(
    r"(?i)\b("
    r"working on (this|it|a fix|this one|this issue)"
    r"|i(?:'| a)?m on it\b"
    r"|i(?:'ll| will| am going to| plan to)\s+(take|handle|do|fix|work on|submit|open)"
    r"|i(?:'ve| have)\s+(started|begun|opened a pr)"
    r"|taking (this|it) (on|up)"
    r"|picking (this|it) up"
    r"|assign(ed)?\s+(this\s+)?to me"
    r"|can i (take|work on|be assigned|pick)"
    r"|pr (incoming|is up|coming|opened)"
    r")\b"
)


def _working_claim(comment_bodies: Optional[list[str]]) -> Optional[str]:
    """Return a short snippet if a comment claims someone is already working."""
    for body in comment_bodies or []:
        m = _WORKING_ON_IT.search(body or "")
        if m:
            snippet = m.group(0).strip()
            return snippet[:80]
    return None


@dataclass(frozen=True)
class SuitabilityWeights:
    """Configurable dimension weights (need not sum to 1.0; normalized on use)."""

    issue_clarity: float = 0.15
    maintainer_intent: float = 0.20
    existing_work: float = 0.15
    repository_health: float = 0.10
    guidelines_fit: float = 0.10
    scope_appropriateness: float = 0.10
    technical_confidence: float = 0.10
    skill_match: float = 0.10

    def as_dict(self) -> dict[str, float]:
        return {
            "issue_clarity": self.issue_clarity,
            "maintainer_intent": self.maintainer_intent,
            "existing_work": self.existing_work,
            "repository_health": self.repository_health,
            "guidelines_fit": self.guidelines_fit,
            "scope_appropriateness": self.scope_appropriateness,
            "technical_confidence": self.technical_confidence,
            "skill_match": self.skill_match,
        }

    @classmethod
    def from_mapping(cls, data: dict) -> "SuitabilityWeights":
        """Build weights from a mapping, ignoring unknown keys and keeping
        defaults for any omitted dimension. Negative weights are rejected."""
        known = {f.name for f in fields(cls)}
        kwargs: dict[str, float] = {}
        for key, value in (data or {}).items():
            if key in known:
                w = float(value)
                if w < 0:
                    raise ValueError(f"suitability weight '{key}' must be >= 0")
                kwargs[key] = w
        return cls(**kwargs)


def load_suitability_weights(
    path: Path | str, *, fallback_to_default: bool = True
) -> SuitabilityWeights:
    """Load suitability weights from a YAML file's ``suitability:`` section.

    Reuses the scoring config file so all tunables live together. If the file or
    the section is absent, built-in defaults are used (first-run flows never
    crash); a malformed file raises so misconfiguration is visible.
    """
    import yaml

    p = Path(path)
    if not p.exists():
        if fallback_to_default:
            return SuitabilityWeights()
        raise FileNotFoundError(f"config not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    section = data.get("suitability") or data.get("suitability_weights") or {}
    return SuitabilityWeights.from_mapping(section)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _recency(dt: Optional[datetime], half_life_days: float) -> float:
    if dt is None:
        return 0.5
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
    return _clamp(0.5 ** (age / half_life_days))


class SuitabilityEngine:
    def __init__(self, weights: Optional[SuitabilityWeights] = None) -> None:
        self.weights = weights or SuitabilityWeights()

    # -- dimensions -----------------------------------------------------------
    def _issue_clarity(self, a: IssueAnalysis) -> tuple[float, str]:
        clarity = 1.0 - a.ambiguity_score
        if a.acceptance_criteria:
            clarity = min(1.0, clarity + 0.1)
        if a.expected_behavior:
            clarity = min(1.0, clarity + 0.05)
        return _clamp(clarity), f"ambiguity={a.ambiguity_score:.2f}, criteria={len(a.acceptance_criteria)}"

    def _maintainer_intent(self, issue: Optional[Issue]) -> tuple[float, str]:
        if issue is None:
            return 0.5, "no issue metadata"
        labels = {l.lower() for l in issue.labels}
        score = 0.5
        if labels & _INVITING_LABELS:
            score += 0.35
        if labels & _DISCUSSION_LABELS:
            score -= 0.25
        if labels & _DISQUALIFYING_LABELS:
            score -= 0.4
        if issue.comments >= 1:  # some maintainer engagement
            score += 0.05
        return _clamp(score), f"labels={sorted(labels) or '[]'}"

    def _existing_work(self, a: IssueAnalysis, issue: Optional[Issue]) -> tuple[float, str]:
        # Higher is better (less conflicting work). Blockers are handled
        # separately; this is the graded signal.
        score = 1.0 - a.duplicate_risk
        detail = f"duplicate_risk={a.duplicate_risk:.2f}"
        if issue and issue.linked_pr_numbers:
            score = min(score, 0.1)
            detail += f", linked_prs={issue.linked_pr_numbers}"
        if issue and issue.assignees:
            score = min(score, 0.15)
            detail += f", assignees={issue.assignees}"
        return _clamp(score), detail

    def _repository_health(self, r: RepositoryReport) -> tuple[float, str]:
        signals = [r.has_tests, r.has_ci, r.has_contributing, r.has_readme,
                   not r.repository.archived]
        base = sum(1 for s in signals if s) / len(signals)
        activity = _recency(r.repository.pushed_at, half_life_days=180)
        return _clamp(0.7 * base + 0.3 * activity), (
            f"tests={r.has_tests}, ci={r.has_ci}, archived={r.repository.archived}"
        )

    def _guidelines_fit(self, r: RepositoryReport) -> tuple[float, str]:
        score = 0.4
        if r.has_contributing:
            score += 0.35
        if r.contributing_requirements:
            score += 0.15
        if r.has_code_of_conduct:
            score += 0.1
        return _clamp(score), f"contributing={r.has_contributing}, reqs={len(r.contributing_requirements)}"

    def _scope(self, a: IssueAnalysis) -> tuple[float, str]:
        # Small, low-risk scope is most appropriate for an assisted contribution.
        score = 1.0 - 0.6 * a.complexity - 0.4 * a.breaking_change_risk
        return _clamp(score), f"complexity={a.complexity:.2f}, breaking={a.breaking_change_risk:.2f}"

    def _technical_confidence(self, a: IssueAnalysis) -> tuple[float, str]:
        return _clamp(a.confidence), f"analysis_confidence={a.confidence:.2f}"

    def _skill_match(self, r: RepositoryReport, profile: DeveloperProfile) -> tuple[float, str]:
        lang = r.repository.primary_language
        weight = profile.language_weight(lang)
        return _clamp(weight), f"language={lang}, weight={weight:.2f}"

    # -- blockers / flags -----------------------------------------------------
    def _blockers(self, a: IssueAnalysis, report: RepositoryReport,
                  issue: Optional[Issue]) -> list[str]:
        blockers: list[str] = []
        if issue is not None and issue.state and issue.state.lower() != "open":
            blockers.append(f"issue is {issue.state}, not open")
        if report.repository.archived:
            blockers.append("repository is archived")
        if issue is not None and issue.linked_pr_numbers:
            blockers.append(f"issue already has linked PR(s) {issue.linked_pr_numbers}")
        if issue is not None and issue.assignees:
            blockers.append(f"issue is assigned to {issue.assignees}")
        if a.duplicate_risk >= 0.8:
            blockers.append(f"high duplicate risk ({a.duplicate_risk:.2f}) — likely already being worked on")
        labels = {l.lower() for l in (issue.labels if issue else [])}
        if labels & _DISQUALIFYING_LABELS:
            blockers.append(f"disqualifying label(s): {sorted(labels & _DISQUALIFYING_LABELS)}")
        return blockers

    def _needs_investigation(self, a: IssueAnalysis, issue: Optional[Issue]) -> Optional[str]:
        labels = {l.lower() for l in (issue.labels if issue else [])}
        if labels & _DISCUSSION_LABELS:
            return f"issue looks like a discussion/design task ({sorted(labels & _DISCUSSION_LABELS)})"
        return None

    # -- public ---------------------------------------------------------------
    def assess(
        self,
        analysis: IssueAnalysis,
        report: RepositoryReport,
        profile: DeveloperProfile,
        *,
        issue: Optional[Issue] = None,
        comment_bodies: Optional[list[str]] = None,
    ) -> SuitabilityAssessment:
        raw: dict[str, tuple[float, str]] = {
            "issue_clarity": self._issue_clarity(analysis),
            "maintainer_intent": self._maintainer_intent(issue),
            "existing_work": self._existing_work(analysis, issue),
            "repository_health": self._repository_health(report),
            "guidelines_fit": self._guidelines_fit(report),
            "scope_appropriateness": self._scope(analysis),
            "technical_confidence": self._technical_confidence(analysis),
            "skill_match": self._skill_match(report, profile),
        }
        weights = self.weights.as_dict()
        total_w = sum(weights.values()) or 1.0

        signals: list[SuitabilitySignal] = []
        base = 0.0
        positives: list[str] = []
        concerns: list[str] = []
        for name, (value, explanation) in raw.items():
            w = weights.get(name, 0.0) / total_w
            weighted = value * w
            base += weighted
            kind = "positive" if value >= 0.66 else ("concern" if value <= 0.4 else "neutral")
            signals.append(SuitabilitySignal(
                name=name, raw=round(value, 4), weight=round(w, 4),
                weighted=round(weighted, 4), kind=kind, explanation=explanation,
            ))
            label = name.replace("_", " ")
            if kind == "positive":
                positives.append(f"{label}: {explanation}")
            elif kind == "concern":
                concerns.append(f"{label}: {explanation}")
        score = round(_clamp(base) * 100.0, 2)

        blockers = self._blockers(analysis, report, issue)
        investigate = self._needs_investigation(analysis, issue)
        work_claim = _working_claim(comment_bodies)
        extra_concerns = list(concerns)
        if investigate:
            extra_concerns.append(investigate)
        if work_claim:
            extra_concerns.append(
                f"a contributor comment suggests work is already underway: \"{work_claim}\" "
                "— confirm this isn't duplicate effort"
            )

        category = self._categorize(score, blockers, investigate, analysis, work_claim)
        explanation = self._explain(category, score, positives, extra_concerns, blockers, investigate)

        return SuitabilityAssessment(
            repository_full_name=report.repository.full_name,
            issue_number=analysis.issue_number,
            category=category,
            score=score,
            signals=signals,
            positives=positives,
            concerns=extra_concerns,
            blockers=blockers,
            explanation=explanation,
            summary=f"suitability {category.value} ({score:.0f}/100)",
            confidence=analysis.confidence,
        )

    def _categorize(self, score: float, blockers: list[str], investigate: Optional[str],
                    a: IssueAnalysis, work_claim: Optional[str] = None) -> SuitabilityCategory:
        if blockers:
            return SuitabilityCategory.BLOCKED
        if investigate:
            return SuitabilityCategory.INVESTIGATE_ONLY
        if a.ambiguity_score >= 0.8:
            return SuitabilityCategory.SKIP
        if score >= 80:
            category = SuitabilityCategory.EXCELLENT
        elif score >= 65:
            category = SuitabilityCategory.GOOD
        elif score >= 45:
            category = SuitabilityCategory.REVIEW_REQUIRED
        else:
            category = SuitabilityCategory.SKIP
        # A claim of in-progress work never silently passes as strong — a human
        # must check for duplicate effort first.
        if work_claim and category in (SuitabilityCategory.EXCELLENT, SuitabilityCategory.GOOD):
            return SuitabilityCategory.REVIEW_REQUIRED
        return category

    def _explain(self, category: SuitabilityCategory, score: float, positives: list[str],
                 concerns: list[str], blockers: list[str], investigate: Optional[str]) -> str:
        if blockers:
            return f"BLOCKED ({score:.0f}/100): " + "; ".join(blockers)
        if investigate:
            return f"INVESTIGATE_ONLY ({score:.0f}/100): {investigate}"
        parts = [f"{category.value} ({score:.0f}/100)."]
        if positives:
            parts.append("Positive: " + "; ".join(positives[:3]) + ".")
        if concerns:
            parts.append("Concerns: " + "; ".join(concerns[:3]) + ".")
        return " ".join(parts)

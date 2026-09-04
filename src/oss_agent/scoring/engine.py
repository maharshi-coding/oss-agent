"""The contribution scoring engine.

Deterministic and fully unit-testable. It combines an :class:`IssueAnalysis`, a
:class:`RepositoryReport`, and a :class:`DeveloperProfile` into a
:class:`ContributionScore` in [0, 100], applying configurable weights and
penalties. The developer profile drives the ``skill_match`` dimension, so the
same opportunity scores differently for different developers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from oss_agent.config.profile import DeveloperProfile
from oss_agent.domain.enums import ContributionType, Difficulty, ProjectSize, Recommendation
from oss_agent.domain.models import (
    ContributionScore,
    Issue,
    IssueAnalysis,
    PenaltyComponent,
    RepositoryReport,
    ScoreComponent,
)
from oss_agent.scoring.config import ScoringConfig


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _recency_score(dt: Optional[datetime], half_life_days: float = 90.0) -> float:
    """1.0 for very recent, decaying with age. 0.5 at one half-life."""
    if dt is None:
        return 0.5
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - dt).total_seconds() / 86400.0)
    return _clamp(0.5 ** (age_days / half_life_days))


_DIFFICULTY_RANK = {
    Difficulty.TRIVIAL: 0,
    Difficulty.EASY: 1,
    Difficulty.MODERATE: 2,
    Difficulty.HARD: 3,
    Difficulty.ANY: 2,
}


class ScoringEngine:
    def __init__(self, config: Optional[ScoringConfig] = None) -> None:
        self.config = config or ScoringConfig()

    # -- individual dimensions ------------------------------------------------
    def _issue_clarity(self, a: IssueAnalysis) -> tuple[float, str]:
        clarity = 1.0 - a.ambiguity_score
        if a.acceptance_criteria:
            clarity = min(1.0, clarity + 0.1)
        if not a.problem_statement:
            clarity *= 0.7
        return _clamp(clarity), f"ambiguity={a.ambiguity_score:.2f}, criteria={len(a.acceptance_criteria)}"

    def _implementation_confidence(self, a: IssueAnalysis) -> tuple[float, str]:
        conf = a.confidence * (1.0 - 0.5 * a.complexity)
        if a.probable_files:
            conf = min(1.0, conf + 0.1)
        return _clamp(conf), f"agent_conf={a.confidence:.2f}, complexity={a.complexity:.2f}"

    def _repository_health(self, r: RepositoryReport) -> tuple[float, str]:
        signals = [r.has_tests, r.has_ci, r.has_contributing, r.has_readme, not r.repository.archived]
        base = sum(1 for s in signals if s) / len(signals)
        stars = r.repository.stars
        star_boost = _clamp((stars ** 0.5) / 200.0) * 0.2  # gentle, saturating
        return _clamp(base * 0.8 + star_boost), f"tests={r.has_tests}, ci={r.has_ci}, stars={stars}"

    def _maintainer_activity(self, r: RepositoryReport) -> tuple[float, str]:
        explicit = r.health_signals.get("maintainer_activity")
        if isinstance(explicit, (int, float)):
            return _clamp(float(explicit)), "explicit signal"
        return _recency_score(r.repository.pushed_at, half_life_days=120), (
            f"pushed_at={r.repository.pushed_at}"
        )

    def _testability(self, r: RepositoryReport, a: IssueAnalysis) -> tuple[float, str]:
        score = 0.0
        if r.has_tests:
            score += 0.5
        if r.test_command:
            score += 0.3
        if a.test_requirements:
            score += 0.2
        return _clamp(score), f"has_tests={r.has_tests}, test_cmd={bool(r.test_command)}"

    def _skill_match(
        self, r: RepositoryReport, a: IssueAnalysis, profile: DeveloperProfile
    ) -> tuple[float, str]:
        lang_weight = profile.language_weight(r.repository.primary_language)
        # Framework overlap.
        repo_frameworks = {f.lower() for f in r.package_managers} | {
            c.lower() for c in r.conventions
        }
        fw_overlap = 0.0
        if profile.frameworks:
            hits = sum(1 for f in profile.frameworks if f.lower() in " ".join(repo_frameworks))
            fw_overlap = hits / len(profile.frameworks)
        # Contribution type preference.
        type_pref = 0.5
        if profile.preferred_contribution_types:
            if a.contribution_type in profile.preferred_contribution_types:
                rank = profile.preferred_contribution_types.index(a.contribution_type)
                type_pref = 1.0 - (rank / (len(profile.preferred_contribution_types) + 1))
            else:
                type_pref = 0.2
        # Difficulty match.
        diff_pref = 1.0
        if profile.preferred_difficulty is not Difficulty.ANY:
            gap = abs(_DIFFICULTY_RANK[a.difficulty] - _DIFFICULTY_RANK[profile.preferred_difficulty])
            diff_pref = _clamp(1.0 - gap * 0.25)
        score = 0.45 * lang_weight + 0.15 * fw_overlap + 0.25 * type_pref + 0.15 * diff_pref
        return _clamp(score), (
            f"lang={lang_weight:.2f}, type={type_pref:.2f}, difficulty={diff_pref:.2f}"
        )

    def _contribution_value(self, a: IssueAnalysis, issue: Optional[Issue]) -> tuple[float, str]:
        value = {
            ContributionType.BUG_FIX: 0.8,
            ContributionType.FEATURE: 0.7,
            ContributionType.DOCUMENTATION: 0.6,
            ContributionType.TEST: 0.65,
            ContributionType.PERFORMANCE: 0.75,
            ContributionType.REFACTOR: 0.5,
            ContributionType.DEPENDENCY: 0.55,
            ContributionType.CI: 0.5,
            ContributionType.CHORE: 0.4,
        }.get(a.contribution_type, 0.5)
        if issue and any(
            l.lower() in {"good first issue", "help wanted", "bug"} for l in issue.labels
        ):
            value = min(1.0, value + 0.15)
        return _clamp(value), f"type={a.contribution_type.value}"

    def _issue_freshness(self, issue: Optional[Issue]) -> tuple[float, str]:
        if issue is None:
            return 0.5, "no issue metadata"
        return _recency_score(issue.updated_at or issue.created_at, half_life_days=60), (
            f"updated_at={issue.updated_at}"
        )

    # -- penalties ------------------------------------------------------------
    def _penalties(self, a: IssueAnalysis) -> list[PenaltyComponent]:
        p = self.config.penalties
        out: list[PenaltyComponent] = []

        def add(name: str, signal: float, explanation: str) -> None:
            cfg = p.get(name)
            if cfg is None or signal <= 0:
                return
            amount = round(_clamp(signal) * cfg.max, 2)
            if amount > 0:
                out.append(PenaltyComponent(name=name, amount=amount, explanation=explanation))

        add("ambiguity", a.ambiguity_score, f"ambiguity_score={a.ambiguity_score:.2f}")
        # high complexity only penalizes the portion above 0.6
        add("high_complexity", max(0.0, (a.complexity - 0.6) / 0.4), f"complexity={a.complexity:.2f}")
        add("duplicate_risk", a.duplicate_risk, f"duplicate_risk={a.duplicate_risk:.2f}")
        add("breaking_change", a.breaking_change_risk, f"breaking_change_risk={a.breaking_change_risk:.2f}")
        add("security_sensitivity", a.security_sensitivity, f"security_sensitivity={a.security_sensitivity:.2f}")
        return out

    # -- public ---------------------------------------------------------------
    def _recommendation(self, overall: float) -> Recommendation:
        t = self.config.thresholds
        if overall >= t.strong_pursue:
            return Recommendation.STRONG_PURSUE
        if overall >= t.pursue:
            return Recommendation.PURSUE
        if overall >= t.consider:
            return Recommendation.CONSIDER
        return Recommendation.SKIP

    def score(
        self,
        analysis: IssueAnalysis,
        report: RepositoryReport,
        profile: DeveloperProfile,
        *,
        issue: Optional[Issue] = None,
    ) -> ContributionScore:
        raw: dict[str, tuple[float, str]] = {
            "issue_clarity": self._issue_clarity(analysis),
            "implementation_confidence": self._implementation_confidence(analysis),
            "repository_health": self._repository_health(report),
            "maintainer_activity": self._maintainer_activity(report),
            "testability": self._testability(report, analysis),
            "skill_match": self._skill_match(report, analysis, profile),
            "contribution_value": self._contribution_value(analysis, issue),
            "issue_freshness": self._issue_freshness(issue),
        }
        weights = self.config.normalized_weights()

        components: list[ScoreComponent] = []
        base = 0.0
        for dim, (value, explanation) in raw.items():
            w = weights.get(dim, 0.0)
            weighted = value * w
            base += weighted
            components.append(
                ScoreComponent(
                    dimension=dim, raw=round(value, 4), weight=round(w, 4),
                    weighted=round(weighted, 4), explanation=explanation,
                )
            )
        base_score = round(base * 100.0, 2)

        penalties = self._penalties(analysis)
        total_penalty = sum(pen.amount for pen in penalties)
        overall = round(_clamp(base_score - total_penalty, 0.0, 100.0), 2)
        recommendation = self._recommendation(overall)

        explanation = (
            f"Base {base_score:.1f}/100 across {len(components)} dimensions; "
            f"penalties -{total_penalty:.1f}; final {overall:.1f} -> {recommendation.value}."
        )
        return ContributionScore(
            repository_full_name=report.repository.full_name,
            issue_number=analysis.issue_number,
            overall=overall,
            base_score=base_score,
            components=components,
            penalties=penalties,
            recommendation=recommendation,
            explanation=explanation,
            summary=explanation,
            confidence=analysis.confidence,
        )

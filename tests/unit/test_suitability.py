"""Unit tests for the contribution-suitability engine."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from oss_agent.config.profile import DEFAULT_PROFILE
from oss_agent.domain.enums import ContributionType, Difficulty, SuitabilityCategory
from oss_agent.domain.models import (
    Issue,
    IssueAnalysis,
    Repository,
    RepositoryReport,
)
from oss_agent.suitability.engine import (
    SuitabilityEngine,
    SuitabilityWeights,
    load_suitability_weights,
)

pytestmark = pytest.mark.unit


def _repo(**kw) -> Repository:
    base = dict(owner="octo", name="util", primary_language="Python",
                stars=500, license="MIT",
                pushed_at=datetime.now(timezone.utc))
    base.update(kw)
    return Repository(**base)


def _report(repo: Repository, **kw) -> RepositoryReport:
    base = dict(repository=repo, has_readme=True, has_contributing=True,
                has_tests=True, has_ci=True, build_system="python",
                contributing_requirements=["run pytest"], test_command="pytest")
    base.update(kw)
    return RepositoryReport(**base)


def _analysis(repo_name="octo/util", number=1, **kw) -> IssueAnalysis:
    base = dict(repository_full_name=repo_name, issue_number=number,
                problem_statement="trailing hyphen", expected_behavior="strip it",
                acceptance_criteria=["slugify('Hi!') == 'hi'"],
                contribution_type=ContributionType.BUG_FIX, difficulty=Difficulty.EASY,
                ambiguity_score=0.05, duplicate_risk=0.05, breaking_change_risk=0.1,
                complexity=0.25, confidence=0.85)
    base.update(kw)
    return IssueAnalysis(**base)


def _issue(number=1, **kw) -> Issue:
    base = dict(number=number, title="slugify trailing hyphen", body="...",
                state="open", labels=["bug", "good first issue"])
    base.update(kw)
    return Issue(**base)


def test_clean_beginner_issue_is_excellent_or_good():
    eng = SuitabilityEngine()
    a = eng.assess(_analysis(), _report(_repo()), DEFAULT_PROFILE, issue=_issue())
    assert a.category in (SuitabilityCategory.EXCELLENT, SuitabilityCategory.GOOD)
    assert a.should_proceed
    assert not a.blockers
    assert a.positives  # has human-readable reasoning, not just a number


def test_existing_linked_pr_is_blocked():
    eng = SuitabilityEngine()
    a = eng.assess(_analysis(), _report(_repo()), DEFAULT_PROFILE,
                   issue=_issue(linked_pr_numbers=[42]))
    assert a.category is SuitabilityCategory.BLOCKED
    assert not a.should_proceed
    assert any("linked PR" in b for b in a.blockers)


def test_assigned_issue_is_blocked():
    eng = SuitabilityEngine()
    a = eng.assess(_analysis(), _report(_repo()), DEFAULT_PROFILE,
                   issue=_issue(assignees=["someone-else"]))
    assert a.category is SuitabilityCategory.BLOCKED
    assert not a.should_proceed


def test_archived_repository_is_blocked():
    eng = SuitabilityEngine()
    a = eng.assess(_analysis(), _report(_repo(archived=True)), DEFAULT_PROFILE, issue=_issue())
    assert a.category is SuitabilityCategory.BLOCKED
    assert any("archived" in b for b in a.blockers)


def test_closed_issue_is_blocked():
    eng = SuitabilityEngine()
    a = eng.assess(_analysis(), _report(_repo()), DEFAULT_PROFILE,
                   issue=_issue(state="closed"))
    assert a.category is SuitabilityCategory.BLOCKED


def test_discussion_label_is_investigate_only():
    eng = SuitabilityEngine()
    a = eng.assess(_analysis(), _report(_repo()), DEFAULT_PROFILE,
                   issue=_issue(labels=["discussion"]))
    assert a.category is SuitabilityCategory.INVESTIGATE_ONLY
    assert not a.should_proceed


def test_high_ambiguity_is_skip():
    eng = SuitabilityEngine()
    a = eng.assess(_analysis(ambiguity_score=0.85, acceptance_criteria=[]),
                   _report(_repo()), DEFAULT_PROFILE, issue=_issue())
    assert a.category is SuitabilityCategory.SKIP
    assert not a.should_proceed


def test_high_duplicate_risk_blocks():
    eng = SuitabilityEngine()
    a = eng.assess(_analysis(duplicate_risk=0.9), _report(_repo()), DEFAULT_PROFILE,
                   issue=_issue())
    assert a.category is SuitabilityCategory.BLOCKED


def test_working_on_it_comment_caps_at_review_required():
    eng = SuitabilityEngine()
    clean = eng.assess(_analysis(), _report(_repo()), DEFAULT_PROFILE, issue=_issue())
    assert clean.category in (SuitabilityCategory.EXCELLENT, SuitabilityCategory.GOOD)

    flagged = eng.assess(
        _analysis(), _report(_repo()), DEFAULT_PROFILE, issue=_issue(),
        comment_bodies=["Hi! I'm working on this, should have a PR up soon."],
    )
    # Same score, but capped so a human checks for duplicate work first.
    assert flagged.category is SuitabilityCategory.REVIEW_REQUIRED
    assert flagged.should_proceed  # still proceeds, but flagged
    assert any("already underway" in c or "duplicate" in c for c in flagged.concerns)


def test_unrelated_comments_do_not_trigger_work_claim():
    eng = SuitabilityEngine()
    a = eng.assess(
        _analysis(), _report(_repo()), DEFAULT_PROFILE, issue=_issue(),
        comment_bodies=["Thanks for reporting!", "I can reproduce this on 3.11."],
    )
    assert a.category in (SuitabilityCategory.EXCELLENT, SuitabilityCategory.GOOD)


def test_various_work_claim_phrasings_are_detected():
    eng = SuitabilityEngine()
    for phrase in ["I'll take this one.", "picking this up now",
                   "Can I work on this?", "PR incoming 🎉", "I've started on a fix"]:
        a = eng.assess(_analysis(), _report(_repo()), DEFAULT_PROFILE,
                       issue=_issue(), comment_bodies=[phrase])
        assert a.category is SuitabilityCategory.REVIEW_REQUIRED, phrase


def test_score_is_bounded_and_signals_sum_to_weighted():
    eng = SuitabilityEngine()
    a = eng.assess(_analysis(), _report(_repo()), DEFAULT_PROFILE, issue=_issue())
    assert 0.0 <= a.score <= 100.0
    # Weights are normalized: they should sum to ~1.0.
    assert abs(sum(s.weight for s in a.signals) - 1.0) < 1e-6


def test_weights_from_mapping_keeps_defaults_and_rejects_negative():
    w = SuitabilityWeights.from_mapping({"skill_match": 0.5, "unknown": 9})
    assert w.skill_match == 0.5
    assert w.issue_clarity == SuitabilityWeights().issue_clarity  # default kept
    with pytest.raises(ValueError):
        SuitabilityWeights.from_mapping({"skill_match": -1})


def test_load_suitability_weights_from_yaml(tmp_path):
    cfg = tmp_path / "scoring.yaml"
    cfg.write_text("suitability:\n  skill_match: 0.4\n", encoding="utf-8")
    w = load_suitability_weights(cfg)
    assert w.skill_match == 0.4
    # Missing file -> defaults, no crash.
    assert load_suitability_weights(tmp_path / "nope.yaml").skill_match == \
        SuitabilityWeights().skill_match

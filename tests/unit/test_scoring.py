import pytest

from oss_agent.config.profile import DeveloperProfile
from oss_agent.domain.enums import ContributionType, Difficulty, Recommendation
from oss_agent.domain.models import Issue, IssueAnalysis, Repository, RepositoryReport
from oss_agent.scoring.config import ScoringConfig
from oss_agent.scoring.engine import ScoringEngine

pytestmark = pytest.mark.unit


def _report(**kw):
    repo = Repository(owner="o", name="r", primary_language="Python", stars=kw.pop("stars", 400), license="MIT")
    return RepositoryReport(
        repository=repo, has_tests=kw.pop("has_tests", True), has_ci=kw.pop("has_ci", True),
        has_contributing=True, has_readme=True, test_command="pytest", **kw,
    )


def _analysis(**kw):
    defaults = dict(
        repository_full_name="o/r", issue_number=1, problem_statement="x",
        acceptance_criteria=["a"], contribution_type=ContributionType.BUG_FIX,
        difficulty=Difficulty.EASY, ambiguity_score=0.1, complexity=0.2,
        confidence=0.85, probable_files=["r/core.py"], test_requirements=["t"],
    )
    defaults.update(kw)
    return IssueAnalysis(**defaults)


def test_score_in_range_and_has_all_dimensions():
    eng = ScoringEngine()
    score = eng.score(_analysis(), _report(), DeveloperProfile(languages={"python": 1.0}))
    assert 0 <= score.overall <= 100
    assert len(score.components) == 8
    assert score.base_score >= score.overall  # penalties never increase score


def test_profile_changes_skill_match_and_overall():
    eng = ScoringEngine()
    py = DeveloperProfile(languages={"python": 1.0}, preferred_contribution_types=[ContributionType.BUG_FIX])
    go = DeveloperProfile(languages={"go": 1.0}, preferred_contribution_types=[ContributionType.FEATURE])
    s_py = eng.score(_analysis(), _report(), py)
    s_go = eng.score(_analysis(), _report(), go)
    sm_py = next(c.raw for c in s_py.components if c.dimension == "skill_match")
    sm_go = next(c.raw for c in s_go.components if c.dimension == "skill_match")
    assert sm_py > sm_go
    assert s_py.overall > s_go.overall


def test_penalties_reduce_score_and_can_force_skip():
    eng = ScoringEngine()
    clean = eng.score(_analysis(), _report(), DeveloperProfile(languages={"python": 1.0}))
    risky = eng.score(
        _analysis(ambiguity_score=0.9, complexity=0.95, duplicate_risk=0.9,
                  breaking_change_risk=0.9, security_sensitivity=0.9, confidence=0.3),
        _report(has_tests=False, has_ci=False, stars=5),
        DeveloperProfile(languages={"go": 1.0}),
    )
    assert risky.overall < clean.overall
    assert risky.total_penalty > 0
    assert risky.recommendation is Recommendation.SKIP


def test_weights_are_configurable():
    cfg = ScoringConfig(weights={"skill_match": 1.0})  # only skill match matters
    eng = ScoringEngine(cfg)
    score = eng.score(_analysis(), _report(), DeveloperProfile(languages={"python": 1.0}))
    weights = {c.dimension: c.weight for c in score.components}
    assert weights["skill_match"] == pytest.approx(1.0)
    assert weights["issue_clarity"] == pytest.approx(0.0)

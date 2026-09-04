import pytest

from oss_agent.config.profile import DeveloperProfile, load_profile
from oss_agent.config.settings import GitHubBackend, Settings
from oss_agent.scoring.config import ScoringConfig, load_scoring_config

pytestmark = pytest.mark.unit


def test_settings_parse_protected_branches_from_csv(monkeypatch):
    monkeypatch.setenv("OSS_AGENT_PROTECTED_BRANCHES", "main, release/prod ,trunk")
    monkeypatch.setenv("OSS_AGENT_GITHUB_BACKEND", "mock")
    s = Settings()
    assert s.protected_branches == ["main", "release/prod", "trunk"]
    assert s.github_backend is GitHubBackend.MOCK


def test_settings_reject_bad_log_level():
    with pytest.raises(Exception):
        Settings(log_level="LOUD")


def test_settings_token_presence():
    assert not Settings(github_token=None).github_token_present
    assert Settings(github_token="x").github_token_present


def test_load_profile_from_yaml(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(
        "name: Tester\n"
        "languages:\n  Python: 1.0\n  Go: 0.5\n"
        "experience_level: advanced\n"
        "preferred_contribution_types: [bug_fix, documentation]\n"
        "filters:\n  min_stars: 100\n  allowed_licenses: [MIT]\n",
        encoding="utf-8",
    )
    profile = load_profile(p)
    assert isinstance(profile, DeveloperProfile)
    assert profile.language_weight("python") == 1.0  # normalized to lowercase
    assert profile.language_weight("GO") == 0.5
    assert profile.filters.min_stars == 100


def test_load_profile_missing_falls_back_to_default(tmp_path):
    profile = load_profile(tmp_path / "nope.yaml")
    assert profile.name == "Default Developer"
    with pytest.raises(FileNotFoundError):
        load_profile(tmp_path / "nope.yaml", fallback_to_default=False)


def test_scoring_config_normalizes_weights(tmp_path):
    p = tmp_path / "scoring.yaml"
    p.write_text("weights:\n  issue_clarity: 2\n  skill_match: 2\n", encoding="utf-8")
    cfg = load_scoring_config(p)
    norm = cfg.normalized_weights()
    assert norm["issue_clarity"] == pytest.approx(0.5)
    assert sum(norm.values()) == pytest.approx(1.0)


def test_default_scoring_weights_sum_to_one():
    assert sum(ScoringConfig().weights.values()) == pytest.approx(1.0)


def test_example_scoring_config_validates_under_both_loaders():
    # `oss-agent init` copies this file to config/scoring.yaml, so it must load
    # cleanly for BOTH scoring and suitability (regression guard: the shared file
    # carries a `suitability:` section that ScoringConfig must accept).
    from pathlib import Path

    from oss_agent.suitability.engine import load_suitability_weights

    example = Path("config/scoring.example.yaml")
    if not example.exists():
        pytest.skip("example config not present")
    cfg = load_scoring_config(example)
    assert "issue_clarity" in cfg.weights
    weights = load_suitability_weights(example)
    assert weights.maintainer_intent > 0

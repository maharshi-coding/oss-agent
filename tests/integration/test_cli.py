"""Smoke tests for the CLI wiring (offline mock backend, seeded demo data)."""

import pytest

from oss_agent.cli.main import main
from oss_agent.config.settings import reset_settings

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch):
    monkeypatch.setenv("OSS_AGENT_GITHUB_BACKEND", "mock")
    monkeypatch.setenv("OSS_AGENT_AGENT_BACKEND", "mock")
    monkeypatch.setenv("OSS_AGENT_DATABASE_URL", "sqlite:///:memory:")
    reset_settings()
    yield
    reset_settings()


def test_cli_analyze_issue(capsys):
    assert main(["analyze-issue", "octo-org/stringutils", "101"]) == 0
    out = capsys.readouterr().out
    assert "bug_fix" in out


def test_cli_score(capsys):
    assert main(["score", "octo-org/stringutils", "101"]) == 0
    out = capsys.readouterr().out
    assert "/100" in out
    assert "skill_match" in out


def test_cli_discover(capsys):
    assert main(["discover"]) == 0
    out = capsys.readouterr().out
    assert "stringutils#101" in out


def test_cli_list_empty(capsys):
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "No workflows found." in out


def test_cli_unknown_repo_returns_error():
    # get_repository raises -> handled and mapped to a non-zero exit.
    assert main(["analyze", "does/not-exist"]) == 2


def test_cli_suitability(capsys):
    assert main(["suitability", "octo-org/stringutils", "101"]) == 0
    out = capsys.readouterr().out
    assert "Suitability for octo-org/stringutils#101" in out


def test_cli_json_score_is_valid_json(capsys):
    import json

    assert main(["--json", "score", "octo-org/stringutils", "101"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["repository_full_name"] == "octo-org/stringutils"
    assert 0 <= payload["overall"] <= 100


def test_cli_config_redacts_secrets(capsys):
    assert main(["config"]) == 0
    out = capsys.readouterr().out
    assert "agent_backend" in out
    assert "github_token_present" in out


def test_cli_json_config_is_valid_json(capsys):
    import json

    assert main(["--json", "config"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["agent_backend"] == "mock"

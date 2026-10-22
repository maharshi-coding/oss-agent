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


def test_cli_create_persists_utf8_requirements_and_related_prs(tmp_path, monkeypatch, capsys):
    import json

    monkeypatch.setenv("OSS_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'workflows.db'}")
    monkeypatch.setenv("OSS_AGENT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OSS_AGENT_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    reset_settings()
    instructions = "  Verify 1:1 and 4:3 in portrait/landscape.\r\nKeep measured results — no invented tests.\r\n"
    path = tmp_path / "requirements.txt"
    path.write_bytes(instructions.encode("utf-8"))

    assert main([
        "create", "octo-org/stringutils", "101", "--id", "with-requirements",
        "--instructions-file", str(path), "--related-pr", "644", "--related-pr", "710",
        "--existing-pr", "822",
    ]) == 0
    capsys.readouterr()
    # The persisted text, rather than a reference to a mutable file, is resumed.
    path.write_text("Later file contents", encoding="utf-8")
    assert main(["--json", "status", "with-requirements"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["user_instructions"] == instructions
    assert payload["related_pr_numbers"] == [644, 710]
    assert payload["existing_pr_number"] == 822


@pytest.mark.parametrize("contents", [None, b"\xff\xfe"])
def test_cli_does_not_create_workflow_when_requirements_cannot_be_read(
    contents, tmp_path, monkeypatch, capsys,
):
    database = tmp_path / "workflows.db"
    monkeypatch.setenv("OSS_AGENT_DATABASE_URL", f"sqlite:///{database}")
    reset_settings()
    path = tmp_path / "requirements.txt"
    if contents is not None:
        path.write_bytes(contents)

    assert main([
        "create", "octo-org/stringutils", "101", "--id", "unreadable-requirements",
        "--instructions-file", str(path),
    ]) == 2
    assert "error:" in capsys.readouterr().err
    assert not database.exists()


def _existing_pr_snapshot(*, draft=True):
    from oss_agent.domain.enums import WorkflowState
    from oss_agent.domain.models import PullRequestContinuation, PullRequestResult, WorkflowSnapshot

    full = "teslamotors/react-native-camera-kit"
    branch = "fix/android-scan-frame-layout"
    url = f"https://github.com/{full}/pull/822"
    return WorkflowSnapshot(
        id="continuation-cli", state=WorkflowState.READY_FOR_PR,
        repository_full_name=full, issue_number=576,
        branch="continue/pr-822/internal-worktree-branch", human_approved=True,
        continuation=PullRequestContinuation(
            number=822, repository_full_name=full, author="maharshi-coding",
            head_sha="a" * 40, base_sha="b" * 40,
            head_repository_full_name="maharshi-coding/react-native-camera-kit",
            head_repository_owner="maharshi-coding", head_branch=branch,
            base_branch="master", draft=draft, url=url,
        ),
        pull_request=PullRequestResult(
            repository_full_name=full, issue_number=576, branch=branch, number=822,
            url=url, draft=draft, title="Center the scan frame", body="Related to #576. Measured results.",
        ),
    )


def test_cli_prepare_existing_pr_shows_actual_owned_target(monkeypatch, capsys):
    import importlib
    from unittest.mock import Mock

    snap = _existing_pr_snapshot()
    app = Mock()
    app.prepare_pr.return_value = snap
    monkeypatch.setattr(importlib.import_module("oss_agent.cli.main"), "_app", lambda args: app)

    assert main(["prepare-pr", snap.id]) == 0
    out = capsys.readouterr().out
    assert "Prepared update to existing draft PR #822 (NOT submitted)" in out
    assert "head repository: maharshi-coding/react-native-camera-kit" in out
    assert "branch: fix/android-scan-frame-layout" in out
    assert "internal-worktree-branch" not in out
    assert "Measured results." in out
    assert "Nothing has been pushed" in out


@pytest.mark.parametrize("draft", [True, False])
def test_cli_submit_existing_pr_confirmation_and_success_describe_an_update(
    draft, monkeypatch, capsys,
):
    import importlib
    from unittest.mock import Mock

    from oss_agent.domain.enums import WorkflowState

    snap = _existing_pr_snapshot(draft=draft)
    submitted = snap.model_copy(deep=True)
    submitted.state = WorkflowState.PR_MONITORING
    submitted.pull_request.created = True
    app = Mock()
    app.status.return_value = snap
    app.submit.return_value = submitted
    monkeypatch.setattr(importlib.import_module("oss_agent.cli.main"), "_app", lambda args: app)
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")

    assert main(["submit", snap.id]) == 0
    out = capsys.readouterr().out
    kind = "draft PR" if draft else "PR"
    assert f"Update existing {kind} #822" in out
    assert "Head repository: maharshi-coding/react-native-camera-kit" in out
    assert "Push branch:     fix/android-scan-frame-layout" in out
    assert "Base branch:     master" in out
    assert "Draft status is preserved" in out
    assert "internal-worktree-branch" not in out
    assert "Create PR:" not in out
    assert "PR #822 updated: https://github.com/teslamotors/react-native-camera-kit/pull/822" in out
    app.submit.assert_called_once_with(snap.id, confirm=True, draft=False)

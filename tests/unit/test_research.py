import json
from types import SimpleNamespace

import pytest

from oss_agent.context.research import collect_research
from oss_agent.domain.models import WorkflowSnapshot
from oss_agent.github.interface import GitHubError
from tests.conftest import FULL_NAME, ISSUE_NUMBER

pytestmark = pytest.mark.unit


def _context(settings, github, **overrides):
    values = dict(
        id="research", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER,
        repository=github.get_repository(FULL_NAME),
        user_instructions="Review existing work before changing code.",
    )
    values.update(overrides)
    return SimpleNamespace(
        settings=settings, github=github, snapshot=WorkflowSnapshot(**values),
    )


def test_collects_and_persists_actual_build_and_pr_inputs(
    test_settings, seeded_github, fake_repo, monkeypatch,
):
    (fake_repo.path / "package.json").write_text('{"scripts":{"test":"jest"}}')
    pr = seeded_github.create_pull_request(
        FULL_NAME, head="other-fix", base="main", title="Existing fix", body="Related work",
    )
    monkeypatch.setattr(seeded_github, "get_pull_request_diff", lambda *args: "diff --git actual")
    ctx = _context(test_settings, seeded_github, related_pr_numbers=[pr.number])

    data = json.loads(collect_research(ctx))

    assert data["files"]["package.json"] == '{"scripts":{"test":"jest"}}'
    assert data["open_pull_requests"][0]["number"] == pr.number
    assert data["related_pull_requests"][0]["diff"] == "diff --git actual"
    assert data["errors"] == []
    saved = test_settings.state_dir / "runs" / "research" / "research.json"
    assert json.loads(saved.read_text()) == data
    # A repeated stage consumes the exact recorded inputs, not invented data.
    monkeypatch.setattr(seeded_github, "list_files", lambda *args: pytest.fail("should use cache"))
    assert json.loads(collect_research(ctx)) == data


def test_reports_unavailable_duplicate_and_diff_evidence(test_settings, seeded_github, monkeypatch):
    def unavailable(*args, **kwargs):
        raise GitHubError("network unavailable")
    monkeypatch.setattr(seeded_github, "list_pull_requests", unavailable)
    monkeypatch.setattr(seeded_github, "get_pull_request", unavailable)
    data = json.loads(collect_research(_context(test_settings, seeded_github, related_pr_numbers=[42])))
    assert len(data["errors"]) == 2
    assert all("network unavailable" in error for error in data["errors"])
    assert "must not be treated as absence" in data["notice"]


def test_rejects_artifact_path_escape(test_settings, seeded_github):
    ctx = _context(test_settings, seeded_github, id="../outside")
    with pytest.raises(ValueError, match="escapes"):
        collect_research(ctx)

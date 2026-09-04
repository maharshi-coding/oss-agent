import pytest

from oss_agent.domain.enums import ContributionType, Difficulty, WorkflowState
from oss_agent.domain.models import (
    IssueAnalysis,
    Repository,
    RepositoryReport,
    WorkflowSnapshot,
)
from oss_agent.observability.visualizer import (
    STAGE_DEFS,
    build_workflow_data,
    render_html,
)

pytestmark = pytest.mark.unit


def _partial_snapshot() -> WorkflowSnapshot:
    repo = Repository(owner="octo-org", name="example", primary_language="Python")
    snap = WorkflowSnapshot(
        id="wf-viz", repository_full_name="octo-org/example", issue_number=7,
        state=WorkflowState.SCORING, repository=repo,
    )
    snap.repository_report = RepositoryReport(repository=repo, has_tests=True, test_command="pytest")
    snap.issue_analysis = IssueAnalysis(
        repository_full_name="octo-org/example", issue_number=7,
        contribution_type=ContributionType.BUG_FIX, difficulty=Difficulty.EASY,
    )
    return snap


def test_nine_stages_defined():
    assert len(STAGE_DEFS) == 9
    assert [d["key"] for d in STAGE_DEFS][0] == "discovery"
    assert [d["key"] for d in STAGE_DEFS][-1] == "prgate"


def test_status_reflects_progress():
    data = build_workflow_data(_partial_snapshot())
    statuses = [s["status"] for s in data["stages"]]
    # discovery, repo, issue analysis are done; scoring is the active frontier.
    assert statuses[0:3] == ["done", "done", "done"]
    assert statuses[3] == "active"
    assert statuses[4:] == ["pending"] * 5
    assert data["current"] == 3


def test_failed_workflow_marks_frontier():
    snap = _partial_snapshot()
    snap.state = WorkflowState.FAILED
    data = build_workflow_data(snap)
    assert data["failed"] is True
    assert data["stages"][3]["status"] == "failed"


def test_render_html_is_standalone_and_embeds_data():
    html = render_html(_partial_snapshot())
    assert html.startswith("<!doctype html>")
    assert "github war room" in html
    assert "octo-org/example" in html
    assert "wf-viz" in html
    # no external resources (fully self-contained)
    assert "http://" not in html.split("prUrl")[0]
    assert "cdnjs" not in html


def test_render_demo_without_snapshot():
    html = render_html(None)
    assert "<!doctype html>" in html
    assert "demo" in html.lower()

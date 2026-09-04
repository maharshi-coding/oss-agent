"""PR preparation is separate from submission, and submission is human-gated.

Verifies the critical safety property (prompt-pack §20): nothing is pushed or a
PR opened without an explicit prepared PR, explicit human approval, and an
explicit confirmation — plus a passing final conflict re-check.
"""

from __future__ import annotations

import pytest

from oss_agent.app import Application
from oss_agent.domain.enums import WorkflowState
from oss_agent.orchestrator.engine import HumanApprovalRequired, SubmissionBlocked

from tests.conftest import FULL_NAME, ISSUE_NUMBER


pytestmark = pytest.mark.integration


def _ready(engine, wid: str):
    engine.create_workflow(workflow_id=wid, repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    engine.run(wid)
    return engine.get(wid)


def test_prepare_pr_does_not_push_or_create(engine):
    app = Application(engine)
    _ready(engine, "prep-1")
    snap = app.prepare_pr("prep-1")
    # PR is composed but NOT created; state stays READY_FOR_PR.
    assert snap.state is WorkflowState.READY_FOR_PR
    assert snap.pull_request is not None
    assert snap.pull_request.created is False
    assert snap.pull_request.number is None
    assert f"#{ISSUE_NUMBER}" in snap.pull_request.body


def test_submit_requires_prepared_pr(engine):
    app = Application(engine)
    _ready(engine, "prep-2")
    app.approve("prep-2")
    with pytest.raises(SubmissionBlocked):
        app.submit("prep-2", confirm=True)  # never prepared


def test_submit_requires_human_approval(engine):
    app = Application(engine)
    _ready(engine, "prep-3")
    app.prepare_pr("prep-3")
    with pytest.raises(HumanApprovalRequired):
        app.submit("prep-3", confirm=True)  # not approved


def test_submit_requires_explicit_confirmation(engine):
    app = Application(engine)
    _ready(engine, "prep-4")
    app.prepare_pr("prep-4")
    app.approve("prep-4")
    with pytest.raises(HumanApprovalRequired):
        app.submit("prep-4", confirm=False)  # confirmation not given


def test_full_gated_submission_succeeds(engine):
    app = Application(engine)
    _ready(engine, "prep-5")
    app.prepare_pr("prep-5")
    app.approve("prep-5")
    snap = app.submit("prep-5", confirm=True)
    assert snap.state is WorkflowState.PR_MONITORING
    assert snap.pull_request.created is True
    assert snap.pull_request.number >= 1


def test_pr_template_is_respected(engine, fake_repo):
    # The repository ships a PR template; the composed PR must include its
    # structure (checklist) for the human to complete.
    tmpl = fake_repo.path / ".github" / "pull_request_template.md"
    tmpl.parent.mkdir(parents=True, exist_ok=True)
    tmpl.write_text("## Checklist\n- [ ] I read CONTRIBUTING.md\n- [ ] Tests added\n",
                    encoding="utf-8")
    app = Application(engine)
    _ready(engine, "tmpl-1")
    snap = app.prepare_pr("tmpl-1")
    body = snap.pull_request.body
    assert "Repository pull-request template" in body
    assert "I read CONTRIBUTING.md" in body   # the template's own content
    assert f"Closes #{ISSUE_NUMBER}" in body   # our evidence-backed summary too


def test_final_conflict_check_blocks_submission(engine, seeded_github):
    app = Application(engine)
    _ready(engine, "prep-6")
    app.prepare_pr("prep-6")
    app.approve("prep-6")
    # A conflicting PR appears on the issue's branch just before submission.
    seeded_github.create_pull_request(
        FULL_NAME, head="fix/issue-101", base="main",
        title="someone else's fix", body="conflicting work",
    )
    with pytest.raises(SubmissionBlocked):
        app.submit("prep-6", confirm=True)
    # Nothing was created.
    assert engine.get("prep-6").pull_request.created is False

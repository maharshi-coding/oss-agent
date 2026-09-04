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


def test_planner_branch_name_does_not_desync_worktree(
    test_settings, seeded_github, fake_repo, slugify_solution
):
    """Regression: a planner that proposes a semantic branch name must NOT
    override the deterministic worktree branch. The worktree is created in
    SELECTED on ``branch_name_for(...)`` and that is the only branch that exists
    in git; adopting the plan's name desynchronizes ``snapshot.branch`` from the
    real branch and breaks the push at PR time ("src refspec ... does not match
    any"). Surfaced by live Claude validation — the mock planner returns the
    deterministic name, so this was invisible before.
    """
    from oss_agent.agents.mock_runner import MockAgentRunner
    from oss_agent.config.profile import DEFAULT_PROFILE
    from oss_agent.git.naming import branch_name_for
    from oss_agent.orchestrator.builder import build_engine
    from oss_agent.orchestrator.repo_provider import MappedRepoProvider
    from oss_agent.persistence.repository import InMemoryWorkflowRepository

    class SemanticBranchRunner(MockAgentRunner):
        def plan(self, ctx):
            p = super().plan(ctx)
            return p.model_copy(update={"branch_name": "feature/totally-different-name"})

    engine = build_engine(
        test_settings,
        repository=InMemoryWorkflowRepository(),
        github=seeded_github,
        runner=SemanticBranchRunner(solution=slugify_solution),
        repo_provider=MappedRepoProvider({FULL_NAME: str(fake_repo.path)}),
        profile=DEFAULT_PROFILE,
    )
    app = Application(engine)
    engine.create_workflow(workflow_id="branch-1", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    engine.run("branch-1")
    snap = engine.get("branch-1")

    expected = branch_name_for(ISSUE_NUMBER)  # fix/issue-101
    # snapshot.branch stays the deterministic worktree branch, not the plan's name.
    assert snap.branch == expected
    assert snap.branch != "feature/totally-different-name"
    # the plan's suggestion is retained for reference only.
    assert snap.plan.branch_name == "feature/totally-different-name"
    # the branch actually exists in the worktree (so a real push would succeed).
    assert engine.git.current_branch(snap.worktree_path) == expected
    # end-to-end: the gated submission still succeeds and targets the real branch.
    app.prepare_pr("branch-1")
    app.approve("branch-1")
    submitted = app.submit("branch-1", confirm=True)
    assert submitted.pull_request.created is True


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

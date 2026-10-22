import pytest

from oss_agent.agents.mock_runner import MockAgentRunner
from oss_agent.app import Application
from oss_agent.config.profile import DEFAULT_PROFILE
from oss_agent.domain.enums import WorkflowState
from oss_agent.orchestrator.builder import build_engine

from tests.conftest import FULL_NAME, ISSUE_NUMBER

pytestmark = pytest.mark.integration


def _sibling_engine(engine, solution=None):
    """A fresh engine sharing the same persistent store (simulated restart)."""
    return build_engine(
        engine.settings,
        repository=engine.repo,
        github=engine.github,
        runner=engine.runner if solution is None else MockAgentRunner(solution=solution),
        repo_provider=engine.repo_provider,
        profile=engine.profile,
    )


def test_workflow_resumes_from_persisted_state(engine):
    engine.create_workflow(workflow_id="wf-resume", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    # Advance a few steps then "crash".
    for _ in range(3):
        engine.step("wf-resume")
    mid = engine.get("wf-resume")
    assert mid.state not in (WorkflowState.DISCOVERY,)  # progressed
    assert not mid.state.is_terminal

    # A brand-new engine over the same store resumes to completion.
    resumed = _sibling_engine(engine).resume("wf-resume")
    assert resumed.state is WorkflowState.READY_FOR_PR
    assert resumed.test_result.passed


def test_user_requirements_are_preserved_across_create_and_resume(engine):
    instructions = "  Keep this change focused.\r\nMeasure the original failure — do not guess.\n"
    related_prs = [644, 710]
    app = Application(engine)
    created = app.create(
        FULL_NAME, ISSUE_NUMBER, workflow_id="wf-requirements",
        user_instructions=instructions, related_pr_numbers=related_prs,
    )
    assert created.user_instructions == instructions
    related_prs.append(812)

    engine.step("wf-requirements")
    resumed = _sibling_engine(engine).resume("wf-requirements")

    assert resumed.state is WorkflowState.READY_FOR_PR
    assert resumed.user_instructions == instructions
    assert resumed.related_pr_numbers == [644, 710]
    assert engine.get("wf-requirements").user_instructions == instructions


def test_worktree_creation_is_idempotent_across_steps(engine):
    engine.create_workflow(workflow_id="wf-idem", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    engine.run("wf-idem")
    snap = engine.get("wf-idem")
    first_path = snap.worktree_path
    assert first_path is not None
    # Re-running does not duplicate the worktree.
    engine.run("wf-idem")
    assert engine.get("wf-idem").worktree_path == first_path


def test_duplicate_workflow_for_same_issue_is_aborted(engine):
    engine.create_workflow(workflow_id="wf-a", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    engine.run("wf-a")  # reaches READY_FOR_PR (active)
    engine.create_workflow(workflow_id="wf-b", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    result = engine.run("wf-b")
    assert result.state is WorkflowState.ABORTED
    assert "duplicate" in (result.last_error or "").lower()


def test_full_history_is_auditable(engine):
    engine.create_workflow(workflow_id="wf-audit", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    engine.run("wf-audit")
    snap = engine.get("wf-audit")
    # State transitions and agent executions are all recorded.
    transitions = [e for e in snap.events if e.type.value == "state_transition"]
    assert len(transitions) >= 8
    assert len(snap.executions) >= 6
    assert all(ex.finished_at is not None for ex in snap.executions)

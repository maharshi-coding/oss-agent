"""End-to-end workflow against a real local fake repository.

Demonstrates the full pipeline the specification requires:
DISCOVERY -> ANALYSIS -> SCORING -> PLANNING -> IMPLEMENTATION -> TEST -> REVIEW
-> APPROVAL, with real git operations and real pytest execution, and no network.
"""

import pytest

from oss_agent.domain.enums import MaintainerVerdict, ReviewVerdict, WorkflowState

from tests.conftest import FULL_NAME, ISSUE_NUMBER

pytestmark = pytest.mark.e2e


def test_full_workflow_reaches_ready_for_pr(engine):
    engine.create_workflow(workflow_id="e2e", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    snap = engine.run("e2e")

    assert snap.state is WorkflowState.READY_FOR_PR

    # Every stage produced its structured artifact.
    assert snap.repository_report is not None
    assert snap.issue_analysis is not None
    assert snap.score is not None and snap.score.overall > 0
    assert snap.plan is not None and snap.plan.branch_name == "fix/issue-101"
    assert snap.implementation is not None

    # Tests were really executed and captured (not inferred).
    assert snap.test_result.passed
    assert snap.test_result.total_tests_passed == 2
    tests_suite = next(s for s in snap.test_result.suites if s.name == "tests")
    assert tests_suite.command.exit_code == 0

    # All gates approved.
    assert snap.code_review.verdict is ReviewVerdict.APPROVE
    assert snap.security_review.verdict is ReviewVerdict.APPROVE
    assert snap.maintainer_review.verdict is MaintainerVerdict.APPROVE


def test_the_fix_actually_changes_the_code(engine, fake_repo):
    engine.create_workflow(workflow_id="e2e2", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    snap = engine.run("e2e2")
    # The worktree contains the real fix; the base repo is untouched.
    from pathlib import Path
    fixed = Path(snap.worktree_path) / "stringutils" / "__init__.py"
    assert 'strip("-")' in fixed.read_text(encoding="utf-8")
    base = fake_repo.path / "stringutils" / "__init__.py"
    assert 'strip("-")' not in base.read_text(encoding="utf-8")


def test_pr_creation_is_gated_and_records_pr(engine):
    engine.create_workflow(workflow_id="e2e3", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    engine.run("e2e3")
    snap = engine.create_pr("e2e3")
    assert snap.state is WorkflowState.PR_MONITORING
    assert snap.pull_request.created
    assert snap.pull_request.number >= 1
    assert f"#{ISSUE_NUMBER}" in snap.pull_request.body  # closes the issue


def test_cannot_create_pr_before_ready(engine):
    from oss_agent.orchestrator.engine import OrchestrationError
    engine.create_workflow(workflow_id="e2e4", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    engine.step("e2e4")  # only DISCOVERY done
    with pytest.raises(OrchestrationError):
        engine.create_pr("e2e4")


def test_failing_fix_exhausts_debug_loop_then_fails(broken_engine):
    broken_engine.create_workflow(workflow_id="e2e-broken", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    snap = broken_engine.run("e2e-broken")
    assert snap.state is WorkflowState.FAILED
    assert snap.debug_iteration == broken_engine.settings.max_debug_iterations
    assert "failing" in (snap.last_error or "").lower()


def test_report_renders(engine):
    from oss_agent.observability.report import render_report
    engine.create_workflow(workflow_id="e2e-report", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    engine.run("e2e-report")
    text = render_report(engine.get("e2e-report"))
    assert "Workflow: e2e-report" in text
    assert "TESTING" in text

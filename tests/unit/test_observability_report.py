"""Status and visualizer evidence report actual counts rather than inferred zero."""

import pytest

from oss_agent.domain.models import (
    CommandOutcome, TestResult as CapturedTestResult,
    TestSuiteResult as CapturedSuiteResult, WorkflowSnapshot,
)
from oss_agent.observability.report import render_report
from oss_agent.observability.visualizer import build_workflow_data


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("count,expected", [
    (None, "case counts unavailable"),
    (3, "3 observed test cases passed"),
    (0, "0 observed test cases passed"),
])
def test_status_and_visualizer_distinguish_unknown_and_observed_case_counts(count, expected):
    suites = [
        CapturedSuiteResult(
            name="source-bound-evidence" if count is None else "counted-tests",
            kind="static" if count is None else "unit", passed=True, tests_passed=count,
            command=CommandOutcome(
                command=["recorded-quality-command"], cwd="isolated-worktree",
                exit_code=0, duration_seconds=0.1,
            ),
        ),
        CapturedSuiteResult(
            name="whitespace", kind="format", passed=True,
            command=CommandOutcome(
                command=["git", "diff", "--cached", "--check"], cwd="isolated-worktree",
                exit_code=0, duration_seconds=0.1,
            ),
        ),
    ]
    snapshot = WorkflowSnapshot(
        id="observable-counts", repository_full_name="owner/repo", issue_number=123,
        test_result=CapturedTestResult(repository_full_name="owner/repo", suites=suites),
    )
    status = render_report(snapshot)
    visualization = build_workflow_data(snapshot)["stages"][6]["e"]
    for rendered in (status, visualization):
        assert "2 executed quality suites passed" in rendered
        assert expected in rendered
        if count is None:
            assert "0 passed" not in rendered
            assert "0 observed test cases" not in rendered


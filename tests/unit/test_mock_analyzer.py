"""Regression tests for the mock issue-analyzer heuristics.

The `_extract_expected` bug below was exposed during live sandbox validation: a
reproduction code comment ("# returns -1, expected 5") leaked into the PR body's
Summary as "5".
"""

from __future__ import annotations

import pytest

from oss_agent.agents.mock_runner import MockAgentRunner

pytestmark = pytest.mark.unit


def test_expected_ignores_reproduction_code_comment():
    body = (
        "## Problem\n\n`add` is wrong.\n\n"
        "## Reproduction\n\n```python\nadd(2, 3)   # returns -1, expected 5\n```\n\n"
        "## Expected behavior\n\n`add(a, b)` should return `a + b`.\n\n"
        "## Acceptance criteria\n\n- [ ] add(2, 3) == 5\n"
    )
    expected = MockAgentRunner()._extract_expected(body)
    assert "should return" in expected
    assert expected != "5"
    assert "```" not in expected


def test_expected_prefers_heading_section():
    body = "Expected behavior\n\nThe function should validate input before use.\n\n"
    assert "validate input" in MockAgentRunner()._extract_expected(body)


def test_expected_absent_returns_empty():
    assert MockAgentRunner()._extract_expected("Just a vague report with no spec.") == ""


def test_expected_does_not_capture_bare_number():
    body = "Steps:\n\n```\nrun()  # expected 42\n```\n"
    # The only "expected" is inside a code block -> no spec extracted.
    assert MockAgentRunner()._extract_expected(body) == ""


def test_pr_body_distinguishes_skipped_suites():
    # Regression: the PR body must not imply a skipped check passed.
    from oss_agent.agents.base import AgentContext
    from oss_agent.domain.models import (
        CommandOutcome, ImplementationPlan, ImplementationResult, Issue,
        TestResult, TestSuiteResult, WorkflowSnapshot,
    )

    def _cmd(code=0):
        return CommandOutcome(command=["x"], cwd=".", exit_code=code, duration_seconds=0.1)

    tr = TestResult(repository_full_name="o/r", suites=[
        TestSuiteResult(name="tests", kind="unit", passed=True, tests_passed=3, command=_cmd()),
        TestSuiteResult(name="lint", kind="lint", passed=False, skipped=True, command=_cmd(127)),
    ])
    snap = WorkflowSnapshot(
        id="t", repository_full_name="o/r", issue_number=1,
        issue=Issue(number=1, title="fix add"),
        plan=ImplementationPlan(repository_full_name="o/r", issue_number=1,
                                objective="add should sum", branch_name="fix/issue-1"),
        implementation=ImplementationResult(plan_branch="fix/issue-1"),
        test_result=tr,
    )

    class _GH:
        def get_file(self, *a, **k):
            return None

    ctx = AgentContext(snapshot=snap, settings=None, github=_GH(), git=None,
                       profile=None, scoring=None, worktree=None)
    body = MockAgentRunner().compose_pull_request(ctx).body
    assert "3 passed across 1 executed suite" in body
    assert "1 skipped: lint" in body
    assert "across 2 suite" not in body  # never conflates skipped with executed

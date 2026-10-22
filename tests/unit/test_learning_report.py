"""Learning prose must distinguish unreported test counts from measured zero."""

import pytest

from oss_agent.domain.models import (
    CommandOutcome, FileChange, ImplementationPlan, ImplementationResult, Issue,
    PullRequestContinuation, RepositoryContext, TestResult as CapturedTestResult,
    TestSuiteResult as CapturedSuiteResult, WorkflowSnapshot,
)
from oss_agent.learning.report import build_learning_report


pytestmark = pytest.mark.unit


def _suite(name, kind, *, count=None, skipped=False):
    return CapturedSuiteResult(
        name=name, kind=kind, passed=not skipped, skipped=skipped,
        tests_passed=count,
        command=CommandOutcome(
            command=["recorded-quality-command", name], cwd="isolated-worktree",
            exit_code=127 if skipped else 0, duration_seconds=0.1,
        ),
    )


def _report(suites):
    snapshot = WorkflowSnapshot(
        id="learning-counts", repository_full_name="owner/repo", issue_number=123,
        test_result=CapturedTestResult(repository_full_name="owner/repo", suites=suites),
    )
    assert snapshot.test_result.passed
    return build_learning_report(snapshot, [])


def test_green_static_and_format_suites_do_not_invent_a_zero_test_count():
    report = _report([
        _suite("source-bound-evidence", "static"), _suite("whitespace", "format"),
    ])
    assert report.why_the_fix_works == "2 executed quality suites passed."
    assert "0 passing" not in report.why_the_fix_works
    assert "full validation" not in report.why_the_fix_works.lower()
    assert report.tests_that_prove_it == [
        "source-bound-evidence (static): passed", "whitespace (format): passed",
    ]


def test_observed_pytest_count_is_preserved_when_other_suites_do_not_report_counts():
    report = _report([_suite("pytest", "unit", count=3), _suite("lint", "lint")])
    assert "2 executed quality suites passed." in report.why_the_fix_works
    assert "Captured counts show 3 passing test cases." in report.why_the_fix_works
    assert "pytest (unit): 3 passed" in report.tests_that_prove_it


def test_explicitly_observed_zero_is_distinct_from_an_unknown_count():
    report = _report([_suite("counted-command", "static", count=0)])
    assert "1 executed quality suite passed." in report.why_the_fix_works
    assert "Captured counts show 0 passing test cases." in report.why_the_fix_works


def test_skipped_suite_counts_are_not_claimed_as_executed_tests():
    report = _report([
        _suite("evidence", "static"), _suite("unavailable-tests", "unit", count=7, skipped=True),
    ])
    assert report.why_the_fix_works == "1 executed quality suite passed."
    assert "unavailable-tests: skipped (tool unavailable)" in report.tests_that_prove_it


def _revised_snapshot():
    return WorkflowSnapshot(
        id="revised-continuation", repository_full_name="owner/repo", issue_number=123,
        review_iteration=1, issue=Issue(number=123, title="Center the frame"),
        continuation=PullRequestContinuation(
            number=456, repository_full_name="owner/repo", author="contributor",
            head_sha="a" * 40, base_sha="b" * 40,
            head_repository_full_name="contributor/repo", head_repository_owner="contributor",
            head_branch="fix/frame", base_branch="main", draft=True,
            url="https://github.com/owner/repo/pull/456",
        ),
        plan=ImplementationPlan(
            repository_full_name="owner/repo", issue_number=123,
            objective="Publish docs/obsolete-validation.md and its screenshots",
            branch_name="fix/frame", affected_files=["Camera.kt", "docs/obsolete-validation.md"],
            risks=["Maintaining docs/obsolete-validation.md"],
            acceptance_criteria=["Publish docs/obsolete-validation.md"],
        ),
        repository_context=RepositoryContext(
            repository_full_name="owner/repo", likely_files=["docs/obsolete-validation.md", "Camera.kt"],
        ),
        implementation=ImplementationResult(
            plan_branch="continue/pr-456/isolated",
            files_changed=[
                FileChange(path="docs/obsolete-validation.md", change_type="deleted"),
                FileChange(path="docs/frame.png", change_type="deleted"),
                FileChange(path=".github/workflows/build.yml"),
            ],
        ),
        test_result=CapturedTestResult(
            repository_full_name="owner/repo",
            suites=[_suite("source-bound-evidence", "static"), _suite("whitespace", "format")],
        ),
    )


def test_final_full_diff_drives_continuation_files_and_maintainer_scope():
    snapshot = _revised_snapshot()
    changed = [
        (2, 0, ".github/workflows/build.yml"), (4, 0, "android/build.gradle"),
        (12, 10, "Camera.kt"), (75, 0, "CameraTest.kt"),
    ]
    report = build_learning_report(snapshot, changed)
    expected_files = [path for _, _, path in changed]
    assert report.files_that_matter == expected_files
    assert all(path in report.why_it_was_broken for path in expected_files)
    file_question = next(q for q in report.maintainer_questions if q.startswith("Why these files"))
    assert all(path in file_question for path in expected_files)
    assert "docs/" not in file_question
    assert "obsolete-validation" not in report.why_it_was_broken
    assert "obsolete-validation" not in report.why_the_fix_works
    assert report.why_the_fix_works == "2 executed quality suites passed."
    assert report.how_discovered.startswith("Initial repository-context selection")
    assert "Initial plan risk (historical)" in report.tradeoffs[0]
    assert "earlier acceptance criteria may have been revised" in report.edge_cases_remaining[0]
    assert report.maintainer_questions[-1] == "How does the final diff satisfy the current reviewed requirements?"


def test_empty_final_diff_does_not_fall_back_to_incremental_doc_deletions():
    report = build_learning_report(_revised_snapshot(), [])
    assert report.files_that_matter == []
    assert report.what_changed == ["(no textual diff captured)"]
    assert "Final changed-file evidence is not available" in report.why_it_was_broken
    assert "docs/" not in report.why_it_was_broken
    assert "obsolete-validation" not in report.why_the_fix_works


def test_fresh_workflow_also_prefers_recorded_diff_over_implementation_claims():
    snapshot = _revised_snapshot()
    snapshot.continuation = None
    snapshot.review_iteration = 0
    report = build_learning_report(snapshot, [(1, 0, "ActualChange.kt")])
    assert report.files_that_matter == ["ActualChange.kt"]
    assert "Why these files (ActualChange.kt)" in report.maintainer_questions[1]

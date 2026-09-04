"""Learning report, diff, and human review gates, exercised end-to-end.

Uses the real fixture engine (real git worktree, real pytest) wrapped in the
Application facade, so the learning report is grounded in the actual diff.
"""

from __future__ import annotations

import pytest

from oss_agent.app import Application
from oss_agent.domain.enums import WorkflowState
from oss_agent.learning.report import build_learning_report, render_learning_report

from tests.conftest import FULL_NAME, ISSUE_NUMBER

pytestmark = pytest.mark.integration


def _ready(engine, wid: str):
    engine.create_workflow(workflow_id=wid, repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    engine.run(wid)
    return engine.get(wid)


def test_learning_report_is_grounded_in_the_real_diff(engine):
    app = Application(engine)
    _ready(engine, "learn-1")
    report = app.learn("learn-1")

    # Grounded: real changed file, real test evidence, real title.
    assert any("stringutils" in f for f in report.files_that_matter)
    assert any("stringutils" in c for c in report.what_changed)
    assert any("+"  in c and "-" in c for c in report.what_changed)  # numstat present
    assert any("passed" in t for t in report.tests_that_prove_it)
    assert "pass" in report.why_the_fix_works.lower()
    assert report.maintainer_questions  # teaches the developer what to defend

    # Persisted on the snapshot and renderable.
    assert engine.get("learn-1").learning_report is not None
    text = render_learning_report(report)
    assert "What changed?" in text and "stringutils" in text


def test_diff_shows_the_real_change(engine):
    app = Application(engine)
    _ready(engine, "diff-1")
    diff = app.diff("diff-1")
    assert 'strip("-")' in diff  # the actual fix appears in the staged diff


def test_explain_is_concise(engine):
    app = Application(engine)
    _ready(engine, "explain-1")
    text = app.explain("explain-1")
    assert "files" in text and "tests" in text


def test_human_approve_sets_flag(engine):
    app = Application(engine)
    _ready(engine, "approve-1")
    snap = app.approve("approve-1", note="looks good")
    assert snap.human_approved is True
    assert snap.human_decision_note == "looks good"
    # Survives reload.
    assert engine.get("approve-1").human_approved is True


def test_human_reject_aborts_and_records_note(engine):
    app = Application(engine)
    engine.create_workflow(workflow_id="reject-1", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    engine.step("reject-1")
    snap = app.reject("reject-1", note="not needed")
    assert snap.state is WorkflowState.ABORTED
    reloaded = engine.get("reject-1")
    assert reloaded.human_approved is False
    assert reloaded.human_decision_note == "not needed"


def test_repository_context_is_built_and_grounded(engine):
    snap = _ready(engine, "ctx-1")
    rc = snap.repository_context
    assert rc is not None
    # Located the real implementation file and symbol from the checked-out code.
    assert any("stringutils" in f for f in rc.likely_files)
    assert any(s.name == "slugify" for s in rc.relevant_symbols)
    assert rc.notes  # inspectable


def test_context_appears_on_status_board(engine):
    from oss_agent.observability.report import render_report

    _ready(engine, "ctx-2")
    text = render_report(engine.get("ctx-2"))
    assert "CONTEXT" in text


def test_learning_report_handles_incomplete_workflow(engine):
    # Before any implementation, a report can still be built without crashing.
    engine.create_workflow(workflow_id="learn-partial", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    engine.step("learn-partial")  # only discovery
    report = build_learning_report(engine.get("learn-partial"), [])
    assert report.repository_full_name == FULL_NAME
    assert report.what_changed  # never empty (falls back gracefully)

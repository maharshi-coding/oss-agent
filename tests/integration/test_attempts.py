"""Repair-loop attempt history is persisted and inspectable."""

from __future__ import annotations

import pytest

from tests.conftest import FULL_NAME, ISSUE_NUMBER

pytestmark = pytest.mark.integration


def test_successful_fix_records_one_passing_attempt(engine):
    engine.create_workflow(workflow_id="att-ok", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    snap = engine.run("att-ok")
    assert len(snap.attempts) == 1
    only = snap.attempts[0]
    assert only.phase == "implement"
    assert only.tests_passed is True
    assert any("stringutils" in f for f in only.files_changed)
    assert only.test_duration_seconds >= 0.0


def test_repair_loop_records_every_attempt(broken_engine):
    broken_engine.create_workflow(workflow_id="att-broken", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    snap = broken_engine.run("att-broken")

    # 1 initial implement + max_debug_iterations repair cycles.
    expected = 1 + broken_engine.settings.max_debug_iterations
    assert len(snap.attempts) == expected
    assert snap.attempts[0].phase == "implement"
    assert all(a.phase == "repair" for a in snap.attempts[1:])
    assert all(a.tests_passed is False for a in snap.attempts)
    # Real captured failure evidence, not a fabricated message.
    assert snap.attempts[0].failure_summary
    # Attempt numbers are 1-based and contiguous.
    assert [a.attempt for a in snap.attempts] == list(range(1, expected + 1))


def test_attempts_survive_persistence_reload(engine):
    engine.create_workflow(workflow_id="att-persist", repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER)
    engine.run("att-persist")
    # Re-read through the repository (deserializes from the stored JSON blob).
    reloaded = engine.get("att-persist")
    assert len(reloaded.attempts) == 1
    assert reloaded.attempts[0].tests_passed is True

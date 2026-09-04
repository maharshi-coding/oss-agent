import pytest

from oss_agent.domain.enums import WorkflowState as S
from oss_agent.domain.state_machine import (
    InvalidTransitionError,
    StateMachine,
    TRANSITIONS,
)

pytestmark = pytest.mark.unit


def test_happy_path_transitions_are_allowed():
    path = [
        (S.DISCOVERY, S.REPOSITORY_ANALYSIS),
        (S.REPOSITORY_ANALYSIS, S.ISSUE_ANALYSIS),
        (S.ISSUE_ANALYSIS, S.SCORING),
        (S.SCORING, S.SELECTED),
        (S.SELECTED, S.PLANNING),
        (S.PLANNING, S.IMPLEMENTATION),
        (S.IMPLEMENTATION, S.TESTING),
        (S.TESTING, S.CODE_REVIEW),
        (S.CODE_REVIEW, S.SECURITY_REVIEW),
        (S.SECURITY_REVIEW, S.MAINTAINER_REVIEW),
        (S.MAINTAINER_REVIEW, S.READY_FOR_PR),
        (S.READY_FOR_PR, S.PR_CREATED),
        (S.PR_CREATED, S.PR_MONITORING),
        (S.PR_MONITORING, S.MERGED),
    ]
    for a, b in path:
        assert StateMachine.can_transition(a, b), f"{a}->{b} should be allowed"
        StateMachine.validate(a, b)  # must not raise


def test_review_and_debug_loops_exist():
    assert StateMachine.can_transition(S.TESTING, S.DEBUGGING)
    assert StateMachine.can_transition(S.DEBUGGING, S.TESTING)
    assert StateMachine.can_transition(S.CODE_REVIEW, S.IMPLEMENTATION)
    assert StateMachine.can_transition(S.SECURITY_REVIEW, S.IMPLEMENTATION)
    assert StateMachine.can_transition(S.MAINTAINER_REVIEW, S.IMPLEMENTATION)
    assert StateMachine.can_transition(S.CHANGES_REQUESTED, S.IMPLEMENTATION)


def test_illegal_transition_raises():
    with pytest.raises(InvalidTransitionError):
        StateMachine.validate(S.DISCOVERY, S.MERGED)
    with pytest.raises(InvalidTransitionError):
        StateMachine.validate(S.PLANNING, S.CODE_REVIEW)


def test_terminal_states_have_no_successors():
    for terminal in (S.MERGED, S.FAILED, S.ABORTED):
        assert StateMachine.is_terminal(terminal)
        assert StateMachine.next_states(terminal) == frozenset()
        with pytest.raises(InvalidTransitionError):
            StateMachine.validate(terminal, S.DISCOVERY)


def test_every_active_state_can_fail_or_abort():
    for state, targets in TRANSITIONS.items():
        if StateMachine.is_terminal(state):
            continue
        assert S.FAILED in targets
        assert S.ABORTED in targets

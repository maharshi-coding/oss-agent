"""The workflow state machine.

Transitions are declared once, here, and validated by the orchestrator before any
state change is persisted. Agents cannot change state; they only produce artifacts.
This keeps the control flow auditable and prevents an LLM from driving the workflow
into an illegal state.
"""

from __future__ import annotations

from oss_agent.domain.enums import WorkflowState as S

__all__ = [
    "TRANSITIONS",
    "InvalidTransitionError",
    "StateMachine",
]


class InvalidTransitionError(RuntimeError):
    """Raised when an illegal state transition is attempted."""

    def __init__(self, current: S, target: S) -> None:
        self.current = current
        self.target = target
        allowed = ", ".join(sorted(s.value for s in TRANSITIONS.get(current, set())))
        super().__init__(
            f"Illegal transition {current.value} -> {target.value}. "
            f"Allowed from {current.value}: [{allowed or 'none (terminal)'}]"
        )


# Every non-terminal state may also move to FAILED or ABORTED. Those are folded in
# programmatically below so the explicit table stays focused on the happy path and
# the intentional loops.
_HAPPY: dict[S, set[S]] = {
    S.DISCOVERY: {S.REPOSITORY_ANALYSIS},
    S.REPOSITORY_ANALYSIS: {S.ISSUE_ANALYSIS},
    S.ISSUE_ANALYSIS: {S.SCORING},
    # Scoring can select the opportunity, or loop back to discover more.
    S.SCORING: {S.SELECTED, S.DISCOVERY},
    S.SELECTED: {S.PLANNING},
    S.PLANNING: {S.IMPLEMENTATION},
    S.IMPLEMENTATION: {S.TESTING},
    # Testing branches: failures go to debugging, success to review.
    S.TESTING: {S.DEBUGGING, S.CODE_REVIEW},
    # Debugging loops back to testing after a fix.
    S.DEBUGGING: {S.TESTING},
    # Reviews approve forward or request changes (back to implementation loop).
    S.CODE_REVIEW: {S.SECURITY_REVIEW, S.IMPLEMENTATION},
    S.SECURITY_REVIEW: {S.MAINTAINER_REVIEW, S.IMPLEMENTATION},
    S.MAINTAINER_REVIEW: {S.READY_FOR_PR, S.IMPLEMENTATION},
    S.READY_FOR_PR: {S.PR_CREATED},
    S.PR_CREATED: {S.PR_MONITORING},
    S.PR_MONITORING: {S.CHANGES_REQUESTED, S.MERGED},
    S.CHANGES_REQUESTED: {S.IMPLEMENTATION},
    # Terminal states.
    S.MERGED: set(),
    S.FAILED: set(),
    S.ABORTED: set(),
}

_TERMINAL = {S.MERGED, S.FAILED, S.ABORTED}


def _build_transitions() -> dict[S, frozenset[S]]:
    table: dict[S, frozenset[S]] = {}
    for state, targets in _HAPPY.items():
        full = set(targets)
        if state not in _TERMINAL:
            # Any active state may fail or be aborted at any time.
            full |= {S.FAILED, S.ABORTED}
        table[state] = frozenset(full)
    return table


TRANSITIONS: dict[S, frozenset[S]] = _build_transitions()


class StateMachine:
    """Validates and describes transitions. Stateless and reusable."""

    transitions = TRANSITIONS

    @classmethod
    def next_states(cls, current: S) -> frozenset[S]:
        return cls.transitions.get(current, frozenset())

    @classmethod
    def can_transition(cls, current: S, target: S) -> bool:
        return target in cls.next_states(current)

    @classmethod
    def validate(cls, current: S, target: S) -> None:
        if current in _TERMINAL:
            raise InvalidTransitionError(current, target)
        if not cls.can_transition(current, target):
            raise InvalidTransitionError(current, target)

    @classmethod
    def is_terminal(cls, state: S) -> bool:
        return state in _TERMINAL

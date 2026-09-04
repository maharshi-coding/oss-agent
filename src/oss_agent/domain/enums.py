"""Enumerations shared across the domain layer.

These are stable, serializable string enums so they can be persisted to SQLite
and round-tripped through JSON / Pydantic without custom encoders.
"""

from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    """The canonical workflow lifecycle states.

    The valid transitions between these states are declared in
    :mod:`oss_agent.domain.state_machine`. Agents never mutate this directly;
    only the orchestrator applies a validated transition.
    """

    DISCOVERY = "DISCOVERY"
    REPOSITORY_ANALYSIS = "REPOSITORY_ANALYSIS"
    ISSUE_ANALYSIS = "ISSUE_ANALYSIS"
    SCORING = "SCORING"
    SELECTED = "SELECTED"
    PLANNING = "PLANNING"
    IMPLEMENTATION = "IMPLEMENTATION"
    TESTING = "TESTING"
    DEBUGGING = "DEBUGGING"
    CODE_REVIEW = "CODE_REVIEW"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    MAINTAINER_REVIEW = "MAINTAINER_REVIEW"
    READY_FOR_PR = "READY_FOR_PR"
    PR_CREATED = "PR_CREATED"
    PR_MONITORING = "PR_MONITORING"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    MERGED = "MERGED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATES


_TERMINAL_STATES = frozenset(
    {WorkflowState.MERGED, WorkflowState.FAILED, WorkflowState.ABORTED}
)


class AgentName(str, Enum):
    """Identifiers for each specialized agent."""

    ORCHESTRATOR = "orchestrator"
    GITHUB_DISCOVERY = "github-discovery"
    REPOSITORY_ANALYZER = "repository-analyzer"
    ISSUE_ANALYZER = "issue-analyzer"
    CONTRIBUTION_SCORER = "contribution-scorer"
    PLANNER = "planner"
    IMPLEMENTER = "implementer"
    TEST_ENGINEER = "test-engineer"
    DEBUGGER = "debugger"
    CODE_REVIEWER = "code-reviewer"
    SECURITY_REVIEWER = "security-reviewer"
    MAINTAINER_SIMULATOR = "maintainer-simulator"
    PR_MANAGER = "pr-manager"
    PR_MONITOR = "pr-monitor"


class ContributionType(str, Enum):
    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    DOCUMENTATION = "documentation"
    TEST = "test"
    REFACTOR = "refactor"
    PERFORMANCE = "performance"
    DEPENDENCY = "dependency"
    CI = "ci"
    CHORE = "chore"


class ExperienceLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class Difficulty(str, Enum):
    TRIVIAL = "trivial"
    EASY = "easy"
    MODERATE = "moderate"
    HARD = "hard"
    ANY = "any"


class ProjectSize(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    ANY = "any"


class Recommendation(str, Enum):
    STRONG_PURSUE = "STRONG_PURSUE"
    PURSUE = "PURSUE"
    CONSIDER = "CONSIDER"
    SKIP = "SKIP"


class SuitabilityCategory(str, Enum):
    """Whether a contribution *should* be pursued — distinct from how well it
    scores technically. Ordered from most to least appropriate."""

    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INVESTIGATE_ONLY = "INVESTIGATE_ONLY"
    SKIP = "SKIP"
    BLOCKED = "BLOCKED"

    @property
    def should_proceed(self) -> bool:
        """Whether the automated workflow may proceed to implementation.

        INVESTIGATE_ONLY, SKIP and BLOCKED stop automation (the issue needs a
        human decision or a maintainer discussion first)."""
        return self in _PROCEED_CATEGORIES


_PROCEED_CATEGORIES = frozenset(
    {
        SuitabilityCategory.EXCELLENT,
        SuitabilityCategory.GOOD,
        SuitabilityCategory.REVIEW_REQUIRED,
    }
)


class ReviewVerdict(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    REJECT = "REJECT"


class MaintainerVerdict(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    REJECT = "REJECT"


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class EventType(str, Enum):
    """Kinds of auditable workflow events."""

    WORKFLOW_CREATED = "workflow_created"
    STATE_TRANSITION = "state_transition"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    COMMAND_EXECUTED = "command_executed"
    SAFETY_BLOCKED = "safety_blocked"
    SAFETY_FLAGGED = "safety_flagged"
    WORKTREE_CREATED = "worktree_created"
    WORKTREE_REMOVED = "worktree_removed"
    PR_CREATED = "pr_created"
    ERROR = "error"
    NOTE = "note"

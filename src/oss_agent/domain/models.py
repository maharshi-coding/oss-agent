"""Domain models and agent output contracts.

Every agent returns a structured payload that validates against one of the
contracts defined here. Human-readable explanation is carried in the ``summary``
field on :class:`AgentArtifact`; it accompanies but never replaces the structured
data.

Naming note: the workflow *lifecycle states* live in the
:class:`~oss_agent.domain.enums.WorkflowState` enum. The persisted workflow
*aggregate* is :class:`WorkflowSnapshot` here to avoid a name collision. This
decision is recorded in ``docs/architecture.md``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from oss_agent.domain.enums import (
    AgentName,
    ContributionType,
    Difficulty,
    EventType,
    MaintainerVerdict,
    Recommendation,
    ReviewVerdict,
    Severity,
    SuitabilityCategory,
    WorkflowState,
)


def utcnow() -> datetime:
    """Timezone-aware UTC now (single source of truth for timestamps)."""
    return datetime.now(timezone.utc)


class _Base(BaseModel):
    """Shared config: forbid silent typos, allow enum values on dump."""

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=False,
        validate_assignment=True,
    )


class AgentArtifact(_Base):
    """Base for every agent contract.

    ``summary`` is the human-readable explanation; ``confidence`` is the agent's
    self-assessed confidence in [0, 1].
    """

    summary: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# --------------------------------------------------------------------------- #
# Core external entities
# --------------------------------------------------------------------------- #
class Repository(_Base):
    """A GitHub repository reference plus lightweight health signals."""

    owner: str
    name: str
    default_branch: str = "main"
    url: Optional[str] = None
    description: Optional[str] = None
    primary_language: Optional[str] = None
    languages: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    license: Optional[str] = None
    archived: bool = False
    pushed_at: Optional[datetime] = None

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @field_validator("owner", "name")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or "/" in v:
            raise ValueError("owner/name must be non-empty and contain no slash")
        return v


class Issue(_Base):
    """A GitHub issue."""

    number: int = Field(ge=1)
    title: str
    body: str = ""
    state: str = "open"
    labels: list[str] = Field(default_factory=list)
    author: Optional[str] = None
    assignees: list[str] = Field(default_factory=list)
    comments: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    url: Optional[str] = None
    linked_pr_numbers: list[int] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Agent contracts
# --------------------------------------------------------------------------- #
class DiscoveryCandidate(_Base):
    repository: Repository
    issue: Issue
    reason: str = ""
    preliminary_signal: float = Field(default=0.0, ge=0.0, le=1.0)


class DiscoveryResult(AgentArtifact):
    """Output of the github-discovery agent."""

    query: str = ""
    candidates: list[DiscoveryCandidate] = Field(default_factory=list)
    filtered_out: int = 0

    @property
    def count(self) -> int:
        return len(self.candidates)


class RepositoryReport(AgentArtifact):
    """Structured repository intelligence report."""

    repository: Repository
    has_readme: bool = False
    has_contributing: bool = False
    has_code_of_conduct: bool = False
    has_security_policy: bool = False
    has_tests: bool = False
    has_ci: bool = False
    license: Optional[str] = None
    build_system: Optional[str] = None
    package_managers: list[str] = Field(default_factory=list)
    test_command: Optional[str] = None
    lint_command: Optional[str] = None
    typecheck_command: Optional[str] = None
    build_command: Optional[str] = None
    conventions: list[str] = Field(default_factory=list)
    architecture_notes: list[str] = Field(default_factory=list)
    contributing_requirements: list[str] = Field(default_factory=list)
    health_signals: dict[str, Any] = Field(default_factory=dict)
    # Anything in the repo that looked like an instruction to the agent.
    injection_flags: list[str] = Field(default_factory=list)


class IssueAnalysis(AgentArtifact):
    """Structured interpretation of an issue."""

    repository_full_name: str
    issue_number: int = Field(ge=1)
    problem_statement: str = ""
    expected_behavior: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    affected_components: list[str] = Field(default_factory=list)
    probable_files: list[str] = Field(default_factory=list)
    contribution_type: ContributionType = ContributionType.BUG_FIX
    difficulty: Difficulty = Difficulty.MODERATE
    test_requirements: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    ambiguity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    is_ambiguous: bool = False
    duplicate_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    breaking_change_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    security_sensitivity: float = Field(default=0.0, ge=0.0, le=1.0)
    complexity: float = Field(default=0.3, ge=0.0, le=1.0)
    injection_flags: list[str] = Field(default_factory=list)


class ScoreComponent(_Base):
    dimension: str
    raw: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0)
    weighted: float
    explanation: str = ""


class PenaltyComponent(_Base):
    name: str
    amount: float = Field(ge=0.0)
    explanation: str = ""


class ContributionScore(AgentArtifact):
    """Quantitative opportunity score in [0, 100]."""

    repository_full_name: str
    issue_number: int = Field(ge=1)
    overall: float = Field(ge=0.0, le=100.0)
    base_score: float = Field(ge=0.0, le=100.0)
    components: list[ScoreComponent] = Field(default_factory=list)
    penalties: list[PenaltyComponent] = Field(default_factory=list)
    recommendation: Recommendation = Recommendation.SKIP
    explanation: str = ""

    @property
    def total_penalty(self) -> float:
        return round(sum(p.amount for p in self.penalties), 2)


class SymbolRef(_Base):
    """A located code symbol (function/class) relevant to an issue."""

    name: str
    kind: str = "function"  # function | class | method
    file: str
    line: int = Field(default=1, ge=1)


class RepositoryContext(AgentArtifact):
    """Compact, inspectable repository understanding built *before* implementation.

    Produced by deterministic context selection (filename/keyword/symbol search
    over the real checked-out code), not by the model — so the AI backend is given
    a focused, grounded slice of the repository instead of the whole thing or only
    the issue text.
    """

    repository_full_name: str
    keywords: list[str] = Field(default_factory=list)
    likely_files: list[str] = Field(default_factory=list)
    related_tests: list[str] = Field(default_factory=list)
    relevant_symbols: list[SymbolRef] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SuitabilitySignal(_Base):
    """One weighted signal in a contribution-suitability assessment."""

    name: str
    raw: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0)
    weighted: float
    kind: str = "neutral"  # positive | concern | neutral
    explanation: str = ""


class SuitabilityAssessment(AgentArtifact):
    """Whether a contribution *should* be made — the anti-"PR spam" gate.

    Distinct from :class:`ContributionScore` (technical fit): this weighs
    maintainer intent, existing/conflicting work, issue clarity, staleness,
    repository etiquette, and skill match into a human-readable recommendation.
    """

    repository_full_name: str
    issue_number: int = Field(ge=1)
    category: SuitabilityCategory = SuitabilityCategory.REVIEW_REQUIRED
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    signals: list[SuitabilitySignal] = Field(default_factory=list)
    positives: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    explanation: str = ""

    @property
    def should_proceed(self) -> bool:
        return self.category.should_proceed


class PlanStep(_Base):
    order: int = Field(ge=1)
    description: str
    target_files: list[str] = Field(default_factory=list)
    rationale: str = ""


class ImplementationPlan(AgentArtifact):
    """Machine-readable implementation plan."""

    repository_full_name: str
    issue_number: int = Field(ge=1)
    objective: str
    contribution_type: ContributionType = ContributionType.BUG_FIX
    branch_name: str
    affected_files: list[str] = Field(default_factory=list)
    do_not_modify: list[str] = Field(default_factory=list)
    steps: list[PlanStep] = Field(default_factory=list)
    test_plan: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    rollback_strategy: str = ""


class FileChange(_Base):
    path: str
    change_type: str = "modified"  # added | modified | deleted
    additions: int = 0
    deletions: int = 0


class ImplementationResult(AgentArtifact):
    """What the implementer/debugger actually changed in the worktree."""

    plan_branch: str
    files_changed: list[FileChange] = Field(default_factory=list)
    unexpected_files: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ImplementationAttempt(_Base):
    """One iteration of the implement → test (→ repair) loop.

    Persisted per cycle so the whole repair history is inspectable
    (``oss-agent attempts``), not just the final state. Evidence is derived from
    git and captured test results — never the model's self-report.
    """

    attempt: int = Field(ge=1)
    phase: str = "implement"  # implement | repair
    files_changed: list[str] = Field(default_factory=list)
    unexpected_files: list[str] = Field(default_factory=list)
    tests_passed: bool = False
    tests_summary: str = ""
    failure_summary: str = ""
    notes: list[str] = Field(default_factory=list)
    test_duration_seconds: float = 0.0
    recorded_at: datetime = Field(default_factory=utcnow)


class CommandOutcome(_Base):
    """A captured command execution (mirror of execution.CommandResult)."""

    command: list[str]
    cwd: str
    exit_code: int
    duration_seconds: float
    stdout_tail: str = ""
    stderr_tail: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class TestSuiteResult(_Base):
    name: str  # e.g. "pytest", "ruff", "mypy", "build"
    kind: str  # unit | integration | lint | format | typecheck | build | static
    passed: bool
    # A suite is "skipped" when its tool is not available (exit 127). Skipped
    # suites are excluded from the pass/fail gate rather than failing it, but are
    # recorded so nothing is hidden.
    skipped: bool = False
    tests_total: Optional[int] = None
    tests_passed: Optional[int] = None
    tests_failed: Optional[int] = None
    command: CommandOutcome


class TestResult(AgentArtifact):
    """Captured, never inferred, test/quality results."""

    repository_full_name: str
    suites: list[TestSuiteResult] = Field(default_factory=list)

    @property
    def executed_suites(self) -> list[TestSuiteResult]:
        return [s for s in self.suites if not s.skipped]

    @property
    def passed(self) -> bool:
        executed = self.executed_suites
        return bool(executed) and all(s.passed for s in executed)

    @property
    def failed_suites(self) -> list[TestSuiteResult]:
        return [s for s in self.suites if not s.passed and not s.skipped]

    @property
    def skipped_suites(self) -> list[TestSuiteResult]:
        return [s for s in self.suites if s.skipped]

    @property
    def total_tests_passed(self) -> int:
        return sum(s.tests_passed or 0 for s in self.suites)


class ReviewFinding(_Base):
    category: str
    severity: Severity = Severity.LOW
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    suggestion: str = ""


class ReviewResult(AgentArtifact):
    """Independent code review verdict."""

    verdict: ReviewVerdict = ReviewVerdict.REQUEST_CHANGES
    findings: list[ReviewFinding] = Field(default_factory=list)
    scope_ok: bool = True
    tests_adequate: bool = True

    @property
    def blocking_findings(self) -> list[ReviewFinding]:
        return [f for f in self.findings if f.severity.rank >= Severity.HIGH.rank]


class SecurityFinding(_Base):
    category: str  # secret | injection | shell | path | authz | dependency | ...
    severity: Severity = Severity.LOW
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    evidence: str = ""


class SecurityResult(AgentArtifact):
    """Security + prompt-injection review verdict."""

    verdict: ReviewVerdict = ReviewVerdict.APPROVE
    findings: list[SecurityFinding] = Field(default_factory=list)
    secrets_detected: bool = False
    prompt_injection_detected: bool = False

    @property
    def blocking_findings(self) -> list[SecurityFinding]:
        return [f for f in self.findings if f.severity.rank >= Severity.HIGH.rank]


class MaintainerReview(AgentArtifact):
    """A simulated maintainer's verdict on the whole contribution."""

    verdict: MaintainerVerdict = MaintainerVerdict.REQUEST_CHANGES
    reasons: list[str] = Field(default_factory=list)
    requested_changes: list[str] = Field(default_factory=list)
    praise: list[str] = Field(default_factory=list)


class LearningReport(AgentArtifact):
    """A structured explanation of the contribution, grounded in the real diff,
    plan, and captured test evidence. Learning is a primary product goal: the
    developer should understand a change well enough to defend it to a maintainer
    before it is ever submitted."""

    repository_full_name: str
    issue_number: int = Field(ge=1)
    title: str = ""
    what_was_broken: str = ""
    why_it_was_broken: str = ""
    how_discovered: str = ""
    files_that_matter: list[str] = Field(default_factory=list)
    what_changed: list[str] = Field(default_factory=list)
    why_the_fix_works: str = ""
    tests_that_prove_it: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    edge_cases_remaining: list[str] = Field(default_factory=list)
    concepts_to_understand: list[str] = Field(default_factory=list)
    maintainer_questions: list[str] = Field(default_factory=list)


class PullRequestResult(AgentArtifact):
    """Result of opening a pull request."""

    repository_full_name: str
    issue_number: int = Field(ge=1)
    branch: str
    number: Optional[int] = None
    url: Optional[str] = None
    title: str = ""
    body: str = ""
    draft: bool = False
    created: bool = False


# --------------------------------------------------------------------------- #
# Workflow aggregate (the persisted record)
# --------------------------------------------------------------------------- #
class WorkflowEvent(_Base):
    """A single auditable event on a workflow's timeline."""

    type: EventType
    at: datetime = Field(default_factory=utcnow)
    agent: Optional[AgentName] = None
    state: Optional[WorkflowState] = None
    action: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class AgentExecution(_Base):
    """Record of one agent invocation."""

    agent: AgentName
    state: WorkflowState
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None
    success: bool = False
    error: Optional[str] = None
    duration_seconds: float = 0.0
    output_kind: Optional[str] = None


class WorkflowSnapshot(AgentArtifact):
    """The full, resumable workflow aggregate.

    This is what is persisted and what ``oss-agent status`` renders. It contains
    the current state plus every artifact produced along the way, so the workflow
    can resume from its last valid state after a crash.
    """

    id: str
    state: WorkflowState = WorkflowState.DISCOVERY
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    repository_full_name: Optional[str] = None
    issue_number: Optional[int] = None

    review_iteration: int = 0
    debug_iteration: int = 0

    worktree_path: Optional[str] = None
    branch: Optional[str] = None

    # Artifacts (populated as the workflow progresses).
    repository: Optional[Repository] = None
    issue: Optional[Issue] = None
    repository_report: Optional[RepositoryReport] = None
    issue_analysis: Optional[IssueAnalysis] = None
    score: Optional[ContributionScore] = None
    suitability: Optional[SuitabilityAssessment] = None
    repository_context: Optional[RepositoryContext] = None
    plan: Optional[ImplementationPlan] = None
    implementation: Optional[ImplementationResult] = None
    attempts: list[ImplementationAttempt] = Field(default_factory=list)
    test_result: Optional[TestResult] = None
    code_review: Optional[ReviewResult] = None
    security_review: Optional[SecurityResult] = None
    maintainer_review: Optional[MaintainerReview] = None
    learning_report: Optional[LearningReport] = None
    pull_request: Optional[PullRequestResult] = None

    # Human-in-the-loop decision. Publishing requires an explicit approval; a
    # rejection aborts the workflow. Defaults preserve backwards compatibility.
    human_approved: bool = False
    human_decision_note: Optional[str] = None

    executions: list[AgentExecution] = Field(default_factory=list)
    events: list[WorkflowEvent] = Field(default_factory=list)
    last_error: Optional[str] = None

    def touch(self) -> None:
        self.updated_at = utcnow()

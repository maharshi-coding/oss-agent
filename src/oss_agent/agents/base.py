"""Agent runtime abstraction.

An :class:`AgentRunner` turns deterministic inputs (the workflow snapshot, the
GitHub client, the git service, the isolated worktree) into the structured
reasoning artifacts defined in :mod:`oss_agent.domain.models`. Two runners exist:

* :class:`~oss_agent.agents.mock_runner.MockAgentRunner` — deterministic,
  in-process, offline. Read-only agents use real heuristics; the *implementer*
  delegates to an injected solution strategy (the test/offline adapter).
* :class:`~oss_agent.agents.claude_runner.ClaudeAgentRunner` — the production
  path that invokes the Claude Code CLI as a subprocess.

The orchestrator depends only on the :class:`AgentRunner` protocol, never on a
concrete runner or on any LLM SDK.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from oss_agent.config.profile import DeveloperProfile
from oss_agent.config.settings import Settings
from oss_agent.domain.models import (
    DiscoveryResult,
    ImplementationPlan,
    ImplementationResult,
    IssueAnalysis,
    MaintainerReview,
    PullRequestResult,
    RepositoryContext,
    RepositoryReport,
    ReviewResult,
    SecurityResult,
    TestResult,
    WorkflowSnapshot,
)
from oss_agent.git.service import GitService
from oss_agent.github.interface import GitHubClient
from oss_agent.scoring.engine import ScoringEngine
from oss_agent.worktrees.manager import WorktreeHandle


class AgentError(RuntimeError):
    """Raised when an agent cannot produce a valid artifact."""


class NoSolutionError(AgentError):
    """The offline mock implementer has no registered solution for this workflow."""


class BackendUnavailableError(AgentError):
    """The AI coding backend (e.g. the ``claude`` CLI) is not installed or
    reachable. Distinct from a backend that ran but failed, so the CLI can tell
    the user to install/authenticate the backend rather than debug a workflow."""


class BackendTimeoutError(AgentError):
    """The AI coding backend was invoked but exceeded its time budget. The
    workflow state is preserved so it can be resumed."""


@dataclass
class AgentContext:
    """Everything an agent may read. Agents never mutate the snapshot directly;
    they return artifacts that the orchestrator records."""

    snapshot: WorkflowSnapshot
    settings: Settings
    github: GitHubClient
    git: GitService
    profile: DeveloperProfile
    scoring: ScoringEngine
    worktree: Optional[WorktreeHandle] = None
    discovery_query: Optional[str] = None
    max_candidates: int = 10
    repository_context: Optional[RepositoryContext] = None


@runtime_checkable
class AgentRunner(Protocol):
    """The reasoning surface. Each method returns a validated contract artifact."""

    def discover(self, ctx: AgentContext) -> DiscoveryResult: ...
    def analyze_repository(self, ctx: AgentContext) -> RepositoryReport: ...
    def analyze_issue(self, ctx: AgentContext) -> IssueAnalysis: ...
    def plan(self, ctx: AgentContext) -> ImplementationPlan: ...
    def implement(self, ctx: AgentContext) -> ImplementationResult: ...
    def debug(self, ctx: AgentContext, test_result: TestResult) -> ImplementationResult: ...
    def review_code(self, ctx: AgentContext) -> ReviewResult: ...
    def review_security(self, ctx: AgentContext) -> SecurityResult: ...
    def maintainer_review(self, ctx: AgentContext) -> MaintainerReview: ...
    def compose_pull_request(self, ctx: AgentContext) -> PullRequestResult: ...

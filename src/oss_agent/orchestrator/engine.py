"""The workflow engine: the deterministic controller.

The engine owns the state machine, delegates reasoning to agents, runs real tests,
enforces safety gates and bounded loops, and persists after every step so any
workflow can resume from its last valid state. Agents never change workflow state;
only the engine applies a :class:`StateMachine`-validated transition.
"""

from __future__ import annotations

import uuid
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional

from oss_agent.agents.base import AgentContext, AgentError, AgentRunner
from oss_agent.config.profile import DeveloperProfile
from oss_agent.config.settings import Settings
from oss_agent.context.builder import RepositoryContextBuilder
from oss_agent.context.sources import LocalFileSource
from oss_agent.domain.enums import (
    AgentName,
    EventType,
    MaintainerVerdict,
    Recommendation,
    ReviewVerdict,
    WorkflowState as S,
)
from oss_agent.domain.models import (
    AgentExecution,
    ImplementationAttempt,
    Issue,
    PullRequestContinuation,
    Repository,
    TestResult,
    WorkflowEvent,
    WorkflowSnapshot,
    utcnow,
)
from oss_agent.domain.state_machine import InvalidTransitionError, StateMachine
from oss_agent.events.bus import EventBus, default_bus
from oss_agent.execution.test_engineer import TestEngineer
from oss_agent.git.naming import branch_name_for
from oss_agent.git.service import GitService
from oss_agent.github.interface import GitHubClient, GitHubError
from oss_agent.observability.logging import get_logger
from oss_agent.orchestrator.repo_provider import RepoProvider
from oss_agent.persistence.repository import WorkflowRepository
from oss_agent.scoring.engine import ScoringEngine
from oss_agent.suitability.engine import SuitabilityEngine
from oss_agent.worktrees.manager import WorktreeHandle, WorktreeManager

logger = get_logger("orchestrator")

# States at which `run` pauses by default (PR creation is a separate, gated step).
DEFAULT_STOP_STATES = frozenset({S.READY_FOR_PR, S.PR_CREATED, S.PR_MONITORING})


class OrchestrationError(RuntimeError):
    pass


class HumanApprovalRequired(OrchestrationError):
    """Submission was attempted without the required explicit human approval."""


class SubmissionBlocked(OrchestrationError):
    """A final pre-submission conflict check found a reason not to submit."""


class WorkflowEngine:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: WorkflowRepository,
        github: GitHubClient,
        git: GitService,
        worktrees: WorktreeManager,
        runner: AgentRunner,
        test_engineer: TestEngineer,
        scoring: ScoringEngine,
        profile: DeveloperProfile,
        repo_provider: RepoProvider,
        event_bus: Optional[EventBus] = None,
        suitability: Optional[SuitabilityEngine] = None,
    ) -> None:
        self.settings = settings
        self.repo = repository
        self.github = github
        self.git = git
        self.worktrees = worktrees
        self.runner = runner
        self.test_engineer = test_engineer
        self.scoring = scoring
        self.suitability = suitability or SuitabilityEngine()
        self.context_builder = RepositoryContextBuilder()
        self.profile = profile
        self.repo_provider = repo_provider
        self.bus = event_bus or default_bus()

    # -- lifecycle ------------------------------------------------------------
    def create_workflow(
        self,
        *,
        workflow_id: Optional[str] = None,
        repository_full_name: Optional[str] = None,
        issue_number: Optional[int] = None,
        user_instructions: str = "",
        related_pr_numbers: Optional[list[int]] = None,
        existing_pr_number: Optional[int] = None,
    ) -> WorkflowSnapshot:
        wid = workflow_id or self._new_id()
        if self.repo.exists(wid):
            raise OrchestrationError(f"workflow already exists: {wid}")
        snapshot = WorkflowSnapshot(
            id=wid,
            state=S.DISCOVERY,
            repository_full_name=repository_full_name,
            issue_number=issue_number,
            user_instructions=user_instructions,
            related_pr_numbers=list(related_pr_numbers or []),
            existing_pr_number=existing_pr_number,
        )
        self._emit(snapshot, EventType.WORKFLOW_CREATED, action="workflow created")
        self.repo.save(snapshot)
        return snapshot

    def _new_id(self) -> str:
        year = datetime.now(timezone.utc).year
        return f"oss-{year}-{uuid.uuid4().hex[:8]}"

    def get(self, workflow_id: str) -> WorkflowSnapshot:
        snap = self.repo.get(workflow_id)
        if snap is None:
            raise OrchestrationError(f"workflow not found: {workflow_id}")
        return snap

    # -- driving --------------------------------------------------------------
    def run(
        self,
        workflow_id: str,
        *,
        stop_states: frozenset[S] = DEFAULT_STOP_STATES,
        max_steps: int = 60,
    ) -> WorkflowSnapshot:
        snapshot = self.get(workflow_id)
        steps = 0
        while steps < max_steps:
            if StateMachine.is_terminal(snapshot.state) or snapshot.state in stop_states:
                break
            snapshot = self.step(workflow_id)
            steps += 1
        return snapshot

    def resume(self, workflow_id: str, **kwargs) -> WorkflowSnapshot:
        """Resume from the persisted last valid state (identical to run)."""
        snapshot = self.get(workflow_id)
        logger.info("resuming workflow", extra={"workflow_id": workflow_id, "state": snapshot.state.value})
        return self.run(workflow_id, **kwargs)

    def step(self, workflow_id: str) -> WorkflowSnapshot:
        """Execute exactly one state's work and persist the result."""
        snapshot = self.get(workflow_id)
        state = snapshot.state
        handler = self._handlers().get(state)
        if handler is None:
            raise OrchestrationError(f"no handler for state {state.value}")
        try:
            next_state = handler(snapshot)
            self._transition(snapshot, next_state)
        except (AgentError, GitHubError, InvalidTransitionError, OrchestrationError) as exc:
            self._fail(snapshot, str(exc))
        except Exception as exc:  # unexpected — still fail loud & persisted
            logger.exception("unexpected error in state %s", state.value)
            self._fail(snapshot, f"unexpected error: {exc}")
        self.repo.save(snapshot)
        return snapshot

    def abort(self, workflow_id: str, reason: str = "aborted by user") -> WorkflowSnapshot:
        snapshot = self.get(workflow_id)
        if StateMachine.is_terminal(snapshot.state):
            return snapshot
        snapshot.last_error = reason
        self._transition(snapshot, S.ABORTED, action=reason)
        self._cleanup_worktree(snapshot)
        self.repo.save(snapshot)
        return snapshot

    # -- state handlers -------------------------------------------------------
    def _handlers(self):
        return {
            S.DISCOVERY: self._h_discovery,
            S.REPOSITORY_ANALYSIS: self._h_repository_analysis,
            S.ISSUE_ANALYSIS: self._h_issue_analysis,
            S.SCORING: self._h_scoring,
            S.SELECTED: self._h_selected,
            S.PLANNING: self._h_planning,
            S.IMPLEMENTATION: self._h_implementation,
            S.TESTING: self._h_testing,
            S.DEBUGGING: self._h_debugging,
            S.CODE_REVIEW: self._h_code_review,
            S.SECURITY_REVIEW: self._h_security_review,
            S.MAINTAINER_REVIEW: self._h_maintainer_review,
            S.CHANGES_REQUESTED: self._h_changes_requested,
        }

    def _h_discovery(self, s: WorkflowSnapshot) -> S:
        if s.repository_full_name and s.issue_number:
            # Targeted workflow: fetch the specific repo + issue.
            repo = self.github.get_repository(s.repository_full_name)
            issue = self.github.get_issue(s.repository_full_name, s.issue_number)
            s.repository, s.issue = repo, issue
        else:
            ctx = self._context(s)
            result = self._run_agent(s, AgentName.GITHUB_DISCOVERY, lambda: self.runner.discover(ctx), "DiscoveryResult")
            if not result.candidates:
                raise OrchestrationError("no suitable candidates discovered")
            best = result.candidates[0]
            s.repository, s.issue = best.repository, best.issue
            s.repository_full_name = best.repository.full_name
            s.issue_number = best.issue.number
        if s.existing_pr_number:
            s.continuation = self._verify_continuation_target(s)
            if s.existing_pr_number not in s.related_pr_numbers:
                s.related_pr_numbers.append(s.existing_pr_number)
            self._emit(s, EventType.NOTE, action=f"adopting owned existing PR #{s.existing_pr_number}",
                       detail=s.continuation.model_dump())
        dup = self._duplicate_reason(s)
        if dup:
            self._emit(s, EventType.SAFETY_BLOCKED, action=f"duplicate: {dup}")
            s.last_error = f"duplicate contribution: {dup}"
            return S.ABORTED
        return S.REPOSITORY_ANALYSIS

    def _h_repository_analysis(self, s: WorkflowSnapshot) -> S:
        ctx = self._context(s)
        report = self._run_agent(s, AgentName.REPOSITORY_ANALYZER, lambda: self.runner.analyze_repository(ctx), "RepositoryReport")
        s.repository_report = report
        if report.injection_flags:
            self._emit(s, EventType.SAFETY_FLAGGED, action="prompt-injection flags in repo content",
                       detail={"flags": report.injection_flags})
        return S.ISSUE_ANALYSIS

    def _h_issue_analysis(self, s: WorkflowSnapshot) -> S:
        ctx = self._context(s)
        analysis = self._run_agent(s, AgentName.ISSUE_ANALYZER, lambda: self.runner.analyze_issue(ctx), "IssueAnalysis")
        analysis.repository_full_name = s.repository_full_name or analysis.repository_full_name
        s.issue_analysis = analysis
        if analysis.injection_flags:
            self._emit(s, EventType.SAFETY_FLAGGED, action="prompt-injection flags in issue content",
                       detail={"flags": analysis.injection_flags})
        if analysis.ambiguity_score >= 0.8:
            s.last_error = "issue requirements are fundamentally ambiguous"
            self._emit(s, EventType.NOTE, action="stopping: ambiguous issue")
            return S.ABORTED
        return S.SCORING

    def _h_scoring(self, s: WorkflowSnapshot) -> S:
        if not (s.issue_analysis and s.repository_report):
            raise OrchestrationError("scoring requires issue analysis and repository report")
        score = self.scoring.score(s.issue_analysis, s.repository_report, self.profile, issue=s.issue)
        s.score = score
        self._record_execution(s, AgentName.CONTRIBUTION_SCORER, "ContributionScore", success=True)
        self._emit(s, EventType.NOTE, action=f"score {score.overall}/100 ({score.recommendation.value})")

        # Contribution-suitability gate: whether a contribution *should* be made
        # here at all (existing PRs, assignment, maintainer intent, staleness,
        # and whether a comment says someone is already working on it). This is
        # the anti-"PR spam" guard and runs even when the technical score is high.
        suitability_issue = s.issue
        if s.continuation and s.issue:
            # The adopted PR is the review target, not a second contribution.
            # All OTHER linked work and the live agent's duplicate risk remain.
            suitability_issue = s.issue.model_copy(update={
                "linked_pr_numbers": [n for n in s.issue.linked_pr_numbers if n != s.continuation.number],
            })
        assessment = self.suitability.assess(
            s.issue_analysis, s.repository_report, self.profile, issue=suitability_issue,
            comment_bodies=self._issue_comment_bodies(s),
        )
        s.suitability = assessment
        self._record_execution(s, AgentName.CONTRIBUTION_SCORER, "SuitabilityAssessment", success=True)
        self._emit(s, EventType.NOTE,
                   action=f"suitability {assessment.category.value} ({assessment.score:.0f}/100)")
        if not assessment.should_proceed:
            reason = f"contribution not recommended: {assessment.category.value} — {assessment.explanation}"
            s.last_error = reason
            self._emit(s, EventType.SAFETY_BLOCKED, action=reason)
            return S.ABORTED

        if score.recommendation is Recommendation.SKIP:
            s.last_error = f"score below threshold: {score.overall}"
            return S.ABORTED
        return S.SELECTED

    def _h_selected(self, s: WorkflowSnapshot) -> S:
        assert s.repository_full_name and s.issue_number and s.issue_analysis
        default_branch = s.repository.default_branch if s.repository else "main"
        base_repo = self.repo_provider.ensure_local(s.repository_full_name, default_branch=default_branch)
        branch = branch_name_for(s.issue_number, s.issue_analysis.contribution_type)
        base = default_branch
        if s.continuation:
            current = self._verify_continuation_target(s)
            if current != s.continuation:
                raise OrchestrationError("adopted PR metadata changed; create a new workflow")
            base = self.git.fetch_pull_request(
                base_repo, s.repository_full_name, current.number, current.head_sha,
            )
            # Fetch the exact upstream base for full-delta review, independently
            # of the fork and without switching the user's checkout.
            fetched_base = self.git.fetch_ref(
                base_repo, f"https://github.com/{s.repository_full_name}.git",
                f"refs/heads/{current.base_branch}",
            )
            if fetched_base != current.base_sha:
                raise OrchestrationError("upstream base changed while fetching; create a new workflow")
            s.review_base_sha = self.git.merge_base(base_repo, current.base_sha, current.head_sha)
            branch = f"continue/pr-{current.number}/{s.id}"
        handle = self.worktrees.create(base_repo, s.id, branch, base=base)
        if s.continuation and self.git.head_sha(handle.path) != s.continuation.head_sha:
            raise OrchestrationError("existing continuation worktree does not match adopted PR head")
        s.worktree_path = handle.path
        s.branch = handle.branch
        self._emit(s, EventType.WORKTREE_CREATED, action=f"worktree at {handle.path}",
                   detail={"branch": handle.branch, "reused": not handle.created})
        # Build a focused repository-context slice from the real checked-out code,
        # so planning/implementation reason over relevant files/symbols — not the
        # whole repo or just the issue text. Deterministic; never fails the step.
        try:
            ctx = self.context_builder.build(
                LocalFileSource(handle.path), s.issue_analysis,
                repository_full_name=s.repository_full_name or "",
            )
            s.repository_context = ctx
            self._emit(s, EventType.NOTE, action=f"context built: {ctx.summary}")
        except Exception as exc:  # context is an aid, not a gate
            logger.warning("context build failed", extra={"error": str(exc)})
        return S.PLANNING

    def _h_planning(self, s: WorkflowSnapshot) -> S:
        ctx = self._context(s)
        plan = self._run_agent(s, AgentName.PLANNER, lambda: self.runner.plan(ctx), "ImplementationPlan")
        s.plan = plan
        # Do NOT adopt plan.branch_name as s.branch. The worktree was already
        # created in SELECTED on the deterministic branch (branch_name_for), and
        # that is the only branch that actually exists in git. A real planner
        # (Claude) often suggests a semantic name (e.g. "fix/power-function-
        # exponentiation"); adopting it here desynchronizes the snapshot from the
        # real worktree branch and breaks the push at PR time ("src refspec ...
        # does not match any"), plus the duplicate/conflict checks that key off
        # the deterministic name. The suggestion is retained on s.plan.branch_name
        # for reference only. (Surfaced by live validation; the mock planner never
        # returned a divergent name so this was invisible before.)
        return S.IMPLEMENTATION

    def _h_implementation(self, s: WorkflowSnapshot) -> S:
        ctx = self._context(s)
        impl = self._run_agent(s, AgentName.IMPLEMENTER, lambda: self.runner.implement(ctx), "ImplementationResult")
        s.implementation = impl
        return S.TESTING

    def _h_testing(self, s: WorkflowSnapshot) -> S:
        if not (s.repository_report and s.worktree_path):
            raise OrchestrationError("testing requires a repository report and worktree")
        result = self.test_engineer.run(s.repository_report, s.worktree_path)
        s.test_result = result
        self._record_execution(s, AgentName.TEST_ENGINEER, "TestResult", success=result.passed)
        self._record_attempt(s, result)
        self._emit(s, EventType.COMMAND_EXECUTED, action=result.summary,
                   detail={"passed": result.passed})
        if result.passed:
            if s.continuation:
                s.validated_diff_digest = self._continuation_diff_digest(s)
            return S.CODE_REVIEW
        if s.debug_iteration >= self.settings.max_debug_iterations:
            s.last_error = f"tests still failing after {s.debug_iteration} debug iteration(s)"
            return S.FAILED
        return S.DEBUGGING

    def _h_debugging(self, s: WorkflowSnapshot) -> S:
        s.debug_iteration += 1
        ctx = self._context(s)
        impl = self._run_agent(
            s, AgentName.DEBUGGER, lambda: self.runner.debug(ctx, s.test_result), "ImplementationResult"
        )
        s.implementation = impl
        return S.TESTING

    def _h_code_review(self, s: WorkflowSnapshot) -> S:
        ctx = self._context(s)
        review = self._run_agent(s, AgentName.CODE_REVIEWER, lambda: self.runner.review_code(ctx), "ReviewResult")
        s.code_review = review
        if review.verdict is ReviewVerdict.APPROVE:
            return S.SECURITY_REVIEW
        return self._loop_back_or_fail(s, f"code review requested changes ({len(review.findings)} finding(s))")

    def _h_security_review(self, s: WorkflowSnapshot) -> S:
        ctx = self._context(s)
        review = self._run_agent(s, AgentName.SECURITY_REVIEWER, lambda: self.runner.review_security(ctx), "SecurityResult")
        s.security_review = review
        if review.verdict is ReviewVerdict.APPROVE:
            return S.MAINTAINER_REVIEW
        if review.verdict is ReviewVerdict.REJECT or review.secrets_detected:
            s.last_error = "security review rejected the change"
            self._emit(s, EventType.SAFETY_BLOCKED, action="security rejection")
            return S.FAILED
        return self._loop_back_or_fail(s, "security review requested changes")

    def _h_maintainer_review(self, s: WorkflowSnapshot) -> S:
        ctx = self._context(s)
        review = self._run_agent(s, AgentName.MAINTAINER_SIMULATOR, lambda: self.runner.maintainer_review(ctx), "MaintainerReview")
        s.maintainer_review = review
        if review.verdict is MaintainerVerdict.APPROVE:
            return S.READY_FOR_PR
        if review.verdict is MaintainerVerdict.REJECT:
            s.last_error = "maintainer simulation rejected the change"
            return S.FAILED
        return self._loop_back_or_fail(s, "maintainer requested changes")

    def _h_changes_requested(self, s: WorkflowSnapshot) -> S:
        # Feedback from PR monitoring re-enters the implementation loop.
        return self._loop_back_or_fail(s, "changes requested on PR", reset_reviews=False)

    # -- PR preparation & submission (separated, human-gated) ----------------
    def prepare_pr(self, workflow_id: str) -> WorkflowSnapshot:
        """Compose the PR title/body and persist it WITHOUT pushing or opening a
        PR. Safe to run repeatedly; nothing leaves the machine."""
        s = self.get(workflow_id)
        if s.state is not S.READY_FOR_PR:
            raise OrchestrationError(
                f"workflow must be READY_FOR_PR to prepare a PR (is {s.state.value})"
            )
        self._assert_gates(s)
        ctx = self._context(s)
        pr_desc = self._run_agent(
            s, AgentName.PR_MANAGER, lambda: self.runner.compose_pull_request(ctx),
            "PullRequestResult",
        )
        pr_desc.created = False
        pr_desc.number = s.continuation.number if s.continuation else None
        pr_desc.url = s.continuation.url if s.continuation else None
        if s.continuation:
            pr_desc.draft = s.continuation.draft
            pr_desc.branch = s.continuation.head_branch
            # A regenerated description needs a fresh human decision too.
            s.human_approved = False
            s.human_decision_note = None
        s.pull_request = pr_desc
        self._emit(s, EventType.NOTE, action="PR prepared (not submitted)")
        self.repo.save(s)
        return s

    def submit(self, workflow_id: str, *, confirm: bool, draft: bool = False) -> WorkflowSnapshot:
        """Submit the prepared PR. Requires explicit human approval, an explicit
        confirmation, and a passing final conflict re-check. This is the only
        path that pushes a branch and opens a PR from ``submit``."""
        s = self.get(workflow_id)
        if s.state is not S.READY_FOR_PR:
            raise OrchestrationError(
                f"workflow must be READY_FOR_PR to submit (is {s.state.value})"
            )
        if s.pull_request is None:
            raise SubmissionBlocked("no prepared PR — run prepare-pr first")
        if not s.human_approved:
            raise HumanApprovalRequired(
                "submission requires explicit human approval — run `oss-agent approve` first"
            )
        if not confirm:
            raise HumanApprovalRequired(
                "submission requires explicit confirmation (not defaulted to yes)"
            )
        self._assert_gates(s)
        conflict = self._submission_conflict(s)
        if conflict:
            self._emit(s, EventType.SAFETY_BLOCKED, action=f"submission blocked: {conflict}")
            s.last_error = f"submission blocked: {conflict}"
            self.repo.save(s)
            raise SubmissionBlocked(conflict)
        if s.continuation:
            try:
                s.pull_request = self._update_existing_pull_request(s)
                self._transition(s, S.PR_CREATED, action=f"PR #{s.continuation.number} updated")
                self._emit(s, EventType.PR_CREATED, action=f"existing PR #{s.continuation.number} updated",
                           detail={"url": s.continuation.url, "existing": True})
                self._transition(s, S.PR_MONITORING, action="monitoring existing PR")
            except Exception as exc:
                self._fail(s, f"existing PR update failed: {exc}")
            self.repo.save(s)
            return s
        # All human gates passed → perform the actual push + PR creation.
        return self.create_pr(workflow_id, draft=draft)

    def _submission_conflict(self, s: WorkflowSnapshot) -> Optional[str]:
        """Re-check live GitHub state immediately before submission. Conditions
        may have changed while the developer reviewed the contribution."""
        full = s.repository_full_name or ""
        num = s.issue_number or 0
        if s.continuation:
            return self._continuation_conflict(s)
        try:
            issue = self.github.get_issue(full, num)
            if issue.state and issue.state.lower() != "open":
                return f"issue #{num} is now {issue.state}"
            if issue.assignees:
                return f"issue #{num} is now assigned to {issue.assignees}"
            if issue.linked_pr_numbers:
                return f"issue #{num} now has linked PR(s) {issue.linked_pr_numbers}"
        except GitHubError:
            pass
        try:
            repo = self.github.get_repository(full)
            if repo.archived:
                return "repository is now archived"
        except GitHubError:
            pass
        try:
            head = s.branch or branch_name_for(num)
            pr = self.github.find_pull_request_by_head(full, head)
            if pr is not None:
                return f"a PR already exists for branch {head} (#{pr.number})"
        except GitHubError:
            pass
        try:
            if self.github.issue_has_open_linked_pr(full, num):
                return f"issue #{num} now has an open linked PR"
        except GitHubError:
            pass
        return None

    # -- PR creation (gated, explicit) ---------------------------------------
    def create_pr(self, workflow_id: str, *, draft: bool = False) -> WorkflowSnapshot:
        s = self.get(workflow_id)
        if s.continuation:
            raise HumanApprovalRequired("existing PR continuations require prepare-pr, approve, and submit --confirm")
        if s.state is not S.READY_FOR_PR:
            raise OrchestrationError(f"workflow must be READY_FOR_PR to open a PR (is {s.state.value})")
        self._assert_gates(s)
        try:
            pr = self._open_pull_request(s, draft=draft)
            s.pull_request = pr
            self._transition(s, S.PR_CREATED, action=f"PR #{pr.number} created")
            self._emit(s, EventType.PR_CREATED, action=f"PR #{pr.number}", detail={"url": pr.url})
            self._transition(s, S.PR_MONITORING, action="monitoring PR")
        except Exception as exc:
            self._fail(s, f"PR creation failed: {exc}")
        self.repo.save(s)
        return s

    def _assert_gates(self, s: WorkflowSnapshot) -> None:
        if not (s.test_result and s.test_result.passed):
            raise OrchestrationError("gate failed: tests are not green")
        if not (s.code_review and s.code_review.verdict is ReviewVerdict.APPROVE):
            raise OrchestrationError("gate failed: code review not approved")
        if not (s.security_review and s.security_review.verdict is ReviewVerdict.APPROVE):
            raise OrchestrationError("gate failed: security review not approved")
        if not (s.maintainer_review and s.maintainer_review.verdict is MaintainerVerdict.APPROVE):
            raise OrchestrationError("gate failed: maintainer review not approved")
        if s.implementation and s.implementation.unexpected_files:
            raise OrchestrationError("gate failed: change is out of scope")
        if s.continuation and (
            not s.validated_diff_digest or self._continuation_diff_digest(s) != s.validated_diff_digest
        ):
            raise OrchestrationError("gate failed: continuation diff changed since passing tests")

    def _open_pull_request(self, s: WorkflowSnapshot, *, draft: bool):
        self._assert_github_account()
        ctx = self._context(s)
        pr_desc = self._run_agent(s, AgentName.PR_MANAGER, lambda: self.runner.compose_pull_request(ctx), "PullRequestResult")
        wt = s.worktree_path
        assert wt and s.branch
        # Commit staged changes (secret scan happens inside GitService.commit).
        if not self.git.is_clean(wt):
            self.git.add_all(wt)
        commit_msg = f"{pr_desc.title}\n\nCloses #{s.issue_number}"
        self.git.commit(
            wt, commit_msg,
            author_name=self.settings.git_author_name,
            author_email=self.settings.git_author_email,
        )
        self._assert_commit_identity(wt)
        # Push only when a remote is configured (offline/mock has none).
        if self.git.has_remote(wt, "origin"):
            self.git.push(wt, s.branch)
        else:
            self._emit(s, EventType.NOTE, action="no 'origin' remote; branch committed locally only")
        default_branch = s.repository.default_branch if s.repository else "main"
        pr = self.github.create_pull_request(
            s.repository_full_name or "",
            head=s.branch,
            base=default_branch,
            title=pr_desc.title,
            body=pr_desc.body,
            draft=draft,
        )
        pr_desc.number = pr.number
        pr_desc.url = pr.url
        pr_desc.created = True
        return pr_desc

    def _assert_github_account(self, *, required: bool = False) -> str:
        expected = self.settings.github_login
        if required and not expected:
            raise OrchestrationError("existing PR continuation requires OSS_AGENT_GITHUB_LOGIN")
        if not expected:
            return ""
        actual = self.github.authenticated_login()
        if actual.lower() != expected.lower():
            raise OrchestrationError(f"authenticated GitHub account is {actual}, expected {expected}")
        return actual

    def _verify_continuation_target(self, s: WorkflowSnapshot) -> PullRequestContinuation:
        login = self._assert_github_account(required=True)
        full = s.repository_full_name or ""
        pr = self.github.get_pull_request(full, s.existing_pr_number or 0)
        if pr.number != s.existing_pr_number:
            raise OrchestrationError("GitHub returned a different PR than the requested continuation")
        if pr.state.lower() != "open" or pr.merged:
            raise OrchestrationError("adopted PR must still be open and unmerged")
        if not pr.author or pr.author.lower() != login.lower():
            raise OrchestrationError("adopted PR author is not the authenticated contributor")
        if pr.repository_full_name != full or pr.url != f"https://github.com/{full}/pull/{pr.number}":
            raise OrchestrationError("adopted PR does not belong to the requested upstream repository")
        if not pr.head_repository_owner or pr.head_repository_owner.lower() != login.lower():
            raise OrchestrationError("adopted PR head fork is not owned by the authenticated contributor")
        fork = pr.head_repository_full_name or ""
        if fork.lower() != f"{login}/{full.split('/')[-1]}".lower() or fork.lower() == full.lower():
            raise OrchestrationError("adopted PR must target a branch in the contributor's matching fork")
        if not re.fullmatch(r"[0-9a-f]{40}", pr.head_sha or "") or not re.fullmatch(r"[0-9a-f]{40}", pr.base_sha or ""):
            raise OrchestrationError("adopted PR is missing verified head/base commit identities")
        self.git.assert_worktree_branch_allowed(pr.head)
        return PullRequestContinuation(
            number=pr.number, repository_full_name=full, author=login,
            head_sha=pr.head_sha, base_sha=pr.base_sha,
            head_repository_full_name=fork, head_repository_owner=pr.head_repository_owner,
            head_branch=pr.head, base_branch=pr.base, draft=pr.draft, url=pr.url,
        )

    def _continuation_diff_digest(self, s: WorkflowSnapshot) -> str:
        assert s.continuation and s.worktree_path
        # Include untracked content by requiring every implementation stage to
        # stage its output before testing; refuse later untracked additions too.
        status = self.git.status_porcelain(s.worktree_path)
        if any(line.startswith("??") for line in status.splitlines()):
            raise OrchestrationError("continuation contains untracked files outside the validated diff")
        delta = self.git.diff(s.worktree_path, base=s.review_base_sha or s.continuation.base_sha)
        return hashlib.sha256(delta.encode()).hexdigest()

    @staticmethod
    def _diff_paths(diff: str) -> set[str]:
        return set(re.findall(r"^(?:\+\+\+ b/|--- a/)(.+)$", diff, re.MULTILINE))

    @staticmethod
    def _shared_scaffolding_matches(own_diff: str, other_diff: str, path: str) -> bool:
        """Identical additive test setup is compatible; production overlap is not.

        This deliberately narrow allowance is derived from the actual changes,
        never from a PR number or an agent's assurance of compatibility.
        """
        if path != "android/build.gradle" and not path.startswith(".github/workflows/"):
            return False

        def edits(diff: str) -> list[tuple[int, str]]:
            selected = False
            lines = []
            old_line = 0
            for line in diff.splitlines():
                if line.startswith("diff --git "):
                    selected = line == f"diff --git a/{path} b/{path}"
                elif selected:
                    hunk = re.match(r"@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@", line)
                    if hunk:
                        old_line = int(hunk.group(1))
                    elif line.startswith(("+++", "---")):
                        continue
                    elif line.startswith("+"):
                        if line[1:].strip():
                            lines.append((old_line, line))
                    elif line.startswith("-"):
                        lines.append((old_line, line))
                        old_line += 1
                    elif line.startswith(" "):
                        old_line += 1
            return lines

        own, other = edits(own_diff), edits(other_diff)
        if not own or not other:
            return False
        if own == other:
            return True
        if path != "android/build.gradle":
            return False
        # Two PRs may add the exact same unit-test dependencies while one also
        # adds instrumentation-only dependencies. Permit that strict superset
        # only when every line is recognized additive test setup at the same
        # original source anchor. Any removal, setting change, production
        # dependency, or contradictory dependency version stays blocked.
        dependency = re.compile(
            r"(testImplementation|androidTestImplementation) ['\"]"
            r"([A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+):([A-Za-z0-9_.+\-]+)['\"]"
        )
        for changes in (own, other):
            seen = {}
            for _, line in changes:
                if not line.startswith("+"):
                    return False
                value = line[1:].strip()
                match = dependency.fullmatch(value)
                if match:
                    key, version = (match.group(1), match.group(2)), match.group(3)
                elif value == "testOptions { unitTests.includeAndroidResources = true }":
                    key, version = ("testOptions", "resources"), "true"
                elif re.fullmatch(r"testInstrumentationRunner ['\"][A-Za-z0-9_.]+['\"]", value):
                    key, version = ("testInstrumentationRunner", "runner"), value
                else:
                    return False
                if key in seen and seen[key] != version:
                    return False
                seen[key] = version
        return set(own).issubset(other) or set(other).issubset(own)

    def _continuation_conflict(self, s: WorkflowSnapshot) -> Optional[str]:
        assert s.continuation and s.worktree_path
        try:
            current = self._verify_continuation_target(s)
            if current != s.continuation:
                return "adopted PR head, base, ownership, or draft state changed; rerun review"
            issue = self.github.get_issue(s.repository_full_name or "", s.issue_number or 0)
            if issue.state.lower() != "open" or issue.assignees:
                return "issue is closed or assigned; contribution needs reassessment"
            if self.github.get_repository(s.repository_full_name or "").archived:
                return "repository is now archived"
            own_diff = self.git.diff(s.worktree_path, base=s.review_base_sha or current.base_sha)
            own_paths = self._diff_paths(own_diff)
            issue_reference = re.compile(rf"(?<!\d)#{s.issue_number}(?!\d)|/issues/{s.issue_number}(?!\d)")
            for pr in self.github.list_pull_requests(s.repository_full_name or ""):
                if pr.number == current.number:
                    continue
                relevant = pr.number in issue.linked_pr_numbers or issue_reference.search(pr.title + "\n" + pr.body)
                if relevant:
                    diff = self.github.get_pull_request_diff(s.repository_full_name or "", pr.number)
                    paths = self._diff_paths(diff)
                    if not paths:
                        return f"cannot verify competing PR #{pr.number} scope"
                    overlap = {
                        path for path in own_paths & paths
                        if not self._shared_scaffolding_matches(own_diff, diff, path)
                    }
                    if overlap:
                        return f"competing PR #{pr.number} overlaps contribution files: {', '.join(sorted(overlap))}"
            return None
        except Exception as exc:
            return f"could not verify continuation conflicts: {exc}"

    def _assert_commit_identity(self, worktree: str) -> None:
        expected = (self.settings.git_author_name, self.settings.git_author_email) * 2
        if self.git.commit_identity(worktree) != expected:
            raise OrchestrationError("actual contribution commit author/committer does not match configured identity")

    def _update_existing_pull_request(self, s: WorkflowSnapshot):
        assert s.continuation and s.worktree_path and s.pull_request
        target, wt, description = s.continuation, s.worktree_path, s.pull_request
        self._assert_github_account(required=True)
        if self._verify_continuation_target(s) != target:
            raise SubmissionBlocked("adopted PR changed immediately before publication")
        if self.git.head_sha(wt) != target.head_sha:
            raise SubmissionBlocked("continuation HEAD changed outside the controlled commit path")
        full = re.escape(target.repository_full_name)
        issue_ref = rf"(?:(?:{full})?#{s.issue_number}|https://github\.com/{full}/issues/{s.issue_number})\b"
        if re.search(
            rf"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+{issue_ref}",
            description.title + "\n" + description.body, re.IGNORECASE,
        ):
            raise SubmissionBlocked("continuation description must reference the issue without closing it")
        self.git.add_all(wt)
        if self.git.staged_diff(wt).strip():
            self.git.commit(
                wt, f"{description.title}\n\nRelated to #{s.issue_number}; continues PR #{target.number}",
                author_name=self.settings.git_author_name, author_email=self.settings.git_author_email,
            )
            self._assert_commit_identity(wt)
            self.git.push_to_owned_branch(
                wt, owner=target.head_repository_owner,
                repository=target.head_repository_full_name.split("/", 1)[1],
                branch=target.head_branch, expected_sha=target.head_sha,
            )
        # No incremental changes means no empty commit and no push. The fully
        # reviewed existing PR can still receive its new evidence in the body.
        self._assert_github_account(required=True)
        current = self._verify_continuation_target(s)
        # GitHub's PR head update can lag the successful fast-forward briefly.
        # Both the original verified SHA and our exact new commit are safe;
        # any other head or changed target must be reviewed again.
        if current.head_sha not in {target.head_sha, self.git.head_sha(wt)} or current.model_copy(
            update={"head_sha": target.head_sha},
        ) != target:
            raise SubmissionBlocked("adopted PR target changed before description update")
        pr = self.github.update_pull_request(
            target.repository_full_name, target.number, title=description.title, body=description.body,
        )
        description.number, description.url = pr.number, pr.url
        description.branch = target.head_branch
        description.draft, description.created = target.draft, True
        return description

    # -- helpers --------------------------------------------------------------
    def _context(self, s: WorkflowSnapshot) -> AgentContext:
        handle = None
        if s.worktree_path and s.branch:
            handle = WorktreeHandle(
                workflow_id=s.id, repo_path=s.repository_full_name or "",
                path=s.worktree_path, branch=s.branch, created=False,
            )
        return AgentContext(
            snapshot=s, settings=self.settings, github=self.github, git=self.git,
            profile=self.profile, scoring=self.scoring, worktree=handle,
            repository_context=s.repository_context,
        )

    def _run_agent(self, s: WorkflowSnapshot, agent: AgentName, call, output_kind: str):
        started = utcnow()
        self._emit(s, EventType.AGENT_STARTED, agent=agent, action=f"{agent.value} started")
        try:
            result = call()
        except Exception as exc:
            self._record_execution(s, agent, output_kind, success=False, error=str(exc), started=started)
            self._emit(s, EventType.AGENT_FAILED, agent=agent, action=f"{agent.value} failed", error=str(exc))
            raise
        self._record_execution(s, agent, output_kind, success=True, started=started)
        self._emit(s, EventType.AGENT_COMPLETED, agent=agent, action=f"{agent.value} completed")
        return result

    def _record_execution(self, s, agent, output_kind, *, success, error=None, started=None):
        started = started or utcnow()
        finished = utcnow()
        s.executions.append(AgentExecution(
            agent=agent, state=s.state, started_at=started, finished_at=finished,
            success=success, error=error, output_kind=output_kind,
            duration_seconds=round((finished - started).total_seconds(), 4),
        ))

    def _record_attempt(self, s: WorkflowSnapshot, result: TestResult) -> None:
        """Persist one implement/repair cycle so the full history is inspectable."""
        impl = s.implementation
        failure = "\n".join(
            f"{suite.name} (exit {suite.command.exit_code}): {suite.command.stderr_tail or suite.command.stdout_tail}".strip()
            for suite in result.failed_suites
        )
        s.attempts.append(ImplementationAttempt(
            attempt=len(s.attempts) + 1,
            phase="implement" if s.debug_iteration == 0 else "repair",
            files_changed=[fc.path for fc in (impl.files_changed if impl else [])],
            unexpected_files=list(impl.unexpected_files) if impl else [],
            tests_passed=result.passed,
            tests_summary=result.summary,
            failure_summary=failure[:2000],
            notes=list(impl.notes) if impl else [],
            test_duration_seconds=round(
                sum(su.command.duration_seconds for su in result.executed_suites), 4
            ),
        ))

    def _loop_back_or_fail(self, s: WorkflowSnapshot, reason: str, *, reset_reviews: bool = True) -> S:
        s.review_iteration += 1
        s.last_error = reason
        if s.review_iteration >= self.settings.max_review_iterations:
            self._emit(s, EventType.NOTE, action=f"max review iterations reached: {reason}")
            return S.FAILED
        self._emit(s, EventType.NOTE, action=f"review loop {s.review_iteration}: {reason}")
        return S.IMPLEMENTATION

    def _issue_comment_bodies(self, s: WorkflowSnapshot) -> list[str]:
        """Best-effort fetch of issue comment bodies for suitability signals.
        Read-only; never fails the workflow if the adapter can't provide them."""
        if not (s.repository_full_name and s.issue_number):
            return []
        try:
            comments = self.github.list_issue_comments(s.repository_full_name, s.issue_number)
            return [c.body for c in comments]
        except (GitHubError, Exception):
            return []

    def _duplicate_reason(self, s: WorkflowSnapshot) -> Optional[str]:
        # Other active work on this issue is a duplicate. Monitoring the exact
        # published PR being explicitly adopted is historical evidence, though,
        # not a competing implementation. Discovery verifies that target live
        # before this check; an unpublished or different PR remains blocked.
        for other in self.repo.list():
            if (
                other.id != s.id
                and other.repository_full_name == s.repository_full_name
                and other.issue_number == s.issue_number
                and not StateMachine.is_terminal(other.state)
            ):
                published = other.pull_request
                target = s.continuation
                if (
                    target
                    and s.existing_pr_number == target.number
                    and other.state is S.PR_MONITORING
                    and published is not None
                    and published.created
                    and published.repository_full_name == target.repository_full_name == s.repository_full_name
                    and published.issue_number == s.issue_number
                    and published.number == target.number
                    and published.url == target.url == f"https://github.com/{s.repository_full_name}/pull/{target.number}"
                ):
                    continue
                return f"active workflow {other.id} already targets this issue"
        # An existing PR for the deterministic branch.
        try:
            head = branch_name_for(s.issue_number or 0)
            pr = self.github.find_pull_request_by_head(s.repository_full_name or "", head)
            if pr is not None and not (s.continuation and pr.number == s.continuation.number):
                return f"PR #{pr.number} already exists for branch {head}"
        except GitHubError:
            pass
        return None

    def _transition(self, s: WorkflowSnapshot, target: S, *, action: str = "") -> None:
        if target is s.state:
            return
        StateMachine.validate(s.state, target)
        previous = s.state
        s.state = target
        s.touch()
        self._emit(s, EventType.STATE_TRANSITION, state=target,
                   action=action or f"{previous.value} -> {target.value}",
                   detail={"from": previous.value, "to": target.value})

    def _fail(self, s: WorkflowSnapshot, error: str) -> None:
        s.last_error = error
        self._emit(s, EventType.ERROR, action="workflow failed", error=error)
        if not StateMachine.is_terminal(s.state):
            try:
                self._transition(s, S.FAILED, action=error)
            except InvalidTransitionError:
                s.state = S.FAILED
        logger.error("workflow failed", extra={"workflow_id": s.id, "error": error})

    def _cleanup_worktree(self, s: WorkflowSnapshot) -> None:
        if s.repository_full_name and s.worktree_path:
            try:
                base = self.repo_provider.ensure_local(s.repository_full_name)
                self.worktrees.remove(base, s.id)
                self._emit(s, EventType.WORKTREE_REMOVED, action="worktree cleaned up")
            except Exception as exc:
                logger.warning("worktree cleanup failed", extra={"error": str(exc)})

    def _emit(self, s: WorkflowSnapshot, event_type: EventType, *, agent: Optional[AgentName] = None,
              state: Optional[S] = None, action: str = "", detail: Optional[dict] = None,
              error: Optional[str] = None) -> None:
        event = WorkflowEvent(
            type=event_type, agent=agent, state=state or s.state, action=action,
            detail=detail or {}, error=error,
        )
        s.events.append(event)
        self.bus.publish(event)

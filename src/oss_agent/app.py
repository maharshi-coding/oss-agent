"""Application facade.

A thin service layer the CLI calls into, so the CLI itself contains no business
logic. It wraps a wired :class:`WorkflowEngine` and adds a few one-off, read-only
analysis helpers (discover / analyze / score) that don't need a persisted
workflow.
"""

from __future__ import annotations

from typing import Optional

from oss_agent.agents.base import AgentContext
from oss_agent.config.settings import Settings, get_settings
from oss_agent.domain.enums import WorkflowState
from oss_agent.domain.models import (
    ContributionScore,
    DiscoveryResult,
    IssueAnalysis,
    RepositoryReport,
    SuitabilityAssessment,
    WorkflowSnapshot,
)
from oss_agent.orchestrator.builder import build_engine
from oss_agent.orchestrator.engine import WorkflowEngine


class Application:
    def __init__(self, engine: WorkflowEngine) -> None:
        self.engine = engine
        self._scout = None
        self._opportunities = None

    @classmethod
    def from_settings(cls, settings: Optional[Settings] = None, **overrides) -> "Application":
        settings = settings or get_settings()
        return cls(build_engine(settings, **overrides))

    # -- read-only analysis helpers ------------------------------------------
    def _transient_context(
        self, *, repository_full_name: Optional[str] = None, issue_number: Optional[int] = None,
        snapshot: Optional[WorkflowSnapshot] = None,
    ) -> AgentContext:
        e = self.engine
        snap = snapshot or WorkflowSnapshot(
            id="transient", repository_full_name=repository_full_name, issue_number=issue_number
        )
        return AgentContext(
            snapshot=snap, settings=e.settings, github=e.github, git=e.git,
            profile=e.profile, scoring=e.scoring, worktree=None,
        )

    def discover(self, query: Optional[str] = None) -> DiscoveryResult:
        ctx = self._transient_context()
        ctx.discovery_query = query
        return self.engine.runner.discover(ctx)

    def analyze_repository(self, full_name: str) -> RepositoryReport:
        repo = self.engine.github.get_repository(full_name)
        snap = WorkflowSnapshot(id="transient", repository_full_name=full_name, repository=repo)
        return self.engine.runner.analyze_repository(self._transient_context(snapshot=snap))

    def analyze_issue(self, full_name: str, number: int) -> IssueAnalysis:
        issue = self.engine.github.get_issue(full_name, number)
        snap = WorkflowSnapshot(
            id="transient", repository_full_name=full_name, issue_number=number, issue=issue
        )
        return self.engine.runner.analyze_issue(self._transient_context(snapshot=snap))

    def score(self, full_name: str, number: int) -> ContributionScore:
        repo = self.engine.github.get_repository(full_name)
        issue = self.engine.github.get_issue(full_name, number)
        snap = WorkflowSnapshot(
            id="transient", repository_full_name=full_name, issue_number=number,
            repository=repo, issue=issue,
        )
        report = self.engine.runner.analyze_repository(self._transient_context(snapshot=snap))
        snap.repository_report = report
        analysis = self.engine.runner.analyze_issue(self._transient_context(snapshot=snap))
        return self.engine.scoring.score(analysis, report, self.engine.profile, issue=issue)

    def context(self, full_name: str, number: int):
        """Build a read-only repository-context slice for an issue (no checkout)."""
        from oss_agent.context.builder import RepositoryContextBuilder
        from oss_agent.context.sources import GitHubFileSource

        issue = self.engine.github.get_issue(full_name, number)
        snap = WorkflowSnapshot(
            id="transient", repository_full_name=full_name, issue_number=number, issue=issue
        )
        analysis = self.engine.runner.analyze_issue(self._transient_context(snapshot=snap))
        source = GitHubFileSource(self.engine.github, full_name)
        return RepositoryContextBuilder().build(source, analysis, repository_full_name=full_name)

    def suitability(self, full_name: str, number: int) -> SuitabilityAssessment:
        """Assess whether a contribution *should* be made (read-only)."""
        repo = self.engine.github.get_repository(full_name)
        issue = self.engine.github.get_issue(full_name, number)
        snap = WorkflowSnapshot(
            id="transient", repository_full_name=full_name, issue_number=number,
            repository=repo, issue=issue,
        )
        report = self.engine.runner.analyze_repository(self._transient_context(snapshot=snap))
        snap.repository_report = report
        analysis = self.engine.runner.analyze_issue(self._transient_context(snapshot=snap))
        try:
            comment_bodies = [c.body for c in self.engine.github.list_issue_comments(full_name, number)]
        except Exception:
            comment_bodies = []
        return self.engine.suitability.assess(
            analysis, report, self.engine.profile, issue=issue, comment_bodies=comment_bodies
        )

    # -- workflow operations (delegate to the engine) ------------------------
    def create(self, full_name: str, number: int, *, workflow_id: Optional[str] = None) -> WorkflowSnapshot:
        return self.engine.create_workflow(
            workflow_id=workflow_id, repository_full_name=full_name, issue_number=number
        )

    def run(self, workflow_id: str) -> WorkflowSnapshot:
        return self.engine.run(workflow_id)

    def resume(self, workflow_id: str) -> WorkflowSnapshot:
        return self.engine.resume(workflow_id)

    def status(self, workflow_id: str) -> WorkflowSnapshot:
        return self.engine.get(workflow_id)

    def attempts(self, workflow_id: str):
        """Return the persisted implement/repair attempt history."""
        return self.engine.get(workflow_id).attempts

    # -- human review & learning ---------------------------------------------
    def diff(self, workflow_id: str) -> str:
        """Return the staged diff of the workflow's worktree (empty if none)."""
        snap = self.engine.get(workflow_id)
        if not snap.worktree_path:
            return ""
        return self.engine.git.diff(snap.worktree_path, staged=True)

    def learn(self, workflow_id: str):
        """Build, persist, and return a grounded learning report."""
        from oss_agent.learning.report import build_learning_report

        snap = self.engine.get(workflow_id)
        numstat: list[tuple[int, int, str]] = []
        if snap.worktree_path:
            try:
                numstat = self.engine.git.diff_numstat(snap.worktree_path, staged=True)
            except Exception:
                numstat = []
        report = build_learning_report(snap, numstat)
        snap.learning_report = report
        self.engine.repo.save(snap)
        return report

    def explain(self, workflow_id: str) -> str:
        """A concise, human-readable explanation of the contribution so far."""
        from oss_agent.learning.report import build_learning_report

        snap = self.engine.get(workflow_id)
        numstat = []
        if snap.worktree_path:
            try:
                numstat = self.engine.git.diff_numstat(snap.worktree_path, staged=True)
            except Exception:
                numstat = []
        r = snap.learning_report or build_learning_report(snap, numstat)
        lines = [
            f"{r.title}",
            f"  what broke : {r.what_was_broken or '(pending)'}",
            f"  why fixed  : {r.why_the_fix_works or '(pending)'}",
            f"  files      : {', '.join(r.files_that_matter) or '(none yet)'}",
            f"  tests      : {', '.join(r.tests_that_prove_it) or '(none yet)'}",
        ]
        return "\n".join(lines)

    def approve(self, workflow_id: str, note: str = "approved by human") -> WorkflowSnapshot:
        """Record explicit human approval (required before submission)."""
        snap = self.engine.get(workflow_id)
        snap.human_approved = True
        snap.human_decision_note = note
        self.engine.repo.save(snap)
        return snap

    def reject(self, workflow_id: str, note: str = "rejected by human") -> WorkflowSnapshot:
        """Record a human rejection and abort the workflow."""
        snap = self.engine.get(workflow_id)
        snap.human_approved = False
        snap.human_decision_note = note
        self.engine.repo.save(snap)  # persist before abort re-fetches the snapshot
        return self.engine.abort(workflow_id, f"human rejected: {note}")

    def prepare_pr(self, workflow_id: str) -> WorkflowSnapshot:
        return self.engine.prepare_pr(workflow_id)

    def submit(self, workflow_id: str, *, confirm: bool, draft: bool = False) -> WorkflowSnapshot:
        return self.engine.submit(workflow_id, confirm=confirm, draft=draft)

    def create_pr(self, workflow_id: str, *, draft: bool = False) -> WorkflowSnapshot:
        return self.engine.create_pr(workflow_id, draft=draft)

    def abort(self, workflow_id: str, reason: str = "aborted by user") -> WorkflowSnapshot:
        return self.engine.abort(workflow_id, reason)

    def list(self, *, state: Optional[WorkflowState] = None) -> list[WorkflowSnapshot]:
        return self.engine.repo.list(state=state)

    def monitor(self) -> list[WorkflowSnapshot]:
        """Return workflows currently in the PR monitoring phase."""
        return self.engine.repo.list(state=WorkflowState.PR_MONITORING)

    # -- continuous scout (read-only; PRs stay human-gated) ------------------
    def scout(self):
        """Lazily build the opportunity scout over the same database."""
        if self._scout is None:
            from oss_agent.persistence.database import Database
            from oss_agent.scout.service import ScoutService
            from oss_agent.scout.store import SqlAlchemyOpportunityRepository

            store = SqlAlchemyOpportunityRepository(Database(self.engine.settings.database_url))
            self._opportunities = store
            self._scout = ScoutService(
                github=self.engine.github, runner=self.engine.runner,
                scoring=self.engine.scoring, profile=self.engine.profile,
                workflows=self.engine.repo, store=store,
            )
        return self._scout

    def scout_once(self, *, query: Optional[str] = None, **kwargs):
        return self.scout().scan(query=query, **kwargs)

    def scout_loop(self, **kwargs):
        return self.scout().run_forever(**kwargs)

    def list_opportunities(self, *, status=None, limit: int = 50):
        self.scout()
        return self._opportunities.list(status=status, limit=limit)

    def dismiss_opportunity(self, key: str) -> bool:
        from oss_agent.scout.models import OpportunityStatus

        self.scout()
        return self._opportunities.set_status(key, OpportunityStatus.DISMISSED)

    def promote_opportunity(self, key: str) -> WorkflowSnapshot:
        from oss_agent.scout.models import OpportunityStatus

        self.scout()
        opp = self._opportunities.get(key)
        if opp is None:
            raise ValueError(f"no such opportunity: {key}")
        snap = self.create(opp.repository_full_name, opp.issue_number)
        self._opportunities.set_status(key, OpportunityStatus.PROMOTED)
        return snap

    def render_visualizer(self, workflow_id: Optional[str] = None) -> str:
        """Return standalone HTML for the pixel-world visualizer.

        With a workflow id, the pixel agents reflect that workflow's real state;
        without one, a demo page is produced.
        """
        from oss_agent.observability.visualizer import render_html

        snapshot = self.engine.get(workflow_id) if workflow_id else None
        return render_html(snapshot)

    def cleanup(self, *, include_active: bool = False) -> int:
        """Remove worktrees for terminal (or all) workflows. Returns count removed."""
        removed = 0
        for snap in self.engine.repo.list():
            terminal = snap.state in (WorkflowState.MERGED, WorkflowState.FAILED, WorkflowState.ABORTED)
            if (terminal or include_active) and snap.repository_full_name and snap.worktree_path:
                try:
                    base = self.engine.repo_provider.ensure_local(snap.repository_full_name)
                    if self.engine.worktrees.remove(base, snap.id):
                        removed += 1
                except Exception:
                    continue
        return removed

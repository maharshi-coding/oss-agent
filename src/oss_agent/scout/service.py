"""The continuous opportunity scout.

Runs read-only discovery + repository/issue analysis + scoring against GitHub and
persists a ranked, deduplicated queue of contribution opportunities. It never
opens a pull request and never mutates a repository — promotion to an actual
contribution is an explicit, human-gated step. Designed to run 24/7 via
:meth:`ScoutService.run_forever`.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from oss_agent.agents.base import AgentContext, AgentRunner
from oss_agent.config.profile import DeveloperProfile
from oss_agent.domain.enums import Difficulty
from oss_agent.domain.models import WorkflowSnapshot
from oss_agent.domain.state_machine import StateMachine
from oss_agent.git.naming import branch_name_for
from oss_agent.github.interface import GitHubClient, GitHubError
from oss_agent.observability.logging import get_logger
from oss_agent.persistence.repository import WorkflowRepository
from oss_agent.scoring.engine import ScoringEngine
from oss_agent.scout.models import Opportunity, OpportunityStatus, ScanResult
from oss_agent.scout.store import OpportunityRepository

logger = get_logger("scout")


class ScoutService:
    def __init__(
        self,
        *,
        github: GitHubClient,
        runner: AgentRunner,
        scoring: ScoringEngine,
        profile: DeveloperProfile,
        workflows: WorkflowRepository,
        store: OpportunityRepository,
    ) -> None:
        self.github = github
        self.runner = runner
        self.scoring = scoring
        self.profile = profile
        self.workflows = workflows
        self.store = store

    # -- one cycle ------------------------------------------------------------
    def scan(
        self,
        *,
        query: Optional[str] = None,
        max_candidates: int = 6,
        analyze_top: int = 4,
        min_score: float = 45.0,
        difficulty: Optional[Difficulty] = None,
        cycle: int = 0,
    ) -> ScanResult:
        result = ScanResult(cycle=cycle, query=query or "")
        ctx = self._context()
        ctx.discovery_query = query
        ctx.max_candidates = max_candidates

        try:
            discovery = self.runner.discover(ctx)
        except (GitHubError, Exception) as exc:  # discovery failure ends the cycle
            result.errors.append(f"discovery: {exc}")
            logger.warning("scout discovery failed", extra={"error": str(exc)})
            return result
        result.query = discovery.query

        for candidate in discovery.candidates[:analyze_top]:
            full = candidate.repository.full_name
            num = candidate.issue.number
            result.scanned += 1
            try:
                dup = self._duplicate_reason(full, num)
                if dup:
                    result.skipped_duplicate += 1
                    logger.info("scout skip duplicate", extra={"target": f"{full}#{num}", "reason": dup})
                    continue
                opp = self._evaluate(candidate)
                if difficulty is not None and opp.difficulty != difficulty:
                    result.skipped_filtered += 1
                    continue
                if opp.score < min_score:
                    result.skipped_low_score += 1
                    continue
                self.store.upsert(opp)
                result.stored += 1
            except Exception as exc:  # one bad candidate must not kill the cycle
                result.errors.append(f"{full}#{num}: {exc}")
                logger.warning("scout candidate failed", extra={"target": f"{full}#{num}", "error": str(exc)})

        result.top = self.store.list(status=OpportunityStatus.NEW, limit=10)
        logger.info("scout cycle complete", extra={"summary": result.summary})
        return result

    def _evaluate(self, candidate) -> Opportunity:
        repo = candidate.repository
        issue = candidate.issue
        snap = WorkflowSnapshot(
            id="scout", repository_full_name=repo.full_name, issue_number=issue.number,
            repository=repo, issue=issue,
        )
        report = self.runner.analyze_repository(self._context(snap))
        snap.repository_report = report
        analysis = self.runner.analyze_issue(self._context(snap))
        score = self.scoring.score(analysis, report, self.profile, issue=issue)

        reasons = [
            f"{c.dimension} {c.raw:.2f}"
            for c in sorted(score.components, key=lambda c: c.weighted, reverse=True)[:3]
        ]
        reasons += [f"penalty {p.name} -{p.amount:.0f}" for p in score.penalties[:2]]

        return Opportunity(
            repository_full_name=repo.full_name, issue_number=issue.number,
            title=issue.title, url=issue.url,
            contribution_type=analysis.contribution_type, difficulty=analysis.difficulty,
            score=score.overall, recommendation=score.recommendation,
            summary=score.explanation, reasons=reasons,
            status=OpportunityStatus.NEW,
        )

    def _duplicate_reason(self, full: str, num: int) -> Optional[str]:
        existing = self.store.get(f"{full}#{num}")
        if existing and existing.status in (
            OpportunityStatus.DISMISSED, OpportunityStatus.PROMOTED, OpportunityStatus.CONTRIBUTED
        ):
            return f"already {existing.status.value}"
        wf = self.workflows.find_by_issue(full, num)
        if wf is not None and not StateMachine.is_terminal(wf.state):
            return f"active workflow {wf.id}"
        try:
            pr = self.github.find_pull_request_by_head(full, branch_name_for(num))
            if pr is not None:
                return f"PR #{pr.number} exists"
        except GitHubError:
            pass
        # Someone else may already have an open PR fixing this issue — never
        # produce a duplicate contribution.
        try:
            if self.github.issue_has_open_linked_pr(full, num):
                return "issue already has an open linked PR"
        except GitHubError:
            pass
        return None

    def _context(self, snapshot: Optional[WorkflowSnapshot] = None) -> AgentContext:
        # Minimal context for read-only agents; no engine/git/worktree needed.
        from oss_agent.config.settings import get_settings

        snap = snapshot or WorkflowSnapshot(id="scout")
        return AgentContext(
            snapshot=snap, settings=get_settings(), github=self.github, git=None,  # type: ignore[arg-type]
            profile=self.profile, scoring=self.scoring, worktree=None,
        )

    # -- 24/7 loop ------------------------------------------------------------
    def run_forever(
        self,
        *,
        interval_seconds: float = 1800.0,
        max_cycles: Optional[int] = None,
        should_stop: Optional[Callable[[], bool]] = None,
        on_cycle: Optional[Callable[[ScanResult], None]] = None,
        sleep: Callable[[float], None] = time.sleep,
        **scan_kwargs,
    ) -> list[ScanResult]:
        """Run scan cycles until stopped. Errors trigger bounded backoff, never a
        crash — the loop is meant to survive an unattended machine."""
        results: list[ScanResult] = []
        cycle = 0
        backoff = 0.0
        while True:
            if should_stop and should_stop():
                break
            cycle += 1
            result = self.scan(cycle=cycle, **scan_kwargs)
            results.append(result)
            if on_cycle:
                on_cycle(result)
            # Back off when a whole cycle errored out (e.g. rate limit / network).
            if result.errors and result.scanned == 0:
                backoff = min(max(interval_seconds, 60.0), (backoff or 30.0) * 2)
                wait = backoff
            else:
                backoff = 0.0
                wait = interval_seconds
            if max_cycles is not None and cycle >= max_cycles:
                break
            self._interruptible_sleep(wait, should_stop, sleep)
        return results

    @staticmethod
    def _interruptible_sleep(seconds: float, should_stop, sleep) -> None:
        remaining = seconds
        step = 2.0
        while remaining > 0:
            if should_stop and should_stop():
                return
            sleep(min(step, remaining))
            remaining -= step

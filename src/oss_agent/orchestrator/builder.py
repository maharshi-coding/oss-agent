"""Composition root: wire a :class:`WorkflowEngine` from configuration.

This is the only place that knows how all the concrete pieces fit together, so
the CLI and tests can obtain a fully wired engine without duplicating wiring.
Dependencies can be overridden (used by tests and the e2e workflow).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from oss_agent.agents.base import AgentRunner
from oss_agent.agents.factory import create_agent_runner
from oss_agent.agents.mock_runner import Solution
from oss_agent.config.profile import DeveloperProfile, load_profile
from oss_agent.config.settings import Settings, get_settings
from oss_agent.events.bus import EventBus, default_bus
from oss_agent.execution.runner import CommandRunner
from oss_agent.execution.test_engineer import TestEngineer
from oss_agent.git.service import GitService
from oss_agent.github.factory import create_github_client
from oss_agent.github.interface import GitHubClient
from oss_agent.orchestrator.engine import WorkflowEngine
from oss_agent.orchestrator.repo_provider import CloningRepoProvider, RepoProvider
from oss_agent.persistence.database import Database
from oss_agent.persistence.repository import (
    SqlAlchemyWorkflowRepository,
    WorkflowRepository,
)
from oss_agent.scoring.config import load_scoring_config
from oss_agent.scoring.engine import ScoringEngine
from oss_agent.suitability.engine import SuitabilityEngine, load_suitability_weights
from oss_agent.worktrees.manager import WorktreeManager


def build_engine(
    settings: Optional[Settings] = None,
    *,
    repository: Optional[WorkflowRepository] = None,
    github: Optional[GitHubClient] = None,
    runner: Optional[AgentRunner] = None,
    repo_provider: Optional[RepoProvider] = None,
    profile: Optional[DeveloperProfile] = None,
    event_bus: Optional[EventBus] = None,
    solution: Optional[Solution] = None,
) -> WorkflowEngine:
    settings = settings or get_settings()
    settings.ensure_dirs()

    command_runner = CommandRunner(default_timeout=settings.command_timeout_seconds)
    git = GitService(runner=command_runner, protected_branches=settings.protected_branches)

    if repository is None:
        database = Database(url=settings.database_url)
        repository = SqlAlchemyWorkflowRepository(database)

    # Seed demo data when using the offline mock so first-run CLI commands
    # (discover/score) have something to show. Real backends ignore `seed`.
    github = github or create_github_client(settings, seed=True)
    runner = runner or create_agent_runner(settings, solution=solution)
    profile = profile or load_profile(settings.profile_path)
    scoring = ScoringEngine(load_scoring_config(settings.scoring_path))
    suitability = SuitabilityEngine(load_suitability_weights(settings.scoring_path))
    worktrees = WorktreeManager(git, settings.worktree_root)
    test_engineer = TestEngineer(command_runner, timeout=settings.command_timeout_seconds)
    if repo_provider is None:
        repo_provider = CloningRepoProvider(git, Path(settings.state_dir) / "repos", runner=command_runner)

    return WorkflowEngine(
        settings=settings,
        repository=repository,
        github=github,
        git=git,
        worktrees=worktrees,
        runner=runner,
        test_engineer=test_engineer,
        scoring=scoring,
        profile=profile,
        repo_provider=repo_provider,
        event_bus=event_bus or default_bus(),
        suitability=suitability,
    )

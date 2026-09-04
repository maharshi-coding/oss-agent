"""Factory that selects a GitHub adapter from configuration.

The rest of the app calls :func:`create_github_client` and receives a
:class:`GitHubClient`; it never imports a concrete adapter directly.
"""

from __future__ import annotations

from typing import Optional

from oss_agent.config.settings import GitHubBackend, Settings, get_settings
from oss_agent.github.gh_cli import GhCliGitHubClient
from oss_agent.github.interface import GitHubClient
from oss_agent.github.mock import InMemoryGitHubClient, seed_demo_data
from oss_agent.observability.logging import get_logger
from oss_agent.safety.rate_limit import RateLimiter

logger = get_logger("github.factory")


def create_github_client(
    settings: Optional[Settings] = None, *, seed: bool = False
) -> GitHubClient:
    settings = settings or get_settings()
    backend = settings.github_backend

    if backend is GitHubBackend.GH:
        logger.info("using gh CLI GitHub backend")
        return GhCliGitHubClient(
            rate_limiter=RateLimiter(min_interval_seconds=settings.github_min_interval_seconds),
            gh_bin="gh",
        )

    if backend is GitHubBackend.API:
        # The REST adapter is a documented future extension. Until it exists we
        # fail loudly rather than silently degrade, unless a token is absent.
        raise NotImplementedError(
            "The direct REST API backend is not implemented yet. Use "
            "OSS_AGENT_GITHUB_BACKEND=gh (recommended) or =mock."
        )

    logger.info("using in-memory (mock) GitHub backend")
    client = InMemoryGitHubClient()
    if seed:
        seed_demo_data(client)
    return client

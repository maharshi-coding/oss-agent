"""GitHub integration: interface, DTOs, and adapters (mock, gh CLI)."""

from oss_agent.github.factory import create_github_client
from oss_agent.github.gh_cli import GhCliGitHubClient
from oss_agent.github.interface import GitHubClient, GitHubError
from oss_agent.github.mock import InMemoryGitHubClient, seed_demo_data
from oss_agent.github.models import (
    CheckRun,
    CIStatus,
    IssueComment,
    PullRequest,
    RepoFile,
    Review,
    ReviewComment,
)

__all__ = [
    "create_github_client",
    "GhCliGitHubClient",
    "GitHubClient",
    "GitHubError",
    "InMemoryGitHubClient",
    "seed_demo_data",
    "CheckRun",
    "CIStatus",
    "IssueComment",
    "PullRequest",
    "RepoFile",
    "Review",
    "ReviewComment",
]

"""The GitHub client interface.

The orchestration layer depends only on :class:`GitHubClient`. Concrete adapters
(in-memory mock, ``gh`` CLI, REST) implement it. This keeps GitHub implementation
details out of the domain and orchestrator, and makes the integration replaceable
and testable.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from oss_agent.domain.models import Issue, Repository
from oss_agent.github.models import (
    CIStatus,
    IssueComment,
    PullRequest,
    RepoFile,
    Review,
    ReviewComment,
)


class GitHubError(RuntimeError):
    """Raised for GitHub adapter failures (network, auth, not found)."""


@runtime_checkable
class GitHubClient(Protocol):
    """Read/write surface for GitHub. All writes are limited to PR creation and
    (optionally) comments; merging is never exposed here."""

    # -- discovery / read -----------------------------------------------------
    def search_repositories(self, query: str, *, limit: int = 20) -> list[Repository]: ...
    def get_repository(self, full_name: str) -> Repository: ...
    def search_issues(self, query: str, *, limit: int = 30) -> list[tuple[Repository, Issue]]: ...
    def list_issues(
        self,
        full_name: str,
        *,
        labels: Optional[list[str]] = None,
        state: str = "open",
        limit: int = 30,
    ) -> list[Issue]: ...
    def get_issue(self, full_name: str, number: int) -> Issue: ...
    def issue_has_open_linked_pr(self, full_name: str, number: int) -> bool: ...

    # -- repository contents --------------------------------------------------
    def get_file(self, full_name: str, path: str, *, ref: Optional[str] = None) -> Optional[str]: ...
    def list_files(self, full_name: str, *, ref: Optional[str] = None) -> list[RepoFile]: ...

    # -- pull requests / reviews ----------------------------------------------
    def list_pull_requests(self, full_name: str, *, state: str = "open") -> list[PullRequest]: ...
    def get_pull_request(self, full_name: str, number: int) -> PullRequest: ...
    def find_pull_request_by_head(self, full_name: str, head: str) -> Optional[PullRequest]: ...
    def create_pull_request(
        self,
        full_name: str,
        *,
        head: str,
        base: str,
        title: str,
        body: str,
        draft: bool = False,
    ) -> PullRequest: ...
    def list_reviews(self, full_name: str, number: int) -> list[Review]: ...
    def list_review_comments(self, full_name: str, number: int) -> list[ReviewComment]: ...
    def list_issue_comments(self, full_name: str, number: int) -> list[IssueComment]: ...

    # -- CI -------------------------------------------------------------------
    def get_ci_status(self, full_name: str, ref: str) -> CIStatus: ...

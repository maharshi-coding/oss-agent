"""In-memory GitHub adapter.

A fully functional, network-free implementation of :class:`GitHubClient` used by
tests, the end-to-end workflow, and offline development. It is a *real* adapter,
not a fake presented as live: PR creation mutates in-memory state and is
reflected by subsequent reads.

It can optionally serve repository file contents from a local directory
(``set_file_root``), which lets the end-to-end test drive discovery + analysis
against a genuine local fake repository.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from oss_agent.domain.models import Issue, Repository, utcnow
from oss_agent.github.interface import GitHubClient, GitHubError
from oss_agent.github.models import (
    CIStatus,
    IssueComment,
    PullRequest,
    RepoFile,
    Review,
    ReviewComment,
)


class InMemoryGitHubClient(GitHubClient):
    def __init__(self) -> None:
        self._repos: dict[str, Repository] = {}
        self._issues: dict[str, dict[int, Issue]] = {}
        self._file_roots: dict[str, Path] = {}
        self._prs: dict[str, list[PullRequest]] = {}
        self._reviews: dict[tuple[str, int], list[Review]] = {}
        self._review_comments: dict[tuple[str, int], list[ReviewComment]] = {}
        self._issue_comments: dict[tuple[str, int], list[IssueComment]] = {}
        self._ci: dict[tuple[str, str], CIStatus] = {}
        self._pr_counter: dict[str, int] = {}
        self._linked_prs: set[tuple[str, int]] = set()

    # -- seeding helpers ------------------------------------------------------
    def add_repository(self, repo: Repository) -> "InMemoryGitHubClient":
        self._repos[repo.full_name] = repo
        self._issues.setdefault(repo.full_name, {})
        self._prs.setdefault(repo.full_name, [])
        return self

    def add_issue(self, full_name: str, issue: Issue) -> "InMemoryGitHubClient":
        self._issues.setdefault(full_name, {})[issue.number] = issue
        return self

    def set_file_root(self, full_name: str, root: str | Path) -> "InMemoryGitHubClient":
        self._file_roots[full_name] = Path(root)
        return self

    def set_ci_status(self, full_name: str, ref: str, status: CIStatus) -> None:
        self._ci[(full_name, ref)] = status

    def add_review(self, full_name: str, number: int, review: Review) -> None:
        self._reviews.setdefault((full_name, number), []).append(review)

    def add_review_comment(self, full_name: str, number: int, comment: ReviewComment) -> None:
        self._review_comments.setdefault((full_name, number), []).append(comment)

    def add_issue_comment(self, full_name: str, number: int, comment: IssueComment) -> None:
        self._issue_comments.setdefault((full_name, number), []).append(comment)

    # -- read -----------------------------------------------------------------
    def search_repositories(self, query: str, *, limit: int = 20) -> list[Repository]:
        q = query.lower()
        results = [
            r
            for r in self._repos.values()
            if q in r.full_name.lower()
            or q in (r.description or "").lower()
            or any(q in t.lower() for t in r.topics)
            or (r.primary_language or "").lower() in q
        ]
        return (results or list(self._repos.values()))[:limit]

    def get_repository(self, full_name: str) -> Repository:
        try:
            return self._repos[full_name]
        except KeyError:
            raise GitHubError(f"repository not found: {full_name}") from None

    def search_issues(self, query: str, *, limit: int = 30) -> list[tuple[Repository, Issue]]:
        q = query.lower()
        # Honor GitHub-style `label:"..."` / `label:x` qualifiers, plus free text.
        wanted_labels = {a or b for a, b in re.findall(r'label:"([^"]+)"|label:(\S+)', q)}
        free_terms = [t for t in re.sub(r'\b\w+:("[^"]*"|\S+)', " ", q).split() if len(t) > 2]
        out: list[tuple[Repository, Issue]] = []
        for full_name, issues in self._issues.items():
            repo = self._repos.get(full_name)
            if repo is None:
                continue
            for issue in issues.values():
                if issue.state != "open":
                    continue
                labels = {l.lower() for l in issue.labels}
                haystack = f"{issue.title} {issue.body} {' '.join(issue.labels)}".lower()
                label_ok = not wanted_labels or bool(wanted_labels & labels)
                text_ok = not free_terms or any(t in haystack for t in free_terms)
                if label_ok and text_ok:
                    out.append((repo, issue))
        return out[:limit]

    def list_issues(
        self,
        full_name: str,
        *,
        labels: Optional[list[str]] = None,
        state: str = "open",
        limit: int = 30,
    ) -> list[Issue]:
        issues = list(self._issues.get(full_name, {}).values())
        if state != "all":
            issues = [i for i in issues if i.state == state]
        if labels:
            wanted = set(labels)
            issues = [i for i in issues if wanted & set(i.labels)]
        return issues[:limit]

    def get_issue(self, full_name: str, number: int) -> Issue:
        try:
            return self._issues[full_name][number]
        except KeyError:
            raise GitHubError(f"issue not found: {full_name}#{number}") from None

    def issue_has_open_linked_pr(self, full_name: str, number: int) -> bool:
        return (full_name, number) in self._linked_prs

    def add_linked_pr(self, full_name: str, number: int) -> "InMemoryGitHubClient":
        """Seed an issue as already having an open PR (for tests)."""
        self._linked_prs.add((full_name, number))
        return self

    def get_file(self, full_name: str, path: str, *, ref: Optional[str] = None) -> Optional[str]:
        root = self._file_roots.get(full_name)
        if root is None:
            return None
        target = (root / path).resolve()
        # Path-traversal guard: never read outside the file root.
        if not str(target).startswith(str(root.resolve())):
            raise GitHubError(f"path traversal blocked: {path}")
        if target.is_file():
            try:
                return target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return None
        return None

    def list_files(self, full_name: str, *, ref: Optional[str] = None) -> list[RepoFile]:
        root = self._file_roots.get(full_name)
        if root is None or not root.exists():
            return []
        files: list[RepoFile] = []
        for p in sorted(root.rglob("*")):
            if ".git" in p.parts:
                continue
            rel = p.relative_to(root).as_posix()
            files.append(RepoFile(path=rel, is_dir=p.is_dir()))
        return files

    # -- pull requests --------------------------------------------------------
    def list_pull_requests(self, full_name: str, *, state: str = "open") -> list[PullRequest]:
        prs = self._prs.get(full_name, [])
        if state == "all":
            return list(prs)
        return [p for p in prs if p.state == state]

    def get_pull_request(self, full_name: str, number: int) -> PullRequest:
        for pr in self._prs.get(full_name, []):
            if pr.number == number:
                return pr
        raise GitHubError(f"PR not found: {full_name}#{number}")

    def find_pull_request_by_head(self, full_name: str, head: str) -> Optional[PullRequest]:
        for pr in self._prs.get(full_name, []):
            if pr.head == head:
                return pr
        return None

    def create_pull_request(
        self,
        full_name: str,
        *,
        head: str,
        base: str,
        title: str,
        body: str,
        draft: bool = False,
    ) -> PullRequest:
        if full_name not in self._repos:
            raise GitHubError(f"repository not found: {full_name}")
        # Idempotency: reuse an existing PR for the same head branch.
        existing = self.find_pull_request_by_head(full_name, head)
        if existing is not None:
            return existing
        number = self._pr_counter.get(full_name, 0) + 1
        self._pr_counter[full_name] = number
        pr = PullRequest(
            number=number,
            title=title,
            body=body,
            state="open",
            head=head,
            base=base,
            draft=draft,
            url=f"https://github.com/{full_name}/pull/{number}",
            author="oss-agent[bot]",
            created_at=utcnow(),
        )
        self._prs.setdefault(full_name, []).append(pr)
        return pr

    def list_reviews(self, full_name: str, number: int) -> list[Review]:
        return list(self._reviews.get((full_name, number), []))

    def list_review_comments(self, full_name: str, number: int) -> list[ReviewComment]:
        return list(self._review_comments.get((full_name, number), []))

    def list_issue_comments(self, full_name: str, number: int) -> list[IssueComment]:
        return list(self._issue_comments.get((full_name, number), []))

    def get_ci_status(self, full_name: str, ref: str) -> CIStatus:
        return self._ci.get((full_name, ref), CIStatus(ref=ref, state="pending"))


def seed_demo_data(client: InMemoryGitHubClient) -> InMemoryGitHubClient:
    """Populate a small, deterministic dataset for demos and unit tests."""
    repo = Repository(
        owner="octo-org",
        name="stringutils",
        default_branch="main",
        description="Small string utility library",
        primary_language="Python",
        languages=["Python"],
        topics=["python", "utilities", "developer-tools"],
        stars=420,
        forks=35,
        open_issues=3,
        license="MIT",
        pushed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        url="https://github.com/octo-org/stringutils",
    )
    client.add_repository(repo)
    client.add_issue(
        repo.full_name,
        Issue(
            number=101,
            title="slugify() drops trailing hyphen but should strip it",
            body=(
                "When input ends with punctuation, `slugify` leaves a trailing "
                "hyphen, e.g. `slugify('Hello!')` returns `'hello-'`. Expected "
                "`'hello'`. Please strip leading/trailing hyphens."
            ),
            state="open",
            labels=["bug", "good first issue"],
            author="maintainer",
            comments=2,
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
            updated_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            url="https://github.com/octo-org/stringutils/issues/101",
        ),
    )
    return client

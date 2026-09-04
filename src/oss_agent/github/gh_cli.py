"""GitHub adapter backed by the authenticated ``gh`` CLI.

This is a real integration. It shells out to ``gh`` (which manages its own auth)
through the controlled :class:`CommandRunner` and a :class:`RateLimiter`. It is
the production read/write path. It requires ``gh auth login`` to have been run;
if ``gh`` is missing or unauthenticated, calls raise :class:`GitHubError` with a
clear message rather than pretending to succeed.

Writes are limited to opening pull requests. Merging is intentionally not
implemented here (spec: never auto-merge).
"""

from __future__ import annotations

import base64
import json
from typing import Any, Optional, Sequence

from oss_agent.domain.models import Issue, Repository
from oss_agent.execution.runner import CommandRunner
from oss_agent.github.interface import GitHubClient, GitHubError
from oss_agent.github.models import (
    CheckRun,
    CIStatus,
    IssueComment,
    PullRequest,
    RepoFile,
    Review,
    ReviewComment,
)
from oss_agent.observability.logging import get_logger
from oss_agent.safety.rate_limit import RateLimiter

logger = get_logger("github.gh")


def _split(full_name: str) -> tuple[str, str]:
    owner, _, name = full_name.partition("/")
    if not owner or not name:
        raise GitHubError(f"invalid repository full name: {full_name!r}")
    return owner, name


class GhCliGitHubClient(GitHubClient):
    def __init__(
        self,
        *,
        runner: Optional[CommandRunner] = None,
        rate_limiter: Optional[RateLimiter] = None,
        gh_bin: str = "gh",
    ) -> None:
        # A large output budget so big JSON API responses are never truncated
        # mid-document (which would corrupt parsing).
        self._runner = runner or CommandRunner(default_timeout=120, output_limit=64_000_000)
        self._rate = rate_limiter or RateLimiter(min_interval_seconds=1.0)
        self._gh = gh_bin

    # -- low level ------------------------------------------------------------
    def _run(self, args: Sequence[str], *, input_text: Optional[str] = None) -> str:
        self._rate.acquire()
        result = self._runner.run([self._gh, *args], input_text=input_text)
        if result.exit_code == 127:
            raise GitHubError(
                "the 'gh' CLI was not found. Install it and run 'gh auth login', "
                "or set OSS_AGENT_GITHUB_BACKEND=mock."
            )
        if not result.ok:
            stderr = result.tail("stderr")
            if "authentication" in stderr.lower() or "gh auth login" in stderr.lower():
                raise GitHubError(f"gh is not authenticated: {stderr}")
            raise GitHubError(f"gh {' '.join(args)} failed ({result.exit_code}): {stderr}")
        return result.stdout

    def _json(self, args: Sequence[str]) -> Any:
        out = self._run(args)
        try:
            # strict=False tolerates raw control characters that occasionally
            # appear inside issue/PR bodies.
            return json.loads(out, strict=False) if out.strip() else None
        except json.JSONDecodeError as exc:
            raise GitHubError(f"failed to parse gh JSON output: {exc}") from exc

    # -- mapping --------------------------------------------------------------
    @staticmethod
    def _to_repo(d: dict[str, Any]) -> Repository:
        owner = d.get("owner", {})
        owner_login = owner.get("login") if isinstance(owner, dict) else owner
        full = d.get("nameWithOwner") or d.get("full_name") or ""
        if full and not owner_login:
            owner_login = full.split("/")[0]
        name = d.get("name") or (full.split("/")[1] if "/" in full else "")
        lic = d.get("licenseInfo") or d.get("license") or {}
        return Repository(
            owner=owner_login or "unknown",
            name=name or "unknown",
            default_branch=(d.get("defaultBranchRef") or {}).get("name")
            or d.get("default_branch")
            or "main",
            description=d.get("description"),
            primary_language=(d.get("primaryLanguage") or {}).get("name")
            if isinstance(d.get("primaryLanguage"), dict)
            else d.get("language"),
            stars=d.get("stargazerCount", d.get("stargazers_count", 0)) or 0,
            forks=d.get("forkCount", d.get("forks_count", 0)) or 0,
            open_issues=(d.get("issues") or {}).get("totalCount", d.get("open_issues_count", 0)) or 0,
            license=(lic.get("spdxId") or lic.get("key")) if isinstance(lic, dict) else None,
            archived=d.get("isArchived", d.get("archived", False)) or False,
            topics=[t.get("name", t) if isinstance(t, dict) else t for t in (d.get("repositoryTopics") or d.get("topics") or [])],
            url=d.get("url") or d.get("html_url"),
        )

    @staticmethod
    def _to_issue(d: dict[str, Any]) -> Issue:
        return Issue(
            number=d.get("number"),
            title=d.get("title", ""),
            body=d.get("body") or "",
            state=(d.get("state") or "open").lower(),
            labels=[l.get("name", l) if isinstance(l, dict) else l for l in (d.get("labels") or [])],
            author=(d.get("author") or {}).get("login") if isinstance(d.get("author"), dict) else d.get("user", {}).get("login") if isinstance(d.get("user"), dict) else None,
            assignees=[a.get("login", a) if isinstance(a, dict) else a for a in (d.get("assignees") or [])],
            comments=d.get("comments", 0) if isinstance(d.get("comments"), int) else len(d.get("comments", []) or []),
            url=d.get("url") or d.get("html_url"),
        )

    # -- discovery / read -----------------------------------------------------
    _REPO_FIELDS = "name,owner,nameWithOwner,description,primaryLanguage,stargazerCount,forkCount,defaultBranchRef,licenseInfo,isArchived,url"

    def search_repositories(self, query: str, *, limit: int = 20) -> list[Repository]:
        data = self._json(
            ["search", "repos", query, "--limit", str(limit), "--json",
             "name,owner,description,language,stargazersCount,forksCount,url,fullName,isArchived,license"]
        ) or []
        return [self._to_repo(d) for d in data]

    def get_repository(self, full_name: str) -> Repository:
        data = self._json(["repo", "view", full_name, "--json", self._REPO_FIELDS])
        if not data:
            raise GitHubError(f"repository not found: {full_name}")
        return self._to_repo(data)

    def search_issues(self, query: str, *, limit: int = 30) -> list[tuple[Repository, Issue]]:
        # Use the REST search endpoint so the full qualifier syntax in `query`
        # (is:issue, label:"...", language:..., sort:...) is honored — the
        # `gh search issues <positional>` form does not parse embedded qualifiers.
        data = self._json(
            ["api", "-X", "GET", "search/issues", "-f", f"q={query}", "-f", f"per_page={min(limit, 100)}"]
        )
        items = (data or {}).get("items", []) if isinstance(data, dict) else []
        results: list[tuple[Repository, Issue]] = []
        for it in items[:limit]:
            if "pull_request" in it:  # search/issues returns PRs too; skip them
                continue
            repo_url = it.get("repository_url", "")
            full = repo_url.split("/repos/", 1)[-1] if "/repos/" in repo_url else ""
            if "/" not in full:
                continue
            owner, name = _split(full)
            results.append((Repository(owner=owner, name=name), self._to_issue(it)))
        return results

    def list_issues(
        self,
        full_name: str,
        *,
        labels: Optional[list[str]] = None,
        state: str = "open",
        limit: int = 30,
    ) -> list[Issue]:
        args = ["issue", "list", "-R", full_name, "--state", state, "--limit", str(limit),
                "--json", "number,title,body,state,labels,author,assignees,url"]
        if labels:
            args += ["--label", ",".join(labels)]
        data = self._json(args) or []
        return [self._to_issue(d) for d in data]

    def get_issue(self, full_name: str, number: int) -> Issue:
        data = self._json(
            ["issue", "view", str(number), "-R", full_name,
             "--json", "number,title,body,state,labels,author,assignees,comments,url"]
        )
        if not data:
            raise GitHubError(f"issue not found: {full_name}#{number}")
        return self._to_issue(data)

    def issue_has_open_linked_pr(self, full_name: str, number: int) -> bool:
        """Whether an open pull request already references/fixes this issue.

        Prevents duplicate contributions: if someone (human or bot) already has an
        open PR for the issue, the scout must skip it. Uses the issue timeline's
        cross-referenced events.
        """
        try:
            events = self._json(["api", f"repos/{full_name}/issues/{number}/timeline"])
        except GitHubError:
            return False
        if not isinstance(events, list):
            return False
        for e in events:
            if e.get("event") in ("cross-referenced", "connected"):
                src = (e.get("source") or {}).get("issue") or {}
                if src.get("pull_request") and (src.get("state") == "open"):
                    return True
        return False

    def get_file(self, full_name: str, path: str, *, ref: Optional[str] = None) -> Optional[str]:
        endpoint = f"repos/{full_name}/contents/{path}"
        if ref:
            endpoint += f"?ref={ref}"
        try:
            data = self._json(["api", endpoint])
        except GitHubError:
            return None
        if not isinstance(data, dict) or data.get("type") != "file":
            return None
        content = data.get("content", "")
        if data.get("encoding") == "base64":
            try:
                return base64.b64decode(content).decode("utf-8", errors="replace")
            except Exception:
                return None
        return content

    def list_files(self, full_name: str, *, ref: Optional[str] = None) -> list[RepoFile]:
        ref = ref or "HEAD"
        try:
            data = self._json(["api", f"repos/{full_name}/git/trees/{ref}?recursive=1"])
        except GitHubError:
            return []
        tree = (data or {}).get("tree", [])
        return [RepoFile(path=t.get("path", ""), is_dir=t.get("type") == "tree") for t in tree]

    # -- pull requests --------------------------------------------------------
    _PR_FIELDS = "number,title,body,state,headRefName,baseRefName,isDraft,url,author,labels"

    def _to_pr(self, d: dict[str, Any]) -> PullRequest:
        return PullRequest(
            number=d.get("number"),
            title=d.get("title", ""),
            body=d.get("body") or "",
            state=(d.get("state") or "open").lower(),
            head=d.get("headRefName") or d.get("head", {}).get("ref", ""),
            base=d.get("baseRefName") or d.get("base", {}).get("ref", "main"),
            draft=d.get("isDraft", d.get("draft", False)) or False,
            merged=(d.get("state", "").lower() == "merged") or d.get("merged", False),
            url=d.get("url") or d.get("html_url"),
            author=(d.get("author") or {}).get("login") if isinstance(d.get("author"), dict) else None,
            labels=[l.get("name", l) if isinstance(l, dict) else l for l in (d.get("labels") or [])],
        )

    def list_pull_requests(self, full_name: str, *, state: str = "open") -> list[PullRequest]:
        data = self._json(
            ["pr", "list", "-R", full_name, "--state", state, "--json", self._PR_FIELDS]
        ) or []
        return [self._to_pr(d) for d in data]

    def get_pull_request(self, full_name: str, number: int) -> PullRequest:
        data = self._json(["pr", "view", str(number), "-R", full_name, "--json", self._PR_FIELDS])
        if not data:
            raise GitHubError(f"PR not found: {full_name}#{number}")
        return self._to_pr(data)

    def find_pull_request_by_head(self, full_name: str, head: str) -> Optional[PullRequest]:
        data = self._json(
            ["pr", "list", "-R", full_name, "--head", head, "--state", "all",
             "--json", self._PR_FIELDS]
        ) or []
        prs = [self._to_pr(d) for d in data]
        return prs[0] if prs else None

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
        # Idempotency: return an existing PR for this head if present.
        existing = self.find_pull_request_by_head(full_name, head)
        if existing is not None:
            logger.info("reusing existing PR", extra={"number": existing.number, "head": head})
            return existing
        args = ["pr", "create", "-R", full_name, "--head", head, "--base", base,
                "--title", title, "--body", body]
        if draft:
            args.append("--draft")
        out = self._run(args).strip()
        # gh prints the PR URL on success; fetch full data by head.
        created = self.find_pull_request_by_head(full_name, head)
        if created is None:
            number = int(out.rstrip("/").split("/")[-1]) if out.rsplit("/", 1)[-1].isdigit() else None
            created = PullRequest(number=number or 0, title=title, body=body, head=head, base=base, url=out or None, draft=draft)
        return created

    def list_reviews(self, full_name: str, number: int) -> list[Review]:
        data = self._json(["api", f"repos/{full_name}/pulls/{number}/reviews"]) or []
        from oss_agent.domain.enums import ReviewVerdict

        state_map = {
            "APPROVED": ReviewVerdict.APPROVE,
            "CHANGES_REQUESTED": ReviewVerdict.REQUEST_CHANGES,
            "COMMENTED": ReviewVerdict.REQUEST_CHANGES,
            "DISMISSED": ReviewVerdict.REQUEST_CHANGES,
        }
        return [
            Review(
                id=d.get("id", 0),
                author=(d.get("user") or {}).get("login"),
                state=state_map.get(d.get("state", ""), ReviewVerdict.REQUEST_CHANGES),
                body=d.get("body") or "",
            )
            for d in data
        ]

    def list_review_comments(self, full_name: str, number: int) -> list[ReviewComment]:
        data = self._json(["api", f"repos/{full_name}/pulls/{number}/comments"]) or []
        return [
            ReviewComment(
                id=d.get("id", 0),
                author=(d.get("user") or {}).get("login"),
                body=d.get("body") or "",
                path=d.get("path"),
                line=d.get("line"),
            )
            for d in data
        ]

    def list_issue_comments(self, full_name: str, number: int) -> list[IssueComment]:
        data = self._json(["api", f"repos/{full_name}/issues/{number}/comments"]) or []
        return [
            IssueComment(id=d.get("id", 0), author=(d.get("user") or {}).get("login"), body=d.get("body") or "")
            for d in data
        ]

    def get_ci_status(self, full_name: str, ref: str) -> CIStatus:
        try:
            combined = self._json(["api", f"repos/{full_name}/commits/{ref}/status"]) or {}
        except GitHubError:
            combined = {}
        checks: list[CheckRun] = []
        try:
            runs = self._json(["api", f"repos/{full_name}/commits/{ref}/check-runs"]) or {}
            for r in runs.get("check_runs", []):
                checks.append(CheckRun(name=r.get("name", "check"), status=r.get("status", "completed"), conclusion=r.get("conclusion")))
        except GitHubError:
            pass
        return CIStatus(ref=ref, state=combined.get("state", "pending"), checks=checks)

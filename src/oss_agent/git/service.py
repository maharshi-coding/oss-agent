"""Git service: the single, controlled abstraction over the git CLI.

No other module shells out to git. Every mutating operation is gated by the
safety layer: pushes to protected branches and force-pushes are refused, and
commits are blocked if the staged diff contains likely secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from oss_agent.execution.runner import CommandResult, CommandRunner
from oss_agent.observability.logging import get_logger
from oss_agent.safety import git_safety, secrets

logger = get_logger("git")


class GitError(RuntimeError):
    """A git command exited non-zero."""

    def __init__(self, result: CommandResult) -> None:
        self.result = result
        super().__init__(
            f"git command failed ({result.exit_code}): {' '.join(result.command)}\n"
            f"{result.tail('stderr')}"
        )


class SecretDetectedError(RuntimeError):
    """A commit was blocked because the staged diff contains likely secrets."""


@dataclass(frozen=True)
class WorktreeInfo:
    path: str
    branch: Optional[str]
    head: Optional[str]
    is_bare: bool = False
    detached: bool = False


class GitService:
    def __init__(
        self,
        runner: Optional[CommandRunner] = None,
        *,
        protected_branches: Sequence[str] = git_safety.DEFAULT_PROTECTED,
    ) -> None:
        self._runner = runner or CommandRunner()
        self._protected = tuple(protected_branches)

    # -- low level ------------------------------------------------------------
    def _git(
        self, args: Sequence[str], *, cwd: Optional[str | Path] = None, check: bool = True
    ) -> CommandResult:
        result = self._runner.run(["git", *args], cwd=cwd)
        if check and not result.ok:
            raise GitError(result)
        return result

    # -- repository facts -----------------------------------------------------
    def version(self) -> str:
        return self._git(["--version"]).stdout.strip()

    def is_git_repo(self, path: str | Path) -> bool:
        result = self._runner.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"]
        )
        return result.ok and result.stdout.strip() == "true"

    def init(self, path: str | Path, *, initial_branch: str = "main") -> None:
        Path(path).mkdir(parents=True, exist_ok=True)
        self._git(["init", "-b", initial_branch, str(path)])

    def current_branch(self, repo: str | Path) -> str:
        return self._git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).stdout.strip()

    def head_sha(self, repo: str | Path) -> str:
        return self._git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()

    def list_branches(self, repo: str | Path) -> list[str]:
        out = self._git(["branch", "--format=%(refname:short)"], cwd=repo).stdout
        return [b.strip() for b in out.splitlines() if b.strip()]

    def branch_exists(self, repo: str | Path, name: str) -> bool:
        result = self._runner.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{name}"], cwd=str(repo)
        )
        return result.ok

    def status_porcelain(self, repo: str | Path) -> str:
        return self._git(["status", "--porcelain"], cwd=repo).stdout

    def is_clean(self, repo: str | Path) -> bool:
        return not self.status_porcelain(repo).strip()

    # -- branches -------------------------------------------------------------
    def create_branch(self, repo: str | Path, name: str, *, base: Optional[str] = None) -> None:
        git_safety.assess_checkout_target(name, protected=self._protected).raise_if_blocked()
        args = ["branch", name] + ([base] if base else [])
        self._git(args, cwd=repo)

    def checkout(self, repo: str | Path, name: str, *, create: bool = False) -> None:
        args = ["checkout"] + (["-b"] if create else []) + [name]
        if create:
            git_safety.assess_checkout_target(name, protected=self._protected).raise_if_blocked()
        self._git(args, cwd=repo)

    def delete_branch(self, repo: str | Path, name: str, *, force: bool = False) -> None:
        git_safety.assess_branch_delete(name, protected=self._protected).raise_if_blocked()
        self._git(["branch", "-D" if force else "-d", name], cwd=repo)

    # -- staging & commit -----------------------------------------------------
    def add_all(self, repo: str | Path) -> None:
        self._git(["add", "-A"], cwd=repo)

    def staged_diff(self, repo: str | Path) -> str:
        return self._git(["diff", "--cached"], cwd=repo, check=False).stdout

    def diff(self, repo: str | Path, *, staged: bool = False, base: Optional[str] = None) -> str:
        args = ["diff"]
        if staged:
            args.append("--cached")
        if base:
            args.append(base)
        return self._git(args, cwd=repo, check=False).stdout

    def diff_numstat(
        self, repo: str | Path, *, staged: bool = False, base: Optional[str] = None
    ) -> list[tuple[int, int, str]]:
        """Return (additions, deletions, path) per changed file. Binary files
        report 0/0 (git prints '-' for them)."""
        args = ["diff", "--numstat"]
        if base:
            args.append(base)
        elif staged:
            args.append("--cached")
        out = self._git(args, cwd=repo, check=False).stdout
        rows: list[tuple[int, int, str]] = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                add = int(parts[0]) if parts[0].isdigit() else 0
                dele = int(parts[1]) if parts[1].isdigit() else 0
                rows.append((add, dele, parts[-1].strip()))
        return rows

    def diff_name_status(self, repo: str | Path, *, base: Optional[str] = None) -> list[tuple[str, str]]:
        args = ["diff", "--name-status"] + ([base] if base else ["--cached"])
        out = self._git(args, cwd=repo, check=False).stdout
        changes: list[tuple[str, str]] = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                changes.append((parts[0].strip(), parts[-1].strip()))
        return changes

    def commit(
        self,
        repo: str | Path,
        message: str,
        *,
        author_name: Optional[str] = None,
        author_email: Optional[str] = None,
        allow_empty: bool = False,
        scan_secrets: bool = True,
    ) -> str:
        """Commit staged changes after a secret scan of the staged diff."""
        if scan_secrets:
            diff = self.staged_diff(repo)
            found = secrets.scan_text(diff)
            if found:
                kinds = ", ".join(sorted({m.kind for m in found}))
                logger.error("commit blocked: secrets in staged diff", extra={"kinds": kinds})
                raise SecretDetectedError(
                    f"refusing to commit: likely secrets detected in staged diff ({kinds})"
                )
        env = {}
        if author_name:
            env["GIT_AUTHOR_NAME"] = author_name
            env["GIT_COMMITTER_NAME"] = author_name
        if author_email:
            env["GIT_AUTHOR_EMAIL"] = author_email
            env["GIT_COMMITTER_EMAIL"] = author_email
        args = ["commit", "-m", message]
        if allow_empty:
            args.append("--allow-empty")
        self._runner.run(["git", *args], cwd=str(repo), env=env or None, check=True)
        return self.head_sha(repo)

    # -- remote ---------------------------------------------------------------
    def remotes(self, repo: str | Path) -> list[str]:
        out = self._git(["remote"], cwd=repo, check=False).stdout
        return [r.strip() for r in out.splitlines() if r.strip()]

    def has_remote(self, repo: str | Path, name: str = "origin") -> bool:
        return name in self.remotes(repo)

    def add_remote(self, repo: str | Path, name: str, url: str) -> None:
        self._git(["remote", "add", name, url], cwd=repo)

    def push(
        self,
        repo: str | Path,
        branch: str,
        *,
        remote: str = "origin",
        force: bool = False,
        set_upstream: bool = True,
    ) -> CommandResult:
        git_safety.assess_push(branch, force=force, protected=self._protected).raise_if_blocked()
        args = ["push"]
        if set_upstream:
            args += ["-u"]
        args += [remote, branch]
        if force:
            args.append("--force-with-lease")
        return self._git(args, cwd=repo)

    # -- worktrees ------------------------------------------------------------
    def add_worktree(
        self, repo: str | Path, path: str | Path, branch: str, *, base: Optional[str] = None
    ) -> None:
        git_safety.assess_checkout_target(branch, protected=self._protected).raise_if_blocked()
        args = ["worktree", "add", "-b", branch, str(path)]
        if base:
            args.append(base)
        self._git(args, cwd=repo)

    def add_worktree_existing_branch(
        self, repo: str | Path, path: str | Path, branch: str
    ) -> None:
        git_safety.assess_checkout_target(branch, protected=self._protected).raise_if_blocked()
        self._git(["worktree", "add", str(path), branch], cwd=repo)

    def remove_worktree(self, repo: str | Path, path: str | Path, *, force: bool = False) -> None:
        args = ["worktree", "remove", str(path)]
        if force:
            args.append("--force")
        self._git(args, cwd=repo)

    def prune_worktrees(self, repo: str | Path) -> None:
        self._git(["worktree", "prune"], cwd=repo)

    def list_worktrees(self, repo: str | Path) -> list[WorktreeInfo]:
        out = self._git(["worktree", "list", "--porcelain"], cwd=repo).stdout
        infos: list[WorktreeInfo] = []
        path: Optional[str] = None
        head: Optional[str] = None
        branch: Optional[str] = None
        bare = False
        detached = False

        def flush() -> None:
            nonlocal path, head, branch, bare, detached
            if path is not None:
                infos.append(WorktreeInfo(path=path, branch=branch, head=head, is_bare=bare, detached=detached))
            path, head, branch, bare, detached = None, None, None, False, False

        for line in out.splitlines():
            line = line.strip()
            if line.startswith("worktree "):
                flush()
                path = line[len("worktree ") :]
            elif line.startswith("HEAD "):
                head = line[len("HEAD ") :]
            elif line.startswith("branch "):
                branch = line[len("branch ") :].replace("refs/heads/", "")
            elif line == "bare":
                bare = True
            elif line == "detached":
                detached = True
        flush()
        return infos

"""Create, reuse, and remove isolated worktrees without touching a base checkout."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from oss_agent.git.service import GitService


@dataclass(frozen=True)
class WorktreeHandle:
    workflow_id: str
    repo_path: str
    path: str
    branch: str
    created: bool


class WorktreeManager:
    """Own worktrees below one runtime root; GitService enforces git safety.

    An existing path is reusable only when git registers it for the requested
    repository and branch. Removal never forces deletion of uncommitted work.
    """

    def __init__(self, git: GitService, root: str | Path) -> None:
        self._git = git
        self._root = Path(root).resolve()

    def _path(self, workflow_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", workflow_id):
            raise ValueError("workflow id must be a safe single path component")
        path = self._root / workflow_id
        # A symlink under the runtime root must not redirect mutations elsewhere.
        if path.is_symlink() or path.resolve().parent != self._root:
            raise ValueError("worktree path must remain inside the runtime root")
        return path

    def create(
        self, repo: str | Path, workflow_id: str, branch: str, *, base: str = "main"
    ) -> WorktreeHandle:
        path = self._path(workflow_id)
        self._git.assert_worktree_branch_allowed(branch)
        repo_path = str(Path(repo).resolve())
        registered = next(
            (w for w in self._git.list_worktrees(repo_path)
             if Path(w.path).resolve() == path), None
        )
        if registered is not None:
            if registered.branch != branch or not path.exists():
                raise ValueError("existing worktree does not match the requested branch/path")
            return WorktreeHandle(workflow_id, repo_path, str(path), branch, False)
        if path.exists():
            raise ValueError("refusing to replace an unregistered existing worktree path")
        self._root.mkdir(parents=True, exist_ok=True)
        if self._git.branch_exists(repo_path, branch):
            self._git.add_worktree_existing_branch(repo_path, path, branch)
        else:
            self._git.add_worktree(repo_path, path, branch, base=base)
        return WorktreeHandle(workflow_id, repo_path, str(path), branch, True)

    def remove(self, repo: str | Path, workflow_id: str) -> bool:
        path = self._path(workflow_id)
        registered = any(
            Path(w.path).resolve() == path for w in self._git.list_worktrees(repo)
        )
        if not registered:
            if path.exists():
                raise ValueError("refusing to remove an unregistered worktree path")
            return False
        self._git.remove_worktree(repo, path)
        return True

"""Resolves a local git checkout of a target repository.

Worktrees are created from a local clone. For the ``gh`` backend this clones the
repository on demand; for the mock/offline backend a preconfigured local path is
used (the end-to-end fake repository). The rest of the orchestrator depends only
on the :class:`RepoProvider` protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from oss_agent.execution.runner import CommandRunner
from oss_agent.git.service import GitService
from oss_agent.observability.logging import get_logger

logger = get_logger("orchestrator.repo_provider")


class RepoProviderError(RuntimeError):
    pass


@runtime_checkable
class RepoProvider(Protocol):
    def ensure_local(self, full_name: str, *, default_branch: str = "main") -> str: ...


class MappedRepoProvider(RepoProvider):
    """Returns preconfigured local paths. Used by tests and the e2e workflow."""

    def __init__(self, mapping: Optional[dict[str, str]] = None) -> None:
        self._mapping = dict(mapping or {})

    def register(self, full_name: str, path: str | Path) -> "MappedRepoProvider":
        self._mapping[full_name] = str(path)
        return self

    def ensure_local(self, full_name: str, *, default_branch: str = "main") -> str:
        path = self._mapping.get(full_name)
        if path is None or not Path(path).exists():
            raise RepoProviderError(f"no local checkout registered for {full_name}")
        return path


class CloningRepoProvider(RepoProvider):
    """Clones repositories under a working directory using git (production path)."""

    def __init__(
        self,
        git: GitService,
        workdir: str | Path,
        *,
        runner: Optional[CommandRunner] = None,
    ) -> None:
        self._git = git
        self._workdir = Path(workdir)
        self._runner = runner or CommandRunner(default_timeout=600)

    def ensure_local(self, full_name: str, *, default_branch: str = "main") -> str:
        dest = (self._workdir / full_name.replace("/", "__")).resolve()
        if dest.exists() and self._git.is_git_repo(dest):
            logger.info("reusing existing clone", extra={"repo": full_name, "path": str(dest)})
            return str(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/{full_name}.git"
        result = self._runner.run(["git", "clone", "--depth", "50", url, str(dest)])
        if not result.ok:
            raise RepoProviderError(f"failed to clone {full_name}: {result.tail('stderr')}")
        return str(dest)

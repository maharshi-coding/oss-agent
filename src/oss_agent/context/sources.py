"""File sources for context building.

A :class:`FileSource` exposes just enough to list and read repository files. Two
implementations cover the two ways context is built:

* :class:`LocalFileSource` — the isolated worktree on disk (the accurate path used
  inside the workflow).
* :class:`GitHubFileSource` — the read-only GitHub adapter (used by the ``context``
  CLI command without checking anything out).

Both cap file size and skip binary content, so building context never reads an
unbounded amount of data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from oss_agent.github.interface import GitHubClient

_MAX_FILE_BYTES = 512_000  # never read a single file larger than this
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist",
              "build", ".mypy_cache", ".pytest_cache", ".tox", "target"}


@runtime_checkable
class FileSource(Protocol):
    def list_files(self) -> list[str]: ...
    def read_file(self, path: str) -> Optional[str]: ...


class LocalFileSource:
    """Reads files from a local directory (e.g. an isolated worktree)."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    def list_files(self) -> list[str]:
        out: list[str] = []
        for p in self._root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in _SKIP_DIRS for part in p.relative_to(self._root).parts):
                continue
            out.append(p.relative_to(self._root).as_posix())
        return sorted(out)

    def read_file(self, path: str) -> Optional[str]:
        target = (self._root / path).resolve()
        # Path-traversal / symlink-escape guard: stay within the root.
        try:
            target.relative_to(self._root)
        except ValueError:
            return None
        if not target.is_file():
            return None
        try:
            if target.stat().st_size > _MAX_FILE_BYTES:
                return None
            return target.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return None


class GitHubFileSource:
    """Reads files through the read-only GitHub client adapter."""

    def __init__(self, github: GitHubClient, full_name: str) -> None:
        self._gh = github
        self._full = full_name

    def list_files(self) -> list[str]:
        try:
            return [f.path for f in self._gh.list_files(self._full) if not f.is_dir]
        except Exception:
            return []

    def read_file(self, path: str) -> Optional[str]:
        try:
            content = self._gh.get_file(self._full, path)
        except Exception:
            return None
        if content is not None and len(content) > _MAX_FILE_BYTES:
            return None
        return content

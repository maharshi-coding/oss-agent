"""Shared test fixtures.

The star fixture is a *real* local fake repository with an intentionally failing
issue scenario, plus a fully wired :class:`WorkflowEngine` using the in-memory
GitHub adapter, the deterministic mock agent runner, and an in-memory workflow
store. No network and no real GitHub are ever touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from oss_agent.agents.base import AgentContext
from oss_agent.agents.mock_runner import MockAgentRunner, Solution
from oss_agent.config.profile import DEFAULT_PROFILE, DeveloperProfile
from oss_agent.config.settings import Settings
from oss_agent.domain.models import Issue, Repository, WorkflowSnapshot
from oss_agent.git.service import GitService
from oss_agent.github.mock import InMemoryGitHubClient
from oss_agent.orchestrator.builder import build_engine
from oss_agent.orchestrator.engine import WorkflowEngine
from oss_agent.orchestrator.repo_provider import MappedRepoProvider
from oss_agent.persistence.repository import InMemoryWorkflowRepository

FULL_NAME = "octo-org/stringutils"
ISSUE_NUMBER = 101

_BUGGED = 'import re\n\n\ndef slugify(text):\n    return re.sub(r"[^a-z0-9]+", "-", text.lower())\n'
_FIXED = 'import re\n\n\ndef slugify(text):\n    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")\n'


@dataclass
class FakeRepo:
    path: Path
    git: GitService


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def fake_repo(tmp_path: Path) -> FakeRepo:
    """A real git repository with a failing test that a fix must turn green."""
    repo = tmp_path / "stringutils"
    git = GitService()
    git.init(repo)
    _write(repo / ".gitignore", "__pycache__/\n*.pyc\n.pytest_cache/\n")
    _write(repo / "pyproject.toml", "[project]\nname = 'stringutils'\nversion = '0.1.0'\n")
    _write(repo / "README.md", "# stringutils\n\nSmall string helpers.\n")
    _write(repo / "CONTRIBUTING.md", "# Contributing\n\n- Please add tests for all changes.\n- Run pytest before submitting.\n")
    _write(repo / "stringutils" / "__init__.py", _BUGGED)
    _write(
        repo / "tests" / "test_slugify.py",
        "from stringutils import slugify\n\n\n"
        "def test_basic():\n    assert slugify('Hello World') == 'hello-world'\n\n\n"
        "def test_trailing():\n    assert slugify('Hello!') == 'hello'\n",
    )
    git.add_all(repo)
    git.commit(repo, "initial commit", author_name="Maintainer", author_email="maint@example.invalid")
    return FakeRepo(path=repo, git=git)


@pytest.fixture
def seeded_github(fake_repo: FakeRepo) -> InMemoryGitHubClient:
    gh = InMemoryGitHubClient()
    repo = Repository(
        owner="octo-org", name="stringutils", default_branch="main",
        description="Small string utility library", primary_language="Python",
        languages=["Python"], topics=["python", "developer-tools"], stars=420,
        forks=30, open_issues=1, license="MIT",
        pushed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        url=f"https://github.com/{FULL_NAME}",
    )
    gh.add_repository(repo).set_file_root(FULL_NAME, fake_repo.path)
    gh.add_issue(FULL_NAME, Issue(
        number=ISSUE_NUMBER,
        title="slugify() leaves a trailing hyphen but should strip it",
        body=(
            "When input ends with punctuation, `slugify` leaves a trailing hyphen. "
            "`slugify('Hello!')` returns `'hello-'`.\n\n"
            "Expected: `'hello'`. Please strip leading and trailing hyphens in "
            "`stringutils/__init__.py`.\n\n- [ ] slugify('Hello!') should equal 'hello'\n"
        ),
        state="open", labels=["bug", "good first issue"], author="maintainer",
        created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        url=f"https://github.com/{FULL_NAME}/issues/{ISSUE_NUMBER}",
    ))
    return gh


@pytest.fixture
def slugify_solution() -> Solution:
    def solution(ctx: AgentContext) -> list[str]:
        target = Path(ctx.worktree.path) / "stringutils" / "__init__.py"
        target.write_text(_FIXED, encoding="utf-8")
        return ["Strip leading/trailing hyphens from slugify output."]
    return solution


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        github_backend="mock",
        agent_backend="mock",
        database_url="sqlite:///:memory:",
        worktree_root=str(tmp_path / "worktrees"),
        state_dir=str(tmp_path / "state"),
        max_review_iterations=3,
        max_debug_iterations=3,
    )


@pytest.fixture
def engine(
    test_settings: Settings,
    seeded_github: InMemoryGitHubClient,
    fake_repo: FakeRepo,
    slugify_solution: Solution,
) -> WorkflowEngine:
    return build_engine(
        test_settings,
        repository=InMemoryWorkflowRepository(),
        github=seeded_github,
        runner=MockAgentRunner(solution=slugify_solution),
        repo_provider=MappedRepoProvider({FULL_NAME: str(fake_repo.path)}),
        profile=DEFAULT_PROFILE,
    )


@pytest.fixture
def broken_engine(
    test_settings: Settings,
    seeded_github: InMemoryGitHubClient,
    fake_repo: FakeRepo,
) -> WorkflowEngine:
    """An engine whose 'solution' does NOT fix the bug (tests stay red)."""
    def no_op(ctx: AgentContext) -> list[str]:
        # Touch a file without fixing the defect, so tests keep failing.
        p = Path(ctx.worktree.path) / "stringutils" / "__init__.py"
        p.write_text(p.read_text(encoding="utf-8") + "\n# noqa\n", encoding="utf-8")
        return ["no-op change"]

    return build_engine(
        test_settings,
        repository=InMemoryWorkflowRepository(),
        github=seeded_github,
        runner=MockAgentRunner(solution=no_op),
        repo_provider=MappedRepoProvider({FULL_NAME: str(fake_repo.path)}),
        profile=DEFAULT_PROFILE,
    )

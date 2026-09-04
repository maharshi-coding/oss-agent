"""Offline end-to-end demo: drive the full workflow against a real local repo.

Run it directly to watch OSS-Agent go from discovery to a ready-for-PR state and
open a pull request (recorded in the in-memory GitHub adapter) — with real git,
real pytest, and no network:

    python scripts/demo_workflow.py

This is the same scenario the end-to-end test uses, but as a standalone script.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from oss_agent.agents.mock_runner import MockAgentRunner
from oss_agent.config.profile import DEFAULT_PROFILE
from oss_agent.config.settings import Settings
from oss_agent.domain.models import Issue, Repository
from oss_agent.git.service import GitService
from oss_agent.github.mock import InMemoryGitHubClient
from oss_agent.observability.logging import configure_logging
from oss_agent.observability.report import render_report
from oss_agent.orchestrator.builder import build_engine
from oss_agent.orchestrator.repo_provider import MappedRepoProvider
from oss_agent.persistence.repository import InMemoryWorkflowRepository

FULL_NAME = "octo-org/stringutils"
BUGGED = 'import re\n\n\ndef slugify(text):\n    return re.sub(r"[^a-z0-9]+", "-", text.lower())\n'
FIXED = 'import re\n\n\ndef slugify(text):\n    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")\n'


def build_fake_repo(root: Path) -> Path:
    repo = root / "stringutils"
    git = GitService()
    git.init(repo)
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n.pytest_cache/\n")
    (repo / "pyproject.toml").write_text("[project]\nname = 'stringutils'\nversion = '0.1.0'\n")
    (repo / "README.md").write_text("# stringutils\n\nSmall string helpers.\n")
    (repo / "CONTRIBUTING.md").write_text("# Contributing\n\n- Please add tests for all changes.\n")
    (repo / "stringutils").mkdir()
    (repo / "stringutils" / "__init__.py").write_text(BUGGED)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_slugify.py").write_text(
        "from stringutils import slugify\n\n\n"
        "def test_basic():\n    assert slugify('Hello World') == 'hello-world'\n\n\n"
        "def test_trailing():\n    assert slugify('Hello!') == 'hello'\n"
    )
    git.add_all(repo)
    git.commit(repo, "initial commit", author_name="Maintainer", author_email="maint@example.invalid")
    return repo


def main() -> None:
    configure_logging("WARNING")
    tmp = Path(tempfile.mkdtemp(prefix="oss-agent-demo-"))
    try:
        repo_dir = build_fake_repo(tmp)

        gh = InMemoryGitHubClient()
        gh.add_repository(Repository(
            owner="octo-org", name="stringutils", primary_language="Python",
            languages=["Python"], topics=["python"], stars=420, license="MIT",
            pushed_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )).set_file_root(FULL_NAME, repo_dir)
        gh.add_issue(FULL_NAME, Issue(
            number=101, title="slugify() leaves a trailing hyphen",
            body="`slugify('Hello!')` returns 'hello-'. Expected 'hello'. "
                 "Strip leading/trailing hyphens in `stringutils/__init__.py`.",
            labels=["bug", "good first issue"],
            updated_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        ))

        def solution(ctx):
            (Path(ctx.worktree.path) / "stringutils" / "__init__.py").write_text(FIXED)
            return ["Strip leading/trailing hyphens from slugify output."]

        settings = Settings(
            github_backend="mock", agent_backend="mock",
            database_url="sqlite:///:memory:",
            worktree_root=str(tmp / "worktrees"), state_dir=str(tmp / "state"),
        )
        engine = build_engine(
            settings, repository=InMemoryWorkflowRepository(), github=gh,
            runner=MockAgentRunner(solution=solution),
            repo_provider=MappedRepoProvider({FULL_NAME: str(repo_dir)}),
            profile=DEFAULT_PROFILE,
        )

        engine.create_workflow(workflow_id="oss-demo", repository_full_name=FULL_NAME, issue_number=101)
        snap = engine.run("oss-demo")
        print(render_report(snap))
        print()
        snap = engine.create_pr("oss-demo")
        pr = snap.pull_request
        print(f"Pull request opened: #{pr.number} -> {pr.url}")
        print(f"Final state: {snap.state.value}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()

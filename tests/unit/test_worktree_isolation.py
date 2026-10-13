"""Real git checks for workspace containment and non-destructive reuse."""

from pathlib import Path

import pytest

from oss_agent.git.service import GitError, GitService
from oss_agent.safety.git_safety import GitSafetyError
from oss_agent.worktrees.manager import WorktreeManager

pytestmark = pytest.mark.unit


def _repo(tmp_path):
    git = GitService()
    repo = tmp_path / "repo"
    git.init(repo)
    (repo / "a.txt").write_text("initial\n")
    git.add_all(repo)
    git.commit(repo, "initial", author_name="test", author_email="test@example.invalid")
    return git, repo


@pytest.mark.parametrize("workflow_id", ["..", "../outside", "/tmp/outside", "a/b", ""])
def test_rejects_path_escape(tmp_path, workflow_id):
    git, repo = _repo(tmp_path)
    manager = WorktreeManager(git, tmp_path / "worktrees")
    with pytest.raises(ValueError):
        manager.create(repo, workflow_id, "fix/issue-1")
    assert git.list_branches(repo) == ["main"]


def test_rejects_symlink_redirect(tmp_path):
    git, repo = _repo(tmp_path)
    root = tmp_path / "worktrees"
    root.mkdir()
    (root / "workflow").symlink_to(repo, target_is_directory=True)
    with pytest.raises(ValueError):
        WorktreeManager(git, root).create(repo, "workflow", "fix/issue-1")


def test_existing_directory_is_preserved(tmp_path):
    git, repo = _repo(tmp_path)
    path = tmp_path / "worktrees" / "workflow"
    path.mkdir(parents=True)
    (path / "keep").write_text("valuable\n")
    manager = WorktreeManager(git, path.parent)
    with pytest.raises(ValueError):
        manager.create(repo, "workflow", "fix/issue-1")
    with pytest.raises(ValueError):
        manager.remove(repo, "workflow")
    assert (path / "keep").read_text() == "valuable\n"


def test_reuse_requires_same_repository_and_branch(tmp_path):
    git, repo = _repo(tmp_path)
    manager = WorktreeManager(git, tmp_path / "worktrees")
    manager.create(repo, "workflow", "fix/issue-1")
    with pytest.raises(ValueError):
        manager.create(repo, "workflow", "fix/issue-2")
    other = tmp_path / "other"
    git.init(other)
    with pytest.raises(ValueError):
        manager.create(other, "workflow", "fix/issue-1")


def test_dirty_removal_refused_and_existing_branch_reusable(tmp_path):
    git, repo = _repo(tmp_path)
    manager = WorktreeManager(git, tmp_path / "worktrees")
    handle = manager.create(repo, "workflow", "fix/issue-1")
    path = Path(handle.path)
    (path / "a.txt").write_text("uncommitted\n")
    with pytest.raises(GitError):
        manager.remove(repo, "workflow")
    assert (path / "a.txt").read_text() == "uncommitted\n"
    (path / "a.txt").write_text("initial\n")
    assert manager.remove(repo, "workflow")
    assert not manager.remove(repo, "workflow")
    recreated = manager.create(repo, "workflow", "fix/issue-1")
    assert recreated.created
    assert git.current_branch(path) == "fix/issue-1"


def test_configured_protected_branch_refused_on_reuse(tmp_path):
    git, repo = _repo(tmp_path)
    root = tmp_path / "worktrees"
    WorktreeManager(git, root).create(repo, "workflow", "fix/issue-1")
    protected = GitService(protected_branches=["main", "fix/issue-1"])
    with pytest.raises(GitSafetyError):
        WorktreeManager(protected, root).create(repo, "workflow", "fix/issue-1")

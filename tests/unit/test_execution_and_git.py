import sys

import pytest

from oss_agent.execution.retry import RetryPolicy, retry_call
from oss_agent.execution.runner import CommandRunner, DangerousCommandError
from oss_agent.git.service import GitService, SecretDetectedError
from oss_agent.safety.git_safety import GitSafetyError
from oss_agent.worktrees.manager import WorktreeManager

pytestmark = pytest.mark.unit


def test_command_runner_captures_result():
    r = CommandRunner().run([sys.executable, "-c", "print('hi')"])
    assert r.ok
    assert "hi" in r.stdout
    assert r.exit_code == 0
    assert r.duration_seconds >= 0


def test_command_runner_nonzero_exit_is_captured_not_raised():
    r = CommandRunner().run([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert not r.ok
    assert r.exit_code == 3


def test_command_runner_blocks_dangerous():
    with pytest.raises(DangerousCommandError):
        CommandRunner().run(["rm", "-rf", "/"])


def test_command_runner_missing_binary():
    r = CommandRunner().run(["this-binary-does-not-exist-xyz"])
    assert r.exit_code == 127


def test_retry_succeeds_after_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    result = retry_call(flaky, RetryPolicy(max_attempts=3, base_delay=0), sleep=lambda s: None)
    assert result == "ok"
    assert calls["n"] == 3


def test_retry_reraises_after_exhaustion():
    def always_fail():
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        retry_call(always_fail, RetryPolicy(max_attempts=2, base_delay=0), sleep=lambda s: None)


# -- git + worktree (real git) ----------------------------------------------
def _init_repo(tmp_path):
    git = GitService()
    repo = tmp_path / "repo"
    git.init(repo)
    (repo / "a.txt").write_text("hello\n")
    git.add_all(repo)
    git.commit(repo, "init", author_name="t", author_email="t@e.invalid")
    return git, repo


def test_worktree_create_reuse_and_remove(tmp_path):
    git, repo = _init_repo(tmp_path)
    wm = WorktreeManager(git, tmp_path / "wt")
    h1 = wm.create(repo, "wf-1", "fix/issue-9")
    assert h1.created and (tmp_path / "wt" / "wf-1").exists()
    assert git.branch_exists(repo, "fix/issue-9")

    h2 = wm.create(repo, "wf-1", "fix/issue-9")
    assert not h2.created  # idempotent reuse

    assert wm.remove(repo, "wf-1")
    assert not (tmp_path / "wt" / "wf-1").exists()


def test_commit_blocks_secret(tmp_path):
    git, repo = _init_repo(tmp_path)
    (repo / "leak.txt").write_text("aws = AKIA" + "A" * 16 + "\n")
    git.add_all(repo)
    with pytest.raises(SecretDetectedError):
        git.commit(repo, "leak")


def test_push_to_protected_branch_blocked(tmp_path):
    git, repo = _init_repo(tmp_path)
    with pytest.raises(GitSafetyError):
        git.push(repo, "main")


def test_cannot_create_worktree_on_protected_branch(tmp_path):
    git, repo = _init_repo(tmp_path)
    wm = WorktreeManager(git, tmp_path / "wt")
    with pytest.raises(GitSafetyError):
        wm.create(repo, "wf-x", "main")

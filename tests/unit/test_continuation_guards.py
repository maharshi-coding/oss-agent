"""Deterministic transport, review-scope, and compatible-scaffolding checks."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from oss_agent.agents.claude_runner import ClaudeAgentRunner
from oss_agent.domain.enums import WorkflowState
from oss_agent.domain.models import PullRequestContinuation, PullRequestResult, WorkflowSnapshot
from oss_agent.github.gh_cli import GhCliGitHubClient
from oss_agent.orchestrator.engine import WorkflowEngine
from oss_agent.persistence.repository import InMemoryWorkflowRepository


pytestmark = pytest.mark.unit


def _patch(path, additions):
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        "@@ -14,3 +14,8 @@ android {\n context\n"
        + "\n".join(additions) + "\n context\n"
    )


@pytest.mark.parametrize("other,compatible", [
    (["+    testImplementation 'junit:junit:4.13.2'"], True),
    (["+    testImplementation 'junit:junit:4.13.2'", "+    androidTestImplementation 'androidx.test:runner:1.6.2'"], True),
    (["+    testImplementation 'junit:junit:5.0.0'"], False),
    (["+    testImplementation 'junit:junit:4.13.2'", "+    testImplementation 'junit:junit:5.0.0'"], False),
    (["+    testImplementation 'junit:junit:4.13.2'", "+    implementation 'camera:core:2.0.0'"], False),
    (["+    testImplementation 'junit:junit:4.13.2'", "+    testOptions { unitTests.includeAndroidResources = false }"], False),
    (["-    existingSetting = true", "+    testImplementation 'junit:junit:4.13.2'"], False),
])
def test_only_identical_additive_test_dependencies_can_overlap(other, compatible):
    path = "android/build.gradle"
    own = _patch(path, ["+    testImplementation 'junit:junit:4.13.2'"])
    assert WorkflowEngine._shared_scaffolding_matches(own, _patch(path, other), path) is compatible


def test_shared_test_setup_at_another_original_anchor_does_not_match():
    path = "android/build.gradle"
    own = _patch(path, ["+    testImplementation 'junit:junit:4.13.2'"])
    other = own.replace("@@ -14,3 +14,8 @@", "@@ -50,3 +50,8 @@")
    assert not WorkflowEngine._shared_scaffolding_matches(own, other, path)


def test_identical_production_edits_are_still_competing_work():
    path = "android/src/main/java/Camera.kt"
    patch = _patch(path, ["+    fixCamera()"])
    assert not WorkflowEngine._shared_scaffolding_matches(patch, patch, path)


def test_gh_reads_complete_rest_pr_identity_and_preserves_public_url(monkeypatch):
    gh = GhCliGitHubClient()
    payload = {
        "number": 822, "title": "Existing fix", "state": "open", "draft": True,
        "url": "https://api.github.com/repos/upstream/camera/pulls/822",
        "html_url": "https://github.com/upstream/camera/pull/822",
        "user": {"login": "maharshi-coding"},
        "head": {
            "ref": "fix/existing", "sha": "a" * 40,
            "repo": {"full_name": "maharshi-coding/camera", "owner": {"login": "maharshi-coding"}},
        },
        "base": {"ref": "main", "sha": "b" * 40, "repo": {"full_name": "upstream/camera"}},
    }
    call = Mock(return_value=payload)
    monkeypatch.setattr(gh, "_json", call)
    pr = gh.get_pull_request("upstream/camera", 822)
    call.assert_called_once_with(["api", "repos/upstream/camera/pulls/822"])
    assert pr.url == payload["html_url"]
    assert pr.repository_full_name == "upstream/camera"
    assert pr.head_repository_full_name == "maharshi-coding/camera"
    assert pr.head_repository_owner == pr.author == "maharshi-coding"
    assert pr.head_sha == "a" * 40 and pr.base_sha == "b" * 40


def test_gh_update_is_structured_patch_without_draft_or_branch_mutation(monkeypatch):
    gh = GhCliGitHubClient()
    run = Mock(return_value="{}")
    fetch = Mock(return_value=object())
    monkeypatch.setattr(gh, "_run", run)
    monkeypatch.setattr(gh, "get_pull_request", fetch)
    body = "Measured validation\n\nLiteral `code` and $variables.\n"
    gh.update_pull_request("upstream/camera", 822, title="Refined fix", body=body)
    assert run.call_args.args[0] == [
        "api", "--method", "PATCH", "repos/upstream/camera/pulls/822", "--input", "-",
    ]
    assert json.loads(run.call_args.kwargs["input_text"]) == {"title": "Refined fix", "body": body}
    fetch.assert_called_once_with("upstream/camera", 822)


def test_claude_review_uses_full_merge_base_delta_and_explicit_adoption_intent():
    target = PullRequestContinuation(
        number=822, repository_full_name="upstream/camera", author="maharshi-coding",
        head_sha="a" * 40, base_sha="b" * 40,
        head_repository_full_name="maharshi-coding/camera", head_repository_owner="maharshi-coding",
        head_branch="fix/existing", base_branch="main", draft=True,
        url="https://github.com/upstream/camera/pull/822",
    )
    snap = WorkflowSnapshot(id="review-existing", continuation=target, review_base_sha="c" * 40)
    git = Mock()
    git.diff.return_value = "FULL_DELTA"
    ctx = SimpleNamespace(snapshot=snap, worktree=SimpleNamespace(path="isolated-worktree"), git=git)
    assert ClaudeAgentRunner._review_diff(ctx) == "FULL_DELTA"
    git.diff.assert_called_once_with("isolated-worktree", base="c" * 40)
    instructions = ClaudeAgentRunner._continuation_instructions(ctx)
    assert "own existing PR #822" in instructions
    assert "OTHER competing work" in instructions
    assert "Preserve every suitability, test, and review gate" in instructions


@pytest.mark.parametrize("field,value", [
    ("existing_pr_number", None), ("existing_pr_number", 823),
    ("continuation", None),
    ("url", "https://github.com/upstream/camera/pull/822/"),
    ("repository_full_name", "other/camera"),
])
def test_duplicate_monitor_exception_requires_consistent_canonical_adoption(field, value):
    full = "upstream/camera"
    url = f"https://github.com/{full}/pull/822"
    target = PullRequestContinuation(
        number=822, repository_full_name=full, author="maharshi-coding",
        head_sha="a" * 40, base_sha="b" * 40,
        head_repository_full_name="maharshi-coding/camera", head_repository_owner="maharshi-coding",
        head_branch="fix/existing", base_branch="main", draft=True, url=url,
    )
    current = WorkflowSnapshot(
        id="adopting", repository_full_name=full, issue_number=521,
        existing_pr_number=822, continuation=target,
    )
    published = WorkflowSnapshot(
        id="published", state=WorkflowState.PR_MONITORING,
        repository_full_name=full, issue_number=521,
        pull_request=PullRequestResult(
            repository_full_name=full, issue_number=521, branch="fix/existing",
            number=822, url=url, created=True,
        ),
    )
    if field in {"url", "repository_full_name"}:
        setattr(current.continuation, field, value)
    else:
        setattr(current, field, value)
    engine = object.__new__(WorkflowEngine)
    engine.repo = InMemoryWorkflowRepository()
    engine.repo.save(published)
    engine.github = Mock()
    engine.github.find_pull_request_by_head.return_value = None
    assert engine._duplicate_reason(current) == "active workflow published already targets this issue"


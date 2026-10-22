"""Adopt an owned PR without duplicating it or bypassing publication gates.

All GitHub calls are in memory. Git fetch/worktree/commit/push commands execute
against real local repositories; a recording transport maps the two exact
GitHub URLs to those repositories, so these tests never use the network.
"""

from pathlib import Path

import pytest

from oss_agent.agents.mock_runner import MockAgentRunner
from oss_agent.app import Application
from oss_agent.domain.enums import WorkflowState
from oss_agent.domain.models import PullRequestResult, WorkflowSnapshot
from oss_agent.execution.runner import CommandRunner
from oss_agent.orchestrator.engine import (
    HumanApprovalRequired, OrchestrationError, SubmissionBlocked,
)

from tests.conftest import FULL_NAME, ISSUE_NUMBER, _FIXED


pytestmark = pytest.mark.integration


@pytest.fixture
def continuation(engine, fake_repo, seeded_github, tmp_path, monkeypatch):
    commands = CommandRunner()
    base_sha = fake_repo.git.head_sha(fake_repo.path)
    fake_repo.git.checkout(fake_repo.path, "fix/existing", create=True)
    (fake_repo.path / "stringutils/__init__.py").write_text(_FIXED)
    fake_repo.git.add_all(fake_repo.path)
    head_sha = fake_repo.git.commit(
        fake_repo.path, "Existing contribution", author_name="Original Author",
        author_email="original@example.invalid",
    )
    fake_repo.git.checkout(fake_repo.path, "main")
    commands.run(
        ["git", "update-ref", "refs/pull/822/head", head_sha],
        cwd=fake_repo.path, check=True,
    )
    fork = tmp_path / "owned-fork.git"
    commands.run(["git", "clone", "--bare", str(fake_repo.path), str(fork)], check=True)
    calls = []

    class LocalTransport:
        def run(self, args, **kwargs):
            calls.append(list(args))
            mapping = {
                f"https://github.com/{FULL_NAME}.git": str(fake_repo.path),
                "https://github.com/maharshi-coding/stringutils.git": str(fork),
            }
            return commands.run([mapping.get(str(arg), arg) for arg in args], **kwargs)

    engine.git._runner = LocalTransport()
    engine.settings.github_login = "maharshi-coding"
    engine.settings.git_author_name = "Maharshi Barot"
    engine.settings.git_author_email = "barotmaharshi393@gmail.com"
    seeded_github.login = "maharshi-coding"
    pr = seeded_github.create_pull_request(
        FULL_NAME, head="fix/existing", base="main", title="Existing fix",
        body="Related to #101", draft=True,
    )
    pr.number = 822
    pr.url = f"https://github.com/{FULL_NAME}/pull/822"
    pr.author = "maharshi-coding"
    pr.repository_full_name = FULL_NAME
    pr.head_repository_full_name = "maharshi-coding/stringutils"
    pr.head_repository_owner = "maharshi-coding"
    pr.head_sha, pr.base_sha = head_sha, base_sha
    engine.runner = MockAgentRunner(solution=lambda ctx: [])
    app = Application(engine)
    app.create(FULL_NAME, ISSUE_NUMBER, workflow_id="continue-822", existing_pr_number=822)
    return app, pr, calls, fork


def _ready(continuation):
    app, pr, calls, fork = continuation
    snap = app.run("continue-822")
    assert snap.state is WorkflowState.READY_FOR_PR, snap.last_error
    return app, pr, calls, fork, snap


def test_adopts_exact_head_and_reviews_full_delta(continuation, fake_repo):
    app, pr, calls, fork, snap = _ready(continuation)
    assert snap.continuation.head_sha == pr.head_sha
    assert snap.related_pr_numbers == [822]
    assert app.engine.git.head_sha(snap.worktree_path) == pr.head_sha
    assert app.engine.git.current_branch(fake_repo.path) == "main"
    assert app.engine.git.head_sha(fake_repo.path) == pr.base_sha
    assert '.strip("-")' in app.diff(snap.id)
    assert not app.engine.git.staged_diff(snap.worktree_path)
    assert ["git", "fetch", "--no-tags", "--", f"https://github.com/{FULL_NAME}.git", "refs/pull/822/head"] in calls


def _published_workflow(app, pr):
    """Persist the original publication as monitoring, as a live submit does."""
    published = WorkflowSnapshot(
        id="original-publication", state=WorkflowState.PR_MONITORING,
        repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER,
        pull_request=PullRequestResult(
            repository_full_name=FULL_NAME, issue_number=ISSUE_NUMBER,
            branch=pr.head, number=pr.number, url=pr.url, created=True,
        ),
    )
    app.engine.repo.save(published)
    return published


def test_adopts_published_pr_while_original_workflow_monitors_it(continuation):
    app, pr, calls, fork = continuation
    published = _published_workflow(app, pr)
    _, _, _, _, snap = _ready(continuation)
    assert snap.continuation.number == published.pull_request.number
    assert snap.continuation.url == published.pull_request.url
    assert snap.test_result.passed
    assert snap.code_review is not None
    assert snap.security_review is not None
    assert snap.maintainer_review is not None
    assert app.engine.get(published.id).state is WorkflowState.PR_MONITORING
    assert not any("push" in c for c in calls)


@pytest.mark.parametrize("field,value", [
    ("created", False), ("number", 823), ("url", None),
    ("url", f"https://github.com/{FULL_NAME}/pull/823"),
    ("url", f"https://github.com/{FULL_NAME}/pull/822/"),
    ("repository_full_name", "other/upstream"), ("issue_number", ISSUE_NUMBER + 1),
])
def test_adoption_blocks_mismatched_or_unpublished_monitoring_record(continuation, field, value):
    app, pr, calls, fork = continuation
    published = _published_workflow(app, pr)
    setattr(published.pull_request, field, value)
    app.engine.repo.save(published)
    snap = app.engine.step("continue-822")
    assert snap.state is WorkflowState.ABORTED
    assert "active workflow original-publication" in snap.last_error
    assert not snap.worktree_path
    assert not any("fetch" in c or "push" in c for c in calls)


@pytest.mark.parametrize("state", [
    WorkflowState.DISCOVERY, WorkflowState.IMPLEMENTATION,
    WorkflowState.READY_FOR_PR, WorkflowState.PR_CREATED,
])
def test_adoption_still_blocks_active_work_even_with_matching_pr_record(continuation, state):
    app, pr, calls, fork = continuation
    published = _published_workflow(app, pr)
    published.state = state
    app.engine.repo.save(published)
    snap = app.engine.step("continue-822")
    assert snap.state is WorkflowState.ABORTED
    assert "active workflow original-publication" in snap.last_error


def test_adoption_still_blocks_a_second_active_continuation(continuation):
    app, pr, calls, fork = continuation
    _published_workflow(app, pr)
    first = app.engine.step("continue-822")
    assert first.state is WorkflowState.REPOSITORY_ANALYSIS
    app.create(FULL_NAME, ISSUE_NUMBER, workflow_id="second-continuation", existing_pr_number=822)
    second = app.engine.step("second-continuation")
    assert second.state is WorkflowState.ABORTED
    assert "active workflow continue-822" in second.last_error


def test_adoption_blocks_monitoring_without_a_publication_record(continuation):
    app, pr, calls, fork = continuation
    published = _published_workflow(app, pr)
    published.pull_request = None
    app.engine.repo.save(published)
    snap = app.engine.step("continue-822")
    assert snap.state is WorkflowState.ABORTED
    assert "active workflow original-publication" in snap.last_error


def test_unadopted_issue_does_not_ignore_a_published_workflow(continuation):
    app, pr, calls, fork = continuation
    published = _published_workflow(app, pr)
    app.engine.repo.delete("continue-822")
    app.create(FULL_NAME, ISSUE_NUMBER, workflow_id="fresh-contribution")
    snap = app.engine.step("fresh-contribution")
    assert snap.state is WorkflowState.ABORTED
    assert f"active workflow {published.id}" in snap.last_error


@pytest.mark.parametrize("field,value", [
    ("author", "someone-else"), ("head_repository_owner", "someone-else"),
    ("head_repository_full_name", "maharshi-coding/other-repo"),
    ("repository_full_name", "other/upstream"), ("state", "closed"),
    ("merged", True), ("head", "main"), ("head_sha", None),
])
def test_rejects_unowned_closed_unverified_or_protected_pr(continuation, field, value):
    app, pr, calls, fork = continuation
    setattr(pr, field, value)
    snap = app.run("continue-822")
    assert snap.state is WorkflowState.FAILED
    assert not snap.worktree_path
    assert not any("fetch" in c or "push" in c for c in calls)


def test_requires_expected_authenticated_account(continuation):
    app, pr, calls, fork = continuation
    app.engine.github.login = "wrong-account"
    snap = app.run("continue-822")
    assert snap.state is WorkflowState.FAILED
    assert "expected maharshi-coding" in snap.last_error


def test_fetch_ref_must_match_the_pinned_pr_head(continuation):
    app, pr, calls, fork = continuation
    pr.head_sha = "1" * 40
    snap = app.run("continue-822")
    assert snap.state is WorkflowState.FAILED
    assert "head changed while fetching" in snap.last_error
    assert snap.worktree_path is None


def test_existing_pr_does_not_bypass_human_or_legacy_gate(continuation):
    app, pr, calls, fork, snap = _ready(continuation)
    with pytest.raises(SubmissionBlocked, match="prepare-pr"):
        app.submit(snap.id, confirm=True)
    app.prepare_pr(snap.id)
    with pytest.raises(HumanApprovalRequired):
        app.submit(snap.id, confirm=True)
    app.approve(snap.id)
    with pytest.raises(HumanApprovalRequired):
        app.submit(snap.id, confirm=False)
    with pytest.raises(HumanApprovalRequired, match="continuations"):
        app.create_pr(snap.id)
    assert not any("push" in c for c in calls)


def test_no_incremental_changes_updates_same_draft_without_commit_or_push(continuation):
    app, pr, calls, fork, snap = _ready(continuation)
    app.prepare_pr(snap.id)
    prepared = app.status(snap.id).pull_request
    assert prepared.number == 822 and prepared.draft
    assert prepared.branch == pr.head
    assert "Related to #101" in prepared.body
    app.approve(snap.id)
    submitted = app.submit(snap.id, confirm=True)
    assert submitted.state is WorkflowState.PR_MONITORING, submitted.last_error
    assert submitted.pull_request.number == 822
    assert submitted.pull_request.draft is True
    assert len(app.engine.github.list_pull_requests(FULL_NAME)) == 1
    assert app.engine.git.head_sha(snap.worktree_path) == pr.head_sha
    assert not any("push" in c or "commit" in c for c in calls)


def test_incremental_change_fast_forwards_exact_fork_branch_with_configured_identity(continuation):
    app, pr, calls, fork = continuation

    def clarify(ctx):
        path = Path(ctx.worktree.path) / "stringutils/__init__.py"
        path.write_text(path.read_text() + "\n# Preserve normalized slugs.\n")
        return ["Clarified existing implementation."]

    app.engine.runner = MockAgentRunner(solution=clarify)
    app, pr, calls, fork, snap = _ready(continuation)
    app.prepare_pr(snap.id)
    app.approve(snap.id)
    submitted = app.submit(snap.id, confirm=True)
    assert submitted.state is WorkflowState.PR_MONITORING, submitted.last_error
    assert app.engine.git.commit_identity(snap.worktree_path) == (
        "Maharshi Barot", "barotmaharshi393@gmail.com",
        "Maharshi Barot", "barotmaharshi393@gmail.com",
    )
    push = [c for c in calls if "push" in c]
    assert push == [[
        "git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential",
        "push", "--", "https://github.com/maharshi-coding/stringutils.git", "HEAD:refs/heads/fix/existing",
    ]]
    pushed = CommandRunner().run(["git", "rev-parse", "refs/heads/fix/existing"], cwd=fork, check=True).stdout.strip()
    assert pushed == app.engine.git.head_sha(snap.worktree_path)
    assert pushed != pr.head_sha


@pytest.mark.parametrize("field,value", [
    ("head_sha", "1" * 40), ("base_sha", "2" * 40),
    ("head_repository_owner", "someone-else"), ("draft", False),
])
def test_submission_rechecks_adopted_pr_metadata(continuation, field, value):
    app, pr, calls, fork, snap = _ready(continuation)
    app.prepare_pr(snap.id)
    app.approve(snap.id)
    setattr(pr, field, value)
    with pytest.raises(SubmissionBlocked):
        app.submit(snap.id, confirm=True)
    assert not any("push" in c for c in calls)


def test_continuation_keeps_tests_and_review_gates(continuation):
    app, pr, calls, fork, snap = _ready(continuation)
    app.prepare_pr(snap.id)
    app.approve(snap.id)
    changed = app.status(snap.id)
    changed.test_result = None
    app.engine.repo.save(changed)
    with pytest.raises(OrchestrationError, match="tests"):
        app.submit(snap.id, confirm=True)


def test_continuation_does_not_override_real_duplicate_risk(continuation):
    app, pr, calls, fork = continuation

    class ConflictingWorkRunner(MockAgentRunner):
        def analyze_issue(self, ctx):
            result = super().analyze_issue(ctx)
            result.duplicate_risk = 0.9
            return result

    app.engine.runner = ConflictingWorkRunner(solution=lambda ctx: [])
    snap = app.run("continue-822")
    assert snap.state is WorkflowState.ABORTED
    assert snap.issue_analysis.duplicate_risk == 0.9
    assert any("high duplicate risk" in b for b in snap.suitability.blockers)
    assert not snap.worktree_path


@pytest.mark.parametrize("reference", [
    "#101", "octo-org/stringutils#101", "https://github.com/octo-org/stringutils/issues/101",
])
def test_continuation_cannot_publish_a_closing_issue_reference(continuation, reference):
    app, pr, calls, fork, snap = _ready(continuation)
    app.prepare_pr(snap.id)
    prepared = app.status(snap.id)
    prepared.pull_request.body += f"\nFixes {reference}\n"
    app.engine.repo.save(prepared)
    app.approve(snap.id)
    result = app.submit(snap.id, confirm=True)
    assert result.state is WorkflowState.FAILED
    assert "without closing it" in result.last_error
    assert not any("push" in c or "commit" in c for c in calls)


def test_regenerated_prepared_description_requires_new_human_decision(continuation):
    app, pr, calls, fork, snap = _ready(continuation)
    app.prepare_pr(snap.id)
    app.approve(snap.id)
    app.prepare_pr(snap.id)
    with pytest.raises(HumanApprovalRequired):
        app.submit(snap.id, confirm=True)


def test_changed_content_after_tests_is_blocked(continuation):
    app, pr, calls, fork, snap = _ready(continuation)
    app.prepare_pr(snap.id)
    app.approve(snap.id)
    path = Path(snap.worktree_path) / "stringutils/__init__.py"
    path.write_text(path.read_text() + "\n# Unreviewed change.\n")
    with pytest.raises(OrchestrationError, match="changed since passing tests"):
        app.submit(snap.id, confirm=True)


def test_full_review_excludes_upstream_changes_after_the_pr_branched(continuation, fake_repo):
    app, pr, calls, fork = continuation
    original_base = pr.base_sha
    (fake_repo.path / "upstream_only.py").write_text("def upstream_feature():\n    return True\n")
    fake_repo.git.add_all(fake_repo.path)
    pr.base_sha = fake_repo.git.commit(
        fake_repo.path, "Unrelated upstream feature", author_name="Maintainer",
        author_email="maintainer@example.invalid",
    )
    app, pr, calls, fork, snap = _ready(continuation)
    assert snap.review_base_sha == original_base
    assert "upstream_only.py" not in app.diff(snap.id)
    assert '.strip("-")' in app.diff(snap.id)


@pytest.mark.parametrize("overlap", [False, True])
def test_competing_work_is_assessed_by_actual_file_scope(continuation, monkeypatch, overlap):
    app, pr, calls, fork, snap = _ready(continuation)
    competitor = app.engine.github.create_pull_request(
        FULL_NAME, head="other-fix", base="main", title="Another related aspect",
        body="Related to #101",
    )
    path = "stringutils/__init__.py" if overlap else "another_component.py"
    monkeypatch.setattr(app.engine.github, "get_pull_request_diff", lambda *a: f"--- a/{path}\n+++ b/{path}\n+change\n")
    app.prepare_pr(snap.id)
    app.approve(snap.id)
    if overlap:
        with pytest.raises(SubmissionBlocked, match="overlaps contribution files"):
            app.submit(snap.id, confirm=True)
    else:
        assert app.submit(snap.id, confirm=True).state is WorkflowState.PR_MONITORING


import pytest

from oss_agent.github.interface import GitHubError
from oss_agent.github.mock import InMemoryGitHubClient, seed_demo_data

pytestmark = pytest.mark.integration


def test_seeded_search_and_get():
    gh = seed_demo_data(InMemoryGitHubClient())
    repos = gh.search_repositories("string")
    assert any(r.full_name == "octo-org/stringutils" for r in repos)
    issue = gh.get_issue("octo-org/stringutils", 101)
    assert issue.number == 101
    assert "good first issue" in issue.labels


def test_search_issues_honors_label_qualifier():
    gh = seed_demo_data(InMemoryGitHubClient())
    results = gh.search_issues('label:"good first issue"')
    assert [(r.full_name, i.number) for r, i in results] == [("octo-org/stringutils", 101)]


def test_pr_creation_is_idempotent_by_head():
    gh = seed_demo_data(InMemoryGitHubClient())
    pr1 = gh.create_pull_request("octo-org/stringutils", head="fix/issue-101", base="main",
                                 title="Fix", body="body")
    pr2 = gh.create_pull_request("octo-org/stringutils", head="fix/issue-101", base="main",
                                 title="Fix again", body="body2")
    assert pr1.number == pr2.number
    assert gh.find_pull_request_by_head("octo-org/stringutils", "fix/issue-101").number == pr1.number


def test_file_serving_and_path_traversal_guard(tmp_path):
    (tmp_path / "README.md").write_text("hello")
    gh = InMemoryGitHubClient()
    from oss_agent.domain.models import Repository
    gh.add_repository(Repository(owner="o", name="r")).set_file_root("o/r", tmp_path)
    assert gh.get_file("o/r", "README.md") == "hello"
    assert gh.get_file("o/r", "missing.md") is None
    with pytest.raises(GitHubError):
        gh.get_file("o/r", "../../secret.txt")


def test_missing_repository_raises():
    gh = InMemoryGitHubClient()
    with pytest.raises(GitHubError):
        gh.get_repository("does/not-exist")

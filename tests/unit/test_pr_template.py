"""Unit tests for shared PR-template discovery."""

from __future__ import annotations

import pytest

from oss_agent.agents.pr_template import PR_TEMPLATE_PATHS, find_pr_template

pytestmark = pytest.mark.unit


class _FakeGitHub:
    def __init__(self, files: dict[str, str]):
        self.files = files
        self.asked: list[str] = []

    def get_file(self, full_name, path, *, ref=None):
        self.asked.append(path)
        return self.files.get(path)


def test_finds_template_in_github_dir():
    gh = _FakeGitHub({".github/pull_request_template.md": "## Checklist\n- [ ] tests"})
    assert "Checklist" in find_pr_template(gh, "o/r")


def test_returns_none_when_absent():
    gh = _FakeGitHub({})
    assert find_pr_template(gh, "o/r") is None
    # It probed the known locations.
    assert set(gh.asked) == set(PR_TEMPLATE_PATHS)


def test_none_repo_short_circuits():
    gh = _FakeGitHub({"PULL_REQUEST_TEMPLATE.md": "x"})
    assert find_pr_template(gh, None) is None
    assert gh.asked == []


def test_ignores_empty_template_file():
    gh = _FakeGitHub({".github/pull_request_template.md": "   \n  "})
    assert find_pr_template(gh, "o/r") is None


def test_get_file_errors_are_swallowed():
    class Boom(_FakeGitHub):
        def get_file(self, *a, **k):
            raise RuntimeError("network")

    assert find_pr_template(Boom({}), "o/r") is None

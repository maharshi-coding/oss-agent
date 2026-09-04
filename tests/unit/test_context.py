"""Unit tests for deterministic repository-context selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from oss_agent.context.builder import RepositoryContextBuilder
from oss_agent.context.sources import LocalFileSource
from oss_agent.domain.enums import ContributionType
from oss_agent.domain.models import IssueAnalysis

pytestmark = pytest.mark.unit


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _write(tmp_path, "pyproject.toml", "[project]\nname='x'\n")
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/encoding.py",
           "def decode_output(data):\n    return data.decode('ascii')\n\n\n"
           "class Decoder:\n    def run(self):\n        return decode_output(b'x')\n")
    _write(tmp_path, "pkg/unrelated.py", "def helper():\n    return 1\n")
    _write(tmp_path, "tests/test_encoding.py",
           "from pkg.encoding import decode_output\n\n"
           "def test_decode():\n    assert decode_output(b'x') == 'x'\n")
    return tmp_path


def _analysis(**kw) -> IssueAnalysis:
    base = dict(
        repository_full_name="o/r", issue_number=1,
        problem_statement="decode_output fails on non-ASCII bytes in encoding",
        expected_behavior="decode using utf-8",
        probable_files=["pkg/encoding.py"],
        contribution_type=ContributionType.BUG_FIX,
    )
    base.update(kw)
    return IssueAnalysis(**base)


def test_locates_likely_file_symbols_and_tests(repo):
    ctx = RepositoryContextBuilder().build(LocalFileSource(repo), _analysis(), "o/r")
    assert "pkg/encoding.py" in ctx.likely_files
    assert "pkg/unrelated.py" not in ctx.likely_files
    names = {s.name for s in ctx.relevant_symbols}
    assert "decode_output" in names and "Decoder" in names
    assert any("test_encoding" in t for t in ctx.related_tests)
    assert "pyproject.toml" in ctx.entry_points
    assert ctx.notes  # inspectable hints


def test_symbol_locations_are_real(repo):
    ctx = RepositoryContextBuilder().build(LocalFileSource(repo), _analysis(), "o/r")
    decode = next(s for s in ctx.relevant_symbols if s.name == "decode_output")
    assert decode.file == "pkg/encoding.py"
    assert decode.kind == "function"
    assert decode.line == 1  # first line of the file


def test_keyword_matching_without_probable_files(repo):
    # Even with no explicit file references, keywords should find the file.
    ctx = RepositoryContextBuilder().build(
        LocalFileSource(repo), _analysis(probable_files=[]), "o/r")
    assert "pkg/encoding.py" in ctx.likely_files


def test_empty_repo_degrades_gracefully(tmp_path):
    ctx = RepositoryContextBuilder().build(LocalFileSource(tmp_path), _analysis(), "o/r")
    assert ctx.likely_files == []
    assert any("under-specify" in n or "No high-confidence" in n for n in ctx.notes)


def test_local_source_skips_git_and_guards_traversal(repo):
    (repo / ".git").mkdir(exist_ok=True)
    _write(repo, ".git/config", "secret")
    src = LocalFileSource(repo)
    assert not any(".git" in f for f in src.list_files())
    assert src.read_file("../../etc/passwd") is None

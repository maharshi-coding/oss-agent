"""Deterministic repository-context selection.

Given an issue analysis and a :class:`FileSource`, locate the small set of files,
tests, and symbols most relevant to the issue, using filename + keyword + symbol
search. Bounded on every axis (files scanned, files read, symbols returned) so it
never sends an unbounded slice of the repository anywhere.
"""

from __future__ import annotations

import ast
import re
from typing import Optional

from oss_agent.context.sources import FileSource
from oss_agent.domain.models import IssueAnalysis, RepositoryContext, SymbolRef

_SOURCE_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb", ".c",
    ".cpp", ".cc", ".h", ".hpp", ".cs", ".php", ".kt", ".swift", ".scala",
}
_MANIFESTS = {
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "package.json",
    "cargo.toml", "go.mod", "pom.xml", "build.gradle", "gemfile", "makefile",
}
_STOPWORDS = frozenset({
    "the", "and", "for", "but", "not", "you", "this", "that", "with", "when",
    "should", "would", "could", "have", "has", "was", "were", "are", "into",
    "from", "issue", "bug", "fix", "error", "expected", "actual", "please",
    "returns", "return", "value", "code", "test", "tests", "add", "use", "using",
})
# Non-Python "def/class" patterns (best-effort).
_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+)?(?:public\s+|private\s+|static\s+|async\s+)*"
    r"(?P<kind>def|class|function|func|fn|type|interface|struct)\s+(?P<name>[A-Za-z_]\w*)",
)

_MAX_SCAN = 800      # files whose names we consider
_MAX_READ = 300      # files whose contents we grep
_MAX_LIKELY = 8
_MAX_SYMBOLS = 20
_MAX_TESTS = 8


def _tokenize(text: str) -> list[str]:
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text or "")
    out: list[str] = []
    seen: set[str] = set()
    for t in toks:
        low = t.lower()
        if low in _STOPWORDS or low in seen:
            continue
        seen.add(low)
        out.append(low)
    return out


def _is_test(path: str) -> bool:
    p = path.lower()
    return "test" in p and (p.startswith("test") or "/test" in p or "test_" in p
                            or p.endswith(("_test.py", "_test.go", ".test.js", ".test.ts", ".spec.ts")))


class RepositoryContextBuilder:
    def build(
        self,
        source: FileSource,
        analysis: Optional[IssueAnalysis],
        repository_full_name: str = "",
    ) -> RepositoryContext:
        keywords = self._keywords(analysis)
        files = source.list_files()[:_MAX_SCAN]
        probable = set(analysis.probable_files if analysis else [])

        source_files = [f for f in files if _dotext(f) in _SOURCE_EXTS]
        entry_points = [f for f in files if f.split("/")[-1].lower() in _MANIFESTS]

        # Score candidate files by keyword hits in the path (cheap) then content.
        scored: list[tuple[float, str]] = []
        read_budget = _MAX_READ
        for f in source_files:
            if _is_test(f):
                continue
            score = 0.0
            if f in probable or any(f.endswith(p) for p in probable):
                score += 5.0
            path_low = f.lower()
            score += 3.0 * sum(1 for k in keywords if k in path_low)
            content = None
            if read_budget > 0:
                content = source.read_file(f)
                read_budget -= 1
                if content:
                    cl = content.lower()
                    score += min(4.0, sum(1 for k in keywords if k in cl))
            if score > 0:
                scored.append((score, f))

        scored.sort(key=lambda t: (-t[0], t[1]))
        likely = [f for _, f in scored[:_MAX_LIKELY]]
        # Always surface issue-named files that actually exist.
        for p in probable:
            match = next((f for f in files if f == p or f.endswith(p)), None)
            if match and match not in likely:
                likely.insert(0, match)
        likely = likely[:_MAX_LIKELY]

        symbols = self._symbols(source, likely, keywords)
        related_tests = self._related_tests(source, files, likely, keywords)
        notes = self._notes(likely, symbols, keywords)

        return RepositoryContext(
            repository_full_name=repository_full_name,
            keywords=keywords[:15],
            likely_files=likely,
            related_tests=related_tests,
            relevant_symbols=symbols,
            entry_points=entry_points[:6],
            notes=notes,
            summary=(f"{len(likely)} likely file(s), {len(symbols)} symbol(s), "
                     f"{len(related_tests)} related test(s)."),
            confidence=0.6 if likely else 0.2,
        )

    # -- pieces ---------------------------------------------------------------
    def _keywords(self, analysis: Optional[IssueAnalysis]) -> list[str]:
        if analysis is None:
            return []
        text = " ".join([
            analysis.problem_statement, analysis.expected_behavior,
            " ".join(analysis.acceptance_criteria), " ".join(analysis.affected_components),
        ])
        kws = _tokenize(text)
        # File stems from probable files are strong signals.
        for p in analysis.probable_files:
            stem = p.split("/")[-1].rsplit(".", 1)[0].lower()
            if len(stem) >= 3 and stem not in kws:
                kws.insert(0, stem)
        return kws

    def _symbols(self, source: FileSource, likely: list[str], keywords: list[str]) -> list[SymbolRef]:
        symbols: list[SymbolRef] = []
        for f in likely:
            content = source.read_file(f)
            if not content:
                continue
            if f.endswith(".py"):
                symbols.extend(self._py_symbols(f, content))
            else:
                symbols.extend(self._regex_symbols(f, content))
        # Prefer symbols matching a keyword; keep order otherwise.
        kw = set(keywords)
        symbols.sort(key=lambda s: (0 if s.name.lower() in kw or any(k in s.name.lower() for k in kw) else 1))
        return symbols[:_MAX_SYMBOLS]

    @staticmethod
    def _py_symbols(path: str, content: str) -> list[SymbolRef]:
        out: list[SymbolRef] = []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return out
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                out.append(SymbolRef(name=node.name, kind="class", file=path, line=node.lineno))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append(SymbolRef(name=node.name, kind="function", file=path, line=node.lineno))
        return out

    @staticmethod
    def _regex_symbols(path: str, content: str) -> list[SymbolRef]:
        out: list[SymbolRef] = []
        for i, line in enumerate(content.splitlines(), start=1):
            m = _SYMBOL_RE.match(line)
            if m:
                kind = m.group("kind")
                kind = "class" if kind in ("class", "interface", "struct", "type") else "function"
                out.append(SymbolRef(name=m.group("name"), kind=kind, file=path, line=i))
        return out

    def _related_tests(self, source: FileSource, files: list[str], likely: list[str],
                       keywords: list[str]) -> list[str]:
        tests = [f for f in files if _is_test(f)]
        stems = {f.split("/")[-1].rsplit(".", 1)[0].lower() for f in likely}
        hits: list[tuple[float, str]] = []
        read_budget = 60
        for t in tests:
            score = 0.0
            tl = t.lower()
            if any(s in tl for s in stems):
                score += 3.0
            if read_budget > 0:
                content = source.read_file(t)
                read_budget -= 1
                if content:
                    cl = content.lower()
                    score += sum(1 for s in stems if s in cl)
                    score += 0.5 * sum(1 for k in keywords if k in cl)
            if score > 0:
                hits.append((score, t))
        hits.sort(key=lambda x: (-x[0], x[1]))
        return [t for _, t in hits[:_MAX_TESTS]]

    def _notes(self, likely: list[str], symbols: list[SymbolRef], keywords: list[str]) -> list[str]:
        notes: list[str] = []
        if likely:
            notes.append(f"Most likely implementation site: {likely[0]}")
        if symbols:
            top = symbols[0]
            notes.append(f"Start from {top.kind} `{top.name}` ({top.file}:{top.line})")
        if not likely:
            notes.append("No high-confidence files located from the issue text; "
                         "the issue may under-specify where the change belongs.")
        return notes


def _dotext(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return "." + name.rsplit(".", 1)[1].lower() if "." in name else ""

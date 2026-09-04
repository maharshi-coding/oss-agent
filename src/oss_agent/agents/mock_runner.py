"""Deterministic, offline agent runner.

Read-only agents (discovery, repository/issue analysis, reviews, maintainer
simulation, PR composition) use *real heuristics* over *real inputs* — they read
the actual repository files (served by the GitHub adapter), parse the actual
issue text, and inspect the actual git diff. Nothing here fabricates results.

The one agent that requires genuine domain reasoning — the *implementer* — cannot
be invented offline for an arbitrary repository. It therefore delegates to an
injected :data:`Solution` strategy. Tests and the end-to-end workflow register a
real solution that performs real edits; in production the Claude runner performs
this step. If no solution is available the runner raises
:class:`NoSolutionError` rather than pretending to have implemented anything.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from oss_agent.agents.base import AgentContext, AgentRunner, NoSolutionError
from oss_agent.agents.pr_template import find_pr_template
from oss_agent.domain.enums import (
    ContributionType,
    Difficulty,
    MaintainerVerdict,
    ReviewVerdict,
    Severity,
)
from oss_agent.domain.models import (
    DiscoveryCandidate,
    DiscoveryResult,
    FileChange,
    ImplementationPlan,
    ImplementationResult,
    Issue,
    IssueAnalysis,
    MaintainerReview,
    PlanStep,
    PullRequestResult,
    Repository,
    RepositoryReport,
    ReviewFinding,
    ReviewResult,
    SecurityFinding,
    SecurityResult,
    TestResult,
)
from oss_agent.git.naming import branch_name_for
from oss_agent.observability.logging import get_logger
from oss_agent.safety import prompt_injection, secrets

logger = get_logger("agents.mock")

# A solution mutates the worktree to satisfy the plan and returns notes. The
# runner computes the *actual* changed files from git afterward (real evidence).
Solution = Callable[[AgentContext], list[str]]

_MANIFESTS = {
    "pyproject.toml": ("python", "pip"),
    "setup.py": ("python", "pip"),
    "setup.cfg": ("python", "pip"),
    "requirements.txt": ("python", "pip"),
    "package.json": ("node", "npm"),
    "Cargo.toml": ("rust", "cargo"),
    "go.mod": ("go", "go"),
    "pom.xml": ("java", "maven"),
    "build.gradle": ("java", "gradle"),
    "Gemfile": ("ruby", "bundler"),
}

_DANGEROUS_CODE = [
    ("eval_exec", re.compile(r"\b(eval|exec)\s*\("), Severity.HIGH, "use of eval/exec"),
    ("shell_true", re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True"), Severity.HIGH, "subprocess with shell=True"),
    ("os_system", re.compile(r"\bos\.system\s*\("), Severity.HIGH, "os.system call"),
    ("yaml_load", re.compile(r"yaml\.load\s*\((?![^)]*Loader)"), Severity.MEDIUM, "unsafe yaml.load"),
    ("pickle_loads", re.compile(r"pickle\.loads?\s*\("), Severity.MEDIUM, "pickle deserialization"),
    ("md5_usage", re.compile(r"hashlib\.md5\s*\("), Severity.LOW, "weak hash md5"),
]


class MockAgentRunner(AgentRunner):
    def __init__(
        self,
        *,
        solution: Optional[Solution] = None,
        debug_solution: Optional[Solution] = None,
    ) -> None:
        self._solution = solution
        self._debug_solution = debug_solution or solution

    # -- discovery ------------------------------------------------------------
    def discover(self, ctx: AgentContext) -> DiscoveryResult:
        profile = ctx.profile
        query = ctx.discovery_query or self._build_query(profile)
        found = ctx.github.search_issues(query, limit=ctx.max_candidates * 3)
        candidates: list[DiscoveryCandidate] = []
        filtered = 0
        for repo, issue in found:
            full = ctx.github.get_repository(repo.full_name) if not repo.stars else repo
            ok, reason = self._passes_filters(full, issue, profile)
            if not ok:
                filtered += 1
                continue
            signal = self._preliminary_signal(full, issue, profile)
            candidates.append(
                DiscoveryCandidate(
                    repository=full, issue=issue, reason=reason, preliminary_signal=signal
                )
            )
        candidates.sort(key=lambda c: c.preliminary_signal, reverse=True)
        candidates = candidates[: ctx.max_candidates]
        return DiscoveryResult(
            query=query,
            candidates=candidates,
            filtered_out=filtered,
            summary=f"Found {len(candidates)} candidate issue(s) for query '{query}'.",
            confidence=0.8 if candidates else 0.3,
        )

    def _build_query(self, profile) -> str:
        langs = " ".join(f"language:{l}" for l in list(profile.known_languages())[:2])
        return f"is:issue is:open label:\"good first issue\" {langs}".strip()

    def _passes_filters(self, repo: Repository, issue: Issue, profile) -> tuple[bool, str]:
        f = profile.filters
        if f.exclude_archived and repo.archived:
            return False, "archived repository"
        if repo.stars < f.min_stars:
            return False, f"below min_stars ({repo.stars}<{f.min_stars})"
        if repo.stars > f.max_stars:
            return False, f"above max_stars ({repo.stars}>{f.max_stars})"
        if (
            f.allowed_licenses
            and repo.license
            and repo.license.lower() not in {lic.lower() for lic in f.allowed_licenses}
        ):
            return False, f"license {repo.license} not allowed"
        text = f"{repo.description or ''} {' '.join(repo.topics)}".lower()
        for domain in profile.excluded_domains:
            if domain.lower() in text:
                return False, f"excluded domain '{domain}'"
        if issue.assignees:
            return False, "already assigned"
        return True, "matches profile filters"

    def _preliminary_signal(self, repo: Repository, issue: Issue, profile) -> float:
        signal = 0.4
        labels = {l.lower() for l in issue.labels}
        if "good first issue" in labels:
            signal += 0.2
        if "help wanted" in labels:
            signal += 0.1
        if "bug" in labels:
            signal += 0.1
        signal += 0.2 * profile.language_weight(repo.primary_language)
        return min(1.0, signal)

    # -- repository analysis --------------------------------------------------
    def analyze_repository(self, ctx: AgentContext) -> RepositoryReport:
        repo = ctx.snapshot.repository or ctx.github.get_repository(
            ctx.snapshot.repository_full_name or ""
        )
        files = {f.path for f in ctx.github.list_files(repo.full_name) if not f.is_dir}
        lower = {p.lower() for p in files}

        def has(*names: str) -> bool:
            return any(n.lower() in lower for n in names)

        has_readme = has("readme.md", "readme.rst", "readme.txt", "readme")
        has_contributing = any("contributing" in p for p in lower)
        has_coc = any("code_of_conduct" in p for p in lower)
        has_security = any(p.endswith("security.md") for p in lower)
        has_tests = any(
            ("test" in p or p.startswith("tests/") or "/tests/" in p) for p in lower
        )
        has_ci = any(".github/workflows/" in p for p in lower)

        build_system = None
        package_managers: list[str] = []
        for manifest, (lang, pm) in _MANIFESTS.items():
            if manifest.lower() in lower:
                build_system = build_system or lang
                if pm not in package_managers:
                    package_managers.append(pm)

        test_cmd, lint_cmd, type_cmd, build_cmd = self._infer_commands(build_system, has_tests, files)

        # Scan README/CONTRIBUTING for injection attempts (untrusted content).
        injection_flags: list[str] = []
        requirements: list[str] = []
        for path in list(files):
            if "contributing" in path.lower() or path.lower().endswith("readme.md"):
                content = ctx.github.get_file(repo.full_name, path) or ""
                injection_flags.extend(prompt_injection.summarize_flags(prompt_injection.scan(content)))
                if "contributing" in path.lower():
                    requirements.extend(self._extract_requirements(content))

        conventions = []
        if build_system == "python":
            conventions.append("PEP 8 / typed Python")
        if has_tests:
            conventions.append("changes require tests")

        return RepositoryReport(
            repository=repo,
            has_readme=has_readme,
            has_contributing=has_contributing,
            has_code_of_conduct=has_coc,
            has_security_policy=has_security,
            has_tests=has_tests,
            has_ci=has_ci,
            license=repo.license,
            build_system=build_system,
            package_managers=package_managers,
            test_command=test_cmd,
            lint_command=lint_cmd,
            typecheck_command=type_cmd,
            build_command=build_cmd,
            conventions=conventions,
            contributing_requirements=requirements[:10],
            architecture_notes=[f"{len(files)} tracked files", f"build system: {build_system or 'unknown'}"],
            health_signals={"file_count": len(files)},
            injection_flags=injection_flags,
            summary=f"{repo.full_name}: build={build_system}, tests={has_tests}, ci={has_ci}.",
            confidence=0.8,
        )

    def _infer_commands(self, build_system, has_tests, files):
        if build_system == "python":
            return ("python -m pytest" if has_tests else None, "ruff check .", "mypy .", None)
        if build_system == "node":
            return ("npm test", "npm run lint", "npm run typecheck", "npm run build")
        if build_system == "rust":
            return ("cargo test", "cargo clippy", None, "cargo build")
        if build_system == "go":
            return ("go test ./...", "go vet ./...", None, "go build ./...")
        return (None, None, None, None)

    def _extract_requirements(self, content: str) -> list[str]:
        reqs = []
        for line in content.splitlines():
            s = line.strip("-*# ").strip()
            if re.match(r"(?i)(all|please|make sure|ensure|run|add|include|follow)\b", s) and len(s) < 160:
                reqs.append(s)
        return reqs

    # -- issue analysis -------------------------------------------------------
    def analyze_issue(self, ctx: AgentContext) -> IssueAnalysis:
        issue = ctx.snapshot.issue or ctx.github.get_issue(
            ctx.snapshot.repository_full_name or "", ctx.snapshot.issue_number or 0
        )
        body = issue.body or ""
        labels = {l.lower() for l in issue.labels}

        problem = self._first_paragraph(body) or issue.title
        expected = self._extract_expected(body)
        criteria = self._extract_criteria(body)
        ctype = self._infer_type(issue, labels)
        difficulty = self._infer_difficulty(labels, body)
        probable_files = self._extract_paths(body)
        ambiguity = self._ambiguity(body, expected, criteria)
        duplicate_risk = 0.6 if issue.linked_pr_numbers else self._duplicate_risk(ctx, issue)
        breaking = 0.5 if any(k in body.lower() for k in ("breaking", "backward", "api change")) else 0.1
        security = 0.6 if any(k in labels for k in ("security", "vulnerability")) else (
            0.3 if any(k in body.lower() for k in ("auth", "password", "token", "injection")) else 0.05
        )
        complexity = self._complexity(body, difficulty)
        inj = prompt_injection.summarize_flags(prompt_injection.scan(body))

        return IssueAnalysis(
            repository_full_name=issue.url and ctx.snapshot.repository_full_name or ctx.snapshot.repository_full_name or "",
            issue_number=issue.number,
            problem_statement=problem,
            expected_behavior=expected,
            acceptance_criteria=criteria,
            affected_components=list({p.split("/")[0] for p in probable_files}) if probable_files else [],
            probable_files=probable_files,
            contribution_type=ctype,
            difficulty=difficulty,
            test_requirements=["Add/adjust tests covering the reported behavior"] if ctx.snapshot.repository_report and ctx.snapshot.repository_report.has_tests else [],
            risks=["Regression in related behavior"] if breaking > 0.3 else [],
            ambiguity_score=ambiguity,
            is_ambiguous=ambiguity >= 0.6,
            duplicate_risk=duplicate_risk,
            breaking_change_risk=breaking,
            security_sensitivity=security,
            complexity=complexity,
            injection_flags=inj,
            summary=f"{ctype.value} in {ctx.snapshot.repository_full_name}#{issue.number}; ambiguity={ambiguity:.2f}.",
            confidence=round(0.9 - 0.5 * ambiguity, 2),
        )

    def _first_paragraph(self, body: str) -> str:
        for para in re.split(r"\n\s*\n", body.strip()):
            p = para.strip()
            if p and not p.startswith("#"):
                return re.sub(r"\s+", " ", p)[:400]
        return ""

    def _extract_expected(self, body: str) -> str:
        m = re.search(r"(?i)expected[:\s]+(.+?)(?:\n\n|\Z)", body, re.DOTALL)
        return re.sub(r"\s+", " ", m.group(1)).strip()[:300] if m else ""

    def _extract_criteria(self, body: str) -> list[str]:
        criteria = []
        for line in body.splitlines():
            s = line.strip()
            if re.match(r"^[-*]\s+\[.\]", s):  # task list
                criteria.append(re.sub(r"^[-*]\s+\[.\]\s*", "", s))
            elif "should" in s.lower() and 8 < len(s) < 200:
                criteria.append(s.strip("-* "))
        # deduplicate preserving order
        seen = set()
        out = []
        for c in criteria:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out[:8]

    def _infer_type(self, issue: Issue, labels: set[str]) -> ContributionType:
        if labels & {"bug", "defect"}:
            return ContributionType.BUG_FIX
        if labels & {"documentation", "docs"}:
            return ContributionType.DOCUMENTATION
        if labels & {"enhancement", "feature"}:
            return ContributionType.FEATURE
        if labels & {"test", "testing"}:
            return ContributionType.TEST
        title = issue.title.lower()
        if any(w in title for w in ("fix", "bug", "broken", "incorrect", "wrong")):
            return ContributionType.BUG_FIX
        if any(w in title for w in ("add", "support", "implement", "feature")):
            return ContributionType.FEATURE
        if any(w in title for w in ("doc", "readme", "typo")):
            return ContributionType.DOCUMENTATION
        return ContributionType.BUG_FIX

    def _infer_difficulty(self, labels: set[str], body: str) -> Difficulty:
        if labels & {"good first issue", "beginner", "easy"}:
            return Difficulty.EASY
        if labels & {"hard", "complex", "epic"}:
            return Difficulty.HARD
        return Difficulty.MODERATE if len(body) > 600 else Difficulty.EASY

    def _extract_paths(self, body: str) -> list[str]:
        paths = re.findall(r"`?([\w./-]+\.(?:py|js|ts|go|rs|java|rb|md|txt|cfg|toml|yaml|yml))`?", body)
        seen = set()
        out = []
        for p in paths:
            if p not in seen and "/" in p or p.endswith((".py", ".js", ".ts", ".go", ".rs")):
                if p not in seen:
                    seen.add(p)
                    out.append(p)
        return out[:8]

    def _ambiguity(self, body: str, expected: str, criteria: list[str]) -> float:
        score = 0.5
        if expected:
            score -= 0.2
        if criteria:
            score -= 0.15
        if "```" in body or re.search(r"`[^`]+`", body):
            score -= 0.1
        if len(body) < 60:
            score += 0.3
        if body.count("?") >= 2:
            score += 0.1
        return round(max(0.0, min(1.0, score)), 2)

    def _complexity(self, body: str, difficulty: Difficulty) -> float:
        base = {Difficulty.TRIVIAL: 0.1, Difficulty.EASY: 0.25, Difficulty.MODERATE: 0.5,
                Difficulty.HARD: 0.8, Difficulty.ANY: 0.4}[difficulty]
        if len(body) > 1200:
            base = min(1.0, base + 0.2)
        return round(base, 2)

    def _duplicate_risk(self, ctx: AgentContext, issue: Issue) -> float:
        try:
            head = branch_name_for(issue.number)
            existing = ctx.github.find_pull_request_by_head(
                ctx.snapshot.repository_full_name or "", head
            )
            return 0.9 if existing else 0.05
        except Exception:
            return 0.1

    # -- planning -------------------------------------------------------------
    def plan(self, ctx: AgentContext) -> ImplementationPlan:
        a = ctx.snapshot.issue_analysis
        if a is None:
            raise NoSolutionError("cannot plan without an issue analysis")
        branch = branch_name_for(a.issue_number, a.contribution_type)
        # Leave affected_files possibly empty when the issue names no concrete
        # paths: an empty list means "scope not enforced by an explicit allowlist"
        # rather than falsely flagging every real change as out of scope.
        affected = list(a.probable_files)
        steps = [
            PlanStep(order=1, description="Reproduce the reported behavior with a failing test",
                     target_files=[f for f in affected if "test" in f] or ["tests/"], rationale="Confirm the defect before fixing"),
            PlanStep(order=2, description=f"Implement the fix: {a.problem_statement[:120]}",
                     target_files=[f for f in affected if "test" not in f] or affected, rationale="Address root cause"),
            PlanStep(order=3, description="Run the full test suite and quality checks",
                     target_files=[], rationale="Capture real evidence of success"),
        ]
        return ImplementationPlan(
            repository_full_name=a.repository_full_name,
            issue_number=a.issue_number,
            objective=a.expected_behavior or a.problem_statement or "Resolve the reported issue",
            contribution_type=a.contribution_type,
            branch_name=branch,
            affected_files=affected,
            do_not_modify=["LICENSE", "CHANGELOG.md", ".github/workflows/"],
            steps=steps,
            test_plan=a.test_requirements or ["Run the repository test suite"],
            acceptance_criteria=a.acceptance_criteria or [a.expected_behavior or "Reported behavior resolved"],
            risks=a.risks,
            rollback_strategy="Revert the feature branch; no protected branch is modified.",
            summary=f"Plan for {a.repository_full_name}#{a.issue_number} on branch {branch}.",
            confidence=a.confidence,
        )

    # -- implementation -------------------------------------------------------
    def implement(self, ctx: AgentContext) -> ImplementationResult:
        return self._apply_solution(ctx, self._solution, "implement")

    def debug(self, ctx: AgentContext, test_result: TestResult) -> ImplementationResult:
        return self._apply_solution(ctx, self._debug_solution, "debug")

    def _apply_solution(self, ctx: AgentContext, solution: Optional[Solution], phase: str) -> ImplementationResult:
        if ctx.worktree is None:
            raise NoSolutionError("implementation requires an isolated worktree")
        if solution is None:
            raise NoSolutionError(
                "offline mock runner has no registered solution; the Claude runner "
                "performs implementation in production. Provide a solution for tests."
            )
        notes = solution(ctx) or []
        # Stage everything and derive REAL changed-file evidence from git.
        ctx.git.add_all(ctx.worktree.path)
        changes = ctx.git.diff_name_status(ctx.worktree.path)  # staged (--cached)
        plan = ctx.snapshot.plan
        allowed = set(plan.affected_files) if plan else set()
        file_changes: list[FileChange] = []
        unexpected: list[str] = []
        for status, path in changes:
            ctype = {"A": "added", "M": "modified", "D": "deleted"}.get(status[0], "modified")
            file_changes.append(FileChange(path=path, change_type=ctype))
            if allowed and path not in allowed and "test" not in path.lower():
                unexpected.append(path)
        return ImplementationResult(
            plan_branch=ctx.worktree.branch,
            files_changed=file_changes,
            unexpected_files=unexpected,
            notes=notes,
            summary=f"{phase}: {len(file_changes)} file(s) changed on {ctx.worktree.branch}.",
            confidence=0.75,
        )

    # -- code review ----------------------------------------------------------
    def review_code(self, ctx: AgentContext) -> ReviewResult:
        diff = self._current_diff(ctx)
        impl = ctx.snapshot.implementation
        plan = ctx.snapshot.plan
        findings: list[ReviewFinding] = []

        scope_ok = True
        if impl and impl.unexpected_files:
            scope_ok = False
            findings.append(ReviewFinding(
                category="scope", severity=Severity.HIGH,
                message=f"Change touches files outside the plan: {impl.unexpected_files}",
                suggestion="Restrict the change to the planned files.",
            ))

        touched_test = any("test" in fc.path.lower() for fc in (impl.files_changed if impl else []))
        tests_adequate = True
        if plan and plan.test_plan and not touched_test:
            tests_adequate = False
            findings.append(ReviewFinding(
                category="tests", severity=Severity.MEDIUM,
                message="No test file was added or modified for a change that requires tests.",
                suggestion="Add a regression test.",
            ))

        if diff.count("\n") > 600:
            findings.append(ReviewFinding(
                category="complexity", severity=Severity.LOW,
                message="Large diff; consider splitting.",
            ))
        for m in secrets.scan_text(diff):
            findings.append(ReviewFinding(
                category="secret", severity=Severity.CRITICAL,
                message=f"Possible secret in diff: {m.kind}", suggestion="Remove the secret.",
            ))

        blocking = [f for f in findings if f.severity.rank >= Severity.HIGH.rank]
        verdict = ReviewVerdict.APPROVE if (not blocking and scope_ok) else ReviewVerdict.REQUEST_CHANGES
        return ReviewResult(
            verdict=verdict, findings=findings, scope_ok=scope_ok, tests_adequate=tests_adequate,
            summary=f"code review: {verdict.value} ({len(findings)} finding(s)).",
            confidence=0.8,
        )

    # -- security review ------------------------------------------------------
    def review_security(self, ctx: AgentContext) -> SecurityResult:
        diff = self._current_diff(ctx)
        added = "\n".join(l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        findings: list[SecurityFinding] = []

        secret_hits = secrets.scan_text(added)
        for m in secret_hits:
            findings.append(SecurityFinding(
                category="secret", severity=Severity.CRITICAL,
                message=f"Likely secret ({m.kind}) introduced in diff.", evidence=m.preview,
            ))
        for name, pattern, sev, msg in _DANGEROUS_CODE:
            if pattern.search(added):
                findings.append(SecurityFinding(category="unsafe_code", severity=sev, message=msg))
        if re.search(r"\.\./", added):
            findings.append(SecurityFinding(
                category="path_traversal", severity=Severity.MEDIUM,
                message="Possible path traversal ('../') introduced.",
            ))
        # Prompt-injection carried from untrusted repo/issue content.
        report = ctx.snapshot.repository_report
        analysis = ctx.snapshot.issue_analysis
        inj_flags = (report.injection_flags if report else []) + (analysis.injection_flags if analysis else [])
        for flag in inj_flags:
            findings.append(SecurityFinding(
                category="prompt_injection", severity=Severity.MEDIUM,
                message=f"Untrusted content flagged for prompt injection: {flag}",
                evidence="repository/issue content",
            ))

        secrets_detected = bool(secret_hits)
        injection_detected = any(f.category == "prompt_injection" for f in findings)
        blocking = [f for f in findings if f.severity.rank >= Severity.HIGH.rank]
        verdict = ReviewVerdict.REJECT if secrets_detected else (
            ReviewVerdict.REQUEST_CHANGES if blocking else ReviewVerdict.APPROVE
        )
        return SecurityResult(
            verdict=verdict, findings=findings,
            secrets_detected=secrets_detected, prompt_injection_detected=injection_detected,
            summary=f"security review: {verdict.value} ({len(findings)} finding(s)).",
            confidence=0.85,
        )

    # -- maintainer simulation ------------------------------------------------
    def maintainer_review(self, ctx: AgentContext) -> MaintainerReview:
        s = ctx.snapshot
        reasons: list[str] = []
        requested: list[str] = []
        praise: list[str] = []

        tests_pass = bool(s.test_result and s.test_result.passed)
        code_ok = bool(s.code_review and s.code_review.verdict == ReviewVerdict.APPROVE)
        sec_ok = bool(s.security_review and s.security_review.verdict == ReviewVerdict.APPROVE)
        scope_ok = bool(s.implementation and not s.implementation.unexpected_files)

        if tests_pass:
            praise.append("All tests and quality checks pass with captured evidence.")
        else:
            reasons.append("Tests are not green.")
            requested.append("Make the full test suite pass.")
        if not code_ok:
            reasons.append("Code review requested changes.")
            requested.extend(f.message for f in (s.code_review.findings if s.code_review else []) if f.severity.rank >= Severity.HIGH.rank)
        if not sec_ok:
            reasons.append("Security review did not approve.")
            requested.extend(f.message for f in (s.security_review.findings if s.security_review else []))
        if not scope_ok:
            reasons.append("Change is out of scope.")
        if s.repository_report and s.repository_report.contributing_requirements:
            praise.append("CONTRIBUTING guidelines were considered.")

        if s.security_review and s.security_review.verdict == ReviewVerdict.REJECT:
            verdict = MaintainerVerdict.REJECT
        elif tests_pass and code_ok and sec_ok and scope_ok:
            verdict = MaintainerVerdict.APPROVE
        else:
            verdict = MaintainerVerdict.REQUEST_CHANGES

        return MaintainerReview(
            verdict=verdict, reasons=reasons or ["Meets the bar for this repository."],
            requested_changes=requested, praise=praise,
            summary=f"maintainer verdict: {verdict.value}.",
            confidence=0.8,
        )

    # -- PR composition -------------------------------------------------------
    def compose_pull_request(self, ctx: AgentContext) -> PullRequestResult:
        s = ctx.snapshot
        plan = s.plan
        issue_no = s.issue_number or 0
        title = (s.issue.title if s.issue else None) or (plan.objective if plan else "Contribution")
        if plan and plan.contribution_type == ContributionType.BUG_FIX and not title.lower().startswith("fix"):
            title = f"fix: {title}"
        changed = [fc.path for fc in (s.implementation.files_changed if s.implementation else [])]
        tests_line = ""
        if s.test_result:
            passed = s.test_result.total_tests_passed
            tests_line = f"- Tests: {passed} passed across {len(s.test_result.suites)} suite(s)\n"
        summary_block = (
            f"## Summary\n\n{plan.objective if plan else ''}\n\n"
            f"Closes #{issue_no}.\n\n"
            f"## Changes\n\n" + ("".join(f"- `{p}`\n" for p in changed) or "- (see diff)\n") +
            f"\n## Verification\n\n{tests_line}"
            f"- Code review: {s.code_review.verdict.value if s.code_review else 'n/a'}\n"
            f"- Security review: {s.security_review.verdict.value if s.security_review else 'n/a'}\n"
        )
        template = find_pr_template(ctx.github, s.repository_full_name)
        if template:
            # Respect the repository's template: keep its structure/checklist for
            # the human to complete, with our evidence-backed summary on top.
            body = (
                f"{summary_block}\n"
                f"---\n<!-- Repository pull-request template (complete before submitting) -->\n\n"
                f"{template}\n\n"
                f"---\n_Prepared by OSS-Agent. Repository content was treated as untrusted data._\n"
            )
        else:
            body = (
                f"{summary_block}\n"
                f"---\n_Prepared by OSS-Agent. Repository content was treated as untrusted data._\n"
            )
        return PullRequestResult(
            repository_full_name=s.repository_full_name or "",
            issue_number=issue_no,
            branch=(s.branch or (plan.branch_name if plan else "")),
            title=title,
            body=body,
            draft=False,
            created=False,
            summary="PR description composed (not yet created).",
            confidence=0.8,
        )

    # -- helpers --------------------------------------------------------------
    def _current_diff(self, ctx: AgentContext) -> str:
        if ctx.worktree is None:
            return ""
        return ctx.git.diff(ctx.worktree.path, staged=True)

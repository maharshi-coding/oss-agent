"""Build and render a :class:`LearningReport` from a completed workflow.

This is deterministic assembly, grounded in artifacts the workflow actually
produced: the issue analysis, the plan, the real changed files (with add/delete
counts from ``git``), and the captured test results. It does not invent a
narrative — every field traces back to recorded evidence. A production AI backend
can enrich the prose later, but the grounded skeleton is always available and
honest.
"""

from __future__ import annotations

from oss_agent.domain.enums import ContributionType
from oss_agent.domain.models import LearningReport, WorkflowSnapshot

_CONCEPTS: dict[ContributionType, list[str]] = {
    ContributionType.BUG_FIX: ["reproducing a defect with a test", "root-cause analysis",
                               "avoiding regressions"],
    ContributionType.FEATURE: ["public API design", "backward compatibility",
                               "feature test coverage"],
    ContributionType.DOCUMENTATION: ["accuracy vs. the code", "doc build/tooling"],
    ContributionType.TEST: ["test isolation", "coverage of edge cases"],
    ContributionType.REFACTOR: ["behavior preservation", "incremental change"],
    ContributionType.PERFORMANCE: ["measuring before/after", "algorithmic complexity"],
    ContributionType.DEPENDENCY: ["version compatibility", "lockfile hygiene"],
    ContributionType.CI: ["pipeline configuration", "reproducible builds"],
    ContributionType.CHORE: ["scope discipline", "minimal diffs"],
}


def build_learning_report(
    snap: WorkflowSnapshot,
    changed: list[tuple[int, int, str]],
) -> LearningReport:
    """Assemble a grounded learning report.

    ``changed`` is the per-file ``(additions, deletions, path)`` numstat from git.
    """
    a = snap.issue_analysis
    plan = snap.plan
    impl = snap.implementation
    tr = snap.test_result
    issue = snap.issue

    ctype = a.contribution_type if a else (plan.contribution_type if plan else ContributionType.BUG_FIX)
    title = (issue.title if issue else None) or (plan.objective if plan else "Contribution")

    what_broken = (a.problem_statement if a else "") or (issue.title if issue else "")
    expected = a.expected_behavior if a else ""
    why_broken = (
        f"Expected behavior: {expected}. " if expected else ""
    ) + (
        f"The plan targeted the root cause in: {', '.join(plan.affected_files)}."
        if plan and plan.affected_files else
        "Root cause was localized during planning."
    )

    rc = snap.repository_context
    if rc and (rc.likely_files or rc.relevant_symbols):
        sym = ", ".join(f"{s.name} ({s.file}:{s.line})" for s in rc.relevant_symbols[:3])
        how_discovered = (
            "Repository-context selection (keyword/symbol search over the checked-out "
            f"code) surfaced likely files: {', '.join(rc.likely_files[:4]) or '—'}"
            + (f"; key symbols: {sym}" if sym else "")
            + "."
        )
    else:
        probable = (a.probable_files if a else []) or (plan.affected_files if plan else [])
        how_discovered = (
            f"Relevant code was located from the issue and repository analysis: "
            f"{', '.join(probable) if probable else 'no explicit file references; located during planning'}."
        )

    files_that_matter = [fc.path for fc in (impl.files_changed if impl else [])]
    what_changed = [
        f"{path}  (+{add}/-{dele})" for add, dele, path in changed
    ] or ["(no textual diff captured)"]

    tests_passed = bool(tr and tr.passed)
    why_fix_works = (
        (f"{plan.objective}. " if plan else "")
        + ("The full validation suite passes on the change, "
           f"capturing {tr.total_tests_passed} passing test(s)." if tests_passed
           else "Validation is not yet green; the fix is not proven.")
    )

    tests_that_prove_it: list[str] = []
    if tr:
        for suite in tr.suites:
            if suite.skipped:
                tests_that_prove_it.append(f"{suite.name}: skipped (tool unavailable)")
            else:
                detail = (f"{suite.tests_passed} passed" if suite.tests_passed is not None
                          else ("passed" if suite.passed else "FAILED"))
                tests_that_prove_it.append(f"{suite.name} ({suite.kind}): {detail}")

    tradeoffs = list(dict.fromkeys((plan.risks if plan else []) + (a.risks if a else [])))
    edge_cases: list[str] = []
    if a and a.breaking_change_risk >= 0.3:
        edge_cases.append("Potential behavior change for existing callers (breaking-change risk).")
    if a and a.security_sensitivity >= 0.3:
        edge_cases.append("Security-sensitive area — validate inputs and error paths.")
    if plan and plan.acceptance_criteria:
        edge_cases.append("Confirm every acceptance criterion is covered: "
                          + "; ".join(plan.acceptance_criteria[:3]) + ".")
    if not edge_cases:
        edge_cases.append("No high-risk edge cases were flagged by the analysis; review the diff regardless.")

    concepts = list(_CONCEPTS.get(ctype, []))
    if snap.repository_report and snap.repository_report.build_system:
        concepts.append(f"{snap.repository_report.build_system} project conventions")

    questions = [
        f"What was the root cause of '{what_broken[:80]}' and how does this change address it?",
        f"Why these files ({', '.join(files_that_matter) or 'the changed files'}) and not others?",
        "What tests prove the fix, and what remains uncovered?",
    ]
    if tradeoffs:
        questions.append(f"What tradeoffs does this introduce? ({tradeoffs[0]})")
    if plan and plan.acceptance_criteria:
        questions.append("Does the change satisfy every stated acceptance criterion?")

    return LearningReport(
        repository_full_name=snap.repository_full_name or "",
        issue_number=snap.issue_number or (a.issue_number if a else 1),
        title=title,
        what_was_broken=what_broken,
        why_it_was_broken=why_broken,
        how_discovered=how_discovered,
        files_that_matter=files_that_matter,
        what_changed=what_changed,
        why_the_fix_works=why_fix_works,
        tests_that_prove_it=tests_that_prove_it,
        tradeoffs=tradeoffs,
        edge_cases_remaining=edge_cases,
        concepts_to_understand=concepts,
        maintainer_questions=questions,
        summary=f"Learning report for {snap.repository_full_name}#{snap.issue_number}.",
        confidence=(a.confidence if a else 0.5),
    )


def render_learning_report(r: LearningReport) -> str:
    def block(title: str, body: str) -> str:
        return f"\n{title}\n{'-' * len(title)}\n{body}\n"

    def bullets(items: list[str]) -> str:
        return "\n".join(f"  - {i}" for i in items) if items else "  (none)"

    out = [f"Learning report — {r.repository_full_name}#{r.issue_number}",
           f"= {r.title} ="]
    out.append(block("What was broken?", r.what_was_broken or "(not recorded)"))
    out.append(block("Why was it broken?", r.why_it_was_broken))
    out.append(block("How was the code path discovered?", r.how_discovered))
    out.append(block("What files matter?", bullets(r.files_that_matter)))
    out.append(block("What changed?", bullets(r.what_changed)))
    out.append(block("Why does the fix work?", r.why_the_fix_works))
    out.append(block("What tests prove it?", bullets(r.tests_that_prove_it)))
    out.append(block("Tradeoffs", bullets(r.tradeoffs)))
    out.append(block("Edge cases remaining", bullets(r.edge_cases_remaining)))
    out.append(block("Concepts to understand", bullets(r.concepts_to_understand)))
    out.append(block("Questions a maintainer might ask", bullets(r.maintainer_questions)))
    return "\n".join(out)

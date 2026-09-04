"""Human-readable workflow report (the status board).

Renders a :class:`WorkflowSnapshot` as a compact, glanceable summary of every
stage plus its captured evidence. Used by ``oss-agent status``.
"""

from __future__ import annotations

from oss_agent.domain.enums import WorkflowState as S
from oss_agent.domain.models import WorkflowSnapshot

# The ordered pipeline stages shown on the board and how to read each one.
_STAGES: list[tuple[str, str]] = [
    ("DISCOVERY", "discovery"),
    ("REPO ANALYSIS", "repository_report"),
    ("ISSUE ANALYSIS", "issue_analysis"),
    ("SCORING", "score"),
    ("SUITABILITY", "suitability"),
    ("CONTEXT", "repository_context"),
    ("PLANNING", "plan"),
    ("IMPLEMENTATION", "implementation"),
    ("TESTING", "test_result"),
    ("CODE REVIEW", "code_review"),
    ("SECURITY", "security_review"),
    ("MAINTAINER", "maintainer_review"),
    ("PULL REQUEST", "pull_request"),
]

# ASCII markers so the report renders on any console encoding (Windows cp1252
# included) without UnicodeEncodeError.
_OK = "[x]"
_FAIL = "[!]"
_PENDING = "[ ]"


def _stage_line(snapshot: WorkflowSnapshot, label: str, attr: str) -> str:
    detail = ""
    mark = _PENDING
    if attr == "discovery":
        done = snapshot.repository_full_name is not None
        mark = _OK if done else _PENDING
        detail = snapshot.repository_full_name or ""
    else:
        value = getattr(snapshot, attr, None)
        if value is not None:
            mark = _OK
            detail = _detail_for(attr, value)
    if attr == "score" and snapshot.score is not None:
        detail = f"{snapshot.score.overall:.0f}/100 {snapshot.score.recommendation.value}"
    if attr == "suitability" and snapshot.suitability is not None:
        su = snapshot.suitability
        mark = _OK if su.should_proceed else _FAIL
        detail = f"{su.category.value} ({su.score:.0f}/100)"
    if attr == "repository_context" and snapshot.repository_context is not None:
        rc = snapshot.repository_context
        detail = f"{len(rc.likely_files)} file(s), {len(rc.relevant_symbols)} symbol(s)"
    if attr == "test_result" and snapshot.test_result is not None:
        tr = snapshot.test_result
        mark = _OK if tr.passed else _FAIL
        detail = f"{tr.total_tests_passed} passed" if tr.passed else "FAILED"
    if attr in ("code_review", "security_review", "maintainer_review"):
        value = getattr(snapshot, attr)
        if value is not None:
            verdict = value.verdict.value
            mark = _OK if verdict in ("APPROVE",) else _FAIL
            detail = verdict
    return f"  {label:<16} {mark}  {detail}"


def _detail_for(attr: str, value) -> str:
    if attr == "repository_report":
        return f"build={value.build_system}, tests={value.has_tests}"
    if attr == "issue_analysis":
        return f"{value.contribution_type.value}, ambiguity={value.ambiguity_score:.2f}"
    if attr == "plan":
        return f"branch {value.branch_name}"
    if attr == "implementation":
        return f"{len(value.files_changed)} file(s) changed"
    if attr == "pull_request":
        return f"#{value.number} {value.url or ''}" if value.created else "composed"
    return ""


def render_report(snapshot: WorkflowSnapshot) -> str:
    lines: list[str] = []
    lines.append(f"Workflow: {snapshot.id}")
    lines.append(f"Repository: {snapshot.repository_full_name or '(pending)'}")
    lines.append(f"Issue: #{snapshot.issue_number}" if snapshot.issue_number else "Issue: (pending)")
    lines.append(f"State: {snapshot.state.value}")
    if snapshot.review_iteration or snapshot.debug_iteration:
        lines.append(f"Iterations: review={snapshot.review_iteration}, debug={snapshot.debug_iteration}")
    lines.append("")
    for label, attr in _STAGES:
        lines.append(_stage_line(snapshot, label, attr))
    lines.append("")
    if snapshot.last_error:
        lines.append(f"Last error: {snapshot.last_error}")
    lines.append(f"Events recorded: {len(snapshot.events)} | Agent runs: {len(snapshot.executions)}")
    lines.append(f"Updated: {snapshot.updated_at.isoformat()}")
    return "\n".join(lines)


def render_list(snapshots: list[WorkflowSnapshot]) -> str:
    if not snapshots:
        return "No workflows found."
    rows = ["ID                    STATE               REPOSITORY / ISSUE",
            "-" * 70]
    for s in snapshots:
        target = f"{s.repository_full_name or '-'}#{s.issue_number or '-'}"
        rows.append(f"{s.id:<21} {s.state.value:<19} {target}")
    return "\n".join(rows)

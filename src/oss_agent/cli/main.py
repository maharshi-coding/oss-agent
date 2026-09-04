"""``oss-agent`` command-line interface.

Thin by design: it parses arguments and calls :class:`~oss_agent.app.Application`.
No business logic lives here. It never bypasses a safety control.
"""

from __future__ import annotations

import argparse
import json as _json
import shutil
import sys
from pathlib import Path
from typing import Optional

from oss_agent.config.settings import get_settings
from oss_agent.observability.logging import configure_logging
from oss_agent.observability.report import render_list, render_report


def _json_mode(args) -> bool:
    return getattr(args, "json", False)


def _emit_json(obj) -> None:
    """Print a pydantic model / list of models / dict as indented JSON."""
    from pydantic import BaseModel

    def conv(o):
        return o.model_dump(mode="json") if isinstance(o, BaseModel) else o

    payload = [conv(o) for o in obj] if isinstance(obj, list) else conv(obj)
    print(_json.dumps(payload, indent=2, default=str))


def _ensure_utf8_stdout() -> None:
    # Windows consoles default to cp1252; make output robust regardless.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def _app(args):
    from oss_agent.app import Application

    return Application.from_settings(get_settings())


# --------------------------------------------------------------------------- #
# Command handlers
# --------------------------------------------------------------------------- #
def cmd_init(args) -> int:
    root = Path.cwd()
    pairs = [
        (root / "config" / "user-profile.example.yaml", root / "config" / "user-profile.yaml"),
        (root / "config" / "scoring.example.yaml", root / "config" / "scoring.yaml"),
        (root / ".env.example", root / ".env"),
    ]
    for src, dst in pairs:
        if src.exists() and not dst.exists():
            shutil.copyfile(src, dst)
            print(f"created {dst.relative_to(root)}")
        elif dst.exists():
            print(f"exists  {dst.relative_to(root)} (unchanged)")
    get_settings(reload=True).ensure_dirs()
    print("initialized runtime directories under .oss-agent/")
    print("Next: edit config/user-profile.yaml and .env, then `oss-agent discover`.")
    return 0


def cmd_discover(args) -> int:
    result = _app(args).discover(args.query)
    if _json_mode(args):
        _emit_json(result)
        return 0
    print(result.summary)
    for i, c in enumerate(result.candidates, 1):
        print(f"{i:>2}. {c.repository.full_name}#{c.issue.number}  "
              f"signal={c.preliminary_signal:.2f}  {c.issue.title[:60]}")
    if result.filtered_out:
        print(f"({result.filtered_out} candidate(s) filtered out)")
    return 0


def cmd_analyze(args) -> int:
    report = _app(args).analyze_repository(args.repository)
    print(f"Repository: {report.repository.full_name}")
    print(f"  build system : {report.build_system}")
    print(f"  test command : {report.test_command}")
    print(f"  has tests/ci : {report.has_tests}/{report.has_ci}")
    print(f"  contributing : {report.has_contributing}")
    if report.injection_flags:
        print(f"  [!] injection flags: {report.injection_flags}")
    print(f"  summary: {report.summary}")
    return 0


def cmd_analyze_issue(args) -> int:
    a = _app(args).analyze_issue(args.repository, args.issue)
    print(f"Issue {args.repository}#{a.issue_number}")
    print(f"  type        : {a.contribution_type.value}")
    print(f"  difficulty  : {a.difficulty.value}")
    print(f"  ambiguity   : {a.ambiguity_score:.2f} (ambiguous={a.is_ambiguous})")
    print(f"  problem     : {a.problem_statement[:120]}")
    print(f"  criteria    : {a.acceptance_criteria}")
    if a.injection_flags:
        print(f"  [!] injection flags: {a.injection_flags}")
    return 0


def cmd_score(args) -> int:
    score = _app(args).score(args.repository, args.issue)
    if _json_mode(args):
        _emit_json(score)
        return 0
    print(f"Score for {args.repository}#{args.issue}: {score.overall:.1f}/100  "
          f"({score.recommendation.value})")
    for c in score.components:
        print(f"  {c.dimension:<26} raw={c.raw:.2f} w={c.weight:.2f} -> {c.weighted*100:.1f}")
    for p in score.penalties:
        print(f"  penalty {p.name:<20} -{p.amount:.1f}  ({p.explanation})")
    print(f"  {score.explanation}")
    return 0


def cmd_suitability(args) -> int:
    a = _app(args).suitability(args.repository, args.issue)
    if _json_mode(args):
        _emit_json(a)
        return 0 if a.should_proceed else 1
    print(f"Suitability for {args.repository}#{args.issue}: {a.category.value} ({a.score:.0f}/100)")
    if a.blockers:
        for b in a.blockers:
            print(f"  [BLOCKED] {b}")
    for p in a.positives:
        print(f"  + {p}")
    for c in a.concerns:
        print(f"  - {c}")
    print(f"  {'proceed' if a.should_proceed else 'do NOT auto-implement'}: {a.explanation}")
    return 0 if a.should_proceed else 1


def cmd_context(args) -> int:
    ctx = _app(args).context(args.repository, args.issue)
    if _json_mode(args):
        _emit_json(ctx)
        return 0
    print(f"Repository context for {args.repository}#{args.issue}")
    print(f"  keywords     : {', '.join(ctx.keywords) or '(none)'}")
    print(f"  likely files : {', '.join(ctx.likely_files) or '(none located)'}")
    print(f"  related tests: {', '.join(ctx.related_tests) or '(none)'}")
    if ctx.relevant_symbols:
        print("  symbols      :")
        for sym in ctx.relevant_symbols[:12]:
            print(f"     {sym.kind:<8} {sym.name}  ({sym.file}:{sym.line})")
    for note in ctx.notes:
        print(f"  note: {note}")
    return 0


def cmd_create(args) -> int:
    snap = _app(args).create(args.repository, args.issue, workflow_id=args.id)
    print(f"created workflow {snap.id} targeting {args.repository}#{args.issue}")
    print(f"run it with: oss-agent run {snap.id}")
    return 0


def cmd_run(args) -> int:
    snap = _app(args).run(args.workflow_id)
    print(render_report(snap))
    return 0 if snap.state.value not in ("FAILED", "ABORTED") else 1


def cmd_resume(args) -> int:
    snap = _app(args).resume(args.workflow_id)
    print(render_report(snap))
    return 0 if snap.state.value not in ("FAILED", "ABORTED") else 1


def cmd_status(args) -> int:
    snap = _app(args).status(args.workflow_id)
    if _json_mode(args):
        _emit_json(snap)
        return 0
    print(render_report(snap))
    return 0


def cmd_attempts(args) -> int:
    attempts = _app(args).attempts(args.workflow_id)
    if not attempts:
        print("No implementation attempts recorded yet.")
        return 0
    print(f"Implementation attempts for {args.workflow_id}:")
    for a in attempts:
        status = "PASS" if a.tests_passed else "FAIL"
        print(f"\n  #{a.attempt} [{a.phase}] -> {status}  ({a.test_duration_seconds:.2f}s)")
        print(f"     files: {', '.join(a.files_changed) or '(none)'}")
        if a.unexpected_files:
            print(f"     [!] out-of-scope: {', '.join(a.unexpected_files)}")
        print(f"     tests: {a.tests_summary}")
        if a.notes:
            print(f"     notes: {'; '.join(a.notes)}")
        if not a.tests_passed and a.failure_summary:
            first = a.failure_summary.splitlines()[0] if a.failure_summary else ""
            print(f"     failure: {first[:120]}")
    return 0


def cmd_review(args) -> int:
    # `review` simply advances the workflow through the gated review pipeline,
    # stopping at READY_FOR_PR (same as run; PR creation stays a separate step).
    snap = _app(args).run(args.workflow_id)
    print(render_report(snap))
    return 0


def cmd_diff(args) -> int:
    diff = _app(args).diff(args.workflow_id)
    if not diff.strip():
        print("No staged changes to show (no worktree or empty diff).")
        return 0
    print(diff)
    return 0


def cmd_learn(args) -> int:
    from oss_agent.learning.report import render_learning_report

    report = _app(args).learn(args.workflow_id)
    print(render_learning_report(report))
    return 0


def cmd_explain(args) -> int:
    print(_app(args).explain(args.workflow_id))
    return 0


def cmd_approve(args) -> int:
    snap = _app(args).approve(args.workflow_id, args.note or "approved by human")
    print(f"workflow {snap.id} approved for submission (state {snap.state.value}).")
    print("next: oss-agent prepare-pr / submit (submission stays human-gated).")
    return 0


def cmd_reject(args) -> int:
    snap = _app(args).reject(args.workflow_id, args.note or "rejected by human")
    print(f"workflow {snap.id} rejected -> {snap.state.value}")
    return 0


def cmd_prepare_pr(args) -> int:
    snap = _app(args).prepare_pr(args.workflow_id)
    pr = snap.pull_request
    if pr is None:
        print("PR could not be prepared.")
        return 1
    print(f"Prepared PR for {snap.repository_full_name}#{snap.issue_number} (NOT submitted):\n")
    print(f"  branch: {snap.branch}")
    print(f"  title : {pr.title}\n")
    print(pr.body)
    print("\nNothing has been pushed. Review, then:")
    print(f"  oss-agent approve {snap.id}")
    print(f"  oss-agent submit {snap.id}")
    return 0


def cmd_submit(args) -> int:
    app = _app(args)
    snap = app.status(args.workflow_id)
    pr = snap.pull_request
    if pr is None:
        print("No prepared PR. Run `oss-agent prepare-pr` first.", file=sys.stderr)
        return 1
    if not snap.human_approved:
        print("Not approved. Run `oss-agent approve` first.", file=sys.stderr)
        return 1

    confirm = args.yes
    if not confirm:
        # Explicit confirmation. Never defaults to yes.
        default_branch = snap.repository.default_branch if snap.repository else "main"
        print("You are about to:\n")
        print(f"  Push branch:     {snap.branch}")
        print(f"  Repository:      {snap.repository_full_name}")
        print(f"  Base branch:     {default_branch}")
        print(f"  Create PR:       \"{pr.title}\"\n")
        answer = input("Proceed? [y/N] ").strip().lower()
        confirm = answer in ("y", "yes")
    if not confirm:
        print("submission cancelled.")
        return 1

    from oss_agent.orchestrator.engine import HumanApprovalRequired, SubmissionBlocked

    try:
        snap = app.submit(args.workflow_id, confirm=True, draft=args.draft)
    except SubmissionBlocked as exc:
        print(f"Submission blocked: {exc}", file=sys.stderr)
        return 1
    except HumanApprovalRequired as exc:
        print(f"Submission refused: {exc}", file=sys.stderr)
        return 1
    if snap.pull_request and snap.pull_request.created:
        print(f"PR #{snap.pull_request.number} created: {snap.pull_request.url}")
        return 0
    print(f"PR not created; state {snap.state.value}: {snap.last_error}", file=sys.stderr)
    return 1


def cmd_create_pr(args) -> int:
    snap = _app(args).create_pr(args.workflow_id, draft=args.draft)
    if snap.pull_request and snap.pull_request.created:
        print(f"PR #{snap.pull_request.number} created: {snap.pull_request.url}")
    else:
        print(f"PR not created; workflow state is {snap.state.value}: {snap.last_error}")
    return 0 if (snap.pull_request and snap.pull_request.created) else 1


def _scout_params(args) -> dict:
    """Resolve scout knobs from --mode preset + explicit filter overrides."""
    from oss_agent.domain.enums import Difficulty
    from oss_agent.scout.filters import ScoutMode, build_query, preset_for

    min_score, maxc, analyze, difficulty = args.min_score, args.max, args.analyze, None
    if args.mode:
        preset = preset_for(ScoutMode(args.mode))
        # Explicit flags win over the preset; argparse defaults yield to it.
        if not _flag_given("--min-score"):
            min_score = preset.min_score
        if not _flag_given("--max"):
            maxc = preset.max_candidates
        if not _flag_given("--analyze"):
            analyze = preset.analyze_top
        difficulty = preset.difficulty
    if args.difficulty:
        difficulty = Difficulty(args.difficulty)

    query = args.query
    if query is None and (args.language or args.label):
        query = build_query(language=args.language, labels=args.label)
    return {
        "query": query, "min_score": min_score, "max_candidates": maxc,
        "analyze_top": analyze, "difficulty": difficulty,
    }


def _flag_given(flag: str) -> bool:
    return any(a == flag or a.startswith(flag + "=") for a in sys.argv[1:])


def cmd_scout(args) -> int:
    app = _app(args)
    params = _scout_params(args)
    if args.loop:
        print(f"scout running continuously (every {args.interval}s). Ctrl+C to stop.")
        print("Opportunities are queued for review; no PR is opened automatically.\n")
        try:
            app.scout_loop(
                interval_seconds=args.interval, max_cycles=args.cycles,
                on_cycle=lambda r: print(r.summary), **params,
            )
        except KeyboardInterrupt:
            print("\nscout stopped.")
        return 0
    result = app.scout_once(**params)
    print(result.summary)
    for o in result.top[: args.top]:
        print(f"  {o.score:5.1f}  {o.recommendation.value:<13} {o.repository_full_name}#{o.issue_number}  {o.title[:52]}")
    if result.errors:
        for e in result.errors:
            print(f"  ! {e}")
    return 0


def cmd_queue(args) -> int:
    from oss_agent.scout.models import OpportunityStatus

    status = OpportunityStatus(args.status) if args.status else None
    opps = _app(args).list_opportunities(status=status, limit=args.top)
    if _json_mode(args):
        _emit_json(opps)
        return 0
    if not opps:
        print("Queue is empty. Run `oss-agent scout` to populate it.")
        return 0
    print(f"{'SCORE':>6}  {'REC':<13} {'TYPE':<10} TARGET  /  TITLE")
    print("-" * 78)
    for o in opps:
        print(f"{o.score:6.1f}  {o.recommendation.value:<13} {o.contribution_type.value:<10} "
              f"{o.repository_full_name}#{o.issue_number}  {o.title[:44]}")
    print("\nReview, then: oss-agent promote <owner/repo> <issue>   (or dismiss)")
    return 0


def cmd_dismiss(args) -> int:
    ok = _app(args).dismiss_opportunity(f"{args.repository}#{args.issue}")
    print("dismissed" if ok else "not found in queue")
    return 0 if ok else 1


def cmd_promote(args) -> int:
    snap = _app(args).promote_opportunity(f"{args.repository}#{args.issue}")
    print(f"created workflow {snap.id} for {args.repository}#{args.issue}")
    print(f"next: oss-agent run {snap.id}   (implementation + tests + review; PR stays gated)")
    return 0


def cmd_visualize(args) -> int:
    import webbrowser
    from pathlib import Path

    html = _app(args).render_visualizer(args.workflow_id)
    out = Path(args.output) if args.output else Path(".oss-agent") / "visualizer.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"visualizer written to {out}")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
        print("opened in your browser")
    else:
        print(f"open it with: start {out}  (or pass --open)")
    return 0


def cmd_monitor(args) -> int:
    snaps = _app(args).monitor()
    if not snaps:
        print("No workflows are currently in PR monitoring.")
        return 0
    for s in snaps:
        pr = s.pull_request
        print(f"{s.id}  {s.repository_full_name}#{s.issue_number}  "
              f"PR #{pr.number if pr else '-'}  {pr.url if pr else ''}")
    return 0


def cmd_list(args) -> int:
    from oss_agent.domain.enums import WorkflowState

    state = WorkflowState(args.state) if args.state else None
    snaps = _app(args).list(state=state)
    if _json_mode(args):
        _emit_json([{"id": s.id, "state": s.state.value,
                     "repository": s.repository_full_name, "issue": s.issue_number,
                     "updated_at": s.updated_at} for s in snaps])
        return 0
    print(render_list(snaps))
    return 0


def cmd_abort(args) -> int:
    snap = _app(args).abort(args.workflow_id, args.reason or "aborted by user")
    print(f"workflow {snap.id} -> {snap.state.value}")
    return 0


def cmd_cleanup(args) -> int:
    removed = _app(args).cleanup(include_active=args.all)
    print(f"removed {removed} worktree(s)")
    return 0


def cmd_config(args) -> int:
    """Show the effective configuration with secrets redacted."""
    s = get_settings()
    data = s.model_dump(mode="json")
    # Never print secret values — redact anything that looks like a credential.
    for key in list(data):
        if data[key] and ("token" in key or "secret" in key or "password" in key):
            data[key] = "***redacted***"
    data["github_token_present"] = s.github_token_present
    if _json_mode(args):
        _emit_json(data)
        return 0
    print("Effective configuration (secrets redacted):")
    for key in sorted(data):
        print(f"  {key:<28} {data[key]}")
    return 0


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="oss-agent",
        description="Human-in-the-loop OSS contribution copilot. Discovers, "
        "evaluates, implements, validates, explains, and prepares contributions "
        "for explicit human review before anything is published.",
    )
    # Global options (place before the subcommand).
    p.add_argument("--json", action="store_true", help="machine-readable JSON output where supported")
    verb = p.add_mutually_exclusive_group()
    verb.add_argument("--quiet", action="store_true", help="only log errors")
    verb.add_argument("--verbose", action="store_true", help="info-level logs")
    verb.add_argument("--debug", action="store_true", help="debug-level logs")
    p.add_argument("--log-json", action="store_true", help="emit logs as JSON")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="scaffold config files and runtime directories").set_defaults(func=cmd_init)

    d = sub.add_parser("discover", help="discover candidate issues")
    d.add_argument("--query", help="override the discovery query")
    d.set_defaults(func=cmd_discover)

    a = sub.add_parser("analyze", help="analyze a repository")
    a.add_argument("repository", help="owner/name")
    a.set_defaults(func=cmd_analyze)

    ai = sub.add_parser("analyze-issue", help="analyze an issue")
    ai.add_argument("repository", help="owner/name")
    ai.add_argument("issue", type=int)
    ai.set_defaults(func=cmd_analyze_issue)

    sc = sub.add_parser("score", help="score a contribution opportunity")
    sc.add_argument("repository", help="owner/name")
    sc.add_argument("issue", type=int)
    sc.set_defaults(func=cmd_score)

    su = sub.add_parser("suitability", help="assess whether a contribution should be made")
    su.add_argument("repository", help="owner/name")
    su.add_argument("issue", type=int)
    su.set_defaults(func=cmd_suitability)

    cx = sub.add_parser("context", help="build a repository-context slice for an issue")
    cx.add_argument("repository", help="owner/name")
    cx.add_argument("issue", type=int)
    cx.set_defaults(func=cmd_context)

    cr = sub.add_parser("create", help="create a workflow targeting an issue")
    cr.add_argument("repository", help="owner/name")
    cr.add_argument("issue", type=int)
    cr.add_argument("--id", help="explicit workflow id")
    cr.set_defaults(func=cmd_create)

    for name, fn, helptext in [
        ("run", cmd_run, "run a workflow to READY_FOR_PR"),
        ("resume", cmd_resume, "resume a workflow from its last state"),
        ("status", cmd_status, "show a workflow status board"),
        ("review", cmd_review, "advance a workflow through review gates"),
        ("attempts", cmd_attempts, "show the implement/repair attempt history"),
    ]:
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("workflow_id")
        sp.set_defaults(func=fn)

    df = sub.add_parser("diff", help="show the staged diff for human review")
    df.add_argument("workflow_id")
    df.set_defaults(func=cmd_diff)

    ln = sub.add_parser("learn", help="generate a grounded learning report")
    ln.add_argument("workflow_id")
    ln.set_defaults(func=cmd_learn)

    ex = sub.add_parser("explain", help="concise explanation of the contribution")
    ex.add_argument("workflow_id")
    ex.set_defaults(func=cmd_explain)

    ap = sub.add_parser("approve", help="record explicit human approval (needed before submit)")
    ap.add_argument("workflow_id")
    ap.add_argument("--note")
    ap.set_defaults(func=cmd_approve)

    rj = sub.add_parser("reject", help="reject the contribution and abort the workflow")
    rj.add_argument("workflow_id")
    rj.add_argument("--note")
    rj.set_defaults(func=cmd_reject)

    pp = sub.add_parser("prepare-pr", help="compose the PR title/body without pushing")
    pp.add_argument("workflow_id")
    pp.set_defaults(func=cmd_prepare_pr)

    sb = sub.add_parser("submit", help="push the branch and open the PR (human-gated)")
    sb.add_argument("workflow_id")
    sb.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    sb.add_argument("--draft", action="store_true")
    sb.set_defaults(func=cmd_submit)

    cpr = sub.add_parser("create-pr", help="open a pull request (gated; legacy one-shot)")
    cpr.add_argument("workflow_id")
    cpr.add_argument("--draft", action="store_true")
    cpr.set_defaults(func=cmd_create_pr)

    ab = sub.add_parser("abort", help="abort a workflow")
    ab.add_argument("workflow_id")
    ab.add_argument("--reason")
    ab.set_defaults(func=cmd_abort)

    sc2 = sub.add_parser("scout", help="continuously discover + score opportunities (read-only)")
    sc2.add_argument("--loop", action="store_true", help="run 24/7 until interrupted")
    sc2.add_argument("--interval", type=float, default=1800.0, help="seconds between cycles in --loop")
    sc2.add_argument("--cycles", type=int, default=None, help="stop after N cycles (--loop)")
    sc2.add_argument("--query", help="override the discovery query")
    sc2.add_argument("--language", help="filter by repository language (e.g. python)")
    sc2.add_argument("--label", action="append", help="filter by issue label (repeatable)")
    sc2.add_argument("--difficulty", choices=["trivial", "easy", "moderate", "hard"],
                     help="keep only opportunities of this analyzed difficulty")
    sc2.add_argument("--mode", choices=["beginner", "learning", "balanced", "productivity", "expert"],
                     help="preset that tunes scan defaults (never bypasses safety/submission)")
    sc2.add_argument("--min-score", type=float, default=45.0, dest="min_score")
    sc2.add_argument("--max", type=int, default=6, help="candidates to discover per cycle")
    sc2.add_argument("--analyze", type=int, default=4, help="candidates to fully analyze per cycle")
    sc2.add_argument("--top", type=int, default=10, help="rows to print")
    sc2.set_defaults(func=cmd_scout)

    q = sub.add_parser("queue", help="show the ranked opportunity queue")
    q.add_argument("--status", choices=["new", "dismissed", "promoted", "contributed"])
    q.add_argument("--top", type=int, default=20)
    q.set_defaults(func=cmd_queue)

    dm = sub.add_parser("dismiss", help="dismiss a queued opportunity")
    dm.add_argument("repository")
    dm.add_argument("issue", type=int)
    dm.set_defaults(func=cmd_dismiss)

    pr2 = sub.add_parser("promote", help="create a workflow from a queued opportunity")
    pr2.add_argument("repository")
    pr2.add_argument("issue", type=int)
    pr2.set_defaults(func=cmd_promote)

    vz = sub.add_parser("visualize", help="generate the pixel-world workflow visualizer (HTML)")
    vz.add_argument("workflow_id", nargs="?", help="workflow to visualize (omit for a demo page)")
    vz.add_argument("--output", help="output HTML path (default .oss-agent/visualizer.html)")
    vz.add_argument("--open", action="store_true", help="open the result in your browser")
    vz.set_defaults(func=cmd_visualize)

    sub.add_parser("monitor", help="list workflows in PR monitoring").set_defaults(func=cmd_monitor)

    ls = sub.add_parser("list", help="list workflows")
    ls.add_argument("--state", help="filter by workflow state")
    ls.set_defaults(func=cmd_list)

    cl = sub.add_parser("cleanup", help="remove worktrees for finished workflows")
    cl.add_argument("--all", action="store_true", help="also remove active worktrees")
    cl.set_defaults(func=cmd_cleanup)

    sub.add_parser("config", help="show effective configuration (secrets redacted)").set_defaults(func=cmd_config)

    return p


def _log_level_from(args, default: str) -> str:
    if getattr(args, "debug", False):
        return "DEBUG"
    if getattr(args, "verbose", False):
        return "INFO"
    if getattr(args, "quiet", False):
        return "ERROR"
    return default


def main(argv: Optional[list[str]] = None) -> int:
    _ensure_utf8_stdout()
    settings = get_settings()
    parser = build_parser()
    args = parser.parse_args(argv)
    fmt = "json" if getattr(args, "log_json", False) else settings.log_format.value
    configure_logging(_log_level_from(args, settings.log_level), fmt)
    try:
        return args.func(args)
    except Exception as exc:  # surface a clean, actionable message; details are logged
        _print_actionable_error(exc, args)
        return 2


def _print_actionable_error(exc: Exception, args) -> None:
    """Map known domain errors to a clear 'what/why/how to recover' message."""
    from oss_agent.agents.base import BackendTimeoutError, BackendUnavailableError
    from oss_agent.orchestrator.engine import HumanApprovalRequired, SubmissionBlocked

    print(f"error: {exc}", file=sys.stderr)
    wid = getattr(args, "workflow_id", None)
    if isinstance(exc, BackendUnavailableError):
        print("  -> install/authenticate the backend, or set "
              "OSS_AGENT_AGENT_BACKEND=mock.", file=sys.stderr)
    elif isinstance(exc, BackendTimeoutError) and wid:
        print(f"  -> state saved; resume with: oss-agent resume {wid}", file=sys.stderr)
    elif isinstance(exc, HumanApprovalRequired) and wid:
        print(f"  -> approve first: oss-agent approve {wid}", file=sys.stderr)
    elif isinstance(exc, SubmissionBlocked):
        print("  -> a conflict was detected; review the issue/PRs before submitting.",
              file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())

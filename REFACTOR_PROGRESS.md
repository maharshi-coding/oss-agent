# OSS Agent Refactor Progress

This file tracks the phased refactor described in `oss-agent-prompt-pack/`.
It is part of the engineering record and is kept accurate — validation is never
exaggerated. Where a feature is only mock-tested, it says so.

Feature status vocabulary (per prompt pack §38):
`IMPLEMENTED` · `UNIT TESTED` · `INTEGRATION TESTED` · `E2E TESTED` ·
`REAL-WORLD VALIDATED` · `EXPERIMENTAL`.

---

## Baseline (captured before any changes)

- **Tests:** `97 passed` (unit + integration + e2e), `pytest` exit 0, ~15s.
- **Lint:** no linter configured in `pyproject.toml` (no ruff/flake8 config). N/A.
- **Type checks:** no `mypy`/`pyright` config committed. `py.typed` ships, but no
  gate is wired. N/A at baseline.
- **Source size:** 57 Python modules under `src/oss_agent`, ~7,073 LOC.
- **Python:** 3.11 (`.venv`), deps: pydantic v2, pydantic-settings, SQLAlchemy 2, PyYAML.

### Current CLI commands (baseline)
`init, discover, analyze, analyze-issue, score, create, run, resume, status,
review, create-pr, abort, scout, queue, dismiss, promote, visualize, monitor,
list, cleanup` (20 commands).

### Current workflow states (baseline)
`DISCOVERY → REPOSITORY_ANALYSIS → ISSUE_ANALYSIS → SCORING → SELECTED →
PLANNING → IMPLEMENTATION → TESTING → (DEBUGGING loop) → CODE_REVIEW →
SECURITY_REVIEW → MAINTAINER_REVIEW → READY_FOR_PR → PR_CREATED → PR_MONITORING →
(CHANGES_REQUESTED loop) → MERGED`. Terminal: `MERGED, FAILED, ABORTED`.

---

## Audit summary (Phase 1 deliverable)

The project is already a serious, well-separated system. Key findings:

**Genuine strengths (preserve):**
- Deterministic state machine (`domain/state_machine.py`) — declarative transition
  table, validated by the engine; agents cannot drive state. Excellent.
- Clean AI/deterministic separation. `AgentRunner` protocol (`agents/base.py`) is
  the backend abstraction; orchestrator depends only on it, never on Claude.
- Resumable persistence: full `WorkflowSnapshot` stored as JSON blob + indexed
  columns (`persistence/orm.py`). Adding optional fields is backwards-compatible;
  `_Base` uses `extra="forbid"` so **fields may be added but not removed**.
- Real safety layer: secret scanning, dangerous-command blocking, protected-branch
  + force-push refusal, prompt-injection trust boundary (`wrap_untrusted`).
- Test engineer measures results from captured exit codes; unavailable tools are
  recorded as *skipped*, never a false pass/fail.
- Visualizer already renders a **real** `WorkflowSnapshot` (not fake timers).
- Event system already exists (`events/bus.py` + `WorkflowEvent`).
- Continuous read-only scout with a human-gated promote step.

**Gaps vs. the prompt pack (targets for later phases):**
1. No dedicated **Contribution Suitability Engine** (maintainer intent, existing
   PRs, assignment, staleness → EXCELLENT/GOOD/REVIEW_REQUIRED/…). (Phase 3)
2. No structured **ContributionRules** / **repository context** object separate
   from `RepositoryReport`. (Phase 3/4)
3. Debug loop exists but **repair attempts are not individually persisted**; no
   `attempts` command. (Phase 4)
4. No **learning report** and no `learn`/`explain`/`diff` commands. (Phase 6)
5. No **prepare-pr / submit** separation with an explicit confirmation gate and a
   final pre-submission conflict re-check (only a single `create-pr`). (Phase 7)
6. Scout lacks `--language/--label/--difficulty` filters; no user **modes**. (Phase 8)
7. No domain-specific error taxonomy or `--json`/verbosity flags. (Phase 10)

**Engineering-judgment decisions:**
- Keep the per-agent `AgentRunner` protocol; it is cleaner than the prompt's
  example `CodingBackend` and already enforces the required separation. We harden
  it (structured invocation results, explicit backend errors) rather than replace it.
- Add new capabilities as **new optional snapshot fields + new states**, preserving
  backwards compatibility and all passing tests.

---

## Phase 1 — Vision, audit, baseline
Status: COMPLETE

Changes:
- Established the test/validation baseline (97 passing).
- Completed a full architecture audit (above); traced real code paths for the
  state machine, engine, both agent runners, persistence, safety, scout, and
  visualizer — not inferred from filenames.
- Created this progress record.

Tests: baseline `97 passed` (unchanged — no code modified in Phase 1).

Known limitations: none introduced. Documentation-only phase.

---

## Phase 2 — AI backend architecture
Status: COMPLETE

What existed already:
- A clean `AgentRunner` protocol (`agents/base.py`) that the orchestrator depends
  on exclusively — the required AI/deterministic separation was already in place
  and is cleaner than the prompt's example `CodingBackend`. Kept it.
- A real `ClaudeAgentRunner` invoking the `claude` CLI via the controlled
  `CommandRunner`, wrapping untrusted content, and validating replies against
  Pydantic contracts.

What changed (hardening, not replacement):
- Added an explicit backend error taxonomy: `BackendUnavailableError` and
  `BackendTimeoutError` (subclasses of `AgentError`) in `agents/base.py`.
- `ClaudeAgentRunner._invoke` now returns a structured `BackendInvocation`
  (raw text, exit code, duration, timed_out) instead of a bare string, and raises
  the *typed* error for each failure mode: 127 → `BackendUnavailableError`,
  timeout → `BackendTimeoutError`, other non-zero → `AgentError` with the stderr
  tail. Failures are never swallowed. Both flow up through the engine's `step()`
  (which already catches `AgentError`) and preserve workflow state for resume.

Files modified: `agents/base.py`, `agents/claude_runner.py`.
Tests added: `tests/unit/test_claude_backend.py` (9 tests) — valid JSON parse,
`--output-format json` envelope unwrap, fenced-block extraction, unavailable/
timeout/non-zero/no-JSON/invalid-schema errors, and the untrusted-content trust
boundary. A fake `CommandRunner` stands in for the CLI.

Validation performed: `pytest` → `106 passed`.

Feature status:
- Backend invocation/parse/error handling: **UNIT TESTED**.
- Live `claude` CLI round-trip (real model generating code): **EXPERIMENTAL** —
  not exercised in CI; requires an authenticated Claude Code install. The path is
  real (subprocess through `CommandRunner`), but end-to-end real-model validation
  has not been performed in this environment.

Known limitations: the real-model implementation loop can only be validated on a
machine with the `claude` CLI installed and authenticated. Offline/tests use the
deterministic `MockAgentRunner`.

## Phase 3 — Contribution suitability & repository context
Status: COMPLETE (suitability engine); repo-context PARTIAL (pre-existing)

What existed already:
- `RepositoryReport` already extracts build system, test/lint/typecheck/build
  commands, `contributing_requirements`, and CI/tests/CoC presence — i.e. the
  "ContributionRules" and much of the repository-context ask (prompt §9/§10) were
  already covered. `IssueAnalysis.probable_files` covers "likely affected files".
- Technical scoring (`scoring/`) existed but only answered *technical fit*, not
  *whether a contribution should be made*.

What changed (the genuine gap — prompt §8):
- New dedicated **`oss_agent.suitability`** package with a deterministic
  `SuitabilityEngine` and configurable `SuitabilityWeights`. It weighs eight
  dimensions (issue clarity, maintainer intent, existing/conflicting work,
  repository health, guidelines fit, scope, technical confidence, skill match)
  and applies **hard blockers** (closed issue, archived repo, existing linked PR,
  assignee, high duplicate risk, disqualifying labels) → `BLOCKED`, plus
  discussion/design labels → `INVESTIGATE_ONLY`, high ambiguity → `SKIP`.
- Categories: `EXCELLENT / GOOD / REVIEW_REQUIRED / INVESTIGATE_ONLY / SKIP /
  BLOCKED`, each with human-readable positives/concerns/blockers and an
  explanation string (never just a number).
- New `SuitabilityCategory` enum + `SuitabilityAssessment`/`SuitabilitySignal`
  models; new optional `WorkflowSnapshot.suitability` field (backwards-compatible).
- Wired as a **real gate** in the engine's scoring stage: if the assessment is
  not `should_proceed`, the workflow aborts with a `SAFETY_BLOCKED` event before
  any worktree/implementation — the core anti-"PR spam" guard.
- New `oss-agent suitability <repo> <issue>` CLI command + `Application.suitability`.
- Surfaced on the `status` board (`observability/report.py`).

Files modified: `domain/enums.py`, `domain/models.py`, `orchestrator/engine.py`,
`app.py`, `cli/main.py`, `observability/report.py`. New: `suitability/`.
Tests added: `tests/unit/test_suitability.py` (9 tests) — excellent/good path,
blocked-on-existing-PR/assignee/archived/closed, investigate-only, skip-on-
ambiguity, blocked-on-duplicate-risk, bounds + normalized weights.

Validation performed: `pytest` → `115 passed`. Smoke-tested the CLI end-to-end
against the seeded mock (`octo-org/stringutils#101` → GOOD 79/100 with reasoning
correctly flagging the missing CONTRIBUTING guide). The e2e workflow still reaches
READY_FOR_PR (the gate rates the fixture issue as proceed-worthy).

Feature status:
- Suitability engine + gate: **IMPLEMENTED, UNIT TESTED, INTEGRATION TESTED**
  (exercised through the real engine scoring stage in e2e).
- Repository-context/ContributionRules: **PARTIAL** — served by the existing
  `RepositoryReport`; a richer symbol/call-graph context object is not built and
  remains a future improvement.

Known limitations: `SuitabilityWeights` are configurable in code but not yet
loadable from YAML (scoring-style config file). Signals rely on issue metadata
present in the analysis; a live backend would enrich maintainer-intent detection
from actual issue comments.

## Phase 4 — Planning, implementation & repair loop
Status: COMPLETE

What existed already:
- A real implement → test → debug → test loop in the engine, bounded by
  `settings.max_debug_iterations` (configurable max repair attempts — prompt §12).
- Structured plans (`ImplementationPlan`) and captured test results.
- Change evidence derived from `git` (not the model's self-report) in both runners.

What changed (the gap — per-attempt history was not persisted):
- New `ImplementationAttempt` model + `WorkflowSnapshot.attempts` list
  (backwards-compatible). The engine records one attempt per test cycle in
  `_h_testing` via `_record_attempt`: attempt number, phase (implement/repair),
  files changed, out-of-scope files, pass/fail, test summary, **captured** failure
  tail, repair notes, and test duration.
- New `oss-agent attempts <workflow>` command + `Application.attempts`.

Files modified: `domain/models.py`, `orchestrator/engine.py`, `app.py`, `cli/main.py`.
Tests added: `tests/integration/test_attempts.py` (3 tests) — success records one
passing attempt; a never-fixing solution records `1 + max_debug_iterations`
attempts (implement + repairs) all failing with real failure evidence and
contiguous 1-based numbering; attempts survive a persistence reload.

Validation performed: `pytest` → `118 passed`.

Feature status: **IMPLEMENTED, INTEGRATION TESTED** (exercised through the real
engine loop with real pytest execution against the fixture repo, offline).

Known limitations: per-attempt raw backend request metadata (prompt/token counts)
is not captured for the mock runner; the Claude runner could attach
`BackendInvocation` metadata to each attempt in a future pass.

## Phase 5 — Diff review & scope enforcement
Status: COMPLETE (mostly pre-existing; added human diff view)

What existed already (verified, not rebuilt):
- A real diff-review agent (`review_code`) that inspects the actual staged diff:
  flags scope violations (files outside `plan.affected_files` → `unexpected_files`),
  missing tests, oversized diffs, and secrets; blocking findings → REQUEST_CHANGES.
- Scope enforcement is real: `ImplementationResult.unexpected_files` is computed
  from the git diff and gates PR creation (`_assert_gates`).
- A separate security review (dangerous code, path traversal, secrets, carried
  prompt-injection flags).

What changed:
- Added `oss-agent diff <workflow>` + `Application.diff` to view the staged diff
  for human review (grounds Phase 6). Added `GitService.diff_numstat` for
  per-file add/delete counts.

Engineering-judgment note: kept the `ReviewVerdict` enum
(APPROVE/REQUEST_CHANGES/REJECT) rather than introducing
PASS_WITH_WARNINGS/REQUIRES_HUMAN_REVIEW — the existing verdicts already gate the
workflow and adding states would churn many tests for no behavioral gain. Scope
"requires review" is surfaced via findings + the human `diff`/`status` views.

Feature status: diff review + scope enforcement **IMPLEMENTED, UNIT + E2E TESTED**
(pre-existing, still green); `diff` command **IMPLEMENTED, INTEGRATION TESTED**.

## Phase 6 — Human review & learning mode
Status: COMPLETE

What was missing (genuine gap): no learning report and no human-review commands.

What changed:
- New **`oss_agent.learning`** package: `build_learning_report` assembles a
  grounded `LearningReport` from real artifacts — issue analysis, plan, the actual
  changed files with git numstat (+adds/-dels), and captured test results. Every
  field traces to recorded evidence (no generic narrative). Renders to a readable
  report answering: what/why it broke, how the code path was found, what files
  matter, what changed, why the fix works, which tests prove it, tradeoffs, edge
  cases, concepts to understand, and questions a maintainer might ask.
- New `LearningReport` model + `WorkflowSnapshot.learning_report`.
- Human-in-the-loop decision fields: `human_approved`, `human_decision_note`.
- New CLI: `learn`, `explain`, `diff`, `approve`, `reject` (+ `Application`
  methods). `approve` records explicit approval (a submission prerequisite —
  Phase 7); `reject` records the note and aborts.

Files modified: `domain/models.py`, `git/service.py`, `app.py`, `cli/main.py`.
New: `learning/`.
Tests added: `tests/integration/test_learning_and_review.py` (6 tests) — report
grounded in the real diff, `diff` shows the real fix, `explain` conciseness,
approve sets+persists the flag, reject aborts+records the note, and graceful
handling of an incomplete workflow.

Validation performed: `pytest` → `124 passed`.

Feature status: learning report + human gates **IMPLEMENTED, INTEGRATION TESTED**
(grounded in the real fixture diff + real pytest results, offline). A production
Claude backend could enrich the prose; the grounded skeleton is always honest.

Known limitations: the learning report's "why it was broken" is assembled from
the analysis/plan rather than a from-scratch root-cause narrative; with the live
backend this becomes richer.

## Phase 7 — PR preparation & submission
Status: COMPLETE

What existed already:
- A single gated `create_pr` that composed the PR, committed (with a staged-diff
  secret scan), pushed only when an `origin` remote exists, and created the PR.
  Review-verdict gates (`_assert_gates`) were already enforced.

What changed (the gap — no prep/submit separation, no final re-check):
- `engine.prepare_pr` composes and persists the PR title/body with `created=False`
  — **nothing is pushed**; safe to run repeatedly; stays in READY_FOR_PR.
- `engine.submit(confirm)` layers the human gates on top of `create_pr`:
  requires (1) a prepared PR, (2) `human_approved` (via `oss-agent approve`),
  (3) an explicit `confirm`, and (4) a passing **final conflict re-check**
  (`_submission_conflict`: issue still open/unassigned/no linked PR, repo not
  archived, no PR already on the branch). New `HumanApprovalRequired` and
  `SubmissionBlocked` errors.
- CLI: `prepare-pr` (prints the composed PR, pushes nothing) and `submit`
  (interactive `Proceed? [y/N]` that **never defaults to yes**; `--yes` for
  automation). `create-pr` retained as a legacy one-shot.

Files modified: `orchestrator/engine.py`, `app.py`, `cli/main.py`.
Tests added: `tests/integration/test_prepare_and_submit.py` (6 tests) — prepare
pushes/creates nothing; submit refuses without a prepared PR / without approval /
without confirmation; the full gated path succeeds; and a conflicting PR appearing
just before submission blocks it (nothing created).

Validation performed: `pytest` → `130 passed`.

Feature status: **IMPLEMENTED, INTEGRATION TESTED** against the in-memory GitHub
adapter (real state mutation). Real push/PR creation against live GitHub is
**NOT exercised** — per the project's hard rule, no unsolicited PRs are opened
against third-party repos; the `gh`/API adapters remain for the developer's own
repos/forks.

Known limitations: PR-template detection (respecting `.github/pull_request_template`)
is not yet wired into the composer; the mock composes a fixed structured body.

## Phase 8 — Scout, skill matching & modes
Status: COMPLETE

What existed already:
- A resilient 24/7 read-only scout with dedup, ranking, and a human-gated queue.
- Skill matching: the scoring/suitability engines already weight the developer
  profile's language weights, frameworks, and preferred contribution types, and
  return per-dimension explanations (prompt §23 largely satisfied).

What changed (the gap — filters & modes):
- New `oss_agent.scout.filters`: `build_query(language, labels)` composes a
  GitHub-style search query; `ScoutMode` + `MODE_PRESETS` (beginner/learning/
  balanced/productivity/expert) tune scan defaults. Modes **never** relax safety
  or the submission gate.
- `ScoutService.scan` gained a `difficulty` post-analysis filter and a
  `skipped_filtered` counter on `ScanResult`.
- CLI `scout` gained `--language`, `--label` (repeatable), `--difficulty`, and
  `--mode`. Explicit flags override the mode preset; the preset overrides argparse
  defaults (`_flag_given` disambiguates).

Files modified: `scout/service.py`, `scout/models.py`, `cli/main.py`. New:
`scout/filters.py`.
Tests added: `tests/unit/test_scout_filters.py` (5) + 2 difficulty-filter tests in
`test_scout.py` — query building, every mode has a preset, beginner favors easy,
difficulty keeps/excludes.

Validation performed: `pytest` → `137 passed`. Smoke-tested `scout --mode beginner`
(correctly applies the stricter min_score=60 preset).

Feature status: filters/modes **IMPLEMENTED, UNIT TESTED**; skill matching
**IMPLEMENTED** (pre-existing, exercised by scoring/suitability tests).

Known limitations: live GitHub API rate-limit caching for the `gh`/API adapters is
not added here (the mock adapter is network-free); `--difficulty` filters after
analysis rather than in the search query (GitHub search has no difficulty field).

## Phase 9 — Visualizer, events & persistence
Status: COMPLETE (largely pre-existing; enriched + guaranteed)

What existed already (verified, preserved):
- The pixel-world visualizer already consumes a **real** `WorkflowSnapshot` (its
  stages, evidence, logs, and event stream come from actual state/artifacts — not
  fake timers). Not rebuilt.
- A real event system: `EventBus` + `WorkflowEvent` + `EventType`, already
  powering logging and the visualizer's event stream. Per prompt §26 ("do not
  create a redundant event system"), this was **kept as-is**, not duplicated.
- Resumable persistence with the full snapshot stored as a JSON blob plus indexed
  columns; `create_all` is idempotent (`CREATE TABLE IF NOT EXISTS`) — no
  destructive resets.

What changed:
- Visualizer now reflects the new real data: the scoring stage shows the
  **suitability** verdict; the PR-gate stage shows **human approval** status and
  whether a **learning report** is ready. HTML/JS layout unchanged (low-risk edit
  to the data-building functions only).
- Added a persistence **backwards-compatibility guarantee** (prompt §27): because
  new capabilities were added as *optional* snapshot fields, a row written by an
  older version still deserializes with defaults — proven by two tests, including
  one that inserts a legacy-shaped row directly into the SQL store and reads it
  back. Existing user data survives the upgrade with no migration required.

Files modified: `observability/visualizer.py`. Tests added: 2 in
`tests/unit/test_persistence_and_domain.py`.

Validation performed: `pytest` → `139 passed` (visualizer tests still green).

Feature status: visualizer **IMPLEMENTED, UNIT TESTED** (renders real snapshots);
persistence backwards-compat **UNIT TESTED**.

Known limitations: no new indexed columns were added, so no ALTER-TABLE migration
runner was introduced (would be speculative — the JSON-blob design already absorbs
additive changes). If a future field needs indexing, a migration step would be
added then.

## Phase 10 — CLI, errors, observability & config
Status: COMPLETE

What existed already:
- A thin, coherent CLI over the `Application` facade; structured logging with
  automatic secret redaction and text/JSON formats.

What changed:
- **`--json`** global flag → machine-readable output for `discover`, `score`,
  `suitability`, `status`, `list`, `queue`, and `config` (pydantic
  `model_dump(mode="json")`).
- **Verbosity flags** `--quiet/--verbose/--debug` and `--log-json`, applied in
  `main()` after parsing (logs go to stderr; JSON output stays clean on stdout).
- New **`config`** command showing the effective settings with any
  token/secret/password value redacted (never prints secrets).
- **Actionable errors**: `_print_actionable_error` maps `BackendUnavailableError`,
  `BackendTimeoutError`, `HumanApprovalRequired`, and `SubmissionBlocked` to a
  "how to recover" hint (e.g. `resume <id>`, `approve <id>`).
- Domain error taxonomy now includes (all actually raised): `NoSolutionError`,
  `BackendUnavailableError`, `BackendTimeoutError`, `HumanApprovalRequired`,
  `SubmissionBlocked` (plus pre-existing `DangerousCommandError`, `GitError`,
  `SecretDetectedError`, `GitHubError`, `GitSafetyError`).

Files modified: `cli/main.py`. Tests added: 4 in `tests/integration/test_cli.py`
(suitability command, JSON score is valid JSON, config redaction, JSON config).

Validation performed: `pytest` → `143 passed`. Smoke-tested `config` (secrets
redacted, `github_token=None`, `github_token_present=False`).

Feature status: **IMPLEMENTED, INTEGRATION TESTED**.

Known limitations: a full YAML config file for backend/workflow/safety/scouting
sections (prompt §31 example) is not added; configuration remains env-var +
per-domain YAML (profile/scoring) which already covers the needs. `--json` is
wired to read commands, not every command.

## Phase 11 — Testing & real-world validation
Status: COMPLETE

Test suite: **143 passed** (unit + integration + e2e), **76% line coverage**
(branch coverage measured). New modules are well covered: learning 93%,
suitability 91%, scout/filters 97%, persistence 98%. The lowest-covered module is
`github/gh_cli.py` (18%) — the live adapter, only exercisable against real GitHub.

**Real-world validation performed (read-only, via the production `gh` adapter):**
- `gh` is installed (2.88.1) and authenticated (`repo` scope). Used it, read-only.
- `get_repository('pallets/click')` → correct metadata (17.6k stars, Python,
  bsd-3-clause, not archived).
- `list_issues(..., state='open')` → real open issues with labels/assignees.
- Full pipeline on **real** issue `pallets/click#3652`: repo analysis
  (build=python, tests/ci/contributing all True), issue analysis (bug_fix,
  ambiguity 0.20), scoring (68.1/100 → PURSUE), suitability (GOOD 79/100, proceed)
  with grounded reasoning. **No write operations were performed** — no PRs, per the
  project's hard rule against unsolicited AI PRs.

This upgrades the production **read path** from "structurally present" to
**REAL-WORLD VALIDATED**. The **write path** (push + PR creation) and the live
**Claude implementation** backend remain EXPERIMENTAL (not exercised here — writes
are deliberately withheld, and the Claude CLI round-trip needs an authenticated
install).

Network-dependent validation is kept out of the automated suite; all CI tests use
the network-free in-memory adapter + real local git/pytest.

## Phase 12 — Documentation, architecture & code quality
Status: COMPLETE

What changed:
- **Removed misleading autonomy claims** (prompt §34): README tagline and
  `pyproject.toml` description repositioned from "Autonomous ... agent" to a
  **human-in-the-loop copilot** that requires explicit approval before publishing
  and does not open unsolicited PRs. CLI top-level description updated to match.
- **README** updated (prompt §35): the "What it does" list now includes
  suitability, the repair loop, learning, and the prepare/submit separation; the
  CLI table lists all new commands and global flags; **added a "What OSS-Agent
  does not do" section**; Limitations now states the honest, per-path validation
  status (read path real-world validated; Claude implementation experimental;
  write path not run against third parties by design).
- **Architecture doc** (prompt §36) already documented the deterministic/AI split;
  added the new `suitability` and `learning` layers + key-module rows.

Code quality (prompt §37): new modules are small and focused (`suitability`,
`learning`, `scout/filters` are each single-purpose); no god classes; **no
circular imports** (verified by import); typed Pydantic contracts; new snapshot
fields are additive/optional (backwards compatible); side effects stay at
boundaries (git/CLI). No speculative frameworks introduced.

Files modified: `README.md`, `pyproject.toml`, `docs/architecture.md`.
Validation: import check clean; all 30 CLI commands register; `pytest` → 143 passed.

Feature status: **DOCUMENTED, verified accurate against the implementation.**

## Phase 13 — Truthfulness & product goals
Status: COMPLETE

- No feature is claimed working on the basis of a passing mock alone. Each phase
  above states its honest level (IMPLEMENTED / UNIT / INTEGRATION / E2E /
  REAL-WORLD VALIDATED / EXPERIMENTAL). Gaps are named, not hidden.
- The **learning goal** is realized: `learn`/`explain` ground an explanation in the
  actual diff + tests so a developer can defend the change; the human review gate
  sits before submission.
- The **GitHub-profile goal** is respected: no artificial commit generation, no
  fake activity — the tool only helps prepare *legitimate* contributions, and
  publishing is human-gated. Consistent with the project's hard rule against
  unsolicited AI PRs.

## Phase 14 — Execution strategy & final validation
Status: COMPLETE

The refactor was executed phase-by-phase; the suite stayed green after every
phase (97 → 106 → 115 → 118 → 124 → 130 → 137 → 139 → 143), never left in a
half-migrated state. See the **Final Report** below.

## Phase 15 — Critical design rules
Status: COMPLETE (upheld throughout)

1. Preserved working engineering (state machine, persistence, safety, visualizer,
   scout — all kept and extended, none rewritten). 2. Fixed root causes, not
   symptoms. 3. Did not fake autonomy (repositioned docs; honest status labels).
   4. Kept implementation capability (repair loop persisted; backend hardened).
   5. AI reasoning stays separate from deterministic execution. 6. Repository/issue
   text remains untrusted data (trust boundary unit-tested). 7. Passing tests are
   necessary-not-sufficient (suitability + review + human gate). 8. Suitability is
   evaluated before coding (new gate). 9. Human understanding is a first-class
   feature (learning report). 10. Human approval is mandatory before publishing
   (prepare/approve/submit + conflict re-check). 11. Quality over volume. 12–15.
   Observable (events/visualizer/attempts), resumable (persistence backcompat
   proven), explainable (learning report), reviewable (diff/review gates).

---

# FINAL ENGINEERING REPORT

**Totals**
- Source modules: **64** (was 57), ~**8,400** LOC (was ~7,073). New packages:
  `suitability/`, `learning/`, `scout/filters.py`, `agents/pr_template.py`.
- Tests: **152 passing / 0 failing** (was 97), across 20 files (unit + integration
  + e2e). Coverage ~**76%** line/branch; new modules 91–97%.
- CLI commands: **30** (was 20). New: `suitability, attempts, diff, learn, explain,
  approve, reject, prepare-pr, submit, config` (+ scout `--language/--label/
  --difficulty/--mode`, global `--json/--quiet/--verbose/--debug/--log-json`).
- Workflow states: 19 (unchanged — suitability enforced within the scoring stage
  by deliberate engineering judgment to avoid destabilizing the state machine).

**Major architecture changes**
- Added a dedicated **contribution-suitability engine** (anti-PR-spam gate).
- Hardened the **AI backend** with structured invocation results + a typed error
  taxonomy (`BackendUnavailable/Timeout`, `HumanApprovalRequired`,
  `SubmissionBlocked`).
- **Persisted repair attempts**; **grounded learning reports**; **PR
  prepare/submit separation** with a final conflict re-check + confirmation.
- Scout **filters + modes**; CLI **JSON/verbosity/config**; visualizer + status
  board now reflect suitability + human approval.

**New capabilities** (see per-phase status): suitability assessment, attempt
history, learning/explain, staged-diff review, human approve/reject, gated
submit, scout filters/modes, machine-readable output.

**Deprecated functionality:** none removed. `create-pr` retained as a legacy
one-shot alongside the safer `prepare-pr`+`submit`.

**Production AI backend status:** read path (analysis/scoring/suitability)
**REAL-WORLD VALIDATED** read-only against live GitHub via `gh`. Claude
implementation backend **EXPERIMENTAL** (invocation/parse/error unit-tested; live
model round-trip needs an authenticated Claude Code install, not in CI).

**Safety status:** all pre-existing controls intact and green — protected-branch/
force-push refusal, secret scan before commit, dangerous-command blocking,
prompt-injection trust boundary. New gates: suitability block, human approval,
pre-submission conflict re-check. No control can be relaxed by repository content.

**Persistence/resume status:** full-snapshot JSON store; resume proven; new fields
additive and **backwards-compatibility proven by test** (legacy rows load).

**Real-world validation performed:** read-only `pallets/click` repo + issue #3652
through the live `gh` adapter and the full analysis→scoring→suitability pipeline.
**No write operations** against third-party repos.

**Known limitations / experimental:** live Claude implementation loop; live push +
PR creation (withheld by design); `api` REST GitHub backend (not implemented);
YAML config for all sections; symbol/call-graph repository-context object.

**Recommended future improvements:** attach `BackendInvocation` metadata to each
attempt; enrich learning-report prose via the live backend; optional
`SuitabilityWeights` YAML; a REST GitHub adapter.

---

## Post-refactor enhancements (continued work)

Two "future improvement" items were implemented (both fully tested, suite stayed
green: 147 → 152):

1. **Comment-aware suitability** (prompt §8: "whether another contributor says
   they are working on it"). `SuitabilityEngine.assess` now accepts issue comment
   bodies and detects in-progress-work claims ("I'll take this", "PR incoming",
   "working on this", …). A claim **caps the recommendation at REVIEW_REQUIRED**
   (surfaced as a concern) rather than silently proceeding — balancing anti-
   duplicate-work against false positives on the developer's own comment. The
   engine and `Application.suitability` fetch comments read-only (best-effort;
   never fail the workflow). *+3 unit tests.*
2. **PR-template-aware composition** (prompt §19: "If a PR template exists, use
   its structure"). New shared `agents/pr_template.py` (`find_pr_template`) probes
   the standard template locations; both the mock composer (includes the template
   verbatim under the evidence-backed summary) and the Claude composer (instructs
   the model to follow it) honor it. Template content stays untrusted data.
   *+1 integration test, +5 unit tests.*

3. **YAML-configurable suitability weights** (prompt §8: "Create a configurable
   scoring model"). `SuitabilityWeights.from_mapping` + `load_suitability_weights`
   read a `suitability:` section from the shared scoring config file; the builder
   wires the configured engine into the workflow. `ScoringConfig` was updated to
   accept (and ignore) that section so the shared file — which `oss-agent init`
   copies — validates under both loaders without relaxing typo protection.
   Documented in `config/scoring.example.yaml`. *+3 unit tests incl. a regression
   guard on the example config.*

4. **Repository-context object** (prompt §10 — the largest remaining gap, now
   closed). New **`oss_agent.context`** package: a deterministic
   `RepositoryContextBuilder` performs context *selection* (filename + keyword +
   symbol search, Python via `ast`, others via regex) over a `FileSource`
   abstraction (`LocalFileSource` for the worktree, `GitHubFileSource` for
   read-only CLI use). It returns a compact, inspectable `RepositoryContext`
   (keywords, likely files, related tests, located symbols with file:line, entry
   points, root-cause notes) — bounded on files scanned/read and symbols returned,
   so it never ships an unbounded slice anywhere. Selection is deterministic
   infra; *reasoning over* it stays in the AI layer.
   - Wired into the workflow at `SELECTED` (built from the real checked-out code
     right after the worktree is created; never gates the step) and **fed to the
     Claude implementer's prompt**, so implementation reasons over relevant
     files/symbols instead of just the issue text.
   - New read-only `oss-agent context <repo> <issue>` command + `Application.context`;
     surfaced on the `status` board; enriches the learning report's "how the code
     path was discovered".
   - *+5 unit tests + 2 integration tests* (grounded against the fixture repo:
     locates `stringutils/__init__.py` and the `slugify` symbol; degrades
     gracefully on an empty repo; guards path traversal / skips `.git`).

Feature status: all four **IMPLEMENTED + UNIT/INTEGRATION TESTED** (offline,
against the in-memory adapter and real fixture repo). Repository-context selection
upgrades the Phase 3 "repository context" item from PARTIAL to **COMPLETE**.

**Updated totals after enhancements:** 67 modules, **162 tests passing**, 21 test
files. Suite stayed green throughout (147 → 152 → 154 → 155 → 160 → 162).

---

# LIVE VALIDATION (git baseline + real backends)

Goal: move from "extensively tested but partially live-unvalidated" to
version-controlled + genuinely validated. Executed on a Windows 11 machine.

## Git baseline
- Working tree audited before staging: `.gitignore` already excludes `.venv/`,
  caches, `.coverage`, `.oss-agent/`, `*.db`, worktrees, `.env*` (keeps
  `.env.example`) and local `config/*.yaml`. **No real secrets committed** — the
  project's own scanner flagged only `tests/unit/test_safety.py`, confirmed to be
  synthetic fixtures (`AKIA…`, a bare PEM header, `sk_live_0123…`, `hunter2…`).
- Initial commit `ed15349` (151 files) on `master`. Development branch
  **`feat/live-backend-validation`** for all validation work.
- Lint/type-check: **NOT CONFIGURED** (no ruff/mypy/flake8 in `pyproject.toml`) —
  reported honestly, not invented.

## Claude implementation backend
- Backend: real `claude` CLI **v2.1.260**, invoked as a subprocess through the
  controlled `CommandRunner` (the production path).
- **Real authenticated model round-trip: BLOCKED BY AUTHENTICATION.** The CLI's
  OAuth session was expired (`is_error: true`,
  `result: "Failed to authenticate: OAuth session expired and could not be refreshed"`)
  and cannot be refreshed non-interactively; no `ANTHROPIC_API_KEY` fallback. The
  live model therefore did **not** generate an implementation. This is reported
  honestly rather than faked.
- **Real invocation path: VALIDATED**, and it exposed two genuine bugs (now fixed,
  commit `f7589c7`, with regression tests using the real captured output):
  1. Windows exec resolution — `subprocess(["claude", …])` exits 127 because the
     npm shim is a `.CMD` and CreateProcess ignores PATHEXT for a bare name. Fixed
     via `shutil.which`; the default runner now reaches the real CLI.
  2. Auth-failure surfacing — the reason is in the JSON envelope `result` (small
     prompt) or plain-text stdout (large prompt), never stderr; OSS-Agent produced
     an empty/misclassified error. Now mapped to `BackendUnavailableError` with an
     actionable message. Verified against the real CLI: the default
     `ClaudeAgentRunner()` now raises a clear auth error.
- Repair loop: **NOT live-validated with the real model** (auth-blocked). It
  remains INTEGRATION-tested (a never-fixing solution drives the real
  implement→test→repair loop over real pytest; see `tests/integration/test_attempts.py`).

## GitHub write path — real, against an OWNED private sandbox
- Sandbox: **`maharshi-coding/oss-agent-sandbox`** (private, created via `gh`),
  a tiny project with an intentional `add()` bug + real issue **#1**.
- Full workflow run through OSS-Agent with the **real `gh` backend + real git
  clone + isolated worktree + real pytest**; the AI *implementation* step was
  provided deterministically (mock solution) because the live model is
  auth-blocked — labeled honestly. Result: discovery → repo analysis → issue
  analysis → **score 74.5/PURSUE** → **suitability EXCELLENT (82)** → real clone +
  worktree (`fix/issue-1`) → context (located `calculator.py`, symbols
  `add`/`multiply`) → plan → fix → **real pytest: 3 passed** → reviews →
  `READY_FOR_PR`. It **stopped at the human gate** (no auto-push).
- Persistence/resume: a **fresh engine over the same SQLite DB** reloaded the
  workflow (plan/impl/tests/attempts/context all persisted) and continued.
- Human gates: `prepare_pr` pushed nothing; `submit` was **refused before
  approval** (`HumanApprovalRequired`); after explicit approval + confirmation the
  pre-submission conflict re-check passed, then the branch was pushed and **real
  PR #2 was created** → `PR_MONITORING`.
- Independently cross-checked on GitHub (not trusting OSS-Agent): PR #2 OPEN,
  `base=main ← head=fix/issue-1`, references #1, diff is exactly
  `-return a - b` / `+return a + b`, remote branch exists, issue #1 still OPEN,
  DB holds the PR metadata. **PR not merged** (left inspectable).
- This run exposed two PR-body quality bugs (fixed, commit `42690e8`, with
  regression tests): a reproduction code-comment leaking "5" into the Summary, and
  a verification line counting skipped suites as executed. PR #2's body was then
  regenerated truthfully via the fixed composer and updated on GitHub.

## Visualizer
- Rendered from the real sandbox workflow snapshot: correct repo/issue, **PR #2**,
  all nine stages `done`, and the event stream shows the **actual** persisted
  events (`PR #2 created`, `monitoring PR`) — not fake timer activity.

## Final tests
- **174 passing / 0 failing** (was 162). +12 regression tests across the two
  live-validation fixes. No test patches the sandbox environment; fixes are in the
  product code.

## Bugs discovered during live validation
1. Windows `claude` exec resolution (127 despite install). — fixed `f7589c7`
2. Claude auth failure surfaced as empty/misclassified error. — fixed `f7589c7`
3. `_extract_expected` leaked a code-comment number into the PR body. — fixed `42690e8`
4. PR verification line counted skipped suites as executed. — fixed `42690e8`

## Final capability matrix
- GitHub read path: **REAL-WORLD VALIDATED** (public `pallets/click` + private sandbox).
- GitHub write path (push + PR): **REAL-WORLD VALIDATED against owned sandbox** (PR #2).
- Local implementation / test / repair mechanics: **END-TO-END VALIDATED** (real
  clone/worktree/pytest; repair loop integration-tested).
- Claude implementation backend: **invocation path REAL-CLI VALIDATED; live model
  round-trip BLOCKED BY AUTHENTICATION** (expired OAuth) — not yet real-world
  validated.
- Safety / human review / PR preparation / persistence / visualizer: validated in
  the real run above.
- Third-party OSS submission: **HUMAN-CONTROLLED BY DESIGN** (never automated).

## Final judgment
**PARTIALLY.** OSS-Agent genuinely performs the intended workflow end-to-end
against a real (owned) GitHub repository — discovery, analysis, scoring,
suitability, real repository setup, context, planning, real test execution,
review, learning, human gates, and a real human-approved PR — all cross-verified
on GitHub. The **one** unproven link is the live Claude model generating the
implementation, which is blocked purely by an expired local OAuth session (an
environment/auth issue, not a code defect); the real invocation path to that model
is validated and hardened. Re-authenticating `claude` and re-running the sandbox
flow would close the remaining gap.

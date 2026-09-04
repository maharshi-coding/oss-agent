# OSS-Agent

> A **human-in-the-loop open-source contribution copilot**. It helps a developer
> discover suitable GitHub issues, understand unfamiliar repositories, evaluate
> whether a contribution is even appropriate, implement a fix locally, validate
> it, **learn from it**, and prepare a high-quality pull request — with **explicit
> human approval required before anything is published**. It is not an unattended
> bot and does not open pull requests on your behalf.

OSS-Agent separates **AI reasoning** (agents that understand repos, plan,
implement, and review) from **deterministic mechanism** (a Python engine that owns
state, persistence, git, execution, safety, scoring, and observability). If a
piece of logic can be tested without an LLM, it lives in Python — not in a prompt.

This repository is a working foundation: it installs, its full test suite (unit +
integration + end-to-end, **143 tests**) passes, and it drives a real local
repository through the entire pipeline with **no network and no real GitHub**. Its
read-only analysis path has additionally been validated against live public
repositories via the `gh` CLI (see *Limitations* for what is and isn't proven).

---

## What it does

Given a developer profile, OSS-Agent will:

1. **Discover** candidate repositories/issues that match your profile.
2. **Analyze** the repository (build system, tests, CI, conventions, CONTRIBUTING)
   and the issue (problem, acceptance criteria, risks, ambiguity).
3. **Score** the opportunity (0–100) using configurable weights + your skill match.
4. **Assess suitability** — whether a contribution *should* be made here at all
   (existing/linked PRs, assignment, maintainer intent, staleness, discussion-only
   issues). This is the guard against becoming a PR-spam machine.
5. **Build a repository-context slice** (likely files, related tests, and located
   symbols) from the checked-out code, then **plan** a minimal, in-scope change —
   so implementation reasons over relevant code, not just the issue text.
6. **Implement** it inside an isolated git worktree, with a bounded **repair loop**
   (every attempt persisted and inspectable via `oss-agent attempts`).
7. **Test** with the repository's real commands and capture the evidence.
8. **Review** the diff independently: code review, security review (incl.
   prompt-injection), and a strict maintainer simulation.
9. **Explain & teach** — a grounded **learning report** (`oss-agent learn`) so you
   can defend the change to a maintainer before submitting.
10. **Prepare a pull request** separately from **submitting** it: nothing is pushed
    without explicit `approve`, an explicit confirmation, and a final conflict
    re-check.

## Architecture at a glance

```
Claude agents (reasoning)          Python engine (mechanism)         GitHub
--------------------------         --------------------------        ----------
discovery / analysis / plan   -->  state machine + orchestrator  --> repos
implement / debug / review         persistence (SQLite)              issues
security / maintainer sim          worktrees + git service           PRs / CI
pr composition / monitoring        execution + safety + scoring
                                   observability (logs + report)
```

- Agents return **structured output** matching Pydantic contracts
  (`oss_agent.domain.models`); prose only accompanies data.
- GitHub, the agent runtime, and persistence sit behind interfaces so each is
  replaceable and testable.
- See [docs/architecture.md](docs/architecture.md).

## Prerequisites

- Python 3.11+
- Git 2.30+ (worktree support)
- Optional for live GitHub: the [`gh` CLI](https://cli.github.com/), authenticated
  (`gh auth login`).
- Optional for live agents: the Claude Code CLI, authenticated.

## Installation

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration

```bash
oss-agent init            # copies example configs and creates runtime dirs
# then edit:
#   config/user-profile.yaml   (languages, domains, filters, difficulty)
#   config/scoring.yaml        (weights, penalties, thresholds)
#   .env                       (backends, tokens, limits)
```

Key environment variables (see [.env.example](.env.example)):

| Variable | Meaning | Default |
| --- | --- | --- |
| `OSS_AGENT_GITHUB_BACKEND` | `mock` \| `gh` \| `api` | `mock` |
| `OSS_AGENT_AGENT_BACKEND` | `mock` \| `claude` | `mock` |
| `OSS_AGENT_DATABASE_URL` | workflow store | `sqlite:///.oss-agent/oss_agent.db` |
| `OSS_AGENT_MAX_REVIEW_ITERATIONS` | review-loop cap | `3` |
| `OSS_AGENT_PROTECTED_BRANCHES` | never-push branches | `main,master,develop,release` |

### GitHub authentication

The `gh` backend uses the `gh` CLI's own authentication — run `gh auth login`.
No token is stored by OSS-Agent. The `api` backend (documented future work) would
read `OSS_AGENT_GITHUB_TOKEN` from the environment. The default `mock` backend
needs no credentials and touches no network.

### Claude Code setup

With `OSS_AGENT_AGENT_BACKEND=claude`, the engine invokes the `claude` CLI as a
subprocess for each reasoning agent (see `oss_agent.agents.ClaudeAgentRunner`).
Offline development and the whole test suite use the deterministic `mock` runner.

## Running locally (offline, no network)

```bash
export OSS_AGENT_GITHUB_BACKEND=mock
export OSS_AGENT_AGENT_BACKEND=mock

oss-agent discover                              # list seeded demo candidates
oss-agent analyze octo-org/stringutils          # repository report
oss-agent analyze-issue octo-org/stringutils 101
oss-agent score octo-org/stringutils 101        # 0-100 with breakdown
```

To drive a full workflow you provide the implementation (the mock runner delegates
the *implementer* step to a solution strategy; the Claude runner does it live).
The end-to-end test in `tests/e2e/` demonstrates the complete pipeline against a
real local fake repository.

## CLI

| Command | Purpose |
| --- | --- |
| `oss-agent init` | scaffold config + runtime dirs |
| `oss-agent discover [--query]` | discover candidate issues |
| `oss-agent analyze <repo>` | repository report |
| `oss-agent analyze-issue <repo> <n>` | issue analysis |
| `oss-agent score <repo> <n>` | opportunity score |
| `oss-agent suitability <repo> <n>` | should a contribution be made here? |
| `oss-agent context <repo> <n>` | likely files/tests/symbols for an issue |
| `oss-agent scout [--language/--label/--difficulty/--mode]` | queue ranked opportunities |
| `oss-agent queue` / `promote` / `dismiss` | manage the opportunity queue |
| `oss-agent create <repo> <n>` | create a workflow for an issue |
| `oss-agent run <id>` | run to `READY_FOR_PR` |
| `oss-agent resume <id>` | resume from last persisted state |
| `oss-agent status <id>` | status board |
| `oss-agent attempts <id>` | implement/repair attempt history |
| `oss-agent diff <id>` | show the staged diff for review |
| `oss-agent learn <id>` / `explain <id>` | grounded learning report |
| `oss-agent approve <id>` / `reject <id>` | record the human decision |
| `oss-agent prepare-pr <id>` | compose the PR (pushes nothing) |
| `oss-agent submit <id>` | push + open the PR (human-gated) |
| `oss-agent monitor` | list PRs being monitored |
| `oss-agent list [--state]` | list workflows |
| `oss-agent visualize [id]` | pixel-world workflow visualizer (HTML) |
| `oss-agent config` | show effective config (secrets redacted) |
| `oss-agent cleanup [--all]` | remove worktrees |

Global flags: `--json` (machine-readable output on read commands),
`--quiet/--verbose/--debug`, `--log-json`. The CLI never bypasses a safety control.

## What OSS-Agent does not do

Being explicit about the boundaries is part of the design:

- It does **not** open pull requests unattended. Submission requires an explicit
  `approve`, an explicit `submit` confirmation (never defaulted to yes), and a
  passing final conflict re-check.
- It does **not** guarantee a maintainer will accept a contribution, and it cannot
  perfectly infer maintainer intent — it surfaces signals, you decide.
- Passing tests does **not** mean the change is correct or appropriate; that is why
  suitability, independent review, and a human learning gate exist.
- It does **not** merge, force-push, push to protected/default branches, or commit
  detected secrets.
- Generated implementations **require human review** — the learning report exists
  so you don't submit code you can't explain.

## Running the tests

```bash
pytest                     # full suite (unit + integration + e2e)
pytest -m unit             # fast unit tests only
pytest tests/e2e -v        # the end-to-end workflow
```

## Safety model (summary)

- Never push to protected branches; never force-push; secret-scan before commit.
- All repository edits happen inside an isolated worktree.
- Repository content is **untrusted data** — a dedicated trust boundary and
  prompt-injection defense keep it from changing agent behavior.
- Deterministic checks live in `oss_agent.safety` and a fail-closed Claude hook
  (`.claude/hooks/guard.py`), independent of any agent's reasoning.
- PRs are gated behind passing tests + code + security + maintainer review, and
  merging is never automatic.

Full details: [docs/security.md](docs/security.md).

## Limitations

Honest status of each major capability (see `REFACTOR_PROGRESS.md` for the full
breakdown):

- **Read path (discovery/analysis/scoring/suitability):** real, and **validated
  read-only against live public repositories** via the authenticated `gh` CLI.
- **Write path (push + PR creation):** **real-world validated against an owned
  private sandbox** — the full workflow ran with a real `gh` backend, real git
  clone, isolated worktree, real `pytest`, and a real human-approved pull request
  (cross-checked on GitHub). It is **not** run against third-party repositories by
  design: OSS-Agent will not open unsolicited AI PRs; use it on your own repos/forks.
- **Local implementation + repair via the `claude` backend:** a real subprocess
  integration, now **real-world validated** — with `claude` authenticated, the live
  model generated a correct local implementation through the production backend
  (owned sandbox issue #3 → PR #4), validated by real `pytest` (5/5) and carried
  through the human-controlled workflow to a real PR. Prompts are delivered on stdin
  and read-only agents run headless in an isolated scratch dir (Windows hardening
  surfaced by this run). The **real repair loop was not exercised** — the first
  implementation passed immediately (not sabotaged); it remains integration-tested.
  Offline/tests use the deterministic `mock` runner, which delegates the
  *implementer* step to a solution strategy.
- The `api` (direct REST) GitHub backend is intentionally not implemented; use
  `gh` (recommended) or `mock`. The interface and factory are ready for it.
- Scoring/analysis heuristics in the mock runner are deliberate, transparent
  approximations; in production the reasoning comes from the AI backend.

## Future architecture

- PostgreSQL persistence (swap the `Database` URL; repository interface unchanged).
- A REST GitHub adapter and GitHub MCP integration.
- Continuous, multi-workflow autonomous operation with a scheduler.
- Richer PR-monitoring automation and maintainer-feedback loops.

## Documentation

- [Architecture](docs/architecture.md)
- [Agent system](docs/agent-system.md)
- [Workflow & state machine](docs/workflow.md)
- [Security & threat model](docs/security.md)
- [GitHub integration](docs/github-integration.md)
- [Development](docs/development.md)
- [Original build specification](docs/build-specification.md)

## License

MIT.

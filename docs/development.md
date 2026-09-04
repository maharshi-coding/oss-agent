# Development

## Setup

```bash
python -m venv .venv
# activate, then:
pip install -e ".[dev]"
pytest
```

## Layout

```
src/oss_agent/
  config/         settings (env) + developer/scoring profiles
  domain/         enums, Pydantic contracts, state machine
  scoring/        configurable scoring engine
  agents/         AgentRunner protocol + mock/claude runners + factory
  github/         GitHubClient interface + mock/gh adapters + factory
  git/            GitService (only git shell-out) + branch naming
  worktrees/      WorktreeManager
  execution/      CommandRunner, retry, TestEngineer
  safety/         secrets, commands, git, prompt-injection, rate limit
  persistence/    ORM, Database, WorkflowRepository (SQLite + in-memory)
  orchestrator/   WorkflowEngine, RepoProvider, builder (composition root)
  observability/  structured logging + report
  events/         event bus
  app.py          application facade (used by the CLI)
  cli/            argparse CLI (thin)
.claude/          agents, skills, hooks, settings.json
tests/            unit, integration, e2e, shared fixtures
```

## Conventions

- Python 3.11+, full type hints, Pydantic v2 for domain models.
- Composition over inheritance; small, single-purpose classes.
- No business logic in `cli/` — it calls `app.Application`.
- Keep GitHub, git, LLM, and domain concerns in separate modules.
- Only `git.service` shells out to git. Only `execution.runner` runs subprocesses.
- Standard library first; no unnecessary dependencies.
- Docstrings on public classes/functions; comments explain *why*.

## Testing

- `pytest -m unit` — fast, isolated (state machine, scoring, safety, persistence,
  git/worktrees, execution).
- `pytest -m integration` — GitHub mock, workflow resume, duplicate detection,
  audit history.
- `pytest -m e2e` — the full pipeline against a real local fake repository, with
  real git and real pytest, no network.

Shared fixtures live in `tests/conftest.py`: a real fake repo with an intentionally
failing scenario, a seeded in-memory GitHub, a wired engine, and both a fixing and
a non-fixing solution (to exercise the bounded debug loop → `FAILED`).

Write tests alongside implementation. Do not weaken tests to make them pass.

## Running with live backends

```bash
gh auth login
export OSS_AGENT_GITHUB_BACKEND=gh
export OSS_AGENT_AGENT_BACKEND=claude   # requires the claude CLI
```

## Extending

- **New agent** → add contract, extend `AgentRunner` + both runners, add
  handler/transition if a new state, add a `.claude/agents` definition, add tests.
- **New GitHub backend** → implement `GitHubClient`, register in the factory.
- **PostgreSQL** → point `OSS_AGENT_DATABASE_URL` at Postgres; the repository
  layer is unchanged.
- **New safety rule** → add to `oss_agent.safety` and mirror it in
  `.claude/hooks/guard.py`.

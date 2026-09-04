# Architecture

OSS-Agent is built on one principle: **separate reasoning from mechanism**.

- **AI reasoning** (Claude Code agents) understands repositories and issues,
  plans, implements, debugs, and reviews.
- **Deterministic mechanism** (this Python package) owns workflow state,
  persistence, transitions, worktrees, command execution, safety, retries, and
  logging.
- **GitHub** owns repositories, issues, branches, PRs, and CI.

If logic can be tested without an LLM, it is Python — not a prompt.

## Layers and dependency direction

```
cli / app            (thin; parse args, call services)
      │
orchestrator         WorkflowEngine, RepoProvider, builder
      │  depends on interfaces, never concretes
domain               enums, Pydantic contracts, state machine
scoring              configurable ScoringEngine (technical/skill fit)
suitability          SuitabilityEngine (should a contribution be made?)
context              RepositoryContextBuilder (deterministic file/symbol selection)
learning             grounded LearningReport builder
agents               AgentRunner protocol + mock/claude runners
github               GitHubClient interface + mock/gh adapters
git / worktrees      GitService (only git shell-out) + WorktreeManager
execution            CommandRunner, retry, TestEngineer
safety               secrets, commands, git, prompt-injection, rate limit
persistence          WorkflowRepository (SQLite + in-memory)
observability        structured logging + report
events               in-process event bus
config               Settings + profile + scoring config
```

Higher layers depend on **interfaces** exported by lower layers. The orchestrator
imports `GitHubClient`, `AgentRunner`, and `WorkflowRepository` — never a concrete
SDK or LLM client. The composition root (`orchestrator.builder.build_engine`) is
the single place that wires concretes together.

## Key modules

| Module | Responsibility |
| --- | --- |
| `domain.models` | Pydantic contracts for every agent output + the `WorkflowSnapshot` aggregate |
| `domain.state_machine` | declared, validated transitions |
| `orchestrator.engine.WorkflowEngine` | the deterministic controller |
| `agents.base.AgentRunner` | reasoning surface (mock + Claude implementations) |
| `github.interface.GitHubClient` | GitHub surface (mock + gh implementations) |
| `git.service.GitService` | the only git shell-out |
| `worktrees.manager.WorktreeManager` | isolated, idempotent worktrees |
| `execution` | captured command execution + real test running |
| `safety` | deterministic, agent-independent controls |
| `scoring.engine.ScoringEngine` | configurable, profile-aware technical scoring |
| `suitability.engine.SuitabilityEngine` | the anti-"PR spam" gate: should a contribution be made? |
| `context.builder.RepositoryContextBuilder` | deterministic file/symbol selection before implementation |
| `learning.report` | grounded, diff-backed learning report |
| `persistence.repository` | resumable workflow store |

## Decision records

**WorkflowState naming.** The lifecycle *states* are the `WorkflowState` enum. The
persisted *aggregate* is `WorkflowSnapshot` (not `WorkflowState`) to avoid a name
collision. The build spec listed a `WorkflowState` contract; `WorkflowSnapshot`
fulfills it.

**Snapshot-as-JSON persistence.** The full snapshot is stored as JSON with a few
denormalized indexed columns. This preserves the entire auditable history, makes
resume trivial, and ports to PostgreSQL by only changing the `Database` URL.

**Implementer as a strategy in the mock runner.** Read-only agents in the mock
runner use real heuristics over real inputs. The *implementer* — which needs
genuine domain reasoning — delegates to an injected solution strategy (the
test/offline adapter) and raises rather than fabricating a change. In production
the Claude runner performs implementation live and the change set is derived from
git, never trusted from the model's self-report.

**Deterministic test evidence.** `TestEngineer` records the exact command, exit
code, output, and duration. Missing tools are recorded as *skipped*, not passed.
Success is measured, never inferred.

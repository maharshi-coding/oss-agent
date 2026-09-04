# Workflow & state machine

The workflow is an explicit state machine declared in
`oss_agent.domain.state_machine`. Agents never change state; only the
`WorkflowEngine` applies a validated transition, and it persists after every step
so any workflow can resume from its last valid state.

## States

```
DISCOVERY → REPOSITORY_ANALYSIS → ISSUE_ANALYSIS → SCORING → SELECTED
   → PLANNING → IMPLEMENTATION → TESTING → CODE_REVIEW → SECURITY_REVIEW
   → MAINTAINER_REVIEW → READY_FOR_PR → PR_CREATED → PR_MONITORING → MERGED

Loops:   TESTING ⇄ DEBUGGING
         CODE_REVIEW / SECURITY_REVIEW / MAINTAINER_REVIEW → IMPLEMENTATION
         PR_MONITORING → CHANGES_REQUESTED → IMPLEMENTATION
Terminal: MERGED, FAILED, ABORTED
```

Every active state may also transition to `FAILED` or `ABORTED`.

## Transitions per state

| From | Allowed targets (happy path) |
| --- | --- |
| DISCOVERY | REPOSITORY_ANALYSIS |
| REPOSITORY_ANALYSIS | ISSUE_ANALYSIS |
| ISSUE_ANALYSIS | SCORING |
| SCORING | SELECTED, DISCOVERY |
| SELECTED | PLANNING |
| PLANNING | IMPLEMENTATION |
| IMPLEMENTATION | TESTING |
| TESTING | CODE_REVIEW, DEBUGGING |
| DEBUGGING | TESTING |
| CODE_REVIEW | SECURITY_REVIEW, IMPLEMENTATION |
| SECURITY_REVIEW | MAINTAINER_REVIEW, IMPLEMENTATION |
| MAINTAINER_REVIEW | READY_FOR_PR, IMPLEMENTATION |
| READY_FOR_PR | PR_CREATED |
| PR_CREATED | PR_MONITORING |
| PR_MONITORING | MERGED, CHANGES_REQUESTED |
| CHANGES_REQUESTED | IMPLEMENTATION |

An illegal transition raises `InvalidTransitionError`.

## Bounded loops

- **Debug loop** (`TESTING ⇄ DEBUGGING`): capped at `MAX_DEBUG_ITERATIONS`
  (default 3). On exhaustion the workflow moves to `FAILED` with captured output.
- **Review loop** (any review → `IMPLEMENTATION`): capped at
  `MAX_REVIEW_ITERATIONS` (default 3). On exhaustion → `FAILED`.
- A security **REJECT** (e.g. secrets) fails immediately; it does not loop.

Loops are always bounded; the system never spins forever.

## Stopping conditions

- **Ambiguous issue**: `issue-analyzer` sets a high `ambiguity_score`; the engine
  aborts rather than guessing.
- **Low score**: a `SKIP` recommendation aborts the workflow at `SCORING`.
- **Duplicate**: an existing active workflow or open PR for the issue aborts at
  `DISCOVERY`.

## Persistence & resume

Each step persists the full `WorkflowSnapshot` (state, artifacts, executions,
events). `oss-agent resume <id>` (or a fresh engine over the same store) continues
from the last valid state after a crash, restart, or interruption. Worktree and
branch creation are idempotent, so resuming never duplicates work.

## PR gating

`create_pr` runs only from `READY_FOR_PR` and re-checks every gate: tests green,
code + security + maintainer approvals, and in-scope changes. It commits (with a
secret scan), pushes only when a remote exists, opens the PR through the GitHub
abstraction, and moves to `PR_MONITORING`. **Merging is never automatic.**

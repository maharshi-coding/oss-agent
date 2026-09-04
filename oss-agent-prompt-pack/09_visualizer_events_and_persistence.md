# Part 9 — Visualizer, Event System, and Persistence

# 25. VISUALIZER: TURN IT INTO A REAL WORKFLOW MONITOR

Keep the pixel-world visualizer.

Do not remove it.

Make it represent real system activity.

Potential agents:

```text
Scout
Investigator
Repository Analyst
Librarian
Planner
Developer
Tester
Reviewer
Guardian
Git Agent
Teacher
Human Gate
```

Each should reflect real workflow states.

Example:

```text
Scout
Searching GitHub issues

Investigator
Analyzing issue #412

Librarian
Reading CONTRIBUTING.md

Planner
Preparing implementation strategy

Developer
Editing process.py

Tester
Running 143 tests

Reviewer
Reviewing 38-line diff

Guardian
Checking safety policy

Teacher
Building learning report

Human Gate
Waiting for review
```

Avoid fake activity.

Visualizer events should come from actual state transitions/event logs.

---

# 26. EVENT SYSTEM

Introduce a clean event model if the project does not already have one.

Examples:

```text
workflow.created
issue.discovered
issue.scored
repository.cloned
context.built
plan.generated
plan.approved
implementation.started
file.modified
test.started
test.completed
repair.started
review.completed
safety.blocked
learning.generated
human.review_required
pr.prepared
submission.approved
pr.created
workflow.completed
```

Events can power:

- visualizer
- CLI status
- logs
- debugging
- audit trail

Do not tightly couple UI to backend internals.

---

# 27. DATABASE / PERSISTENCE

Review the SQLite schema.

Persist enough information to resume and inspect workflows.

Potential entities:

```text
workflows
issues
repositories
scores
plans
implementation_attempts
command_runs
test_runs
review_results
safety_results
learning_reports
pull_request_drafts
events
```

Do not over-normalize unless needed.

Add schema migrations rather than destructive resets.

Existing user data should survive upgrades where feasible.

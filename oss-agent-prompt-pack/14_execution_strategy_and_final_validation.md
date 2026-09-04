# Part 14 — Implementation Strategy, Progress Reporting, and Final Validation

# 43. IMPLEMENTATION STRATEGY

Do not attempt an uncontrolled full rewrite in one pass.

Work systematically.

Recommended sequence:

PHASE 1
Audit and map current architecture.

PHASE 2
Stabilize tests and define interfaces.

PHASE 3
Refactor backend abstraction.

PHASE 4
Implement repository/context analysis.

PHASE 5
Implement contribution suitability.

PHASE 6
Implement planning.

PHASE 7
Implement real AI execution.

PHASE 8
Implement repair loop.

PHASE 9
Implement diff/review system.

PHASE 10
Implement learning reports.

PHASE 11
Implement human gates.

PHASE 12
Implement PR preparation/submission.

PHASE 13
Update visualizer.

PHASE 14
Add integration/e2e tests.

PHASE 15
Rewrite documentation.

At each phase:

- run tests
- fix regressions
- keep project runnable
- avoid leaving large broken intermediate states

---

# 44. OUTPUT WHILE WORKING

As you modify the codebase, provide concise engineering updates.

After major phases report:

```text
What changed
Why it changed
Files/modules affected
Tests added
Tests passing
Remaining limitations
Next step
```

If you encounter architectural problems, fix them rather than implementing workarounds that increase technical debt.

---

# 45. FINAL VALIDATION

Before declaring the project complete:

Run the entire test suite.

Run:

- formatting
- linting
- type checks where configured
- integration tests
- e2e tests

Then perform at least one complete controlled workflow.

Confirm:

```text
discovery works
scoring works
repository setup works
plan generation works
backend implementation works
repair loop works
tests work
review works
learning report works
PR preparation works
human submission gate works
visualizer receives actual events
workflow resumes after interruption
```

Produce a final engineering report containing:

```text
Total modules
Total tests
Passing tests
Major architecture changes
New commands
Removed/deprecated commands
Backend status
Safety status
Real-world validation performed
Known limitations
Recommended future improvements
```

Do not claim success for functionality that was not actually exercised.

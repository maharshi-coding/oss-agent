---
name: testing
description: How to run and capture real test/lint/type-check/build results. Success is measured from captured exit codes, never inferred.
---

# Testing

Use to verify a change with real evidence.

## Instructions
- Determine the applicable gates from the `RepositoryReport` (test, lint,
  type-check, build).
- Execute each through `oss_agent.execution.TestEngineer`, which captures the
  command, exit code, stdout/stderr, and duration.
- A suite passes **only** if its captured exit code says so.
- A tool that is not installed is **skipped** (excluded from the pass/fail gate),
  never treated as passing. Record it as skipped.

## Hard rules
- Never fabricate or infer results.
- Never weaken, delete, or skip tests to make the suite green — fix the code.
- Do not run repository scripts you do not understand.

## Output
A `TestResult` with one captured `TestSuiteResult` per gate.

# Part 4 — Implementation Planning, Repair Loop, and Testing Strategy

# 11. REQUIRE AN IMPLEMENTATION PLAN

Before code generation, produce a structured plan.

Example:

```text
Problem
Unicode filenames fail when subprocess output contains non-ASCII bytes.

Root cause
The helper decodes command output as ASCII.

Files likely affected
- src/utils/process.py
- tests/test_process.py

Proposed change
Decode using UTF-8 according to repository conventions.

Tests
Add regression coverage for non-ASCII output.

Risks
Changing decoding behavior may affect invalid byte sequences.

Confidence
0.88
```

The plan should be stored.

Allow CLI commands such as:

```text
oss-agent plan <workflow>
oss-agent approve-plan <workflow>
oss-agent reject-plan <workflow>
```

Exact naming may differ if the existing CLI style suggests better names.

For safe and high-confidence local experimentation, plan approval could be configurable.

But submission approval must always remain human-controlled.

---

# 12. IMPLEMENT A TRUE FIX LOOP

Do not use one-shot implementation.

The workflow should be:

```text
Generate solution
→ inspect changed files
→ run targeted tests
→ run required lint/format checks
→ if failure:
     collect failure
     send structured failure context to backend
     repair
     rerun
→ repeat until pass or retry limit reached
```

Make maximum attempts configurable.

Example:

```text
max_repair_attempts = 3
```

Every attempt should be persisted.

Record:

```text
attempt number
backend request metadata
files changed
diff summary
commands executed
test results
failure summaries
repair explanation
timestamps
```

The user should be able to inspect attempts.

For example:

```text
oss-agent attempts <workflow>
```

---

# 13. TESTING STRATEGY

Testing should happen in stages.

Stage 1:
targeted tests closest to affected files

Stage 2:
relevant package/module tests

Stage 3:
repository-required checks

Stage 4:
broader test suite when reasonable

Also support:

- formatting
- linting
- type checking
- build commands
- pre-commit
- custom project validation

Commands should come from:

1. repository configuration
2. contribution documentation
3. OSS Agent config
4. carefully inferred defaults

Do not execute arbitrary issue text as a command.

All commands must pass through the safety layer.

Capture:

```text
command
cwd
duration
stdout
stderr
exit_code
timeout
```

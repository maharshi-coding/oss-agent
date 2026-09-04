# Part 10 — CLI, Errors, Observability, and Configuration

# 28. CLI REDESIGN

Review the current 20-command CLI.

Do not keep commands just because they already exist.

Make the CLI coherent.

A possible command structure:

```text
oss-agent scout
oss-agent queue
oss-agent analyze
oss-agent score

oss-agent create
oss-agent plan
oss-agent approve-plan

oss-agent run
oss-agent status
oss-agent attempts

oss-agent diff
oss-agent review
oss-agent explain
oss-agent learn

oss-agent test

oss-agent prepare-pr
oss-agent submit

oss-agent promote
oss-agent dismiss

oss-agent visualize
```

Do not blindly use this exact list.

Prefer consistency with the existing interface.

Add `--json` output for automation where practical.

Ensure errors are readable and actionable.

---

# 29. ERROR HANDLING

Replace generic exceptions with clear domain errors where appropriate.

Examples:

```text
RepositorySetupError
GitHubRateLimitError
ContributionConflictError
NoSolutionError
BackendUnavailableError
BackendTimeoutError
ImplementationError
TestFailure
RepairLimitExceeded
SafetyViolation
HumanApprovalRequired
SubmissionBlocked
```

CLI errors should explain:

- what failed
- why
- how to recover
- whether workflow can resume

Example:

```text
Implementation paused.

Claude backend exited with status 1.

Workflow state has been saved.

Resume with:
oss-agent run 73f2c
```

---

# 30. OBSERVABILITY

Add structured logging.

Support verbosity levels.

Potential modes:

```text
--quiet
--verbose
--debug
```

Do not expose secrets in logs.

Include workflow IDs consistently.

Useful log fields:

```text
timestamp
workflow_id
repository
issue
state
component
event
duration
result
```

---

# 31. CONFIGURATION

Review configuration structure.

Separate:

- GitHub settings
- model/backend settings
- safety settings
- scoring settings
- workflow settings
- test settings
- contribution settings
- UI settings

Allow config through a file and environment variables where appropriate.

Never require API keys inside repository files.

Example:

```yaml
backend:
  provider: claude
  timeout_seconds: 600
  max_repair_attempts: 3

workflow:
  require_plan_approval: true
  require_submission_approval: true

safety:
  block_force_push: true
  protect_default_branch: true
  secret_scan: true

scouting:
  languages:
    - python
    - typescript
```

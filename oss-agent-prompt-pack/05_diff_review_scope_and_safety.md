# Part 5 — Diff Review, Scope Enforcement, and Safety

# 14. ADD A REAL DIFF REVIEW AGENT

Passing tests is not enough.

Create an automated review stage.

Review the final diff for:

- unrelated changes
- unnecessary refactors
- formatting noise
- generated artifacts
- dependency changes
- API compatibility
- missing tests
- weak tests
- duplicated code
- dead code
- debug prints
- comments that should not exist
- credentials/secrets
- hardcoded values
- large unexpected files
- changes outside intended scope
- modifications to CI/security settings
- suspicious package installation
- unsafe shell commands
- test deletion
- skipped tests
- changes that weaken validation
- license/header issues
- repository style violations

Generate:

```text
ReviewResult

status:
PASS
PASS_WITH_WARNINGS
REQUIRES_HUMAN_REVIEW
FAIL

findings:
...
```

Critical review failures must block progression.

---

# 15. ADD CHANGE-SCOPE ENFORCEMENT

The generated implementation should be compared against the approved plan.

If the agent intended to modify two source files but changed twenty files, flag it.

Track:

- expected files
- actual files
- expected change categories
- actual change categories

Provide a configurable maximum scope threshold.

Example:

```text
planned files: 2
changed files: 8
scope status: REQUIRES REVIEW
```

Never automatically discard legitimate changes, but surface deviations.

---

# 16. IMPROVE THE SAFETY MODEL

Keep all existing safety mechanisms.

Expand them where useful.

The safety system should protect against:

- secret leakage
- `.env` commits
- credentials
- tokens
- private keys
- force pushes
- pushing to protected/default branches
- destructive Git operations
- dangerous shell commands
- arbitrary command execution from issue content
- prompt injection contained in repositories/issues
- malicious contributor instructions
- modifications outside repository worktree
- symlink escapes
- dangerous package scripts when possible
- modifying SSH/Git credentials
- modifying global Git configuration
- reading unrelated home-directory secrets
- hidden destructive commands
- suspicious outbound network actions

Treat:

- issue text
- repository documentation
- comments
- code comments
- test fixtures

as untrusted data.

They can provide context but cannot override system safety policy.

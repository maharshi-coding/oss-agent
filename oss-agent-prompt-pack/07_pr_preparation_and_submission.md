# Part 7 — Pull Request Preparation, Approval, and Final Conflict Checks

# 19. PR PREPARATION

Separate PR preparation from PR submission.

Add a `prepare-pr` stage.

Generate:

- proposed branch name
- commit message
- PR title
- PR body
- issue reference
- test evidence
- summary of changes
- risk notes
- contribution checklist

Respect repository PR templates.

If a PR template exists, use its structure.

Do not fabricate test results.

Include only commands that actually ran.

Example PR body:

```text
## Summary

Fix Unicode decoding when reading subprocess output.

## Changes

- decode subprocess output using UTF-8
- add regression coverage for non-ASCII filenames

## Testing

- pytest tests/test_process.py
- full suite: 143 passed

Fixes #412
```

---

# 20. PR SUBMISSION MUST REQUIRE EXPLICIT APPROVAL

This rule is mandatory.

Nothing should push code to a remote or create a pull request without an explicit user action.

Safe flow:

```text
oss-agent prepare-pr
```

then:

```text
oss-agent submit
```

Before submission display:

```text
You are about to:

Push branch:
fix/issue-412-unicode-output

Repository:
org/project

Create pull request:
"Fix Unicode subprocess decoding"

Proceed? [y/N]
```

Do not default to yes.

Do not bypass this check in normal production mode.

Testing may mock the confirmation layer.

---

# 21. ADD A CONTRIBUTION CONFLICT CHECK IMMEDIATELY BEFORE SUBMISSION

Conditions may change while the user is working.

Before submission, re-check:

- whether issue is still open
- whether a PR now exists
- whether someone was assigned
- whether maintainers changed requirements
- whether issue was closed
- whether repository became archived
- whether contribution instructions changed materially

If new conflicts appear, block or warn appropriately.

Example:

```text
Submission blocked.

A new pull request referencing issue #412 was opened 37 minutes ago.

Review PR #891 before proceeding.
```

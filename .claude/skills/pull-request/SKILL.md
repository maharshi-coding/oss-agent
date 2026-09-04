---
name: pull-request
description: How to compose and open a high-quality pull request after every gate passes. Never merge.
---

# Pull request

Use only after tests pass and code, security, and maintainer reviews approve.

## PR description
Write a clear, honest description:
- **Summary** of the change and why.
- `Closes #<issue>`.
- **Changes**: the list of files/behaviors touched.
- **Verification**: captured test evidence (counts, exit codes) and review
  verdicts.
- Note that repository content was treated as untrusted data.

## Opening the PR
- Open via the GitHub abstraction. Reuse an existing PR for the same head branch
  (idempotent).
- The commit → push → PR mechanism runs through the deterministic engine, which
  re-scans for secrets and enforces git safety.

## Hard rules
- Never merge. Never push to a protected branch. Never force-push.
- Do not spam: one PR per issue, courteous and on-topic.

## Output
A `PullRequestResult` with `title`, `body`, `branch`, `number`, `url`.

---
name: git-workflow
description: The safe git and worktree workflow — deterministic branch names, isolated worktrees, and the operations that are always blocked.
---

# Git workflow

Use whenever a change must be made to a repository.

## Rules
- All repository changes happen in an **isolated worktree** created by
  `oss_agent.worktrees.WorktreeManager`. Never edit the base checkout.
- Branch names are **deterministic**: `fix/issue-<n>`, `feature/issue-<n>`,
  `docs/issue-<n>`, `chore/issue-<n>` (`oss_agent.git.branch_name_for`).
- All git runs through `oss_agent.git.GitService`. No other module shells out to
  git.

## Always blocked (fail closed)
- Pushing to a protected branch (`main`, `master`, `develop`, `release`).
- Force-push (`--force`; `--force-with-lease` only where explicitly allowed).
- Hard reset or deletion of a protected branch.
- Committing a staged diff that contains likely secrets.

## Idempotency
A resumed workflow reuses its existing worktree/branch and any existing PR for the
same head — it never duplicates work.

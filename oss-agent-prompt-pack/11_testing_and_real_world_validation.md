# Part 11 — Testing and Real-World Validation

# 32. TEST THE NEW ARCHITECTURE THOROUGHLY

Maintain or exceed the current test quality.

Tests should include:

## Unit tests

- scoring
- suitability evaluation
- state transitions
- backend parsing
- context selection
- contribution-rule parsing
- scope comparison
- safety checks
- retry logic
- PR generation
- human gates

## Integration tests

- repository setup
- worktree behavior
- Git command execution
- backend integration through mocks
- test runner
- SQLite persistence
- workflow resume
- CLI interactions

## End-to-end tests

Create local fixture repositories.

Simulate:

```text
issue
→ repository analysis
→ plan
→ AI mock implementation
→ failing test
→ repair
→ passing tests
→ review
→ learning report
→ PR preparation
```

No test should accidentally submit a real PR.

Network-dependent tests must be clearly separated.

---

# 33. REAL-WORLD VALIDATION

Where safe, test read-only functionality against real public GitHub repositories.

Validate:

- discovery
- issue analysis
- PR conflict detection
- repository health
- contribution guideline extraction
- scoring

For implementation testing, prefer:

- local fixture repos
- repositories owned by the developer
- controlled forks
- sandbox repositories

Do not spam third-party projects with test pull requests.

# Part 2 — AI Coding Backend Architecture and Production Backend Validation

# 6. BUILD A REAL CODING BACKEND ABSTRACTION

One of the biggest current weaknesses is that implementation is not truly autonomous within the tool.

The offline runner currently depends on an injected solution or fails with something equivalent to `NoSolutionError`.

Fix this architecture properly.

Introduce or improve a clean abstraction similar to:

```python
class CodingBackend:
    def analyze_repository(...)
    def analyze_issue(...)
    def propose_plan(...)
    def implement(...)
    def repair(...)
    def review_diff(...)
    def explain_solution(...)
```

Do not require these exact method names if the existing architecture suggests something cleaner.

Backends should eventually support implementations such as:

```text
ClaudeBackend
OpenAIBackend
LocalModelBackend
ManualBackend
MockBackend
```

The deterministic orchestration layer must NOT depend directly on Claude-specific behavior.

Backend responsibilities:

- reason about repository context
- produce implementation plans
- generate patches/code changes
- analyze failed tests
- repair implementations
- review generated diffs
- explain solutions

Deterministic orchestration responsibilities:

- Git
- worktrees
- state management
- persistence
- file allow/deny rules
- command execution
- test execution
- lint execution
- safety checks
- branch protection
- secret detection
- timeout enforcement
- retry limits
- logging
- workflow transitions

Keep those concerns separated.

---

# 7. VALIDATE THE PRODUCTION AI BACKEND

The existing Claude CLI backend must not merely exist structurally.

Make it actually usable.

Test whether it can:

1. inspect a repository
2. understand an issue
3. generate a plan
4. modify code
5. add/update tests
6. react to failures
7. produce a corrected patch
8. stop safely when uncertain

Build the backend so execution results are structured rather than relying on fragile parsing of arbitrary terminal output.

Capture:

- exit code
- stdout
- stderr
- changed files
- generated explanation
- backend failure reason
- timeout
- tool errors

Do not silently swallow backend failures.

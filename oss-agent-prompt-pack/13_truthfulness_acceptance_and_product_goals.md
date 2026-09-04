# Part 13 — Truthfulness, Acceptance Criteria, Productivity, Learning, and GitHub Profile Goals

# 38. DO NOT FAKE FUNCTIONALITY

This rule is extremely important.

Never mark something as working because:

- an interface exists
- a mock passes
- a function returns placeholder data
- a CLI command prints something convincing

A feature should only be considered complete if its actual path works.

For every major feature, distinguish:

```text
IMPLEMENTED
TESTED
INTEGRATION-TESTED
REAL-WORLD VALIDATED
EXPERIMENTAL
```

Do not hide gaps.

---

# 39. ACCEPTANCE CRITERIA

The refactor should be considered successful when this workflow can genuinely run:

```text
1. User runs scout.

2. OSS Agent finds current public GitHub issues.

3. It excludes obvious conflicts such as existing PRs.

4. User promotes an issue.

5. OSS Agent clones/prepares repository safely.

6. It reads repository contribution instructions.

7. It analyzes relevant code and tests.

8. It generates a concrete implementation plan.

9. Plan is reviewable.

10. AI backend generates an actual local implementation.

11. Tests are executed.

12. If tests fail, backend receives failure context.

13. Backend repairs the implementation.

14. Validation passes or workflow clearly fails.

15. Diff is reviewed for scope and safety.

16. OSS Agent generates an explanation of the fix.

17. User can inspect diff, tests, attempts, and explanation.

18. OSS Agent prepares a PR title/body.

19. Nothing is pushed yet.

20. User explicitly approves submission.

21. System performs final conflict check.

22. Branch is pushed safely.

23. PR is created.

24. Workflow stores PR metadata.

25. Visualizer reflects real workflow activity.
```

---

# 40. PRODUCTIVITY GOAL

The tool should make a workflow like this practical:

```text
oss-agent scout

oss-agent promote <issue>

oss-agent run <workflow>

oss-agent review <workflow>

oss-agent learn <workflow>

oss-agent prepare-pr <workflow>

oss-agent submit <workflow>
```

The developer should be able to discover a useful issue, understand it, get help implementing it, learn from the implementation, review the resulting change, and submit a well-prepared contribution without manually performing every repetitive repository-management step.

---

# 41. LEARNING GOAL

The user should NOT be able to contribute code they cannot explain.

Before submission, OSS Agent should help them understand:

- the bug
- relevant architecture
- root cause
- implementation
- test strategy
- tradeoffs
- edge cases

The system should enhance learning rather than replace it.

---

# 42. GITHUB PROFILE GOAL

Do not add artificial commit-generation behavior.

Do not create fake activity.

Do not commit meaningless changes.

The project should improve GitHub activity naturally by helping the developer make legitimate:

- bug fixes
- tests
- documentation improvements
- small features
- OSS pull requests
- contributions to their own projects

Contribution quality is more important than contribution count.

# Part 12 — Documentation, Architecture Documentation, and Code Quality

# 34. REMOVE MISLEADING CLAIMS

Audit:

- README
- CLI help
- package description
- comments
- docstrings
- visualizer text

Remove claims suggesting:

```text
fully autonomous OSS contributor
automatically solves GitHub issues
ships accepted PRs unattended
```

unless the behavior is genuinely proven and appropriately qualified.

Preferred positioning:

**OSS Agent helps developers discover, understand, implement, validate, learn from, and prepare open-source contributions with human review before submission.**

---

# 35. README REWRITE

Rewrite the README after the engineering changes are complete.

Include:

1. project description
2. motivation
3. architecture
4. workflow diagram
5. feature overview
6. installation
7. configuration
8. backend setup
9. basic usage
10. scout usage
11. implementation workflow
12. learning workflow
13. PR preparation
14. safety philosophy
15. human-review model
16. visualizer
17. development setup
18. testing
19. limitations
20. roadmap

Include a clear section:

## What OSS Agent does not do

Explain that:

- it does not guarantee maintainers will accept a contribution
- it cannot perfectly determine maintainer intent
- generated implementations require review
- it does not publish without explicit approval
- passing tests does not guarantee correctness

This increases credibility.

---

# 36. ARCHITECTURE DOCUMENTATION

Create clear documentation explaining the division:

```text
Deterministic Layer

Git
State machine
Persistence
Safety
Testing
Commands
Workflow
Validation

AI Reasoning Layer

Repository understanding
Planning
Implementation
Repair
Review
Explanation
```

This separation is one of the strongest aspects of the project and should be explicit.

---

# 37. CODE QUALITY REQUIREMENTS

During refactoring:

- avoid giant modules
- avoid circular imports
- avoid god classes
- use dependency injection where it improves testability
- prefer typed interfaces
- keep side effects at system boundaries
- avoid global state
- use clear domain objects
- document complex decisions
- preserve backwards compatibility where reasonable
- use migrations for persistent schema changes
- avoid speculative abstractions

Do not turn the project into an over-engineered framework.

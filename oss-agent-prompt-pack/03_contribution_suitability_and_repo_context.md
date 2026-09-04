# Part 3 — Contribution Suitability, Repository Rules, and Repository Context

# 8. ADD CONTRIBUTION SUITABILITY ANALYSIS

The system currently evaluates technical issue suitability but not sufficiently whether a contribution should exist.

Create a dedicated **Contribution Suitability Engine**.

It should inspect signals such as:

- existing open PR for the issue
- existing draft PR
- issue assignment
- issue labels
- maintainer comments
- explicit request for contributions
- repository activity
- latest commit/activity
- issue age
- issue discussion activity
- contributor guidelines
- repository-specific contribution rules
- code of conduct where relevant
- issue clarity
- reproducibility
- estimated scope
- whether the issue appears stale
- whether maintainers have rejected similar approaches
- whether the requested behavior is already implemented
- whether another contributor says they are working on it
- whether a maintainer requested an implementation before code is written
- whether an issue is a discussion rather than an implementation request
- whether there are architecture requirements
- whether a design proposal is required first

Create a configurable scoring model.

For example:

```text
Issue clarity                 15
Maintainer intent             20
Existing work/conflicts       15
Repository health             10
Contribution guidelines fit   10
Scope appropriateness         10
Technical confidence          10
Skill match                   10
```

The exact scoring system can be improved.

Return categories such as:

```text
EXCELLENT
GOOD
REVIEW_REQUIRED
INVESTIGATE_ONLY
SKIP
BLOCKED
```

Every score must have human-readable reasoning.

Do not output only a number.

Example:

```text
Score: 82/100
Recommendation: GOOD

Positive signals:
- clearly defined bug
- maintainer confirmed behavior
- active repository
- no existing PR
- small localized scope

Concerns:
- issue has no reproduction test
- maintainer requested backward compatibility
```

---

# 9. READ CONTRIBUTION RULES BEFORE CODING

Before implementation, inspect repository-level instructions.

Look for files such as:

```text
CONTRIBUTING.md
CONTRIBUTING.rst
CONTRIBUTING
README.md
CODE_OF_CONDUCT.md
DEVELOPMENT.md
HACKING.md
docs/contributing*
.github/CONTRIBUTING*
.github/pull_request_template*
.github/ISSUE_TEMPLATE/*
```

Also inspect relevant package/tool configuration.

Examples:

```text
pyproject.toml
package.json
Cargo.toml
go.mod
Makefile
tox.ini
pytest.ini
ruff.toml
.eslintrc*
.pre-commit-config.yaml
```

Extract actionable rules.

Store them in structured workflow context.

Example:

```text
ContributionRules:
- formatter: ruff format
- lint: ruff check
- test command: pytest
- PR title convention: conventional commits
- changelog required: no
- DCO required: yes
```

The implementation agent should receive these rules.

---

# 10. BUILD REPOSITORY UNDERSTANDING BEFORE IMPLEMENTATION

Do not ask the AI backend to modify code with only the GitHub issue text.

Create a repository-context phase.

It should discover:

- likely affected files
- relevant symbols/classes/functions
- nearby tests
- call paths
- dependency relationships
- configuration involved
- public interfaces
- existing similar implementations
- previous related fixes where available locally
- package structure
- project conventions

Build a compact but useful context object.

Avoid blindly sending an entire repository into the model.

Implement context selection.

Potential strategies:

- symbol search
- filename search
- import graph
- call references
- test references
- issue keywords
- git grep/ripgrep
- AST where practical
- repository metadata

The result should be inspectable.

Example:

```text
Repository Context

Likely implementation:
src/parser/encoding.py

Related:
src/parser/reader.py
src/utils/subprocess.py

Tests:
tests/parser/test_encoding.py

Relevant functions:
decode_output()
read_filename()
run_parser()

Potential root cause:
decode_output() assumes ASCII.
```

# Part 1 — Project Vision, Scope, Audit, and Existing Strengths

You are working inside an existing codebase for a project called **OSS Agent**.

Your task is NOT to create a new project from scratch.

Your task is to **deeply audit, refactor, repair, and evolve the existing project into a production-quality open-source contribution copilot** that can genuinely help a developer discover suitable open-source issues, understand unfamiliar repositories, implement fixes locally using an AI coding backend, validate those fixes, explain the solution for learning purposes, and prepare high-quality pull requests for explicit human review and approval.

Do not blindly rewrite the repository.

Preserve all good existing architecture, tests, modules, CLI behavior, persistence, safety mechanisms, visualizer functionality, and working GitHub integrations wherever possible.

The objective is to turn the existing project into something that is technically honest, actually useful, reliable, educational, and safe to use against real open-source repositories.

---

# 1. PROJECT VISION

OSS Agent should become:

**An AI-powered open-source contribution copilot that discovers suitable GitHub issues, analyzes repository context, evaluates whether a contribution is appropriate, creates an implementation plan, generates and iteratively repairs a local solution, validates it through tests and repository checks, explains the solution to the developer, and prepares a contribution for explicit human review before anything is pushed or submitted.**

The system should optimize for:

- developer productivity
- learning
- contribution quality
- repository etiquette
- safety
- reproducibility
- transparency
- maintainability

It must NOT optimize for generating large numbers of automated pull requests.

---

# 2. NON-NEGOTIABLE PRODUCT PRINCIPLE

The system must remain capable of performing real implementation work.

Do NOT downgrade this project into only:

- an issue search tool
- a repository analyzer
- a read-only dashboard
- an issue ranking system

Those features should remain, but OSS Agent must also support:

- repository understanding
- implementation planning
- AI-assisted code changes
- iterative repair
- local testing
- validation
- diff review
- contribution preparation

However, **publishing a contribution must require explicit human approval.**

The system must never blindly open a pull request immediately after generating code.

The intended workflow is:

GitHub discovery
→ contribution suitability analysis
→ repository analysis
→ implementation plan
→ human approval when appropriate
→ AI implementation
→ test/repair loop
→ automated review
→ learning report
→ human review
→ PR preparation
→ explicit human submission

---

# 3. FIRST STEP: AUDIT THE EXISTING PROJECT

Before making significant changes, inspect the entire repository.

Understand:

- directory structure
- current architecture
- state machine
- workflow model
- SQLite persistence
- GitHub client/integration
- issue discovery logic
- scoring system
- worktree management
- command execution
- safety layer
- secret detection
- prompt injection handling
- protected branch handling
- force-push protection
- existing AI backend abstraction
- Claude CLI backend
- offline backend
- test runner
- visualizer
- queue system
- CLI commands
- configuration system
- logging
- error handling
- current tests

Identify:

1. what is genuinely working
2. what is fragile
3. what is duplicated
4. what is incomplete
5. what is misleading
6. what is tightly coupled
7. what prevents real unattended implementation
8. what allows low-quality contributions
9. what is missing for a safe human-review workflow

Do not remove working functionality simply because refactoring would be easier.

---

# 4. PRESERVE THE EXISTING STRENGTHS

The project already contains valuable engineering infrastructure.

Preserve and improve these areas rather than replacing them unnecessarily:

- deterministic state machine
- SQLite persistence
- resumable workflows
- isolated Git worktrees
- GitHub discovery
- issue analysis
- issue scoring
- open-PR detection
- queue system
- configuration
- deterministic safety checks
- secret detection
- dangerous-command blocking
- protected branch protections
- force-push refusal
- prompt-injection trust boundaries
- test execution
- captured exit codes
- CLI
- visualizer
- unit tests
- integration tests
- end-to-end tests

All existing tests should continue to pass unless a test represents behavior that is intentionally being replaced.

If behavior changes intentionally, update the test and clearly document why.

---

# 5. REDEFINE THE CORE WORKFLOW

Replace the simplistic contribution flow with a proper staged workflow.

The ideal lifecycle should look similar to:

DISCOVER
→ FILTER
→ ANALYZE_ISSUE
→ ANALYZE_REPOSITORY
→ EVALUATE_CONTRIBUTION
→ BUILD_CONTEXT
→ CREATE_PLAN
→ AWAIT_PLAN_APPROVAL
→ IMPLEMENT
→ TEST
→ REPAIR_IF_NEEDED
→ REVIEW_DIFF
→ VALIDATE_CONTRIBUTION
→ GENERATE_LEARNING_REPORT
→ AWAIT_HUMAN_REVIEW
→ PREPARE_PR
→ AWAIT_SUBMISSION_APPROVAL
→ SUBMIT
→ COMPLETE

Failure states must also exist.

Examples:

DISCOVERY_FAILED
ANALYSIS_FAILED
REPOSITORY_SETUP_FAILED
NO_SOLUTION
IMPLEMENTATION_FAILED
TEST_FAILED
REPAIR_EXHAUSTED
SAFETY_BLOCKED
CONTRIBUTION_NOT_RECOMMENDED
HUMAN_REJECTED
SUBMISSION_FAILED

Every state transition should be deterministic and persisted.

A process interrupted by:

- crash
- terminal exit
- machine restart
- tool failure
- backend failure

should be resumable whenever safely possible.

You are working inside my existing OSS Agent project repository.

I have added a folder named:

oss-agent-prompt-pack/


This folder contains a complete phased refactor plan for the project.

Your job is to use that folder as the authoritative implementation roadmap and begin improving the existing project.

Important: do not treat this as a new project

Do NOT rebuild OSS Agent from scratch.

Do NOT replace working architecture unnecessarily.

Do NOT perform a giant uncontrolled rewrite.

This is an existing functioning project with working tests, CLI functionality, GitHub integration, persistence, safety infrastructure, worktrees, scoring, queue functionality, and a visualizer.

Your job is to inspect what already exists and evolve it carefully.

STEP 1 — READ THE PROMPT PACK

First, inspect:

oss-agent-prompt-pack/00_README.md


Then inspect the numbered prompt files available inside:

oss-agent-prompt-pack/


They should include files similar to:

01_project_vision_and_existing_system.md
02_ai_backend_architecture.md
03_contribution_suitability_and_repo_context.md
04_planning_implementation_and_testing_loop.md
05_diff_review_scope_and_safety.md
06_human_review_and_learning_mode.md
07_pr_preparation_and_submission.md
08_scout_skill_matching_and_modes.md
09_visualizer_events_and_persistence.md
10_cli_errors_observability_and_config.md
11_testing_and_real_world_validation.md
12_documentation_architecture_and_code_quality.md
13_truthfulness_acceptance_and_product_goals.md
14_execution_strategy_and_final_validation.md
15_critical_design_rules.md


There may also be:

99_FULL_MASTER_PROMPT.md


Use 99_FULL_MASTER_PROMPT.md only as a reference.

Do NOT try to execute the entire master prompt in one uncontrolled pass.

The numbered files are the actual implementation sequence.

STEP 2 — INSPECT THE EXISTING PROJECT BEFORE MODIFYING IT

Before making significant changes, inspect the repository thoroughly.

Understand:





project structure



package/module organization



CLI entry points



current commands



state machine



workflow states



SQLite schema and persistence



migrations if present



GitHub integration



GitHub issue discovery



issue analysis



scoring



queue/promote/dismiss flow



worktree management



Git execution



command execution



test execution



AI/backend abstractions



Claude backend



offline/manual/mock backends



safety infrastructure



secret detection



dangerous-command protection



protected branch protection



force-push protection



prompt-injection boundaries



configuration



logging



error handling



visualizer



event system if one exists



current documentation



all tests

Do not infer how something works from filenames alone.

Trace the important code paths.

STEP 3 — ESTABLISH THE CURRENT BASELINE

Before modifying code, run the project's existing validation.

Determine the correct commands from the repository itself.

Run, where applicable:

unit tests
integration tests
end-to-end tests
linting
format checks
type checking
build/package validation


Record the actual baseline.

For example:

Tests before refactor: X passing, Y failing
Lint: PASS/FAIL
Type checking: PASS/FAIL


If some tests already fail before your changes, document that clearly.

Do NOT silently attribute pre-existing failures to the refactor.

STEP 4 — CREATE A REFACTOR PROGRESS FILE

Create or maintain:

REFACTOR_PROGRESS.md


at the project root.

It should track each prompt-pack phase.

Use a structure similar to:

# OSS Agent Refactor Progress

## Baseline

Tests:
Lint:
Type checks:
Current CLI commands:
Current workflow states:

## Phase 1
Status: NOT STARTED / IN PROGRESS / COMPLETE / BLOCKED

Changes:
-

Tests:
-

Known limitations:
-

## Phase 2
Status: NOT STARTED

...


Update this file after every major phase.

This file is part of the engineering record and must remain accurate.

STEP 5 — START WITH PHASE 1

Begin with:

oss-agent-prompt-pack/01_project_vision_and_existing_system.md


Read the entire file.

Then execute its requirements against the actual existing project.

Do not simply summarize the prompt.

Implement what it requires.

However, use engineering judgment.

If the prompt suggests an example architecture but the existing project already has a cleaner equivalent, improve the existing design instead of creating redundant systems.

STEP 6 — WORK PHASE BY PHASE

After Phase 1 is complete, proceed through the files sequentially:

01
↓
02
↓
03
↓
04
↓
05
↓
06
↓
07
↓
08
↓
09
↓
10
↓
11
↓
12
↓
13
↓
14
↓
15


For every phase:





Read the complete prompt file.



Inspect the related existing implementation.



Identify what already satisfies the requirements.



Preserve working functionality.



Implement missing or broken functionality.



Refactor poor architecture only when justified.



Add/update tests.



Run relevant targeted tests.



Run the broader test suite.



Update REFACTOR_PROGRESS.md.



Report what was actually validated.

Do not blindly implement requirements that already exist.

Do not duplicate existing systems.

DO NOT STOP AFTER EACH FILE JUST BECAUSE THE FILE ENDED

The prompt files are parts of one continuous project.

Continue through the phases as long as the repository remains stable and the work can be safely completed.

If a phase exposes a foundational issue that must be fixed before later phases, fix that root cause first.

Do not add temporary hacks just to advance to the next numbered file.

VERY IMPORTANT — IMPLEMENT REAL FUNCTIONALITY

Do not fake completion.

A feature is NOT complete merely because:





a class exists



an interface exists



a CLI command exists



a mock test passes



placeholder data is returned



TODO comments describe intended behavior



output looks convincing

For major features, determine whether they are:

IMPLEMENTED
UNIT TESTED
INTEGRATION TESTED
END-TO-END TESTED
REAL-WORLD VALIDATED
EXPERIMENTAL


Be explicit.

IMPORTANT — THE IMPLEMENTATION BACKEND MUST ACTUALLY WORK

A major goal of this refactor is to make OSS Agent capable of real local implementation.

Do not leave the AI backend as an architectural stub.

The actual production backend should eventually be able to:

issue
↓
repository understanding
↓
implementation plan
↓
local code modification
↓
test execution
↓
failure analysis
↓
repair
↓
passing validation or explicit failure


If the Claude backend is currently the production backend, verify the real invocation path.

Do not claim it is functional merely because its class exists.

IMPORTANT — PRESERVE THE DETERMINISTIC / AI SEPARATION

AI reasoning should handle things like:

repository understanding
issue reasoning
planning
implementation
repair
diff reasoning
explanation


Deterministic infrastructure should handle things like:

Git
worktrees
state transitions
persistence
command execution
tests
timeouts
secret scanning
branch protection
safety policies
submission gates
logging


Do not let the model directly control sensitive infrastructure without deterministic validation.

IMPORTANT — CONTRIBUTION QUALITY

OSS Agent must not become a PR spam machine.

Before implementation, evaluate whether the issue is genuinely suitable for contribution.

Check things like:

existing PRs
draft PRs
issue assignment
maintainer intent
contribution rules
repo activity
issue clarity
scope
possible duplicate work
architecture requirements
discussion/proposal requirements


Passing tests does NOT automatically mean a contribution is appropriate.

IMPORTANT — HUMAN CONTROL

Local implementation may be highly automated.

Publishing must not be.

Nothing should:

push to a remote
create a PR
modify the default branch
force push


without the appropriate deterministic safeguards.

Creating or submitting a real pull request must require explicit human approval.

Keep PR preparation separate from PR submission.

IMPORTANT — LEARNING IS A PRIMARY FEATURE

The tool should help the developer understand contributions instead of blindly generating them.

The final workflow should be capable of explaining:

what the issue was
what caused it
which code path mattered
what changed
why the fix works
what tests validate it
what tradeoffs exist
what edge cases remain
what the developer should understand before submitting


Ground explanations in the actual repository and actual diff.

IMPORTANT — TEST SAFELY

For end-to-end implementation testing, use:

fixture repositories
local repositories
sandbox repositories
repositories owned by the developer
controlled forks


Do not create experimental pull requests against unrelated third-party repositories just to prove that submission works.

Read-only GitHub operations may be validated against real public repositories where appropriate.

IMPORTANT — VISUALIZER

Do not remove the pixel-world visualizer.

Make it represent real system activity.

The visualizer should ultimately consume actual workflow/event information rather than displaying fake timed activity.

Examples of real events:

issue.discovered
issue.scored
repository.cloned
context.built
plan.generated
implementation.started
file.modified
test.started
test.completed
repair.started
review.completed
human.review_required
pr.prepared
workflow.completed


Use the project's existing event architecture if one already exists.

Do not create a redundant event system without inspecting the current implementation.

CODE QUALITY RULES

While refactoring:





avoid giant modules



avoid god classes



avoid circular imports



avoid global mutable state



avoid duplicated abstractions



keep side effects at system boundaries



use typed interfaces where appropriate



prefer clear domain objects



preserve backwards compatibility where reasonable



use database migrations instead of destructive schema resets



keep CLI behavior coherent



make errors actionable



do not leak secrets into logs



avoid unnecessary dependencies



avoid speculative over-engineering

Fix root causes rather than layering workarounds.

DO NOT DELETE EXISTING WORK WITHOUT JUSTIFICATION

Before removing or replacing a module, determine:

What uses it?
What tests cover it?
Is it actually broken?
Can it be improved instead?
Will removing it break compatibility?


Existing working functionality should survive unless the new design intentionally supersedes it.

Document intentional behavior changes.

TESTING REQUIREMENT AFTER EVERY MAJOR CHANGE

After modifying an important subsystem, run the relevant tests immediately.

Do not accumulate dozens of architectural changes and test only at the end.

Use a loop like:

inspect
↓
change
↓
targeted tests
↓
fix
↓
broader tests
↓
continue


KEEP THE PROJECT RUNNABLE

Do not leave the repository in a half-migrated state between phases.

Whenever practical, each phase should end with:

application imports successfully
CLI starts
database loads
tests pass
existing functionality still works
new functionality is tested


OUTPUT FORMAT WHILE WORKING

Provide concise progress updates as you work.

For each completed phase report:

PHASE X — COMPLETE

What existed already:
-

What changed:
-

Files/modules modified:
-

Tests added/updated:
-

Validation performed:
-

Test status:
-

Real-world validation:
-

Known limitations:
-

Next phase:
-


Do not exaggerate validation.

If something is only mock-tested, say so.

If something was not exercised against the real backend, say so.

FINAL ACCEPTANCE TARGET

The project should eventually support this genuine workflow:

oss-agent scout
↓
find real suitable issues
↓
promote/select issue
↓
prepare isolated repository/worktree
↓
read contribution instructions
↓
understand relevant repository context
↓
evaluate contribution suitability
↓
generate implementation plan
↓
perform AI-assisted local implementation
↓
run tests
↓
repair failures when possible
↓
review final diff
↓
perform safety checks
↓
generate learning report
↓
human reviews contribution
↓
prepare PR
↓
re-check GitHub for conflicts
↓
explicit user approval
↓
push safe branch
↓
create PR
↓
persist final workflow metadata


The visualizer should reflect the real workflow throughout.

FINAL VALIDATION REQUIREMENT

Before declaring the entire refactor complete:

Run the complete project validation.

Verify:

discovery
analysis
scoring
queue
repository setup
persistence
resume behavior
contribution suitability
context building
planning
AI implementation
repair loop
test execution
diff review
scope enforcement
safety checks
learning report
human gates
PR preparation
submission confirmation
visualizer events
CLI behavior


Then produce a final report containing:

Total modules
Total tests
Passing tests
Failing tests
CLI commands
Workflow states
Major architecture changes
New capabilities
Deprecated functionality
Production AI backend status
Safety status
Persistence/resume status
Real-world validation performed
Known limitations
Experimental functionality
Recommended future improvements


Do not declare the refactor complete unless the actual implementation and actual tests support that conclusion.

BEGIN NOW

Start by:





Reading oss-agent-prompt-pack/00_README.md.



Inspecting the entire existing repository.



Running the current test/validation baseline.



Creating REFACTOR_PROGRESS.md.



Reading oss-agent-prompt-pack/01_project_vision_and_existing_system.md.



Beginning Phase 1 implementation.



Continuing through the numbered prompt files sequentially while keeping the project stable.

Do not just tell me what you plan to do.

Start inspecting and modifying the actual repository now.








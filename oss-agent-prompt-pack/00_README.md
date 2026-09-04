# OSS Agent Refactor Prompt Pack

This folder contains the full OSS Agent master refactor prompt split into focused implementation files.

## Recommended execution order

1. `01_project_vision_and_existing_system.md`
2. `02_ai_backend_architecture.md`
3. `03_contribution_suitability_and_repo_context.md`
4. `04_planning_implementation_and_testing_loop.md`
5. `05_diff_review_scope_and_safety.md`
6. `06_human_review_and_learning_mode.md`
7. `07_pr_preparation_and_submission.md`
8. `08_scout_skill_matching_and_modes.md`
9. `09_visualizer_events_and_persistence.md`
10. `10_cli_errors_observability_and_config.md`
11. `11_testing_and_real_world_validation.md`
12. `12_documentation_architecture_and_code_quality.md`
13. `13_truthfulness_acceptance_and_product_goals.md`
14. `14_execution_strategy_and_final_validation.md`
15. `15_critical_design_rules.md`

A complete combined version is also included as:

- `99_FULL_MASTER_PROMPT.md`

## How to use these files

Give the coding agent `01_project_vision_and_existing_system.md` first so it understands the product direction and what must be preserved.

Then provide the remaining files sequentially. The agent should finish each phase, run the test suite, report what changed, and only then move to the next file.

Do not let the agent interpret these files as permission to perform a full uncontrolled rewrite. The project should remain runnable throughout the refactor.

The final product should be a serious human-in-the-loop OSS contribution copilot that:

- discovers suitable GitHub issues,
- evaluates whether a contribution is appropriate,
- understands unfamiliar repositories,
- creates implementation plans,
- performs real local AI-assisted implementation,
- iteratively repairs failed solutions,
- runs repository validation,
- reviews generated diffs,
- teaches the developer what changed,
- prepares high-quality pull requests,
- and requires explicit human approval before publishing.

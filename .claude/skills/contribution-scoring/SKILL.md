---
name: contribution-scoring
description: How the configurable scoring engine turns analysis signals plus the developer profile into a 0-100 opportunity score with penalties and a recommendation.
---

# Contribution scoring

Use to evaluate whether an opportunity is worth pursuing.

## How it works
The number is computed **deterministically** by `oss_agent.scoring.ScoringEngine`
from weighted dimensions (config in `config/scoring.yaml`):

| Dimension | Default weight |
| --- | --- |
| issue_clarity | 0.20 |
| implementation_confidence | 0.20 |
| repository_health | 0.15 |
| maintainer_activity | 0.15 |
| testability | 0.10 |
| skill_match (uses the developer profile) | 0.10 |
| contribution_value | 0.05 |
| issue_freshness | 0.05 |

Penalties subtract for ambiguity, high complexity, duplicate risk, breaking
change, and security sensitivity. The penalized score maps to `STRONG_PURSUE /
PURSUE / CONSIDER / SKIP`.

## Your role
Validate the input signals and explain the recommendation. Never override the
engine's math with an invented number; if a signal is wrong, request re-analysis.

## Output
A `ContributionScore` consistent with the engine.

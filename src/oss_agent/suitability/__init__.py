"""Contribution suitability: whether a contribution *should* be made.

This package answers a different question from :mod:`oss_agent.scoring`. Scoring
asks "how good a technical/skill fit is this opportunity for the developer?".
Suitability asks "is opening a contribution here appropriate right now?" —
weighing maintainer intent, existing or conflicting work, issue clarity,
staleness, and repository etiquette. It is the primary guard against turning
OSS-Agent into a pull-request spam machine.
"""

from oss_agent.suitability.engine import (
    SuitabilityEngine,
    SuitabilityWeights,
    load_suitability_weights,
)

__all__ = ["SuitabilityEngine", "SuitabilityWeights", "load_suitability_weights"]

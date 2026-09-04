"""Scoring configuration: weights, penalties, and thresholds.

Fully data-driven so the scoring system is never hardcoded across the codebase
(spec section 13). Loadable from YAML; a validated default is built in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field


class PenaltyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max: float = Field(ge=0.0)


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strong_pursue: float = 75.0
    pursue: float = 60.0
    consider: float = 45.0


DIMENSIONS = (
    "issue_clarity",
    "implementation_confidence",
    "repository_health",
    "maintainer_activity",
    "testability",
    "skill_match",
    "contribution_value",
    "issue_freshness",
)


class ScoringConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "issue_clarity": 0.20,
            "implementation_confidence": 0.20,
            "repository_health": 0.15,
            "maintainer_activity": 0.15,
            "testability": 0.10,
            "skill_match": 0.10,
            "contribution_value": 0.05,
            "issue_freshness": 0.05,
        }
    )
    penalties: dict[str, PenaltyConfig] = Field(
        default_factory=lambda: {
            "ambiguity": PenaltyConfig(max=20),
            "high_complexity": PenaltyConfig(max=15),
            "duplicate_risk": PenaltyConfig(max=25),
            "breaking_change": PenaltyConfig(max=20),
            "security_sensitivity": PenaltyConfig(max=15),
        }
    )
    thresholds: Thresholds = Field(default_factory=Thresholds)
    # The shared config file may also carry a `suitability:` section consumed by
    # `oss_agent.suitability.load_suitability_weights`. Declared here (rather than
    # relaxing extra="forbid") so the same file validates while typos are still
    # caught. Not used by scoring itself.
    suitability: dict[str, float] = Field(default_factory=dict)

    def normalized_weights(self) -> dict[str, float]:
        total = sum(self.weights.values()) or 1.0
        return {k: v / total for k, v in self.weights.items()}


def load_scoring_config(
    path: Path | str, *, fallback_to_default: bool = True
) -> ScoringConfig:
    p = Path(path)
    if not p.exists():
        if fallback_to_default:
            return ScoringConfig()
        raise FileNotFoundError(f"scoring config not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return ScoringConfig.model_validate(data)

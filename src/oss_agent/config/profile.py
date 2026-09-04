"""Developer profile and scoring configuration loaded from YAML.

The profile feeds the "skill match" scoring dimension and discovery filters.
The scoring config makes weights, penalties, and thresholds fully configurable
without touching code (spec section 13: do not hardcode scoring throughout).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from oss_agent.domain.enums import (
    ContributionType,
    Difficulty,
    ExperienceLevel,
    ProjectSize,
)


class ProfileFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_stars: int = 0
    max_stars: int = 10_000_000
    require_contributing_guide: bool = False
    require_tests: bool = False
    exclude_archived: bool = True
    allowed_licenses: list[str] = Field(default_factory=list)


class DeveloperProfile(BaseModel):
    """The developer profile that shapes discovery and skill-match scoring."""

    model_config = ConfigDict(extra="forbid")

    name: str = "Anonymous Developer"
    languages: dict[str, float] = Field(default_factory=dict)
    frameworks: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    excluded_domains: list[str] = Field(default_factory=list)
    experience_level: ExperienceLevel = ExperienceLevel.INTERMEDIATE
    preferred_contribution_types: list[ContributionType] = Field(default_factory=list)
    preferred_project_size: ProjectSize = ProjectSize.ANY
    preferred_difficulty: Difficulty = Difficulty.ANY
    filters: ProfileFilters = Field(default_factory=ProfileFilters)

    @field_validator("languages")
    @classmethod
    def _clamp_language_weights(cls, v: dict[str, float]) -> dict[str, float]:
        return {k.lower(): max(0.0, min(1.0, float(w))) for k, w in v.items()}

    def language_weight(self, language: Optional[str]) -> float:
        """Confidence weight for a language, 0.0 if unknown."""
        if not language:
            return 0.0
        return self.languages.get(language.lower(), 0.0)

    def known_languages(self) -> set[str]:
        return set(self.languages.keys())


DEFAULT_PROFILE = DeveloperProfile(
    name="Default Developer",
    languages={"python": 1.0},
    frameworks=["pytest"],
    domains=["developer-tools"],
    experience_level=ExperienceLevel.INTERMEDIATE,
    preferred_contribution_types=[
        ContributionType.BUG_FIX,
        ContributionType.DOCUMENTATION,
        ContributionType.TEST,
    ],
    preferred_project_size=ProjectSize.ANY,
    preferred_difficulty=Difficulty.EASY,
)


def load_profile(path: Path | str, *, fallback_to_default: bool = True) -> DeveloperProfile:
    """Load a developer profile from YAML.

    If the file does not exist and ``fallback_to_default`` is true, the built-in
    default profile is returned (so first-run flows don't crash). Malformed files
    always raise so misconfiguration is visible.
    """
    p = Path(path)
    if not p.exists():
        if fallback_to_default:
            return DEFAULT_PROFILE
        raise FileNotFoundError(f"profile not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return DeveloperProfile.model_validate(data)

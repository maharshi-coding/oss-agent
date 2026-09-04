"""Scout query building and user-mode presets.

Filters shape *discovery* (the GitHub search query) and *post-analysis* results
(difficulty). Modes are convenience presets over the scout's own knobs — they
tune how much to scan and what to favor, and never touch safety or the human
submission gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

from oss_agent.domain.enums import Difficulty


def build_query(
    *,
    language: Optional[str] = None,
    labels: Optional[Sequence[str]] = None,
    base: str = "is:issue is:open",
) -> str:
    """Compose a GitHub-style search query from filter fragments."""
    parts = [base]
    for label in labels or []:
        label = label.strip()
        if label:
            parts.append(f'label:"{label}"' if " " in label else f"label:{label}")
    if language:
        parts.append(f"language:{language.strip()}")
    return " ".join(parts)


class ScoutMode(str, Enum):
    BEGINNER = "beginner"
    LEARNING = "learning"
    BALANCED = "balanced"
    PRODUCTIVITY = "productivity"
    EXPERT = "expert"


@dataclass(frozen=True)
class ModePreset:
    """Default scout knobs for a mode (all explicitly overridable on the CLI).
    None means "no constraint". Modes never relax safety or submission gates."""

    min_score: float
    max_candidates: int
    analyze_top: int
    difficulty: Optional[Difficulty] = None
    description: str = ""


MODE_PRESETS: dict[ScoutMode, ModePreset] = {
    ScoutMode.BEGINNER: ModePreset(
        min_score=60.0, max_candidates=6, analyze_top=4, difficulty=Difficulty.EASY,
        description="favor small, easy, well-scoped issues",
    ),
    ScoutMode.LEARNING: ModePreset(
        min_score=50.0, max_candidates=8, analyze_top=6, difficulty=None,
        description="allow moderate stretch; maximize learning",
    ),
    ScoutMode.BALANCED: ModePreset(
        min_score=45.0, max_candidates=6, analyze_top=4, difficulty=None,
        description="reasonable automation with normal human gates",
    ),
    ScoutMode.PRODUCTIVITY: ModePreset(
        min_score=55.0, max_candidates=10, analyze_top=6, difficulty=None,
        description="scan more; still requires submission approval",
    ),
    ScoutMode.EXPERT: ModePreset(
        min_score=40.0, max_candidates=12, analyze_top=8, difficulty=None,
        description="broader scope, compact output",
    ),
}


def preset_for(mode: ScoutMode) -> ModePreset:
    return MODE_PRESETS[mode]

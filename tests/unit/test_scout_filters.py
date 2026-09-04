"""Scout query building, mode presets, and difficulty filtering."""

from __future__ import annotations

import pytest

from oss_agent.domain.enums import Difficulty
from oss_agent.scout.filters import MODE_PRESETS, ScoutMode, build_query, preset_for

pytestmark = pytest.mark.unit


def test_build_query_with_language_and_labels():
    q = build_query(language="python", labels=["good first issue", "bug"])
    assert 'label:"good first issue"' in q
    assert "label:bug" in q
    assert "language:python" in q
    assert q.startswith("is:issue is:open")


def test_build_query_empty_is_base_only():
    assert build_query() == "is:issue is:open"


def test_every_mode_has_a_preset():
    for mode in ScoutMode:
        preset = preset_for(mode)
        assert preset.min_score >= 0
        assert preset.max_candidates >= 1
        assert preset.analyze_top >= 1


def test_beginner_mode_favors_easy():
    assert preset_for(ScoutMode.BEGINNER).difficulty is Difficulty.EASY
    # Beginner is the most conservative min_score.
    assert preset_for(ScoutMode.BEGINNER).min_score >= preset_for(ScoutMode.EXPERT).min_score


def test_presets_cover_all_modes():
    assert set(MODE_PRESETS.keys()) == set(ScoutMode)

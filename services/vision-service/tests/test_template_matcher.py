"""
Unit tests for TemplateMatcher.

Uses synthetic templates (programmatically generated images) so
no real Valorant screenshots are needed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from template_matcher import TemplateMatcher


def _make_template(color: tuple[int, int, int] = (255, 255, 255),
                   size: tuple[int, int] = (40, 80)) -> np.ndarray:
    """Gray template: solid rectangle."""
    h, w = size
    img = np.full((h, w), 50, dtype=np.uint8)
    img[5:h - 5, 5:w - 5] = color[0]  # use just first channel for gray
    return img


def _make_scene(template: np.ndarray, pos: tuple[int, int] = (100, 200)) -> np.ndarray:
    """1080p gray scene with template pasted at pos."""
    scene = np.full((1080, 1920), 30, dtype=np.uint8)
    y, x = pos
    th, tw = template.shape[:2]
    scene[y:y + th, x:x + tw] = template
    bgr = cv2.cvtColor(scene, cv2.COLOR_GRAY2BGR)
    return bgr


class TestTemplateMatcher:

    def _matcher_with_template(self, name: str, template: np.ndarray) -> TemplateMatcher:
        """Build a TemplateMatcher that has one synthetic template injected."""
        m = TemplateMatcher.__new__(TemplateMatcher)
        m._templates = {name: template}
        return m

    def test_match_returns_result(self) -> None:
        tmpl = _make_template()
        scene = _make_scene(tmpl, pos=(100, 200))
        m = self._matcher_with_template("test", tmpl)
        result = m.match(scene, "test")
        assert result.template_name == "test"
        assert 0.0 <= result.confidence <= 1.0

    def test_match_detects_exact_placement(self) -> None:
        tmpl = _make_template()
        scene = _make_scene(tmpl, pos=(150, 300))
        m = self._matcher_with_template("test", tmpl)
        result = m.match(scene, "test")
        assert result.confidence > 0.85, f"Expected high confidence, got {result.confidence}"
        assert result.detected

    def test_no_match_on_missing_template(self) -> None:
        scene = np.zeros((1080, 1920, 3), dtype=np.uint8)
        m = self._matcher_with_template("present", _make_template())
        result = m.match(scene, "absent")
        assert result.confidence == 0.0
        assert not result.detected

    def test_low_confidence_on_random_noise(self) -> None:
        """Template should not falsely match on pure noise."""
        tmpl = _make_template(color=(200, 200, 200), size=(30, 60))
        scene = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
        m = self._matcher_with_template("test", tmpl)
        result = m.match(scene, "test")
        # On noise there's no guarantee it's below threshold, but
        # it should not be near 1.0
        assert result.confidence < 0.99

    def test_match_any_returns_all(self) -> None:
        scene = np.zeros((1080, 1920, 3), dtype=np.uint8)
        m = TemplateMatcher.__new__(TemplateMatcher)
        m._templates = {
            "a": _make_template(),
            "b": _make_template(),
        }
        results = m.match_any(scene, ["a", "b", "c"])
        assert set(results.keys()) == {"a", "b", "c"}

    def test_no_crash_on_empty_templates(self) -> None:
        m = TemplateMatcher.__new__(TemplateMatcher)
        m._templates = {}
        scene = np.zeros((1080, 1920, 3), dtype=np.uint8)
        result = m.match(scene, "anything")
        assert result.confidence == 0.0

    def test_template_names_property(self) -> None:
        m = TemplateMatcher.__new__(TemplateMatcher)
        m._templates = {"buy_phase": _make_template(), "victory": _make_template()}
        assert set(m.template_names) == {"buy_phase", "victory"}

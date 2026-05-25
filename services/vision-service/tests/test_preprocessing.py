"""Unit tests for the preprocessing pipeline — no OCR required."""

from __future__ import annotations

import numpy as np
import pytest

from preprocessing import (
    preprocess,
    preprocess_banner,
    preprocess_killfeed,
    preprocess_numeric,
    preprocess_timer,
)


def _make_bgr(h: int = 40, w: int = 100) -> np.ndarray:
    img = np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)
    return img


def _make_gray(h: int = 40, w: int = 100) -> np.ndarray:
    return np.random.randint(0, 255, (h, w), dtype=np.uint8)


class TestPreprocessors:
    @pytest.mark.parametrize("fn", [
        preprocess_numeric,
        preprocess_timer,
        preprocess_banner,
        preprocess_killfeed,
    ])
    def test_returns_2d_array(self, fn) -> None:
        result = fn(_make_bgr())
        assert result.ndim == 2, "Preprocessor should return grayscale (2D)"

    @pytest.mark.parametrize("fn", [
        preprocess_numeric,
        preprocess_timer,
        preprocess_banner,
        preprocess_killfeed,
    ])
    def test_accepts_gray_input(self, fn) -> None:
        result = fn(_make_gray())
        assert result.ndim == 2

    @pytest.mark.parametrize("fn", [
        preprocess_numeric,
        preprocess_timer,
    ])
    def test_upscales(self, fn) -> None:
        src = _make_bgr(h=30, w=80)
        result = fn(src)
        # Both functions scale up by at least 2×
        assert result.shape[0] >= src.shape[0] * 2
        assert result.shape[1] >= src.shape[1] * 2

    def test_preprocess_dispatch(self) -> None:
        """preprocess() should route to the right preset without raising."""
        for roi_name in [
            "health", "armor", "credits", "ammo_current",
            "match_timer", "buy_phase_banner", "killfeed",
        ]:
            result = preprocess(_make_bgr(), roi_name)
            assert result is not None
            assert result.ndim == 2

    def test_unknown_roi_falls_back(self) -> None:
        """Unknown ROI names should fall back to numeric preset."""
        result = preprocess(_make_bgr(), "nonexistent_roi")
        assert result.ndim == 2

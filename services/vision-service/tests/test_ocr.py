"""
OCR unit tests.

These tests mock EasyOCR so they run without a GPU or model download.
They verify the OCR wrapper's filtering, confidence handling, and
convenience helpers (ocr_numeric, ocr_text).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

import ocr as ocr_module
from models import OcrResult


def _dummy_image() -> np.ndarray:
    return np.zeros((60, 200, 3), dtype=np.uint8)


def _mock_reader(raw_results):
    """Return a mock EasyOCR Reader that always returns raw_results."""
    reader = MagicMock()
    reader.readtext.return_value = raw_results
    return reader


class TestOcrRegion:

    def test_returns_list_of_ocr_results(self) -> None:
        raw = [([0, 0, 10, 10], "100", 0.95)]
        with patch("ocr._get_reader", return_value=_mock_reader(raw)):
            results = ocr_module.ocr_region(_dummy_image(), "health")
        assert len(results) == 1
        assert results[0].text == "100"
        assert results[0].confidence == pytest.approx(0.95)
        assert results[0].region == "health"

    def test_filters_low_confidence(self) -> None:
        raw = [
            ([0, 0, 10, 10], "good", 0.9),
            ([0, 0, 10, 10], "bad", 0.1),   # below default 0.3
        ]
        with patch("ocr._get_reader", return_value=_mock_reader(raw)):
            results = ocr_module.ocr_region(_dummy_image(), "health", min_confidence=0.3)
        assert len(results) == 1
        assert results[0].text == "good"

    def test_sorted_by_confidence_descending(self) -> None:
        raw = [
            ([0, 0, 10, 10], "low", 0.5),
            ([0, 0, 10, 10], "high", 0.9),
            ([0, 0, 10, 10], "mid", 0.7),
        ]
        with patch("ocr._get_reader", return_value=_mock_reader(raw)):
            results = ocr_module.ocr_region(_dummy_image(), "test")
        confs = [r.confidence for r in results]
        assert confs == sorted(confs, reverse=True)

    def test_empty_text_excluded(self) -> None:
        raw = [([0, 0, 10, 10], "  ", 0.99)]
        with patch("ocr._get_reader", return_value=_mock_reader(raw)):
            results = ocr_module.ocr_region(_dummy_image(), "test")
        assert results == []

    def test_retry_returns_first_success(self) -> None:
        call_count = 0
        def fake_readtext(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return []
            return [([0, 0, 10, 10], "42", 0.8)]

        reader = MagicMock()
        reader.readtext.side_effect = fake_readtext
        with patch("ocr._get_reader", return_value=reader):
            results = ocr_module.ocr_region(_dummy_image(), "credits", retries=2)
        assert len(results) == 1
        assert results[0].text == "42"


class TestOcrNumeric:

    def test_parses_integer(self) -> None:
        raw = [([0, 0, 10, 10], "3900", 0.9)]
        with patch("ocr._get_reader", return_value=_mock_reader(raw)):
            value = ocr_module.ocr_numeric(_dummy_image(), "credits")
        assert value == 3900

    def test_strips_noise_characters(self) -> None:
        raw = [([0, 0, 10, 10], "3,900", 0.9)]
        with patch("ocr._get_reader", return_value=_mock_reader(raw)):
            value = ocr_module.ocr_numeric(_dummy_image(), "credits")
        assert value == 3900

    def test_returns_none_on_no_digits(self) -> None:
        raw = [([0, 0, 10, 10], "abc", 0.9)]
        with patch("ocr._get_reader", return_value=_mock_reader(raw)):
            value = ocr_module.ocr_numeric(_dummy_image(), "health")
        assert value is None

    def test_returns_none_on_empty(self) -> None:
        with patch("ocr._get_reader", return_value=_mock_reader([])):
            value = ocr_module.ocr_numeric(_dummy_image(), "health")
        assert value is None


class TestOcrText:

    def test_returns_highest_confidence_text(self) -> None:
        raw = [
            ([0, 0, 10, 10], "BUY PHASE", 0.95),
            ([0, 0, 10, 10], "BUP PHASE", 0.6),
        ]
        with patch("ocr._get_reader", return_value=_mock_reader(raw)):
            text = ocr_module.ocr_text(_dummy_image(), "buy_phase_banner")
        assert text == "BUY PHASE"

    def test_returns_none_on_empty(self) -> None:
        with patch("ocr._get_reader", return_value=_mock_reader([])):
            text = ocr_module.ocr_text(_dummy_image(), "any")
        assert text is None

"""
Integration tests for the vision pipeline.

Uses a synthetic 1920×1080 frame and mocked OCR/templates so no
hardware, game, or model downloads are needed.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from event_engine import EventEngine
from extractor import FrameExtractor
from models import EventType, GameState, RoundResult


def _blank_frame() -> np.ndarray:
    return np.zeros((1080, 1920, 3), dtype=np.uint8)


def _mock_ocr_results(text: str, conf: float = 0.9):
    from models import OcrResult
    return [OcrResult(text=text, confidence=conf, region="test")]


# ─────────────────────────────────────────────────────────────────────────────
# Extractor integration
# ─────────────────────────────────────────────────────────────────────────────

class TestFrameExtractorIntegration:

    @patch("extractor.tm_module.matcher.match_any")
    @patch("extractor.ocr_module.ocr_region")
    def test_buy_phase_from_template(self, mock_ocr, mock_match):
        """Template detection of buy phase should set buy_phase=True."""
        from template_matcher import MatchResult
        mock_match.return_value = {
            "buy_phase": MatchResult("buy_phase", 0.90, (0, 0), 1.0),
            "victory": MatchResult("victory", 0.0, (0, 0), 1.0),
            "defeat": MatchResult("defeat", 0.0, (0, 0), 1.0),
            "spike_planted": MatchResult("spike_planted", 0.0, (0, 0), 1.0),
            "spike_defused": MatchResult("spike_defused", 0.0, (0, 0), 1.0),
            "player_dead": MatchResult("player_dead", 0.0, (0, 0), 1.0),
        }
        mock_ocr.return_value = []

        ext = FrameExtractor()
        state = ext.extract(_blank_frame(), frame_id=1)
        assert state.buy_phase is True
        assert state.confidence.buy_phase == pytest.approx(0.90)

    @patch("extractor.tm_module.matcher.match_any")
    @patch("extractor.ocr_module.ocr_region")
    def test_health_extracted_from_ocr(self, mock_ocr, mock_match):
        """OCR returning '85' in health ROI should parse to health=85."""
        from template_matcher import MatchResult
        from models import OcrResult

        # All templates miss
        no_match = MatchResult("x", 0.0, (0, 0), 1.0)
        mock_match.return_value = {
            k: no_match for k in
            ["buy_phase", "victory", "defeat", "spike_planted", "spike_defused", "player_dead"]
        }

        def fake_ocr(image, roi_name, **kw):
            if roi_name == "health":
                return [OcrResult(text="85", confidence=0.92, region="health")]
            return []

        mock_ocr.side_effect = fake_ocr

        ext = FrameExtractor()
        state = ext.extract(_blank_frame(), frame_id=2)
        assert state.health == 85
        assert state.confidence.health == pytest.approx(0.92)

    @patch("extractor.tm_module.matcher.match_any")
    @patch("extractor.ocr_module.ocr_region")
    def test_processing_ms_populated(self, mock_ocr, mock_match):
        from template_matcher import MatchResult
        no_match = MatchResult("x", 0.0, (0, 0), 1.0)
        mock_match.return_value = {k: no_match for k in
            ["buy_phase", "victory", "defeat", "spike_planted", "spike_defused", "player_dead"]}
        mock_ocr.return_value = []

        ext = FrameExtractor()
        state = ext.extract(_blank_frame(), frame_id=3)
        assert state.processing_ms >= 0.0

    @patch("extractor.tm_module.matcher.match_any")
    @patch("extractor.ocr_module.ocr_region")
    def test_credits_clamped_to_valid_range(self, mock_ocr, mock_match):
        """OCR returning '99999' (out of 0–9000 range) should yield None."""
        from template_matcher import MatchResult
        from models import OcrResult

        no_match = MatchResult("x", 0.0, (0, 0), 1.0)
        mock_match.return_value = {k: no_match for k in
            ["buy_phase", "victory", "defeat", "spike_planted", "spike_defused", "player_dead"]}

        def fake_ocr(image, roi_name, **kw):
            if roi_name == "credits":
                return [OcrResult(text="99999", confidence=0.85, region="credits")]
            return []

        mock_ocr.side_effect = fake_ocr
        ext = FrameExtractor()
        state = ext.extract(_blank_frame(), frame_id=4)
        assert state.credits is None


# ─────────────────────────────────────────────────────────────────────────────
# Full pipeline: extractor → event engine
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineIntegration:

    def test_spike_planted_event_fires(self) -> None:
        engine = EventEngine()
        engine.process(GameState(spike_planted=False))
        events = engine.process(GameState(spike_planted=True))
        assert any(e.event_type == EventType.SPIKE_PLANTED for e in events)

    def test_full_round_lifecycle(self) -> None:
        """Simulate a round: buy → fight → death → round end."""
        engine = EventEngine()
        all_events: list = []

        # Initial stable state
        engine.process(GameState())

        # Buy phase opens
        all_events += engine.process(GameState(buy_phase=True))
        # Buy phase closes → round starts
        all_events += engine.process(GameState(buy_phase=False, credits=3900))
        # Player health drops
        all_events += engine.process(GameState(buy_phase=False, health=80, credits=3900))
        # Health goes critical
        all_events += engine.process(GameState(buy_phase=False, health=20, credits=3900))
        # Player dies
        all_events += engine.process(GameState(player_dead=True))
        # Round ends
        all_events += engine.process(GameState(round_result=RoundResult.DEFEAT))

        event_types = {e.event_type for e in all_events}
        assert EventType.BUY_PHASE_STARTED in event_types
        assert EventType.BUY_PHASE_ENDED in event_types
        assert EventType.ROUND_STARTED in event_types
        assert EventType.HEALTH_CRITICAL in event_types
        assert EventType.PLAYER_DIED in event_types
        assert EventType.ROUND_ENDED in event_types

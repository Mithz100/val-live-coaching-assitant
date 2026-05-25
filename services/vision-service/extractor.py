"""
Frame extractor — combines ROI crops, preprocessing, OCR, and template matching
into a single normalised GameState per frame.

This is the "brain" of the vision pipeline.  Each method extracts one logical
group of fields and populates the GameState + ConfidenceMap.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

import numpy as np

import ocr as ocr_module
import preprocessing
import template_matcher as tm_module
from models import (
    ConfidenceMap,
    GameState,
    KillfeedEntry,
    OcrResult,
    RoundResult,
)
from rois import registry

logger = logging.getLogger(__name__)

# Templates that must be present in templates/ for binary detection
_TEMPLATE_NAMES = [
    "buy_phase",
    "victory",
    "defeat",
    "spike_planted",
    "spike_defused",
    "player_dead",
]

# Timer regex: optional leading digit(s), colon, two digits
_TIMER_RE = re.compile(r"(\d{1,2}:\d{2})")


class FrameExtractor:
    """
    Stateless extractor — same instance processes every frame.
    State (previous GameState for delta detection) lives in EventEngine.
    """

    def extract(self, frame: np.ndarray, frame_id: int) -> GameState:
        t0 = time.perf_counter()
        state = GameState(frame_id=frame_id)
        conf = ConfidenceMap()

        # ── Template-based binary detections ──────────────────────────────────
        template_results = tm_module.matcher.match_any(frame, _TEMPLATE_NAMES)

        buy_match = template_results.get("buy_phase")
        if buy_match and buy_match.detected:
            state.buy_phase = True
            conf.buy_phase = buy_match.confidence

        dead_match = template_results.get("player_dead")
        if dead_match and dead_match.detected:
            state.player_dead = True
            conf.player_dead = dead_match.confidence

        planted_match = template_results.get("spike_planted")
        if planted_match and planted_match.detected:
            state.spike_planted = True
            conf.spike_planted = planted_match.confidence

        defused_match = template_results.get("spike_defused")
        if defused_match and defused_match.detected:
            state.spike_defused = True
            conf.spike_defused = defused_match.confidence

        # ── Round result ──────────────────────────────────────────────────────
        victory_match = template_results.get("victory")
        defeat_match = template_results.get("defeat")
        if victory_match and victory_match.detected:
            state.round_result = RoundResult.VICTORY
            conf.round_result = victory_match.confidence
        elif defeat_match and defeat_match.detected:
            state.round_result = RoundResult.DEFEAT
            conf.round_result = defeat_match.confidence

        # ── OCR: health ───────────────────────────────────────────────────────
        hp, hp_conf = self._extract_numeric(frame, "health", 0, 150)
        state.health = hp
        conf.health = hp_conf

        # ── OCR: armor ───────────────────────────────────────────────────────
        armor, armor_conf = self._extract_numeric(frame, "armor", 0, 50)
        state.armor = armor
        conf.armor = armor_conf

        # ── OCR: credits ──────────────────────────────────────────────────────
        credits, credits_conf = self._extract_numeric(frame, "credits", 0, 9000)
        state.credits = credits
        conf.credits = credits_conf

        # ── OCR: ammo ─────────────────────────────────────────────────────────
        ammo_c, ammo_c_conf = self._extract_numeric(frame, "ammo_current", 0, 300)
        ammo_r, ammo_r_conf = self._extract_numeric(frame, "ammo_reserve", 0, 999)
        state.ammo_current = ammo_c
        state.ammo_reserve = ammo_r
        conf.ammo = (ammo_c_conf + ammo_r_conf) / 2.0

        # ── OCR: match timer ──────────────────────────────────────────────────
        timer, timer_conf = self._extract_timer(frame)
        state.match_timer = timer
        conf.match_timer = timer_conf

        # ── OCR: killfeed ─────────────────────────────────────────────────────
        killfeed, kf_conf = self._extract_killfeed(frame)
        state.killfeed = killfeed
        conf.killfeed = kf_conf

        # ── Fallback: buy phase from OCR banner ───────────────────────────────
        if not state.buy_phase:
            banner_text, banner_conf = self._extract_banner_text(frame)
            if banner_text and "buy" in banner_text.lower() and banner_conf > 0.5:
                state.buy_phase = True
                conf.buy_phase = banner_conf

        state.confidence = conf
        state.processing_ms = (time.perf_counter() - t0) * 1000.0
        return state

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _crop_and_preprocess(
        self, frame: np.ndarray, roi_name: str
    ) -> Optional[np.ndarray]:
        roi = registry.get(roi_name)
        if roi is None:
            return None
        crop = roi.crop(frame)
        if crop.size == 0:
            return None
        return preprocessing.preprocess(crop, roi_name)

    def _extract_numeric(
        self,
        frame: np.ndarray,
        roi_name: str,
        lo: int,
        hi: int,
    ) -> tuple[Optional[int], float]:
        processed = self._crop_and_preprocess(frame, roi_name)
        if processed is None:
            return None, 0.0

        results = ocr_module.ocr_region(processed, roi_name)
        for r in results:
            cleaned = "".join(c for c in r.text if c.isdigit())
            if not cleaned:
                continue
            value = int(cleaned)
            if lo <= value <= hi:
                return value, r.confidence
        return None, 0.0

    def _extract_timer(
        self, frame: np.ndarray
    ) -> tuple[Optional[str], float]:
        processed = self._crop_and_preprocess(frame, "match_timer")
        if processed is None:
            return None, 0.0

        results = ocr_module.ocr_region(processed, "match_timer")
        for r in results:
            match = _TIMER_RE.search(r.text)
            if match:
                return match.group(1), r.confidence
        return None, 0.0

    def _extract_killfeed(
        self, frame: np.ndarray
    ) -> tuple[list[KillfeedEntry], float]:
        processed = self._crop_and_preprocess(frame, "killfeed")
        if processed is None:
            return [], 0.0

        results = ocr_module.ocr_region(processed, "killfeed")
        entries: list[KillfeedEntry] = []
        total_conf = 0.0
        for r in results:
            if len(r.text.strip()) < 2:
                continue
            entries.append(
                KillfeedEntry(raw_text=r.text.strip(), confidence=r.confidence)
            )
            total_conf += r.confidence

        avg_conf = total_conf / len(entries) if entries else 0.0
        return entries, avg_conf

    def _extract_banner_text(
        self, frame: np.ndarray
    ) -> tuple[Optional[str], float]:
        """Fallback: OCR the buy phase / round result banner area."""
        processed = self._crop_and_preprocess(frame, "buy_phase_banner")
        if processed is None:
            return None, 0.0
        results = ocr_module.ocr_region(processed, "buy_phase_banner")
        if results:
            return results[0].text, results[0].confidence
        return None, 0.0


# Module-level singleton
extractor = FrameExtractor()

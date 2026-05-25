"""
Debug visualization overlay.

Draws ROI boxes, OCR values, template matches, confidence scores,
event stream, FPS, and latency onto a copy of the current frame.
Optionally displays it in a cv2 window and/or saves it to disk.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from config import settings
from models import GameEvent, GameState
from rois import registry
from template_matcher import matcher as tm_matcher

logger = logging.getLogger(__name__)

_FONT = cv2.FONT_HERSHEY_SIMPLEX
_GREEN = (0, 255, 0)
_RED = (0, 0, 255)
_YELLOW = (0, 255, 255)
_WHITE = (255, 255, 255)
_BG = (20, 20, 20)


class DebugOverlay:
    def __init__(self) -> None:
        self._event_log: deque[str] = deque(maxlen=8)
        self._last_save = 0.0
        if settings.debug_save_frames:
            Path(settings.debug_frame_dir).mkdir(parents=True, exist_ok=True)

    def render(
        self,
        frame: np.ndarray,
        state: GameState,
        events: list[GameEvent],
        fps: float,
    ) -> np.ndarray:
        out = frame.copy()

        # ── ROI boxes ─────────────────────────────────────────────────────────
        out = registry.draw_debug(out)

        # ── Template match boxes ──────────────────────────────────────────────
        all_matches = tm_matcher.match_any(
            frame,
            ["buy_phase", "victory", "defeat", "spike_planted", "spike_defused", "player_dead"],
        )
        out = tm_matcher.draw_debug(out, all_matches)

        # ── HUD values panel (top-left) ───────────────────────────────────────
        panel_lines = [
            f"FPS: {fps:.1f}",
            f"Frame: {state.frame_id}",
            f"Proc: {state.processing_ms:.1f}ms",
            "",
            f"HP:      {state.health}  ({state.confidence.health:.2f})",
            f"Armor:   {state.armor}  ({state.confidence.armor:.2f})",
            f"Credits: {state.credits}  ({state.confidence.credits:.2f})",
            f"Ammo:    {state.ammo_current}/{state.ammo_reserve}",
            f"Timer:   {state.match_timer}  ({state.confidence.match_timer:.2f})",
            "",
            f"Buy phase:  {state.buy_phase}",
            f"Dead:       {state.player_dead}",
            f"Planted:    {state.spike_planted}",
            f"Defused:    {state.spike_defused}",
            f"Result:     {state.round_result}",
        ]
        self._draw_panel(out, panel_lines, x=10, y=10)

        # ── Recent events panel (bottom-left) ─────────────────────────────────
        for ev in events:
            self._event_log.appendleft(
                f"[{ev.event_type.value}] conf={ev.confidence:.2f}"
            )
        self._draw_panel(out, list(self._event_log), x=10, y=out.shape[0] - 200, color=_YELLOW)

        # ── Killfeed OCR (top-right annotation) ───────────────────────────────
        for i, entry in enumerate(state.killfeed[:5]):
            cv2.putText(
                out,
                f"KF: {entry.raw_text[:40]}",
                (out.shape[1] - 460, 80 + i * 20),
                _FONT,
                0.4,
                _GREEN,
                1,
            )

        # ── Optional save ─────────────────────────────────────────────────────
        if settings.debug_save_frames:
            now = time.perf_counter()
            if now - self._last_save >= 5.0:
                path = Path(settings.debug_frame_dir) / f"debug_{state.frame_id:08d}.jpg"
                cv2.imwrite(str(path), out, [cv2.IMWRITE_JPEG_QUALITY, 80])
                self._last_save = now

        # ── Optional window display ───────────────────────────────────────────
        if settings.debug_show_window:
            display = cv2.resize(out, (1280, 720))
            cv2.imshow("Vision Debug", display)
            cv2.waitKey(1)

        return out

    @staticmethod
    def _draw_panel(
        image: np.ndarray,
        lines: list[str],
        x: int = 10,
        y: int = 10,
        color: tuple = _GREEN,
        font_scale: float = 0.45,
        thickness: int = 1,
        line_height: int = 18,
    ) -> None:
        for i, line in enumerate(lines):
            oy = y + i * line_height
            if oy > image.shape[0] - 5:
                break
            # Shadow for readability
            cv2.putText(image, line, (x + 1, oy + 1), _FONT, font_scale, _BG, thickness + 1)
            cv2.putText(image, line, (x, oy), _FONT, font_scale, color, thickness)


overlay = DebugOverlay()

"""
Main vision pipeline loop.

Responsibilities:
  1. Pull the latest frame from FrameIngester at the configured analysis FPS.
  2. Pass it through FrameExtractor → GameState.
  3. Pass GameState through EventEngine → list[GameEvent].
  4. Broadcast state + events to WebSocket clients.
  5. Optionally render debug overlay.
  6. Log benchmark stats.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from config import settings
from debug_overlay import overlay
from event_engine import EventEngine
from extractor import extractor
from ingestion import FrameIngester
from models import GameState, PipelineStats

if TYPE_CHECKING:
    from server import BroadcastManager

logger = logging.getLogger(__name__)


class VisionPipeline:
    def __init__(
        self,
        ingester: FrameIngester,
        broadcaster: "BroadcastManager",
    ) -> None:
        self._ingester = ingester
        self._broadcaster = broadcaster
        self._engine = EventEngine()
        self.stats = PipelineStats()
        self._target_interval = 1.0 / settings.analysis_fps
        self._last_benchmark = time.perf_counter()

    async def run(self) -> None:
        logger.info("Vision pipeline started at %.1f FPS", settings.analysis_fps)

        while True:
            loop_start = time.perf_counter()

            frame_obj = await self._ingester.get_latest()
            self.stats.frames_received = self._ingester.stats.frames_received

            if frame_obj is None:
                await asyncio.sleep(0.05)
                continue

            self.stats.frames_processed += 1

            # ── Extract ───────────────────────────────────────────────────────
            state: GameState = extractor.extract(frame_obj.image, frame_obj.frame_id)

            # ── Events ────────────────────────────────────────────────────────
            events = self._engine.process(state)
            self.stats.events_emitted += len(events)

            # ── Broadcast ─────────────────────────────────────────────────────
            await self._broadcaster.broadcast_state(state)
            for event in events:
                await self._broadcaster.broadcast_event(event)

            # ── Debug overlay ─────────────────────────────────────────────────
            if settings.debug_mode:
                overlay.render(frame_obj.image, state, events, self._ingester.stats.fps)

            # ── Benchmark log ─────────────────────────────────────────────────
            if settings.benchmark_mode:
                now = time.perf_counter()
                if now - self._last_benchmark >= settings.benchmark_log_interval:
                    self._log_benchmark(state)
                    self._last_benchmark = now

            # ── Pace to target FPS ────────────────────────────────────────────
            elapsed = time.perf_counter() - loop_start
            sleep_for = self._target_interval - elapsed
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    def _log_benchmark(self, state: GameState) -> None:
        s = self.stats
        logger.info(
            "[BENCH] proc=%d drop=%d events=%d proc_ms=%.1f in_fps=%.1f",
            s.frames_processed,
            s.frames_dropped,
            s.events_emitted,
            state.processing_ms,
            self._ingester.stats.fps,
        )

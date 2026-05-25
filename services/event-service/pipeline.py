"""
Main event-service pipeline loop.

Per raw event:
  1. Update round lifecycle state machine.
  2. Run semantic engine → SemanticEvents.
  3. Persist raw + semantic events.
  4. On ROUND_ENDED: generate summary, update profile, detect patterns.
  5. Broadcast everything to API clients.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING

from config import settings
from consumer import EventConsumer
from memory import db_store
from models.schemas import (
    RawEvent,
    RawEventType,
    SemanticEvent,
)
from pattern_detector import PatternDetector
from player_profile import PlayerProfileManager
from round_lifecycle import RoundLifecycleEngine
from round_summary import generate as generate_summary
from semantic_engine import SemanticEngine

if TYPE_CHECKING:
    from server import BroadcastManager

logger = logging.getLogger(__name__)


class EventPipeline:
    def __init__(
        self,
        consumer: EventConsumer,
        broadcaster: "BroadcastManager",
    ) -> None:
        self._consumer = consumer
        self._broadcaster = broadcaster
        self._lifecycle = RoundLifecycleEngine()
        self._semantic = SemanticEngine(consumer)
        self._pattern = PatternDetector()
        self.session_id = str(uuid.uuid4())[:8]

        self._profile_mgr = PlayerProfileManager(self.session_id)

        # Within-round accumulators
        self._round_semantic_events: list[SemanticEvent] = []
        self._round_raw_count = 0
        self._last_benchmark = time.perf_counter()

    async def run(self) -> None:
        await db_store.upsert_match(self.session_id)
        logger.info("Event pipeline started (session=%s)", self.session_id)

        while True:
            try:
                event: RawEvent = await asyncio.wait_for(
                    self._consumer.event_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                await self._check_lifecycle_timeout()
                continue

            await self._process(event)

            if settings.benchmark_mode:
                now = time.perf_counter()
                if now - self._last_benchmark >= settings.benchmark_log_interval_s:
                    self._log_benchmark()
                    self._last_benchmark = now

    async def _process(self, event: RawEvent) -> None:
        t0 = time.perf_counter()

        # 1. Update lifecycle
        self._lifecycle.process_event(event.event_type, event.payload)
        round_state = self._lifecycle.state
        self._round_raw_count += 1

        # 2. Persist raw event (fire-and-forget)
        asyncio.create_task(
            db_store.save_raw_event(self.session_id, round_state.round_number, event)
        )

        # 3. Semantic analysis
        semantic_events = self._semantic.process(
            event, round_state, self._profile_mgr.profile
        )
        self._round_semantic_events.extend(semantic_events)

        # 4. Record semantic events in lifecycle + persist
        for sem_ev in semantic_events:
            self._lifecycle.record_semantic_event(sem_ev.event_type.value)
            asyncio.create_task(
                db_store.save_semantic_event(
                    self.session_id, round_state.round_number, sem_ev
                )
            )

        # 5. Broadcast
        await self._broadcaster.broadcast_semantic_events(semantic_events)
        await self._broadcaster.broadcast_round_state(round_state)

        # 6. On round end — close out the round
        if event.event_type == RawEventType.ROUND_ENDED:
            await self._close_round()

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if elapsed_ms > 100:
            logger.warning("Pipeline iteration slow: %.1fms", elapsed_ms)

    async def _close_round(self) -> None:
        rs = self._lifecycle.state
        sem_events = list(self._round_semantic_events)
        raw_count = self._round_raw_count

        gs = self._consumer.latest_game_state
        credits_remaining = gs.get("credits")

        # Generate summary
        summary = generate_summary(
            rs,
            sem_events,
            raw_count,
            credits_remaining=credits_remaining,
        )

        # Update pattern detector
        self._pattern.add_round(summary, [e.event_type.value for e in sem_events])
        patterns = self._pattern.detect()

        # Update player profile
        self._profile_mgr.update_from_round(summary, sem_events)
        self._profile_mgr.update_active_patterns([p.pattern_type for p in patterns])

        # Persist everything
        asyncio.create_task(db_store.save_round_summary(self.session_id, summary))
        asyncio.create_task(db_store.increment_match_rounds(self.session_id))
        asyncio.create_task(self._profile_mgr.persist())
        for p in patterns:
            asyncio.create_task(db_store.save_pattern(self.session_id, p))

        # Broadcast
        await self._broadcaster.broadcast_round_summary(summary)
        await self._broadcaster.broadcast_patterns(patterns)
        await self._broadcaster.broadcast_player_profile(self._profile_mgr.profile)

        # Reset accumulators
        self._round_semantic_events.clear()
        self._round_raw_count = 0

        logger.info(
            "Round %d closed | mistakes=%d patterns=%d",
            rs.round_number,
            len(summary.major_mistakes),
            len(patterns),
        )

    async def _check_lifecycle_timeout(self) -> None:
        """Called when the event queue is idle — lifecycle engine handles timeouts."""
        pass

    def _log_benchmark(self) -> None:
        p = self._profile_mgr.profile
        logger.info(
            "[BENCH] session=%s rounds=%d survival=%.2f aggression=%.2f force_buys=%d",
            self.session_id,
            p.rounds_tracked,
            p.avg_survival_rate,
            p.avg_aggression_score,
            p.total_force_buys,
        )

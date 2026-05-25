"""
WebSocket event consumer.

Connects to vision-service /events and /game-state, ingests both streams,
deduplicates events within a time window, and exposes them via asyncio queues.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Optional

import websockets
from websockets.exceptions import ConnectionClosed

from config import settings
from models.schemas import RawEvent

logger = logging.getLogger(__name__)


class EventConsumer:
    """
    Maintains two WebSocket connections (events + game-state) and
    publishes to internal queues consumed by the pipeline.
    """

    def __init__(self) -> None:
        self.event_queue: asyncio.Queue[RawEvent] = asyncio.Queue(maxsize=128)
        # Latest game state snapshot (credits, health, etc.)
        self.latest_game_state: dict = {}
        # Dedup registry: event_type → last seen timestamp
        self._seen: dict[str, float] = {}
        # Short recent history for context
        self._recent: deque[RawEvent] = deque(maxlen=20)
        self._running = False

    # ── Public ────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._running = True
        await asyncio.gather(
            self._run_events_stream(),
            self._run_state_stream(),
        )

    async def stop(self) -> None:
        self._running = False

    def recent_events(self, n: int = 10) -> list[RawEvent]:
        return list(self._recent)[-n:]

    # ── Event stream ──────────────────────────────────────────────────────────

    async def _run_events_stream(self) -> None:
        while self._running:
            try:
                await self._connect_events()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Events stream disconnected — reconnecting in %.1fs",
                    settings.consumer_reconnect_delay_s,
                )
                await asyncio.sleep(settings.consumer_reconnect_delay_s)

    async def _connect_events(self) -> None:
        url = settings.vision_events_url
        logger.info("Connecting to events stream: %s", url)
        async with websockets.connect(url, ping_interval=10, ping_timeout=5) as ws:
            logger.info("Events stream connected")
            async for message in ws:
                if not self._running:
                    break
                try:
                    data = json.loads(message)
                    event = RawEvent(**data)
                except Exception:
                    logger.debug("Malformed event message", exc_info=True)
                    continue

                if self._is_duplicate(event):
                    continue

                self._record(event)
                try:
                    self.event_queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.debug("Event queue full — dropping %s", event.event_type)

    def _is_duplicate(self, event: RawEvent) -> bool:
        key = event.event_type
        last = self._seen.get(key, 0.0)
        if time.time() - last < settings.event_dedup_window_s:
            return True
        return False

    def _record(self, event: RawEvent) -> None:
        self._seen[event.event_type] = time.time()
        self._recent.append(event)

    # ── Game state stream ─────────────────────────────────────────────────────

    async def _run_state_stream(self) -> None:
        while self._running:
            try:
                await self._connect_state()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "State stream disconnected — reconnecting in %.1fs",
                    settings.consumer_reconnect_delay_s,
                )
                await asyncio.sleep(settings.consumer_reconnect_delay_s)

    async def _connect_state(self) -> None:
        url = settings.vision_state_url
        logger.info("Connecting to game-state stream: %s", url)
        async with websockets.connect(url, ping_interval=10, ping_timeout=5) as ws:
            logger.info("Game-state stream connected")
            async for message in ws:
                if not self._running:
                    break
                try:
                    self.latest_game_state = json.loads(message)
                except Exception:
                    pass

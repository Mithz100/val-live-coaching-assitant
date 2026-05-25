"""
WebSocket frame ingestion from capture-service.

Maintains a single-slot "latest frame" cache so the vision pipeline always
works on the most recent frame without queue back-pressure from slow consumers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
import websockets
from websockets.exceptions import ConnectionClosed

from config import settings

logger = logging.getLogger(__name__)

_RECONNECT_DELAY_S = 2.0


@dataclass
class IngestedFrame:
    frame_id: int
    captured_at: float       # remote timestamp from capture-service
    received_at: float       # local time.perf_counter() when we got it
    image: np.ndarray        # BGR HxWx3

    @property
    def network_latency_ms(self) -> float:
        return (self.received_at - self.captured_at) * 1000.0


@dataclass
class IngestionStats:
    frames_received: int = 0
    frames_dropped: int = 0
    fps: float = 0.0
    _window_start: float = field(default_factory=time.perf_counter, repr=False)
    _window_count: int = field(default=0, repr=False)

    def record(self) -> None:
        self.frames_received += 1
        self._window_count += 1
        elapsed = time.perf_counter() - self._window_start
        if elapsed >= 1.0:
            self.fps = self._window_count / elapsed
            self._window_count = 0
            self._window_start = time.perf_counter()

    def record_drop(self) -> None:
        self.frames_dropped += 1


class FrameIngester:
    """
    Connects to the capture-service WebSocket and maintains a
    latest-frame slot.  Call `get_latest()` from the vision pipeline.
    """

    def __init__(self) -> None:
        self._latest: Optional[IngestedFrame] = None
        self._lock = asyncio.Lock()
        self._running = False
        self.stats = IngestionStats()

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_latest(self) -> Optional[IngestedFrame]:
        async with self._lock:
            return self._latest

    async def run(self) -> None:
        """Run forever, reconnecting on disconnects."""
        self._running = True
        while self._running:
            try:
                await self._connect_and_receive()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Ingestion disconnected — reconnecting in %.1fs", _RECONNECT_DELAY_S
                )
                await asyncio.sleep(_RECONNECT_DELAY_S)

    async def stop(self) -> None:
        self._running = False

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _connect_and_receive(self) -> None:
        url = settings.capture_ws_url
        logger.info("Connecting to capture service at %s", url)

        async with websockets.connect(
            url,
            max_size=20 * 1024 * 1024,   # 20 MB — safe for 1080p JPEG
            ping_interval=10,
            ping_timeout=5,
        ) as ws:
            logger.info("Ingestion connected")
            async for message in ws:
                if not isinstance(message, bytes):
                    continue
                received_at = time.perf_counter()
                frame = self._decode(message, received_at)
                if frame is None:
                    continue
                self.stats.record()
                async with self._lock:
                    if self._latest is not None:
                        self.stats.record_drop()  # previous frame never consumed
                    self._latest = frame

    @staticmethod
    def _decode(message: bytes, received_at: float) -> Optional[IngestedFrame]:
        try:
            meta_len = struct.unpack_from("<I", message, 0)[0]
            meta = json.loads(message[4 : 4 + meta_len])
            jpeg = message[4 + meta_len :]
            arr = np.frombuffer(jpeg, dtype=np.uint8)
            image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if image is None:
                logger.debug("cv2.imdecode returned None")
                return None
            return IngestedFrame(
                frame_id=meta["frame_id"],
                captured_at=meta["timestamp"],
                received_at=received_at,
                image=image,
            )
        except Exception:
            logger.debug("Failed to decode incoming frame", exc_info=True)
            return None

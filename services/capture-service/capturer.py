"""
Core screen-capture loop using dxcam.

Runs in a dedicated thread so it never blocks the asyncio event loop.
Frames are placed into an asyncio.Queue for downstream consumers.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import dxcam
import numpy as np

from config import settings
from models import FrameStats, RawFrame
from window_finder import find_game_window

logger = logging.getLogger(__name__)


class ScreenCapturer:
    """
    Manages a dxcam capture session and feeds frames to an asyncio queue.

    Usage
    -----
    capturer = ScreenCapturer(loop, queue)
    capturer.start()
    ...
    capturer.stop()
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[RawFrame],
    ) -> None:
        self._loop = loop
        self._queue = queue
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._camera: Optional[dxcam.DXCamera] = None
        self._frame_id = 0
        self.stats = FrameStats()

        if settings.debug_mode:
            Path(settings.frame_save_dir).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            logger.warning("Capturer already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._capture_loop, name="capture-thread", daemon=True
        )
        self._thread.start()
        logger.info("Capture thread started")

    def stop(self) -> None:
        logger.info("Stopping capture thread…")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        if self._camera:
            self._camera.stop()
            self._camera = None
        logger.info("Capture thread stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_region(self) -> Optional[tuple[int, int, int, int]]:
        rect = find_game_window(settings.game_window_title)
        if rect:
            left, top, right, bottom = rect
            # Clamp to configured resolution
            right = min(right, left + settings.capture_width)
            bottom = min(bottom, top + settings.capture_height)
            return left, top, right, bottom
        logger.warning(
            "Valorant window not found — falling back to full-screen capture region "
            "(0, 0, %d, %d)",
            settings.capture_width,
            settings.capture_height,
        )
        return 0, 0, settings.capture_width, settings.capture_height

    def _capture_loop(self) -> None:
        region = self._resolve_region()
        target_interval = 1.0 / settings.target_fps
        last_benchmark_log = time.perf_counter()
        last_debug_save = time.perf_counter()

        try:
            self._camera = dxcam.create(output_color="BGR")
            self._camera.start(
                region=region,
                target_fps=settings.target_fps,
                video_mode=True,
            )
            logger.info(
                "dxcam started | region=%s | target=%d FPS", region, settings.target_fps
            )

            while not self._stop_event.is_set():
                t0 = time.perf_counter()
                frame = self._camera.get_latest_frame()

                if frame is None:
                    # dxcam returned nothing yet; spin briefly
                    time.sleep(0.001)
                    continue

                captured_at = time.perf_counter()
                latency_ms = (captured_at - t0) * 1000.0
                self.stats.record_capture(latency_ms)
                self._frame_id += 1

                raw = RawFrame(
                    frame_id=self._frame_id,
                    captured_at=captured_at,
                    image=frame,
                )

                # Enqueue without blocking the capture thread
                try:
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, raw)
                except asyncio.QueueFull:
                    self.stats.record_drop()
                    logger.debug("Queue full — frame %d dropped", self._frame_id)

                # Optional debug frame saving
                if settings.debug_mode:
                    now = time.perf_counter()
                    if now - last_debug_save >= settings.frame_save_interval:
                        self._save_debug_frame(raw)
                        last_debug_save = now

                # Benchmark logging
                if settings.benchmark_mode:
                    now = time.perf_counter()
                    if now - last_benchmark_log >= settings.benchmark_log_interval:
                        self._log_benchmark()
                        last_benchmark_log = now

                # Pace ourselves if we're running faster than target
                elapsed = time.perf_counter() - t0
                sleep_for = target_interval - elapsed
                if sleep_for > 0:
                    time.sleep(sleep_for)

        except Exception:
            logger.exception("Fatal error in capture loop")
        finally:
            if self._camera:
                self._camera.stop()
                self._camera = None

    def _save_debug_frame(self, raw: RawFrame) -> None:
        path = Path(settings.frame_save_dir) / f"frame_{raw.frame_id:08d}.jpg"
        annotated = raw.image.copy()
        cv2.putText(
            annotated,
            f"FPS:{self.stats.fps_current:.1f} ID:{raw.frame_id}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
        )
        cv2.imwrite(str(path), annotated, [cv2.IMWRITE_JPEG_QUALITY, 90])
        logger.debug("Saved debug frame → %s", path)

    def _log_benchmark(self) -> None:
        s = self.stats
        logger.info(
            "[BENCH] fps_now=%.1f fps_avg=%.1f total=%d dropped=%d latency_ms=%.1f",
            s.fps_current,
            s.fps_avg,
            s.total_frames,
            s.dropped_frames,
            s.latency_ms_last,
        )

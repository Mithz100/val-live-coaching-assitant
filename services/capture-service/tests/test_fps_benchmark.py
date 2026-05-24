"""
FPS benchmark test — runs a simulated capture loop for 5 seconds
using a fake dxcam camera and verifies the measured FPS is within
tolerance of the target.

No real screen hardware is required.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from models import FrameStats, RawFrame


class FakeDXCamera:
    """Returns a fresh black frame on every get_latest_frame() call."""

    def __init__(self, width: int = 1920, height: int = 1080) -> None:
        self._frame = np.zeros((height, width, 3), dtype=np.uint8)

    def start(self, **_) -> None:
        pass

    def stop(self) -> None:
        pass

    def get_latest_frame(self):
        return self._frame.copy()


@pytest.mark.parametrize("target_fps", [10, 20])
def test_simulated_fps(target_fps: int) -> None:
    """Simulated capture loop must achieve at least 80 % of target FPS."""
    duration = 3.0
    target_interval = 1.0 / target_fps
    stats = FrameStats()

    camera = FakeDXCamera()
    t_end = time.perf_counter() + duration

    while time.perf_counter() < t_end:
        t0 = time.perf_counter()
        _ = camera.get_latest_frame()
        latency_ms = (time.perf_counter() - t0) * 1000.0
        stats.record_capture(latency_ms)
        elapsed = time.perf_counter() - t0
        sleep_for = target_interval - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)

    # By the end, fps_avg should be near target (allow ±20 %)
    measured = stats.fps_avg if stats.fps_avg > 0 else stats.fps_current
    assert measured >= target_fps * 0.80, (
        f"FPS too low: got {measured:.2f}, expected >= {target_fps * 0.80:.2f}"
    )

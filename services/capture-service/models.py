from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np


@dataclass(slots=True)
class RawFrame:
    """A single captured frame plus its metadata."""

    frame_id: int
    captured_at: float  # time.perf_counter() timestamp
    image: np.ndarray  # BGR, HxWx3 uint8

    @property
    def age_ms(self) -> float:
        return (time.perf_counter() - self.captured_at) * 1000.0


@dataclass
class FrameStats:
    """Running capture statistics."""

    total_frames: int = 0
    dropped_frames: int = 0
    fps_current: float = 0.0
    fps_avg: float = 0.0
    latency_ms_last: float = 0.0
    _window_start: float = field(default_factory=time.perf_counter, repr=False)
    _window_count: int = field(default=0, repr=False)

    def record_capture(self, latency_ms: float) -> None:
        self.total_frames += 1
        self._window_count += 1
        self.latency_ms_last = latency_ms
        elapsed = time.perf_counter() - self._window_start
        if elapsed >= 1.0:
            self.fps_current = self._window_count / elapsed
            self.fps_avg = (
                self.fps_avg * 0.9 + self.fps_current * 0.1
                if self.fps_avg > 0
                else self.fps_current
            )
            self._window_count = 0
            self._window_start = time.perf_counter()

    def record_drop(self) -> None:
        self.dropped_frames += 1

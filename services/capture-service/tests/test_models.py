"""Unit tests for models.py — no hardware required."""

import time

import numpy as np
import pytest

from models import FrameStats, RawFrame


def _dummy_frame(frame_id: int = 1) -> RawFrame:
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    return RawFrame(frame_id=frame_id, captured_at=time.perf_counter(), image=img)


class TestRawFrame:
    def test_age_ms_positive(self) -> None:
        f = _dummy_frame()
        time.sleep(0.01)
        assert f.age_ms >= 10.0

    def test_frame_id(self) -> None:
        f = _dummy_frame(frame_id=42)
        assert f.frame_id == 42

    def test_image_shape(self) -> None:
        f = _dummy_frame()
        assert f.image.shape == (1080, 1920, 3)


class TestFrameStats:
    def test_initial_state(self) -> None:
        s = FrameStats()
        assert s.total_frames == 0
        assert s.dropped_frames == 0
        assert s.fps_current == 0.0

    def test_record_capture_increments(self) -> None:
        s = FrameStats()
        s.record_capture(5.0)
        assert s.total_frames == 1
        assert s.latency_ms_last == 5.0

    def test_record_drop(self) -> None:
        s = FrameStats()
        s.record_drop()
        s.record_drop()
        assert s.dropped_frames == 2

    def test_fps_computed_after_1s(self) -> None:
        import time
        from unittest.mock import patch

        s = FrameStats()
        # Simulate 10 frames arriving over 1.1 seconds
        fake_start = 0.0
        with patch("time.perf_counter", return_value=fake_start):
            s._window_start = fake_start

        with patch("time.perf_counter", return_value=fake_start + 1.1):
            s._window_count = 10
            s.record_capture(3.0)

        assert s.fps_current == pytest.approx(10 / 1.1, rel=0.05)

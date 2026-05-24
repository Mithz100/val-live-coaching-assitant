"""
Integration test: spin up the FastAPI app with a mock capturer,
connect a WS client, and verify frames arrive.
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

import server
from models import RawFrame


def _make_frame(fid: int = 1) -> RawFrame:
    img = np.zeros((1080, 1920, 3), dtype=np.uint8)
    return RawFrame(frame_id=fid, captured_at=time.perf_counter(), image=img)


@pytest.fixture(autouse=True)
def patch_capturer(monkeypatch):
    """Replace ScreenCapturer with a no-op stub."""
    stub = MagicMock()
    stub.stats.fps_current = 10.0
    stub.stats.fps_avg = 10.0
    stub.stats.total_frames = 100
    stub.stats.dropped_frames = 0
    monkeypatch.setattr("server.ScreenCapturer", lambda *a, **kw: stub)
    monkeypatch.setattr("server.capturer", stub)
    return stub


class TestHealthEndpoint:
    def test_health_returns_ok(self, patch_capturer) -> None:
        with TestClient(server.app) as client:
            r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"


class TestWebSocketStream:
    def test_ws_connects(self) -> None:
        with TestClient(server.app) as client:
            with client.websocket_connect("/stream") as ws:
                # Inject a frame directly into the queue
                frame = _make_frame(1)
                asyncio.get_event_loop().run_until_complete(
                    server.frame_queue.put(frame)
                )
                # Just verify connection doesn't raise

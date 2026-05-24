"""
FastAPI application + WebSocket frame-streaming endpoint.

Architecture
------------
  ScreenCapturer (thread)
       │  asyncio.Queue[RawFrame]
       ▼
  broadcast_task (coroutine)
       │  pushes encoded frames to each ConnectionManager client
       ▼
  WebSocket clients
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from capturer import ScreenCapturer
from config import settings
from encoder import encode_jpeg
from models import RawFrame

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.append(ws)
        logger.info("Client connected — total=%d", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.remove(ws)
        logger.info("Client disconnected — total=%d", len(self._clients))

    async def broadcast_bytes(self, data: bytes) -> None:
        dead: list[WebSocket] = []
        for ws in self._clients:
            try:
                await ws.send_bytes(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in self._clients:
                self._clients.remove(ws)

    @property
    def client_count(self) -> int:
        return len(self._clients)


manager = ConnectionManager()
frame_queue: asyncio.Queue[RawFrame] = asyncio.Queue(
    maxsize=settings.max_queue_size
)
capturer: ScreenCapturer | None = None


# ---------------------------------------------------------------------------
# Background broadcast task
# ---------------------------------------------------------------------------


async def _broadcast_loop() -> None:
    """Pull frames from the queue and push them to all WS clients."""
    while True:
        try:
            raw: RawFrame = await asyncio.wait_for(frame_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        if manager.client_count == 0:
            frame_queue.task_done()
            continue

        try:
            jpeg = encode_jpeg(raw.image)
        except Exception:
            logger.exception("JPEG encode failed for frame %d", raw.frame_id)
            frame_queue.task_done()
            continue

        # Build a tiny metadata header (newline-delimited JSON + raw bytes)
        meta = json.dumps(
            {
                "frame_id": raw.frame_id,
                "timestamp": raw.captured_at,
                "fps": round(capturer.stats.fps_current if capturer else 0.0, 2),
                "age_ms": round(raw.age_ms, 2),
            }
        ).encode()

        # Protocol: [4-byte meta length LE][meta JSON][JPEG bytes]
        header = len(meta).to_bytes(4, "little")
        payload = header + meta + jpeg

        await manager.broadcast_bytes(payload)
        frame_queue.task_done()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global capturer

    loop = asyncio.get_running_loop()
    capturer = ScreenCapturer(loop, frame_queue)
    capturer.start()

    broadcast_task = asyncio.create_task(_broadcast_loop(), name="broadcast")
    logger.info(
        "Capture service ready — ws://%s:%d/stream",
        settings.ws_host,
        settings.ws_port,
    )

    try:
        yield
    finally:
        broadcast_task.cancel()
        try:
            await broadcast_task
        except asyncio.CancelledError:
            pass
        capturer.stop()
        logger.info("Capture service shut down cleanly")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Valorant Capture Service", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    if capturer is None:
        return {"status": "starting"}
    s = capturer.stats
    return {
        "status": "ok",
        "fps_current": round(s.fps_current, 2),
        "fps_avg": round(s.fps_avg, 2),
        "total_frames": s.total_frames,
        "dropped_frames": s.dropped_frames,
        "clients": manager.client_count,
    }


@app.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        # Keep the connection alive — actual frames arrive via broadcast
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG if settings.debug_mode else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    uvicorn.run(
        "server:app",
        host=settings.ws_host,
        port=settings.ws_port,
        log_level="debug" if settings.debug_mode else "info",
    )

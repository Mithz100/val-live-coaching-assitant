"""
FastAPI application exposing:

  GET  /health              → service status + stats
  WS   /game-state          → streams GameState JSON every analysed frame
  WS   /events              → streams GameEvent JSON only when events fire

Both WebSocket endpoints support multiple simultaneous clients.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from config import settings
from ingestion import FrameIngester
from models import GameEvent, GameState, PipelineStats
from pipeline import VisionPipeline

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Broadcast manager
# ─────────────────────────────────────────────────────────────────────────────

class BroadcastManager:
    def __init__(self) -> None:
        self._state_clients: list[WebSocket] = []
        self._event_clients: list[WebSocket] = []

    # ── Registration ──────────────────────────────────────────────────────────

    async def connect_state(self, ws: WebSocket) -> None:
        await ws.accept()
        self._state_clients.append(ws)
        logger.info("game-state client connected (total=%d)", len(self._state_clients))

    def disconnect_state(self, ws: WebSocket) -> None:
        if ws in self._state_clients:
            self._state_clients.remove(ws)
        logger.info("game-state client disconnected (total=%d)", len(self._state_clients))

    async def connect_event(self, ws: WebSocket) -> None:
        await ws.accept()
        self._event_clients.append(ws)
        logger.info("events client connected (total=%d)", len(self._event_clients))

    def disconnect_event(self, ws: WebSocket) -> None:
        if ws in self._event_clients:
            self._event_clients.remove(ws)
        logger.info("events client disconnected (total=%d)", len(self._event_clients))

    # ── Broadcast ─────────────────────────────────────────────────────────────

    async def broadcast_state(self, state: GameState) -> None:
        await self._send_all(self._state_clients, state.to_json())

    async def broadcast_event(self, event: GameEvent) -> None:
        await self._send_all(self._event_clients, event.to_json())

    @staticmethod
    async def _send_all(clients: list[WebSocket], payload: dict) -> None:
        if not clients:
            return
        dead: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in clients:
                clients.remove(ws)

    @property
    def state_client_count(self) -> int:
        return len(self._state_clients)

    @property
    def event_client_count(self) -> int:
        return len(self._event_clients)


# ─────────────────────────────────────────────────────────────────────────────
# Globals
# ─────────────────────────────────────────────────────────────────────────────

broadcaster = BroadcastManager()
ingester = FrameIngester()
pipeline: VisionPipeline | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global pipeline

    pipeline = VisionPipeline(ingester, broadcaster)

    ingest_task = asyncio.create_task(ingester.run(), name="ingestion")
    pipeline_task = asyncio.create_task(pipeline.run(), name="pipeline")

    logger.info(
        "Vision service ready — ws://%s:%d/game-state | ws://%s:%d/events",
        settings.ws_host,
        settings.ws_port,
        settings.ws_host,
        settings.ws_port,
    )

    try:
        yield
    finally:
        ingest_task.cancel()
        pipeline_task.cancel()
        await asyncio.gather(ingest_task, pipeline_task, return_exceptions=True)
        logger.info("Vision service shut down cleanly")


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Valorant Vision Service", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    stats = pipeline.stats if pipeline else PipelineStats()
    return {
        "status": "ok",
        "frames_received": stats.frames_received,
        "frames_processed": stats.frames_processed,
        "events_emitted": stats.events_emitted,
        "state_clients": broadcaster.state_client_count,
        "event_clients": broadcaster.event_client_count,
        "ingestion_fps": round(ingester.stats.fps, 2),
    }


@app.websocket("/game-state")
async def ws_game_state(ws: WebSocket) -> None:
    await broadcaster.connect_state(ws)
    try:
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.disconnect_state(ws)


@app.websocket("/events")
async def ws_events(ws: WebSocket) -> None:
    await broadcaster.connect_event(ws)
    try:
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.disconnect_event(ws)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

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

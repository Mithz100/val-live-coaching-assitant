"""
FastAPI application for the event service.

WebSocket endpoints (port 8200):
  /semantic-events   → SemanticEvent stream
  /round-state       → RoundState on every raw event
  /round-summary     → RoundSummary at end of each round
  /patterns          → DetectedPattern list after each round
  /profile           → PlayerProfile snapshot after each round

REST endpoints:
  GET /health
  GET /round/current
  GET /round/recent
  GET /player/profile
  GET /player/mistakes
  GET /player/tendencies
  GET /analytics/economy
  GET /analytics/aggression
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import uvicorn
from fastapi import FastAPI, WebSocket

from api import routes as rest_routes
from api import ws_routes
from config import settings
from consumer import EventConsumer
from models.db import create_tables
from models.schemas import (
    DetectedPattern,
    PlayerProfile,
    RoundState,
    RoundSummary,
    SemanticEvent,
)
from pipeline import EventPipeline

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Broadcast manager
# ─────────────────────────────────────────────────────────────────────────────

class BroadcastManager:
    CHANNELS = ("semantic", "round_state", "summary", "patterns", "profile")

    def __init__(self) -> None:
        self._clients: dict[str, list[WebSocket]] = {ch: [] for ch in self.CHANNELS}

    async def connect(self, ws: WebSocket, channel: str) -> None:
        await ws.accept()
        self._clients[channel].append(ws)
        logger.info("%s client connected (total=%d)", channel, len(self._clients[channel]))

    def disconnect(self, ws: WebSocket, channel: str) -> None:
        if ws in self._clients[channel]:
            self._clients[channel].remove(ws)

    async def _broadcast(self, channel: str, payload: Any) -> None:
        clients = self._clients.get(channel, [])
        if not clients:
            return
        dead: list[WebSocket] = []
        for ws in clients:
            try:
                if isinstance(payload, dict):
                    await ws.send_json(payload)
                else:
                    await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in clients:
                clients.remove(ws)

    async def broadcast_semantic_events(self, events: list[SemanticEvent]) -> None:
        for ev in events:
            await self._broadcast("semantic", ev.to_dict())

    async def broadcast_round_state(self, state: RoundState) -> None:
        await self._broadcast("round_state", state.model_dump(mode="json"))

    async def broadcast_round_summary(self, summary: RoundSummary) -> None:
        await self._broadcast("summary", summary.to_dict())

    async def broadcast_patterns(self, patterns: list[DetectedPattern]) -> None:
        if patterns:
            await self._broadcast("patterns", [p.to_dict() for p in patterns])

    async def broadcast_player_profile(self, profile: PlayerProfile) -> None:
        await self._broadcast("profile", profile.to_dict())


# ─────────────────────────────────────────────────────────────────────────────
# Globals
# ─────────────────────────────────────────────────────────────────────────────

broadcaster = BroadcastManager()
consumer = EventConsumer()
pipeline: EventPipeline | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global pipeline

    await create_tables()
    pipeline = EventPipeline(consumer, broadcaster)

    rest_routes.set_pipeline(pipeline)
    ws_routes.set_broadcaster(broadcaster)

    consumer_task  = asyncio.create_task(consumer.run(),   name="consumer")
    pipeline_task  = asyncio.create_task(pipeline.run(),   name="pipeline")

    logger.info(
        "Event service ready on ws://%s:%d", settings.ws_host, settings.ws_port
    )

    try:
        yield
    finally:
        consumer_task.cancel()
        pipeline_task.cancel()
        await asyncio.gather(consumer_task, pipeline_task, return_exceptions=True)
        logger.info("Event service shut down cleanly")


# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Valorant Event Service", lifespan=lifespan)
app.include_router(rest_routes.router)
app.include_router(ws_routes.router)


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

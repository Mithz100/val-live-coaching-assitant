"""WebSocket routes for real-time event streaming."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()

# BroadcastManager is injected after construction
_broadcaster = None


def set_broadcaster(b) -> None:
    global _broadcaster
    _broadcaster = b


@router.websocket("/semantic-events")
async def ws_semantic_events(ws: WebSocket) -> None:
    await _broadcaster.connect(ws, "semantic")
    try:
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        pass
    finally:
        _broadcaster.disconnect(ws, "semantic")


@router.websocket("/round-state")
async def ws_round_state(ws: WebSocket) -> None:
    await _broadcaster.connect(ws, "round_state")
    try:
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        pass
    finally:
        _broadcaster.disconnect(ws, "round_state")


@router.websocket("/round-summary")
async def ws_round_summary(ws: WebSocket) -> None:
    await _broadcaster.connect(ws, "summary")
    try:
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        pass
    finally:
        _broadcaster.disconnect(ws, "summary")


@router.websocket("/patterns")
async def ws_patterns(ws: WebSocket) -> None:
    await _broadcaster.connect(ws, "patterns")
    try:
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        pass
    finally:
        _broadcaster.disconnect(ws, "patterns")


@router.websocket("/profile")
async def ws_profile(ws: WebSocket) -> None:
    await _broadcaster.connect(ws, "profile")
    try:
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        pass
    finally:
        _broadcaster.disconnect(ws, "profile")

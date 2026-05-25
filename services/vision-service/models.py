"""
Pydantic schemas for game state, events, and OCR results.
All downstream services consume these normalized structures.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# OCR result
# ─────────────────────────────────────────────────────────────────────────────

class OcrResult(BaseModel):
    text: str
    confidence: float
    region: str  # which ROI produced this result


# ─────────────────────────────────────────────────────────────────────────────
# Killfeed entry
# ─────────────────────────────────────────────────────────────────────────────

class KillfeedEntry(BaseModel):
    raw_text: str
    confidence: float
    timestamp: float = Field(default_factory=time.time)


# ─────────────────────────────────────────────────────────────────────────────
# Round result
# ─────────────────────────────────────────────────────────────────────────────

class RoundResult(str, Enum):
    VICTORY = "VICTORY"
    DEFEAT = "DEFEAT"
    DRAW = "DRAW"


# ─────────────────────────────────────────────────────────────────────────────
# Confidence map — one float per extracted field
# ─────────────────────────────────────────────────────────────────────────────

class ConfidenceMap(BaseModel):
    health: float = 0.0
    armor: float = 0.0
    credits: float = 0.0
    ammo: float = 0.0
    match_timer: float = 0.0
    buy_phase: float = 0.0
    player_dead: float = 0.0
    spike_planted: float = 0.0
    spike_defused: float = 0.0
    round_result: float = 0.0
    killfeed: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Core game state — emitted every processed frame
# ─────────────────────────────────────────────────────────────────────────────

class GameState(BaseModel):
    # Meta
    frame_id: int = 0
    timestamp: float = Field(default_factory=time.time)
    processing_ms: float = 0.0       # wall-clock time spent analysing this frame

    # Round
    round_number: int = 0
    buy_phase: bool = False
    match_timer: Optional[str] = None   # "1:22" format

    # Player vitals
    player_dead: bool = False
    health: Optional[int] = None        # 0–150 (shields not counted in HP)
    armor: Optional[int] = None         # 0–50
    credits: Optional[int] = None       # 0–9000
    weapon: Optional[str] = None

    # Ammo  (current / reserve)
    ammo_current: Optional[int] = None
    ammo_reserve: Optional[int] = None

    # Spike
    spike_planted: bool = False
    spike_defused: bool = False

    # Round outcome
    round_result: Optional[RoundResult] = None

    # Killfeed
    killfeed: list[KillfeedEntry] = Field(default_factory=list)

    # Per-field extraction confidence
    confidence: ConfidenceMap = Field(default_factory=ConfidenceMap)

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ─────────────────────────────────────────────────────────────────────────────
# Semantic events
# ─────────────────────────────────────────────────────────────────────────────

class EventType(str, Enum):
    ROUND_STARTED       = "ROUND_STARTED"
    ROUND_ENDED         = "ROUND_ENDED"
    BUY_PHASE_STARTED   = "BUY_PHASE_STARTED"
    BUY_PHASE_ENDED     = "BUY_PHASE_ENDED"
    PLAYER_DIED         = "PLAYER_DIED"
    PLAYER_RESPAWNED    = "PLAYER_RESPAWNED"
    SPIKE_PLANTED       = "SPIKE_PLANTED"
    SPIKE_DEFUSED       = "SPIKE_DEFUSED"
    LOW_ECONOMY         = "LOW_ECONOMY"
    FORCE_BUY_DETECTED  = "FORCE_BUY_DETECTED"
    HEALTH_CRITICAL     = "HEALTH_CRITICAL"      # health < 30


class GameEvent(BaseModel):
    event_type: EventType
    timestamp: float = Field(default_factory=time.time)
    frame_id: int = 0
    confidence: float = 1.0
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ─────────────────────────────────────────────────────────────────────────────
# Frame pipeline metadata (for benchmarking / debug)
# ─────────────────────────────────────────────────────────────────────────────

class PipelineStats(BaseModel):
    frames_received: int = 0
    frames_processed: int = 0
    frames_dropped: int = 0
    fps_in: float = 0.0
    fps_processed: float = 0.0
    avg_latency_ms: float = 0.0
    ocr_calls: int = 0
    template_calls: int = 0
    events_emitted: int = 0

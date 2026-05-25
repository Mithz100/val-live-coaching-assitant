"""
Pydantic schemas used across the event service.
These are the data contracts — kept separate from SQLAlchemy ORM models.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Raw vision events (mirrored from vision-service so we're self-contained)
# ─────────────────────────────────────────────────────────────────────────────

class RawEventType(str, Enum):
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
    HEALTH_CRITICAL     = "HEALTH_CRITICAL"


class RawEvent(BaseModel):
    event_type: str
    timestamp: float
    frame_id: int = 0
    confidence: float = 1.0
    payload: dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Semantic event types
# ─────────────────────────────────────────────────────────────────────────────

class SemanticEventType(str, Enum):
    SOLO_PEEK_DEATH              = "SOLO_PEEK_DEATH"
    LOW_VALUE_FORCE_BUY          = "LOW_VALUE_FORCE_BUY"
    UNUSED_UTILITY_DEATH         = "UNUSED_UTILITY_DEATH"
    HIGH_RISK_REPEEK             = "HIGH_RISK_REPEEK"
    EARLY_ROUND_DEATH            = "EARLY_ROUND_DEATH"
    LOW_ECON_IMPULSE_BUY         = "LOW_ECON_IMPULSE_BUY"
    LOW_DISCIPLINE_SAVE          = "LOW_DISCIPLINE_SAVE"
    AGGRESSIVE_OVEREXTENSION     = "AGGRESSIVE_OVEREXTENSION"
    CONSISTENT_ECON_MISTAKE      = "CONSISTENT_ECON_MISTAKE"
    HIGH_CONFIDENCE_ENTRY        = "HIGH_CONFIDENCE_ENTRY"
    REPEATED_DEATH_PATTERN       = "REPEATED_DEATH_PATTERN"
    POST_PLANT_DISCIPLINE        = "POST_PLANT_DISCIPLINE"
    ECO_ROUND_DETECTED           = "ECO_ROUND_DETECTED"
    PANIC_BUY_DETECTED           = "PANIC_BUY_DETECTED"
    LOW_HEALTH_ENGAGEMENT        = "LOW_HEALTH_ENGAGEMENT"


class SemanticEvent(BaseModel):
    event_type: SemanticEventType
    timestamp: float = Field(default_factory=time.time)
    round_number: int = 0
    confidence: float = 1.0
    # Linked raw events that triggered this semantic event
    source_events: list[str] = Field(default_factory=list)
    # Human-readable explanation (used by future coaching layer)
    explanation: str = ""
    # Structured metadata for analytics
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ─────────────────────────────────────────────────────────────────────────────
# Round lifecycle states
# ─────────────────────────────────────────────────────────────────────────────

class RoundPhase(str, Enum):
    IDLE        = "IDLE"
    BUY_PHASE   = "BUY_PHASE"
    COMBAT      = "COMBAT"
    POST_PLANT  = "POST_PLANT"
    ENDED       = "ENDED"


class RoundResult(str, Enum):
    VICTORY = "VICTORY"
    DEFEAT  = "DEFEAT"
    DRAW    = "DRAW"
    UNKNOWN = "UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────────
# Round state (hot, lives in Redis / memory)
# ─────────────────────────────────────────────────────────────────────────────

class RoundState(BaseModel):
    round_number: int = 0
    phase: RoundPhase = RoundPhase.IDLE
    phase_started_at: float = Field(default_factory=time.time)
    round_started_at: Optional[float] = None
    buy_phase_started_at: Optional[float] = None
    combat_started_at: Optional[float] = None
    spike_planted_at: Optional[float] = None
    ended_at: Optional[float] = None
    result: Optional[RoundResult] = None

    # Snapshot of player vitals at key moments
    health_at_combat_start: Optional[int] = None
    credits_at_buy: Optional[int] = None

    # Within-round tracking
    death_count: int = 0
    solo_peek_count: int = 0
    utility_used: bool = False
    semantic_events: list[str] = Field(default_factory=list)

    @property
    def time_in_phase(self) -> float:
        return time.time() - self.phase_started_at

    @property
    def survival_time_s(self) -> Optional[float]:
        if self.round_started_at is None:
            return None
        end = self.ended_at or time.time()
        return end - self.round_started_at


# ─────────────────────────────────────────────────────────────────────────────
# Round summary (cold, persisted to DB)
# ─────────────────────────────────────────────────────────────────────────────

class EconomyQuality(str, Enum):
    FULL_BUY    = "full_buy"
    HALF_BUY    = "half_buy"
    ECO         = "eco"
    FORCE_BUY   = "force_buy"
    SAVE        = "save"
    UNKNOWN     = "unknown"


class RoundSummary(BaseModel):
    round_number: int
    phase_durations: dict[str, float] = Field(default_factory=dict)
    economy_quality: EconomyQuality = EconomyQuality.UNKNOWN
    aggression_score: float = 0.0       # 0.0 (passive) → 1.0 (hyper-aggressive)
    survival_time_seconds: Optional[float] = None
    survived: bool = False
    spike_planted: bool = False
    result: RoundResult = RoundResult.UNKNOWN
    credits_spent: Optional[int] = None
    credits_remaining: Optional[int] = None
    major_mistakes: list[str] = Field(default_factory=list)
    positive_behaviors: list[str] = Field(default_factory=list)
    semantic_events: list[str] = Field(default_factory=list)
    raw_event_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ─────────────────────────────────────────────────────────────────────────────
# Player profile snapshot
# ─────────────────────────────────────────────────────────────────────────────

class PlayerProfile(BaseModel):
    session_id: str = ""
    rounds_tracked: int = 0

    # Rolling metrics (exponential moving averages)
    avg_survival_rate: float = 0.5
    avg_economy_discipline: float = 0.5   # 1.0 = always full buys correctly
    avg_aggression_score: float = 0.5
    force_buy_frequency: float = 0.0     # fraction of rounds
    early_death_frequency: float = 0.0
    solo_peek_frequency: float = 0.0

    # Counts (absolute, this session)
    total_force_buys: int = 0
    total_solo_peek_deaths: int = 0
    total_early_deaths: int = 0
    total_unused_utility_deaths: int = 0

    # Mistake registry: mistake_type → count
    mistake_counts: dict[str, int] = Field(default_factory=dict)

    # Detected patterns this session
    active_patterns: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ─────────────────────────────────────────────────────────────────────────────
# Pattern detection result
# ─────────────────────────────────────────────────────────────────────────────

class DetectedPattern(BaseModel):
    pattern_type: str
    occurrences: int
    window_rounds: int
    confidence: float
    description: str
    first_seen_round: int
    last_seen_round: int
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ─────────────────────────────────────────────────────────────────────────────
# Rule context — snapshot fed into every rule evaluation
# ─────────────────────────────────────────────────────────────────────────────

class RuleContext(BaseModel):
    """Snapshot of all available context at the moment a raw event arrives."""
    triggering_event: RawEvent
    round_state: RoundState
    player_profile: PlayerProfile
    recent_events: list[RawEvent] = Field(default_factory=list)  # last N events
    # Latest game state snapshot (forwarded from vision-service /game-state)
    health: Optional[int] = None
    armor: Optional[int] = None
    credits: Optional[int] = None
    ammo_current: Optional[int] = None
    buy_phase: bool = False
    spike_planted: bool = False

    class Config:
        arbitrary_types_allowed = True

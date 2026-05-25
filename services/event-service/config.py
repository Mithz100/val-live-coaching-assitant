"""Centralized configuration for the event service."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EventServiceConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EVENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Upstream vision service ───────────────────────────────────────────────
    vision_events_url: str = Field(default="ws://localhost:8100/events")
    vision_state_url: str = Field(default="ws://localhost:8100/game-state")

    # ── Output server ─────────────────────────────────────────────────────────
    ws_host: str = Field(default="0.0.0.0")
    ws_port: int = Field(default=8200, ge=1024, le=65535)

    # ── Database (SQLite default, PostgreSQL in production) ───────────────────
    # Override with:  postgresql+asyncpg://user:pass@localhost/valorant_coach
    database_url: str = Field(default="sqlite+aiosqlite:///./valorant_memory.db")
    db_echo: bool = Field(default=False)

    # ── Redis (optional — in-memory fallback used when absent) ───────────────
    redis_url: str = Field(default="")           # empty = use in-memory store
    redis_ttl_s: int = Field(default=3600)

    # ── Event consumer ────────────────────────────────────────────────────────
    consumer_reconnect_delay_s: float = Field(default=2.0)
    event_dedup_window_s: float = Field(default=1.5)

    # ── Round lifecycle ───────────────────────────────────────────────────────
    round_timeout_s: float = Field(default=130.0)   # max Valorant round length
    buy_phase_max_s: float = Field(default=30.0)
    early_round_threshold_s: float = Field(default=45.0)  # "early death" window

    # ── Semantic / rule engine ────────────────────────────────────────────────
    # Force-buy: credits below this when buying expensive weapon
    force_buy_credits_threshold: int = Field(default=2900)
    # Eco: team credits average below this → eco round
    eco_round_threshold: int = Field(default=1900)
    # Low health before re-engaging
    low_health_peek_threshold: int = Field(default=35)
    # Aggressive overextension: N solo peeks within a round
    aggression_solo_peek_limit: int = Field(default=2)
    # Rule cooldown — same semantic event won't fire more than once per N seconds
    rule_cooldown_s: float = Field(default=4.0)

    # ── Pattern detection ─────────────────────────────────────────────────────
    # Look back this many rounds for patterns
    pattern_window_rounds: int = Field(default=5)
    # Minimum occurrences in window to flag as pattern
    pattern_min_occurrences: int = Field(default=2)
    # Minimum confidence to surface a pattern
    pattern_confidence_min: float = Field(default=0.60)

    # ── Player profile ────────────────────────────────────────────────────────
    profile_ema_alpha: float = Field(default=0.2)  # exponential moving avg weight
    profile_session_rounds_min: int = Field(default=3)

    # ── Benchmark / debug ─────────────────────────────────────────────────────
    debug_mode: bool = Field(default=False)
    benchmark_mode: bool = Field(default=False)
    benchmark_log_interval_s: float = Field(default=10.0)


settings = EventServiceConfig()

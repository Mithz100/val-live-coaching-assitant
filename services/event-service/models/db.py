"""
SQLAlchemy ORM models for persistent storage.

Default: SQLite via aiosqlite (zero setup)
Production: PostgreSQL via asyncpg (set EVENT_DATABASE_URL)
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings


# ─────────────────────────────────────────────────────────────────────────────
# Engine + session factory
# ─────────────────────────────────────────────────────────────────────────────

engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    # SQLite requires check_same_thread=False for async
    connect_args={"check_same_thread": False}
    if "sqlite" in settings.database_url
    else {},
)

AsyncSession = async_sessionmaker(engine, expire_on_commit=False)


# ─────────────────────────────────────────────────────────────────────────────
# Base
# ─────────────────────────────────────────────────────────────────────────────

class Base(AsyncAttrs, DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Tables
# ─────────────────────────────────────────────────────────────────────────────

class MatchRecord(Base):
    """One gameplay session (from first event to explicit end or timeout)."""
    __tablename__ = "matches"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    session_id   = Column(String(64), nullable=False, index=True)
    started_at   = Column(DateTime, server_default=func.now())
    ended_at     = Column(DateTime, nullable=True)
    round_count  = Column(Integer, default=0)
    map_name     = Column(String(64), nullable=True)
    extra        = Column(JSON, default={})


class RoundRecord(Base):
    """Persisted round summary."""
    __tablename__ = "rounds"

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    session_id            = Column(String(64), nullable=False, index=True)
    round_number          = Column(Integer, nullable=False)
    started_at            = Column(DateTime, nullable=True)
    ended_at              = Column(DateTime, nullable=True)
    result                = Column(String(16), default="UNKNOWN")
    economy_quality       = Column(String(16), default="unknown")
    aggression_score      = Column(Float, default=0.0)
    survival_time_s       = Column(Float, nullable=True)
    survived              = Column(Boolean, default=False)
    spike_planted         = Column(Boolean, default=False)
    credits_spent         = Column(Integer, nullable=True)
    credits_remaining     = Column(Integer, nullable=True)
    major_mistakes        = Column(JSON, default=[])
    positive_behaviors    = Column(JSON, default=[])
    semantic_events       = Column(JSON, default=[])
    raw_event_count       = Column(Integer, default=0)

    __table_args__ = (
        Index("ix_rounds_session_round", "session_id", "round_number"),
    )


class RawEventRecord(Base):
    """Every raw event received from the vision service."""
    __tablename__ = "raw_events"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    session_id   = Column(String(64), nullable=False, index=True)
    round_number = Column(Integer, nullable=True, index=True)
    event_type   = Column(String(64), nullable=False, index=True)
    timestamp    = Column(Float, nullable=False)
    frame_id     = Column(Integer, default=0)
    confidence   = Column(Float, default=1.0)
    payload      = Column(JSON, default={})
    created_at   = Column(DateTime, server_default=func.now())


class SemanticEventRecord(Base):
    """Every emitted semantic event."""
    __tablename__ = "semantic_events"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    session_id     = Column(String(64), nullable=False, index=True)
    round_number   = Column(Integer, nullable=True, index=True)
    event_type     = Column(String(64), nullable=False, index=True)
    timestamp      = Column(Float, nullable=False)
    confidence     = Column(Float, default=1.0)
    source_events  = Column(JSON, default=[])
    explanation    = Column(Text, default="")
    metadata_json  = Column(JSON, default={})
    created_at     = Column(DateTime, server_default=func.now())


class EconomyRecord(Base):
    """Economy snapshot per round."""
    __tablename__ = "economy"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    session_id       = Column(String(64), nullable=False, index=True)
    round_number     = Column(Integer, nullable=False)
    credits_at_buy   = Column(Integer, nullable=True)
    credits_spent    = Column(Integer, nullable=True)
    credits_after    = Column(Integer, nullable=True)
    economy_quality  = Column(String(16), default="unknown")
    was_force_buy    = Column(Boolean, default=False)
    was_eco          = Column(Boolean, default=False)
    was_save         = Column(Boolean, default=False)


class DeathRecord(Base):
    """Each player death with context."""
    __tablename__ = "deaths"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    session_id          = Column(String(64), nullable=False, index=True)
    round_number        = Column(Integer, nullable=False, index=True)
    timestamp           = Column(Float, nullable=False)
    time_into_round_s   = Column(Float, nullable=True)
    health_before       = Column(Integer, nullable=True)
    was_early           = Column(Boolean, default=False)   # < early_round_threshold_s
    was_solo_peek       = Column(Boolean, default=False)
    was_low_health_peek = Column(Boolean, default=False)
    utility_unused      = Column(Boolean, default=False)
    round_phase         = Column(String(16), default="UNKNOWN")


class PlayerProfileRecord(Base):
    """Player profile snapshot saved periodically."""
    __tablename__ = "player_profiles"

    id                      = Column(Integer, primary_key=True, autoincrement=True)
    session_id              = Column(String(64), nullable=False, index=True)
    snapshot_at             = Column(DateTime, server_default=func.now())
    rounds_tracked          = Column(Integer, default=0)
    avg_survival_rate       = Column(Float, default=0.5)
    avg_economy_discipline  = Column(Float, default=0.5)
    avg_aggression_score    = Column(Float, default=0.5)
    force_buy_frequency     = Column(Float, default=0.0)
    early_death_frequency   = Column(Float, default=0.0)
    solo_peek_frequency     = Column(Float, default=0.0)
    mistake_counts          = Column(JSON, default={})
    active_patterns         = Column(JSON, default=[])


class PatternRecord(Base):
    """Detected behavioral patterns."""
    __tablename__ = "patterns"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    session_id       = Column(String(64), nullable=False, index=True)
    pattern_type     = Column(String(64), nullable=False, index=True)
    detected_at      = Column(DateTime, server_default=func.now())
    occurrences      = Column(Integer, default=0)
    window_rounds    = Column(Integer, default=0)
    confidence       = Column(Float, default=0.0)
    description      = Column(Text, default="")
    first_seen_round = Column(Integer, default=0)
    last_seen_round  = Column(Integer, default=0)
    metadata_json    = Column(JSON, default={})


# ─────────────────────────────────────────────────────────────────────────────
# Schema creation helper
# ─────────────────────────────────────────────────────────────────────────────

async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

"""
PostgreSQL/SQLite persistence layer.

All writes are fire-and-forget from the pipeline's perspective —
they're awaited before the next frame arrives but never block
the semantic engine.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from models.db import (
    AsyncSession,
    DeathRecord,
    EconomyRecord,
    MatchRecord,
    PatternRecord,
    PlayerProfileRecord,
    RawEventRecord,
    RoundRecord,
    SemanticEventRecord,
)
from models.schemas import (
    DetectedPattern,
    PlayerProfile,
    RawEvent,
    RoundSummary,
    SemanticEvent,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Match
# ─────────────────────────────────────────────────────────────────────────────

async def upsert_match(session_id: str) -> None:
    async with AsyncSession() as db:
        result = await db.execute(
            select(MatchRecord).where(MatchRecord.session_id == session_id)
        )
        match = result.scalar_one_or_none()
        if match is None:
            db.add(MatchRecord(session_id=session_id, started_at=_now()))
            await db.commit()


async def increment_match_rounds(session_id: str) -> None:
    async with AsyncSession() as db:
        result = await db.execute(
            select(MatchRecord).where(MatchRecord.session_id == session_id)
        )
        match = result.scalar_one_or_none()
        if match:
            match.round_count = (match.round_count or 0) + 1
            await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Raw events
# ─────────────────────────────────────────────────────────────────────────────

async def save_raw_event(session_id: str, round_number: int, event: RawEvent) -> None:
    async with AsyncSession() as db:
        db.add(RawEventRecord(
            session_id=session_id,
            round_number=round_number,
            event_type=event.event_type,
            timestamp=event.timestamp,
            frame_id=event.frame_id,
            confidence=event.confidence,
            payload=event.payload,
        ))
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Semantic events
# ─────────────────────────────────────────────────────────────────────────────

async def save_semantic_event(
    session_id: str, round_number: int, event: SemanticEvent
) -> None:
    async with AsyncSession() as db:
        db.add(SemanticEventRecord(
            session_id=session_id,
            round_number=round_number,
            event_type=event.event_type.value,
            timestamp=event.timestamp,
            confidence=event.confidence,
            source_events=event.source_events,
            explanation=event.explanation,
            metadata_json=event.metadata,
        ))
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Round summary
# ─────────────────────────────────────────────────────────────────────────────

async def save_round_summary(session_id: str, summary: RoundSummary) -> None:
    async with AsyncSession() as db:
        db.add(RoundRecord(
            session_id=session_id,
            round_number=summary.round_number,
            ended_at=_now(),
            result=summary.result.value,
            economy_quality=summary.economy_quality.value,
            aggression_score=summary.aggression_score,
            survival_time_s=summary.survival_time_seconds,
            survived=summary.survived,
            spike_planted=summary.spike_planted,
            credits_spent=summary.credits_spent,
            credits_remaining=summary.credits_remaining,
            major_mistakes=summary.major_mistakes,
            positive_behaviors=summary.positive_behaviors,
            semantic_events=summary.semantic_events,
            raw_event_count=summary.raw_event_count,
        ))
        await db.commit()


async def get_recent_rounds(session_id: str, limit: int = 10) -> list[dict]:
    async with AsyncSession() as db:
        result = await db.execute(
            select(RoundRecord)
            .where(RoundRecord.session_id == session_id)
            .order_by(RoundRecord.round_number.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "round_number": r.round_number,
                "result": r.result,
                "economy_quality": r.economy_quality,
                "aggression_score": r.aggression_score,
                "survival_time_s": r.survival_time_s,
                "survived": r.survived,
                "major_mistakes": r.major_mistakes,
                "positive_behaviors": r.positive_behaviors,
                "semantic_events": r.semantic_events,
            }
            for r in rows
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Death records
# ─────────────────────────────────────────────────────────────────────────────

async def save_death(
    session_id: str,
    round_number: int,
    timestamp: float,
    time_into_round_s: float | None,
    health_before: int | None,
    was_early: bool,
    was_solo_peek: bool,
    was_low_health_peek: bool,
    utility_unused: bool,
    phase: str,
) -> None:
    async with AsyncSession() as db:
        db.add(DeathRecord(
            session_id=session_id,
            round_number=round_number,
            timestamp=timestamp,
            time_into_round_s=time_into_round_s,
            health_before=health_before,
            was_early=was_early,
            was_solo_peek=was_solo_peek,
            was_low_health_peek=was_low_health_peek,
            utility_unused=utility_unused,
            round_phase=phase,
        ))
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Economy
# ─────────────────────────────────────────────────────────────────────────────

async def save_economy(
    session_id: str,
    round_number: int,
    credits_at_buy: int | None,
    credits_spent: int | None,
    credits_after: int | None,
    economy_quality: str,
    was_force_buy: bool,
    was_eco: bool,
    was_save: bool,
) -> None:
    async with AsyncSession() as db:
        db.add(EconomyRecord(
            session_id=session_id,
            round_number=round_number,
            credits_at_buy=credits_at_buy,
            credits_spent=credits_spent,
            credits_after=credits_after,
            economy_quality=economy_quality,
            was_force_buy=was_force_buy,
            was_eco=was_eco,
            was_save=was_save,
        ))
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Player profile
# ─────────────────────────────────────────────────────────────────────────────

async def save_player_profile(session_id: str, profile: PlayerProfile) -> None:
    async with AsyncSession() as db:
        db.add(PlayerProfileRecord(
            session_id=session_id,
            snapshot_at=_now(),
            rounds_tracked=profile.rounds_tracked,
            avg_survival_rate=profile.avg_survival_rate,
            avg_economy_discipline=profile.avg_economy_discipline,
            avg_aggression_score=profile.avg_aggression_score,
            force_buy_frequency=profile.force_buy_frequency,
            early_death_frequency=profile.early_death_frequency,
            solo_peek_frequency=profile.solo_peek_frequency,
            mistake_counts=profile.mistake_counts,
            active_patterns=profile.active_patterns,
        ))
        await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Patterns
# ─────────────────────────────────────────────────────────────────────────────

async def save_pattern(session_id: str, pattern: DetectedPattern) -> None:
    async with AsyncSession() as db:
        db.add(PatternRecord(
            session_id=session_id,
            pattern_type=pattern.pattern_type,
            detected_at=_now(),
            occurrences=pattern.occurrences,
            window_rounds=pattern.window_rounds,
            confidence=pattern.confidence,
            description=pattern.description,
            first_seen_round=pattern.first_seen_round,
            last_seen_round=pattern.last_seen_round,
            metadata_json=pattern.metadata,
        ))
        await db.commit()


async def get_recent_semantic_events(
    session_id: str, limit: int = 20
) -> list[dict]:
    async with AsyncSession() as db:
        result = await db.execute(
            select(SemanticEventRecord)
            .where(SemanticEventRecord.session_id == session_id)
            .order_by(SemanticEventRecord.id.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "round_number": r.round_number,
                "event_type": r.event_type,
                "confidence": r.confidence,
                "explanation": r.explanation,
                "metadata": r.metadata_json,
            }
            for r in rows
        ]

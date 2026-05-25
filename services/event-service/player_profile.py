"""
Player profile manager.

Maintains rolling averages of behavioral metrics using exponential moving
averages (EMA).  Profile snapshots are saved to the database periodically.
"""

from __future__ import annotations

import logging

from config import settings
from memory import db_store
from models.schemas import (
    PlayerProfile,
    RoundSummary,
    SemanticEvent,
    SemanticEventType,
)

logger = logging.getLogger(__name__)

_ALPHA = settings.profile_ema_alpha   # EMA decay factor


def _ema(current: float, new_value: float) -> float:
    return _ALPHA * new_value + (1 - _ALPHA) * current


class PlayerProfileManager:
    """Owns the in-memory PlayerProfile and updates it after each round."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._profile = PlayerProfile(session_id=session_id)

    @property
    def profile(self) -> PlayerProfile:
        return self._profile

    def update_from_round(
        self,
        summary: RoundSummary,
        semantic_events: list[SemanticEvent],
    ) -> None:
        p = self._profile
        p.rounds_tracked += 1

        # ── Survival rate ─────────────────────────────────────────────────────
        p.avg_survival_rate = _ema(p.avg_survival_rate, 1.0 if summary.survived else 0.0)

        # ── Aggression ────────────────────────────────────────────────────────
        p.avg_aggression_score = _ema(p.avg_aggression_score, summary.aggression_score)

        # ── Economy discipline ────────────────────────────────────────────────
        is_good_econ = summary.economy_quality.value in ("full_buy", "half_buy", "eco", "save")
        p.avg_economy_discipline = _ema(p.avg_economy_discipline, 1.0 if is_good_econ else 0.0)

        # ── Per-event counters ────────────────────────────────────────────────
        sem_types = {e.event_type for e in semantic_events}

        if SemanticEventType.LOW_VALUE_FORCE_BUY in sem_types:
            p.total_force_buys += 1
        if SemanticEventType.SOLO_PEEK_DEATH in sem_types:
            p.total_solo_peek_deaths += 1
        if SemanticEventType.EARLY_ROUND_DEATH in sem_types:
            p.total_early_deaths += 1
        if SemanticEventType.UNUSED_UTILITY_DEATH in sem_types:
            p.total_unused_utility_deaths += 1

        # ── Frequencies (rolling) ─────────────────────────────────────────────
        rounds = max(p.rounds_tracked, 1)
        p.force_buy_frequency = p.total_force_buys / rounds
        p.early_death_frequency = p.total_early_deaths / rounds
        p.solo_peek_frequency = p.total_solo_peek_deaths / rounds

        # ── Mistake registry ──────────────────────────────────────────────────
        for ev in semantic_events:
            key = ev.event_type.value
            p.mistake_counts[key] = p.mistake_counts.get(key, 0) + 1

        logger.debug(
            "Profile updated: rounds=%d survival=%.2f aggression=%.2f",
            p.rounds_tracked,
            p.avg_survival_rate,
            p.avg_aggression_score,
        )

    def update_active_patterns(self, pattern_types: list[str]) -> None:
        self._profile.active_patterns = pattern_types

    async def persist(self) -> None:
        await db_store.save_player_profile(self.session_id, self._profile)
        logger.debug("Player profile persisted")

"""
Round summary generator.

Converts the completed RoundState + semantic events into a
structured, machine-readable RoundSummary.  No natural language.
"""

from __future__ import annotations

import logging
import time

from models.schemas import (
    EconomyQuality,
    RoundPhase,
    RoundResult,
    RoundState,
    RoundSummary,
    SemanticEvent,
    SemanticEventType,
)

logger = logging.getLogger(__name__)

# Mapping semantic event types → mistake or positive
_MISTAKE_EVENTS = {
    SemanticEventType.SOLO_PEEK_DEATH,
    SemanticEventType.LOW_VALUE_FORCE_BUY,
    SemanticEventType.UNUSED_UTILITY_DEATH,
    SemanticEventType.HIGH_RISK_REPEEK,
    SemanticEventType.EARLY_ROUND_DEATH,
    SemanticEventType.LOW_ECON_IMPULSE_BUY,
    SemanticEventType.LOW_DISCIPLINE_SAVE,
    SemanticEventType.AGGRESSIVE_OVEREXTENSION,
    SemanticEventType.CONSISTENT_ECON_MISTAKE,
    SemanticEventType.LOW_HEALTH_ENGAGEMENT,
    SemanticEventType.REPEATED_DEATH_PATTERN,
}

_POSITIVE_EVENTS = {
    SemanticEventType.HIGH_CONFIDENCE_ENTRY,
    SemanticEventType.POST_PLANT_DISCIPLINE,
}


def _classify_economy(round_state: RoundState) -> EconomyQuality:
    credits = round_state.credits_at_buy
    if credits is None:
        return EconomyQuality.UNKNOWN
    if credits >= 3900:
        return EconomyQuality.FULL_BUY
    if credits >= 2400:
        return EconomyQuality.HALF_BUY
    if credits >= 800:
        return EconomyQuality.ECO
    return EconomyQuality.SAVE


def _compute_aggression(round_state: RoundState, semantic_events: list[SemanticEvent]) -> float:
    """
    Aggression score 0.0–1.0 derived from:
      - solo peek count
      - early death
      - aggressive overextension event
    """
    score = 0.0
    score += min(round_state.solo_peek_count * 0.25, 0.5)

    sem_types = {e.event_type for e in semantic_events}
    if SemanticEventType.SOLO_PEEK_DEATH in sem_types:
        score += 0.2
    if SemanticEventType.EARLY_ROUND_DEATH in sem_types:
        score += 0.1
    if SemanticEventType.AGGRESSIVE_OVEREXTENSION in sem_types:
        score += 0.2

    return min(score, 1.0)


def generate(
    round_state: RoundState,
    semantic_events: list[SemanticEvent],
    raw_event_count: int,
    credits_remaining: int | None = None,
    credits_spent: int | None = None,
) -> RoundSummary:
    sem_type_names = [e.event_type.value for e in semantic_events]

    mistakes = [
        e.event_type.value
        for e in semantic_events
        if e.event_type in _MISTAKE_EVENTS
    ]
    positives = [
        e.event_type.value
        for e in semantic_events
        if e.event_type in _POSITIVE_EVENTS
    ]

    econ = _classify_economy(round_state)

    # If the round lifecycle explicitly logged force buy in semantic events,
    # override classification
    if SemanticEventType.LOW_VALUE_FORCE_BUY.value in sem_type_names:
        econ = EconomyQuality.FORCE_BUY
    if SemanticEventType.ECO_ROUND_DETECTED.value in sem_type_names:
        econ = EconomyQuality.ECO

    summary = RoundSummary(
        round_number=round_state.round_number,
        economy_quality=econ,
        aggression_score=_compute_aggression(round_state, semantic_events),
        survival_time_seconds=round_state.survival_time_s,
        survived=round_state.death_count == 0,
        spike_planted=round_state.spike_planted_at is not None,
        result=round_state.result or RoundResult.UNKNOWN,
        credits_spent=credits_spent,
        credits_remaining=credits_remaining,
        major_mistakes=mistakes,
        positive_behaviors=positives,
        semantic_events=sem_type_names,
        raw_event_count=raw_event_count,
    )

    logger.info(
        "Round %d summary: econ=%s aggression=%.2f survived=%s mistakes=%s",
        summary.round_number,
        summary.economy_quality.value,
        summary.aggression_score,
        summary.survived,
        summary.major_mistakes,
    )
    return summary

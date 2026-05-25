"""
Configurable gameplay rule engine.

Each rule is a pure function:
    rule(ctx: RuleContext) -> Optional[SemanticEvent]

Rules return None when their conditions are not met.
The engine collects all non-None results and deduplicates by
SemanticEventType within a cooldown window.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from config import settings
from models.schemas import (
    RawEventType,
    RoundPhase,
    RuleContext,
    SemanticEvent,
    SemanticEventType,
)

logger = logging.getLogger(__name__)

RuleFunc = Callable[[RuleContext], Optional[SemanticEvent]]


# ─────────────────────────────────────────────────────────────────────────────
# Helper builders
# ─────────────────────────────────────────────────────────────────────────────

def _event(
    event_type: SemanticEventType,
    ctx: RuleContext,
    explanation: str,
    confidence: float = 1.0,
    **metadata,
) -> SemanticEvent:
    return SemanticEvent(
        event_type=event_type,
        round_number=ctx.round_state.round_number,
        confidence=confidence,
        source_events=[ctx.triggering_event.event_type],
        explanation=explanation,
        metadata=dict(metadata),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Individual rules
# ─────────────────────────────────────────────────────────────────────────────

def rule_solo_peek_death(ctx: RuleContext) -> Optional[SemanticEvent]:
    """
    Player died at high health in early/mid round without recent teammate
    deaths — implies an unsupported aggressive peek.
    """
    if ctx.triggering_event.event_type != RawEventType.PLAYER_DIED:
        return None
    if ctx.round_state.phase not in (RoundPhase.COMBAT, RoundPhase.POST_PLANT):
        return None

    health = ctx.health
    # We need a health reading from just before death — HEALTH_CRITICAL fires
    # when health < 30, so if health was NOT critical we know they had decent HP
    health_was_high = health is None or health >= 50  # proxy: no HEALTH_CRITICAL in recent

    recent_types = [e.event_type for e in ctx.recent_events[-5:]]
    health_critical_recently = RawEventType.HEALTH_CRITICAL in recent_types

    is_early = False
    if ctx.round_state.round_started_at:
        elapsed = time.time() - ctx.round_state.round_started_at
        is_early = elapsed < settings.early_round_threshold_s

    if health_was_high and not health_critical_recently and is_early:
        ctx.round_state.solo_peek_count += 1
        return _event(
            SemanticEventType.SOLO_PEEK_DEATH,
            ctx,
            explanation=(
                "Died with high health early in the round — "
                "likely an unsupported solo peek with poor trade potential."
            ),
            confidence=0.75,
            time_into_round=time.time() - (ctx.round_state.round_started_at or time.time()),
        )
    return None


def rule_early_round_death(ctx: RuleContext) -> Optional[SemanticEvent]:
    """Died within the early round threshold."""
    if ctx.triggering_event.event_type != RawEventType.PLAYER_DIED:
        return None
    if ctx.round_state.round_started_at is None:
        return None

    elapsed = time.time() - ctx.round_state.round_started_at
    if elapsed < settings.early_round_threshold_s:
        return _event(
            SemanticEventType.EARLY_ROUND_DEATH,
            ctx,
            explanation=(
                f"Died {elapsed:.0f}s into the round — "
                "early deaths remove map control and put team at a disadvantage."
            ),
            confidence=0.9,
            time_into_round_s=round(elapsed, 1),
        )
    return None


def rule_low_value_force_buy(ctx: RuleContext) -> Optional[SemanticEvent]:
    """
    Force buy detected when credits are below the comfort threshold.
    """
    if ctx.triggering_event.event_type != RawEventType.FORCE_BUY_DETECTED:
        return None

    credits = ctx.credits or ctx.triggering_event.payload.get("credits", 9999)
    if credits < settings.force_buy_credits_threshold:
        return _event(
            SemanticEventType.LOW_VALUE_FORCE_BUY,
            ctx,
            explanation=(
                f"Bought with only ₹{credits} — force buying with insufficient credits "
                "hurts both this round and the next round's economy."
            ),
            confidence=0.85,
            credits=credits,
            threshold=settings.force_buy_credits_threshold,
        )
    return None


def rule_eco_round(ctx: RuleContext) -> Optional[SemanticEvent]:
    """Credits below eco threshold at buy phase end — classify as eco round."""
    if ctx.triggering_event.event_type != RawEventType.BUY_PHASE_ENDED:
        return None

    credits = ctx.credits
    if credits is not None and credits < settings.eco_round_threshold:
        return _event(
            SemanticEventType.ECO_ROUND_DETECTED,
            ctx,
            explanation=(
                f"Entered combat with ₹{credits} — eco round. "
                "Prioritize information and trades over individual duels."
            ),
            confidence=0.80,
            credits=credits,
        )
    return None


def rule_unused_utility_death(ctx: RuleContext) -> Optional[SemanticEvent]:
    """
    Player died without using utility this round.
    Proxied by: PLAYER_DIED fires but no utility-use signals preceded it.
    (Utility tracking is limited without minimap — low confidence.)
    """
    if ctx.triggering_event.event_type != RawEventType.PLAYER_DIED:
        return None
    if ctx.round_state.utility_used:
        return None  # utility was used — no fault
    if ctx.round_state.phase not in (RoundPhase.COMBAT, RoundPhase.POST_PLANT):
        return None

    return _event(
        SemanticEventType.UNUSED_UTILITY_DEATH,
        ctx,
        explanation=(
            "Died without evidence of utility usage — "
            "undeployed smokes, flashes, or molotovs reduce impact."
        ),
        confidence=0.55,  # low confidence: utility detection is imperfect
    )


def rule_high_risk_repeek(ctx: RuleContext) -> Optional[SemanticEvent]:
    """
    HEALTH_CRITICAL fired and player hasn't died yet — about to re-engage
    with very low HP.
    """
    if ctx.triggering_event.event_type != RawEventType.HEALTH_CRITICAL:
        return None
    if ctx.round_state.phase != RoundPhase.COMBAT:
        return None

    health = ctx.health or ctx.triggering_event.payload.get("health", 100)
    if health <= settings.low_health_peek_threshold:
        return _event(
            SemanticEventType.HIGH_RISK_REPEEK,
            ctx,
            explanation=(
                f"Engaging with {health} HP — low health re-peeks rarely succeed "
                "and waste a weapon."
            ),
            confidence=0.80,
            health=health,
        )
    return None


def rule_aggressive_overextension(ctx: RuleContext) -> Optional[SemanticEvent]:
    """Player has taken N or more solo peeks in a single round."""
    if ctx.triggering_event.event_type != RawEventType.PLAYER_DIED:
        return None

    if ctx.round_state.solo_peek_count >= settings.aggression_solo_peek_limit:
        return _event(
            SemanticEventType.AGGRESSIVE_OVEREXTENSION,
            ctx,
            explanation=(
                f"Took {ctx.round_state.solo_peek_count} isolated fights this round — "
                "consistent overaggression without support reduces win probability."
            ),
            confidence=0.85,
            solo_peeks=ctx.round_state.solo_peek_count,
        )
    return None


def rule_consistent_econ_mistake(ctx: RuleContext) -> Optional[SemanticEvent]:
    """
    Player has force-bought multiple rounds in a row (tracked via profile).
    """
    if ctx.triggering_event.event_type != RawEventType.FORCE_BUY_DETECTED:
        return None

    force_buy_count = ctx.player_profile.total_force_buys
    if force_buy_count >= 2:
        return _event(
            SemanticEventType.CONSISTENT_ECON_MISTAKE,
            ctx,
            explanation=(
                f"This is force buy #{force_buy_count + 1} in the session — "
                "repeated force buys indicate systemic economy mismanagement."
            ),
            confidence=min(0.5 + 0.1 * force_buy_count, 0.95),
            total_force_buys=force_buy_count,
        )
    return None


def rule_low_econ_impulse_buy(ctx: RuleContext) -> Optional[SemanticEvent]:
    """Credits are very low but player is in buy phase — impulse spend risk."""
    if ctx.triggering_event.event_type != RawEventType.LOW_ECONOMY:
        return None
    if ctx.round_state.phase != RoundPhase.BUY_PHASE:
        return None

    credits = ctx.credits or ctx.triggering_event.payload.get("credits", 9999)
    return _event(
        SemanticEventType.LOW_ECON_IMPULSE_BUY,
        ctx,
        explanation=(
            f"Only ₹{credits} available during buy phase — "
            "spending now may prevent a full buy next round."
        ),
        confidence=0.70,
        credits=credits,
    )


def rule_low_health_engagement(ctx: RuleContext) -> Optional[SemanticEvent]:
    """HEALTH_CRITICAL fires — player is engaging while nearly dead."""
    if ctx.triggering_event.event_type != RawEventType.HEALTH_CRITICAL:
        return None

    health = ctx.health or 0
    return _event(
        SemanticEventType.LOW_HEALTH_ENGAGEMENT,
        ctx,
        explanation=(
            f"Continuing to engage at {health} HP — "
            "consider repositioning or saving the weapon."
        ),
        confidence=0.75,
        health=health,
    )


def rule_spike_planted_discipline(ctx: RuleContext) -> Optional[SemanticEvent]:
    """Spike was planted — positive behavior, player is executing correctly."""
    if ctx.triggering_event.event_type != RawEventType.SPIKE_PLANTED:
        return None

    return _event(
        SemanticEventType.POST_PLANT_DISCIPLINE,
        ctx,
        explanation=(
            "Successfully planted the spike — now shift to post-plant defense."
        ),
        confidence=0.9,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Rule registry + engine
# ─────────────────────────────────────────────────────────────────────────────

_ALL_RULES: list[RuleFunc] = [
    rule_solo_peek_death,
    rule_early_round_death,
    rule_low_value_force_buy,
    rule_eco_round,
    rule_unused_utility_death,
    rule_high_risk_repeek,
    rule_aggressive_overextension,
    rule_consistent_econ_mistake,
    rule_low_econ_impulse_buy,
    rule_low_health_engagement,
    rule_spike_planted_discipline,
]


class RuleEngine:
    """Applies all rules to a RuleContext and returns semantic events."""

    def __init__(self) -> None:
        self._cooldowns: dict[str, float] = {}  # event_type.value → last emit time

    def evaluate(self, ctx: RuleContext) -> list[SemanticEvent]:
        results: list[SemanticEvent] = []
        for rule in _ALL_RULES:
            try:
                result = rule(ctx)
            except Exception:
                logger.exception("Rule %s raised unexpectedly", rule.__name__)
                continue

            if result is None:
                continue
            if self._is_on_cooldown(result.event_type.value):
                logger.debug("Rule %s on cooldown", result.event_type.value)
                continue

            self._cooldowns[result.event_type.value] = time.time()
            results.append(result)
            logger.debug(
                "Rule fired: %s conf=%.2f", result.event_type.value, result.confidence
            )

        return results

    def _is_on_cooldown(self, key: str) -> bool:
        last = self._cooldowns.get(key, 0.0)
        return time.time() - last < settings.rule_cooldown_s

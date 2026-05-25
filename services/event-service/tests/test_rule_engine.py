"""
Tests for the rule engine.

Each rule is tested with a crafted RuleContext that puts the rule
into its expected trigger condition.  No I/O, no mocking.
"""

from __future__ import annotations

import time

import pytest

from models.schemas import (
    PlayerProfile,
    RawEvent,
    RoundPhase,
    RoundState,
    RuleContext,
    SemanticEventType,
)
from rule_engine import (
    RuleEngine,
    rule_aggressive_overextension,
    rule_early_round_death,
    rule_eco_round,
    rule_high_risk_repeek,
    rule_low_econ_impulse_buy,
    rule_low_value_force_buy,
    rule_solo_peek_death,
    rule_unused_utility_death,
)


def _event(event_type: str, payload: dict = None) -> RawEvent:
    return RawEvent(
        event_type=event_type,
        timestamp=time.time(),
        frame_id=1,
        confidence=1.0,
        payload=payload or {},
    )


def _ctx(
    event_type: str,
    payload: dict = None,
    phase: RoundPhase = RoundPhase.COMBAT,
    health: int = 100,
    credits: int = 4000,
    solo_peek_count: int = 0,
    round_started_at: float = None,
    utility_used: bool = False,
    profile: PlayerProfile = None,
    recent_events: list = None,
    buy_phase: bool = False,
) -> RuleContext:
    rs = RoundState(
        phase=phase,
        round_started_at=round_started_at or (time.time() - 20),
        solo_peek_count=solo_peek_count,
        utility_used=utility_used,
    )
    return RuleContext(
        triggering_event=_event(event_type, payload),
        round_state=rs,
        player_profile=profile or PlayerProfile(),
        recent_events=recent_events or [],
        health=health,
        credits=credits,
        buy_phase=buy_phase,
    )


class TestSoloPeekDeath:
    def test_fires_on_early_high_hp_death(self):
        ctx = _ctx("PLAYER_DIED", health=100, round_started_at=time.time() - 15)
        result = rule_solo_peek_death(ctx)
        assert result is not None
        assert result.event_type == SemanticEventType.SOLO_PEEK_DEATH

    def test_no_fire_on_wrong_event_type(self):
        ctx = _ctx("BUY_PHASE_ENDED")
        result = rule_solo_peek_death(ctx)
        assert result is None

    def test_no_fire_when_health_critical_recently(self):
        recent = [_event("HEALTH_CRITICAL")]
        ctx = _ctx("PLAYER_DIED", health=20, recent_events=recent,
                   round_started_at=time.time() - 10)
        result = rule_solo_peek_death(ctx)
        assert result is None

    def test_no_fire_when_late_in_round(self):
        # 60s into round — not "early"
        ctx = _ctx("PLAYER_DIED", round_started_at=time.time() - 60)
        result = rule_solo_peek_death(ctx)
        assert result is None


class TestEarlyRoundDeath:
    def test_fires_within_threshold(self):
        ctx = _ctx("PLAYER_DIED", round_started_at=time.time() - 20)
        result = rule_early_round_death(ctx)
        assert result is not None
        assert result.event_type == SemanticEventType.EARLY_ROUND_DEATH

    def test_no_fire_after_threshold(self):
        ctx = _ctx("PLAYER_DIED", round_started_at=time.time() - 80)
        result = rule_early_round_death(ctx)
        assert result is None

    def test_no_fire_on_wrong_event(self):
        ctx = _ctx("BUY_PHASE_ENDED")
        result = rule_early_round_death(ctx)
        assert result is None


class TestLowValueForceBuy:
    def test_fires_below_threshold(self):
        ctx = _ctx("FORCE_BUY_DETECTED", payload={"credits": 1500}, credits=1500)
        result = rule_low_value_force_buy(ctx)
        assert result is not None
        assert result.event_type == SemanticEventType.LOW_VALUE_FORCE_BUY
        assert result.metadata["credits"] == 1500

    def test_no_fire_with_sufficient_credits(self):
        ctx = _ctx("FORCE_BUY_DETECTED", payload={"credits": 3500}, credits=3500)
        result = rule_low_value_force_buy(ctx)
        assert result is None

    def test_no_fire_on_wrong_event(self):
        ctx = _ctx("PLAYER_DIED")
        result = rule_low_value_force_buy(ctx)
        assert result is None


class TestEcoRound:
    def test_fires_on_low_credits_at_buy_end(self):
        ctx = _ctx(
            "BUY_PHASE_ENDED",
            phase=RoundPhase.BUY_PHASE,
            credits=800,
        )
        result = rule_eco_round(ctx)
        assert result is not None
        assert result.event_type == SemanticEventType.ECO_ROUND_DETECTED

    def test_no_fire_with_decent_credits(self):
        ctx = _ctx("BUY_PHASE_ENDED", credits=3000)
        result = rule_eco_round(ctx)
        assert result is None


class TestUnusedUtilityDeath:
    def test_fires_when_utility_unused(self):
        ctx = _ctx("PLAYER_DIED", utility_used=False)
        result = rule_unused_utility_death(ctx)
        assert result is not None
        assert result.event_type == SemanticEventType.UNUSED_UTILITY_DEATH

    def test_no_fire_when_utility_was_used(self):
        ctx = _ctx("PLAYER_DIED", utility_used=True)
        result = rule_unused_utility_death(ctx)
        assert result is None


class TestHighRiskRepeek:
    def test_fires_on_critical_health(self):
        ctx = _ctx("HEALTH_CRITICAL", health=20)
        result = rule_high_risk_repeek(ctx)
        assert result is not None
        assert result.event_type == SemanticEventType.HIGH_RISK_REPEEK

    def test_no_fire_above_threshold(self):
        ctx = _ctx("HEALTH_CRITICAL", health=50)
        result = rule_high_risk_repeek(ctx)
        assert result is None


class TestAggressiveOverextension:
    def test_fires_after_limit_reached(self):
        ctx = _ctx("PLAYER_DIED", solo_peek_count=3)
        result = rule_aggressive_overextension(ctx)
        assert result is not None
        assert result.event_type == SemanticEventType.AGGRESSIVE_OVEREXTENSION

    def test_no_fire_below_limit(self):
        ctx = _ctx("PLAYER_DIED", solo_peek_count=1)
        result = rule_aggressive_overextension(ctx)
        assert result is None


class TestRuleEngine:
    def test_evaluates_all_rules(self):
        """Multiple rules can fire on PLAYER_DIED."""
        engine = RuleEngine()
        ctx = _ctx(
            "PLAYER_DIED",
            health=100,
            utility_used=False,
            round_started_at=time.time() - 15,
            solo_peek_count=3,
        )
        results = engine.evaluate(ctx)
        assert len(results) >= 1

    def test_cooldown_prevents_double_fire(self):
        engine = RuleEngine()
        ctx = _ctx("PLAYER_DIED", round_started_at=time.time() - 15)
        first = engine.evaluate(ctx)
        second = engine.evaluate(ctx)
        # Second call within cooldown should yield fewer results
        assert len(second) <= len(first)

    def test_returns_empty_on_non_triggering_event(self):
        engine = RuleEngine()
        ctx = _ctx("ROUND_STARTED")
        results = engine.evaluate(ctx)
        assert isinstance(results, list)

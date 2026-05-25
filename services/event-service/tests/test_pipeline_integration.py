"""
Integration tests for the full event pipeline.

Simulates realistic event sequences and verifies that semantic events
and round summaries are correctly generated end-to-end.

No database, no Redis, no WebSocket — all external I/O is mocked.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.schemas import (
    EconomyQuality,
    RawEvent,
    RoundPhase,
    RoundResult,
    SemanticEventType,
)
from round_lifecycle import RoundLifecycleEngine
from round_summary import generate as gen_summary
from pattern_detector import PatternDetector
from player_profile import PlayerProfileManager
from rule_engine import RuleEngine
from models.schemas import RuleContext, RoundState, PlayerProfile


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _raw(event_type: str, payload: dict = None) -> RawEvent:
    return RawEvent(
        event_type=event_type,
        timestamp=time.time(),
        frame_id=0,
        confidence=1.0,
        payload=payload or {},
    )


def _ctx(
    event: RawEvent,
    round_state: RoundState,
    health: int = 100,
    credits: int = 4000,
) -> RuleContext:
    return RuleContext(
        triggering_event=event,
        round_state=round_state,
        player_profile=PlayerProfile(),
        health=health,
        credits=credits,
    )


# ── Scenario tests ────────────────────────────────────────────────────────────

class TestForceEcoScenario:
    """
    Scenario: player has 1800 credits, enters combat, dies early.
    Expected: ECO_ROUND_DETECTED + EARLY_ROUND_DEATH
    """

    def test_eco_then_early_death(self):
        lifecycle = RoundLifecycleEngine()
        engine = RuleEngine()
        all_events = []

        sequence = [
            ("BUY_PHASE_STARTED", {}),
            ("BUY_PHASE_ENDED", {}),    # triggers eco check
            ("PLAYER_DIED", {}),        # early death (default start = now - 20s)
        ]

        for et, payload in sequence:
            lifecycle.process_event(et, payload)
            rs = lifecycle.state
            rs.round_started_at = time.time() - 20   # ensure "early"
            event = _raw(et, payload)
            ctx = _ctx(event, rs, credits=1800)
            results = engine.evaluate(ctx)
            all_events.extend(results)

        types = {e.event_type for e in all_events}
        assert SemanticEventType.ECO_ROUND_DETECTED in types
        assert SemanticEventType.EARLY_ROUND_DEATH in types


class TestForceBuyScenario:
    """
    Scenario: credits = 1500 → FORCE_BUY_DETECTED
    Expected: LOW_VALUE_FORCE_BUY
    """

    def test_force_buy_detected(self):
        lifecycle = RoundLifecycleEngine()
        engine = RuleEngine()
        lifecycle.process_event("BUY_PHASE_STARTED", {})
        lifecycle.process_event("FORCE_BUY_DETECTED", {"credits": 1500})
        rs = lifecycle.state

        event = _raw("FORCE_BUY_DETECTED", {"credits": 1500})
        ctx = _ctx(event, rs, credits=1500)
        results = engine.evaluate(ctx)
        assert any(e.event_type == SemanticEventType.LOW_VALUE_FORCE_BUY for e in results)


class TestHighRiskRepeekScenario:
    """
    Scenario: HEALTH_CRITICAL fires with health=20
    Expected: HIGH_RISK_REPEEK
    """

    def test_low_health_engagement(self):
        lifecycle = RoundLifecycleEngine()
        engine = RuleEngine()
        lifecycle.process_event("BUY_PHASE_STARTED", {})
        lifecycle.process_event("BUY_PHASE_ENDED", {})
        rs = lifecycle.state

        event = _raw("HEALTH_CRITICAL", {"health": 20})
        ctx = _ctx(event, rs, health=20)
        results = engine.evaluate(ctx)
        types = {e.event_type for e in results}
        assert SemanticEventType.HIGH_RISK_REPEEK in types


class TestRoundSummaryGeneration:
    """
    Verify round summary fields are correctly computed.
    """

    def test_survived_round(self):
        rs = RoundState(
            round_number=3,
            phase=RoundPhase.ENDED,
            round_started_at=time.time() - 60,
            ended_at=time.time(),
            death_count=0,
            credits_at_buy=4000,
        )
        summary = gen_summary(rs, [], raw_event_count=5)
        assert summary.survived is True
        assert summary.round_number == 3
        assert summary.economy_quality == EconomyQuality.FULL_BUY

    def test_force_buy_round(self):
        from models.schemas import SemanticEvent, SemanticEventType
        rs = RoundState(round_number=2, credits_at_buy=1200)
        sem_event = SemanticEvent(
            event_type=SemanticEventType.LOW_VALUE_FORCE_BUY,
            round_number=2,
            explanation="test",
        )
        summary = gen_summary(rs, [sem_event], raw_event_count=3)
        assert summary.economy_quality == EconomyQuality.FORCE_BUY
        assert "LOW_VALUE_FORCE_BUY" in summary.major_mistakes

    def test_aggression_score_from_solo_peeks(self):
        rs = RoundState(round_number=1, solo_peek_count=3)
        summary = gen_summary(rs, [], raw_event_count=2)
        assert summary.aggression_score >= 0.5


class TestPlayerProfileAccumulation:
    """
    Simulate 3 rounds and verify profile metrics update correctly.
    """

    def test_force_buy_frequency_accumulates(self):
        from models.schemas import SemanticEvent, SemanticEventType, RoundSummary, EconomyQuality, RoundResult

        mgr = PlayerProfileManager("test-session")
        for i in range(1, 4):
            rs = RoundState(round_number=i)
            summary = RoundSummary(
                round_number=i,
                economy_quality=EconomyQuality.FORCE_BUY,
                survived=False,
                result=RoundResult.DEFEAT,
            )
            sem_ev = SemanticEvent(
                event_type=SemanticEventType.LOW_VALUE_FORCE_BUY, round_number=i
            )
            mgr.update_from_round(summary, [sem_ev])

        assert mgr.profile.total_force_buys == 3
        assert mgr.profile.force_buy_frequency == pytest.approx(1.0)

    def test_survival_rate_ema(self):
        from models.schemas import RoundSummary, EconomyQuality, RoundResult

        mgr = PlayerProfileManager("s")
        # 3 deaths
        for i in range(3):
            mgr.update_from_round(
                RoundSummary(round_number=i, survived=False, result=RoundResult.DEFEAT),
                [],
            )
        # Should be lower than initial 0.5
        assert mgr.profile.avg_survival_rate < 0.5

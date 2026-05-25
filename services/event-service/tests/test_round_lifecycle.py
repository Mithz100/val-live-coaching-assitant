"""Tests for the round lifecycle state machine."""

from __future__ import annotations

import pytest

from models.schemas import RoundPhase, RoundResult
from round_lifecycle import RoundLifecycleEngine


def _engine() -> RoundLifecycleEngine:
    return RoundLifecycleEngine()


class TestInitialState:
    def test_starts_idle(self):
        e = _engine()
        assert e.state.phase == RoundPhase.IDLE

    def test_starts_round_zero(self):
        e = _engine()
        assert e.state.round_number == 0


class TestBuyPhaseTransition:
    def test_buy_phase_started(self):
        e = _engine()
        e.process_event("BUY_PHASE_STARTED", {})
        assert e.state.phase == RoundPhase.BUY_PHASE

    def test_buy_phase_increments_round(self):
        e = _engine()
        e.process_event("BUY_PHASE_STARTED", {})
        e.process_event("ROUND_ENDED", {"result": "DEFEAT"})
        e.process_event("BUY_PHASE_STARTED", {})
        assert e.state.round_number == 1

    def test_buy_phase_records_timestamp(self):
        e = _engine()
        e.process_event("BUY_PHASE_STARTED", {})
        assert e.state.buy_phase_started_at is not None


class TestCombatTransition:
    def test_buy_phase_ended_moves_to_combat(self):
        e = _engine()
        e.process_event("BUY_PHASE_STARTED", {})
        e.process_event("BUY_PHASE_ENDED", {})
        assert e.state.phase == RoundPhase.COMBAT

    def test_round_started_moves_to_combat(self):
        e = _engine()
        e.process_event("BUY_PHASE_STARTED", {})
        e.process_event("ROUND_STARTED", {})
        assert e.state.phase == RoundPhase.COMBAT

    def test_combat_records_start_time(self):
        e = _engine()
        e.process_event("BUY_PHASE_STARTED", {})
        e.process_event("BUY_PHASE_ENDED", {})
        assert e.state.round_started_at is not None


class TestSpikePlanted:
    def test_spike_transitions_to_post_plant(self):
        e = _engine()
        e.process_event("BUY_PHASE_STARTED", {})
        e.process_event("BUY_PHASE_ENDED", {})
        e.process_event("SPIKE_PLANTED", {})
        assert e.state.phase == RoundPhase.POST_PLANT

    def test_spike_planted_records_timestamp(self):
        e = _engine()
        e.process_event("BUY_PHASE_STARTED", {})
        e.process_event("BUY_PHASE_ENDED", {})
        e.process_event("SPIKE_PLANTED", {})
        assert e.state.spike_planted_at is not None


class TestRoundEnded:
    def test_round_ended_victory(self):
        e = _engine()
        e.process_event("BUY_PHASE_STARTED", {})
        e.process_event("BUY_PHASE_ENDED", {})
        e.process_event("ROUND_ENDED", {"result": "VICTORY"})
        assert e.state.phase == RoundPhase.ENDED
        assert e.state.result == RoundResult.VICTORY

    def test_round_ended_defeat(self):
        e = _engine()
        e.process_event("BUY_PHASE_STARTED", {})
        e.process_event("BUY_PHASE_ENDED", {})
        e.process_event("ROUND_ENDED", {"result": "DEFEAT"})
        assert e.state.result == RoundResult.DEFEAT

    def test_ended_records_timestamp(self):
        e = _engine()
        e.process_event("BUY_PHASE_STARTED", {})
        e.process_event("BUY_PHASE_ENDED", {})
        e.process_event("ROUND_ENDED", {"result": "VICTORY"})
        assert e.state.ended_at is not None


class TestDeathTracking:
    def test_death_increments_counter(self):
        e = _engine()
        e.process_event("BUY_PHASE_STARTED", {})
        e.process_event("BUY_PHASE_ENDED", {})
        e.process_event("PLAYER_DIED", {})
        e.process_event("PLAYER_DIED", {})
        assert e.state.death_count == 2


class TestFullRoundLifecycle:
    def test_full_round(self):
        e = _engine()
        events = [
            ("BUY_PHASE_STARTED", {}),
            ("BUY_PHASE_ENDED", {}),
            ("PLAYER_DIED", {}),
            ("SPIKE_PLANTED", {}),
            ("ROUND_ENDED", {"result": "DEFEAT"}),
        ]
        for ev, payload in events:
            e.process_event(ev, payload)

        assert e.state.phase == RoundPhase.ENDED
        assert e.state.death_count == 1
        assert e.state.spike_planted_at is not None
        assert e.state.result == RoundResult.DEFEAT

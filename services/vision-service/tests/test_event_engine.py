"""
Unit tests for the EventEngine state-transition logic.

No real frames needed — we construct GameState objects directly.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from event_engine import EventEngine
from models import EventType, GameState, RoundResult


def _state(**kwargs) -> GameState:
    return GameState(**kwargs)


class TestEventEngine:

    def setup_method(self) -> None:
        self.engine = EventEngine()
        # Feed one baseline state so _prev is populated
        self.engine.process(_state())

    # ── Buy phase ─────────────────────────────────────────────────────────────

    def test_buy_phase_started(self) -> None:
        events = self.engine.process(_state(buy_phase=True))
        types = [e.event_type for e in events]
        assert EventType.BUY_PHASE_STARTED in types

    def test_buy_phase_ended_triggers_round_started(self) -> None:
        self.engine.process(_state(buy_phase=True))
        events = self.engine.process(_state(buy_phase=False))
        types = [e.event_type for e in events]
        assert EventType.BUY_PHASE_ENDED in types
        assert EventType.ROUND_STARTED in types

    # ── Player death ──────────────────────────────────────────────────────────

    def test_player_died(self) -> None:
        events = self.engine.process(_state(player_dead=True))
        assert any(e.event_type == EventType.PLAYER_DIED for e in events)

    def test_player_respawned(self) -> None:
        self.engine.process(_state(player_dead=True))
        events = self.engine.process(_state(player_dead=False))
        assert any(e.event_type == EventType.PLAYER_RESPAWNED for e in events)

    # ── Spike ─────────────────────────────────────────────────────────────────

    def test_spike_planted(self) -> None:
        events = self.engine.process(_state(spike_planted=True))
        assert any(e.event_type == EventType.SPIKE_PLANTED for e in events)

    def test_spike_defused(self) -> None:
        events = self.engine.process(_state(spike_defused=True))
        assert any(e.event_type == EventType.SPIKE_DEFUSED for e in events)

    # ── Round result ──────────────────────────────────────────────────────────

    def test_round_ended_on_victory(self) -> None:
        events = self.engine.process(_state(round_result=RoundResult.VICTORY))
        types = [e.event_type for e in events]
        assert EventType.ROUND_ENDED in types
        ev = next(e for e in events if e.event_type == EventType.ROUND_ENDED)
        assert ev.payload["result"] == RoundResult.VICTORY

    # ── Economy ───────────────────────────────────────────────────────────────

    def test_low_economy(self) -> None:
        self.engine.process(_state(credits=4000))  # above threshold
        events = self.engine.process(_state(credits=1500, buy_phase=False))
        assert any(e.event_type == EventType.LOW_ECONOMY for e in events)

    def test_force_buy(self) -> None:
        self.engine.process(_state(credits=5000))
        events = self.engine.process(_state(credits=2500, buy_phase=False))
        assert any(e.event_type == EventType.FORCE_BUY_DETECTED for e in events)

    # ── Health critical ───────────────────────────────────────────────────────

    def test_health_critical(self) -> None:
        self.engine.process(_state(health=80))
        events = self.engine.process(_state(health=20, player_dead=False))
        assert any(e.event_type == EventType.HEALTH_CRITICAL for e in events)

    # ── Deduplication ─────────────────────────────────────────────────────────

    def test_dedup_within_window(self) -> None:
        """Same event should not fire twice within dedup window."""
        events1 = self.engine.process(_state(player_dead=True))
        assert any(e.event_type == EventType.PLAYER_DIED for e in events1)
        # Immediately again — should be deduped
        self.engine._prev = _state(player_dead=False)  # reset prev
        events2 = self.engine.process(_state(player_dead=True))
        assert not any(e.event_type == EventType.PLAYER_DIED for e in events2)

    def test_event_after_dedup_window(self) -> None:
        """Event should fire again after the dedup window expires."""
        self.engine.process(_state(player_dead=True))
        # Wind the clock forward past the dedup window
        self.engine._last_emit[EventType.PLAYER_DIED] = time.perf_counter() - 999
        self.engine._prev = _state(player_dead=False)
        events = self.engine.process(_state(player_dead=True))
        assert any(e.event_type == EventType.PLAYER_DIED for e in events)

    # ── No false positives on no-change ───────────────────────────────────────

    def test_no_events_on_stable_state(self) -> None:
        stable = _state(health=100, credits=4000, buy_phase=False)
        self.engine.process(stable)
        events = self.engine.process(stable)
        assert events == []

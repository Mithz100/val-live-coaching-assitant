"""Unit tests for Pydantic game state models."""

from __future__ import annotations

import time

import pytest

from models import (
    ConfidenceMap,
    EventType,
    GameEvent,
    GameState,
    KillfeedEntry,
    OcrResult,
    RoundResult,
)


class TestGameState:
    def test_defaults(self) -> None:
        s = GameState()
        assert s.health is None
        assert s.buy_phase is False
        assert s.player_dead is False
        assert s.killfeed == []

    def test_to_json_roundtrip(self) -> None:
        s = GameState(
            frame_id=42,
            health=85,
            credits=3900,
            buy_phase=True,
            round_result=RoundResult.VICTORY,
        )
        j = s.to_json()
        assert j["frame_id"] == 42
        assert j["health"] == 85
        assert j["credits"] == 3900
        assert j["buy_phase"] is True
        assert j["round_result"] == "VICTORY"

    def test_killfeed_entries(self) -> None:
        entry = KillfeedEntry(raw_text="Player1 killed Player2", confidence=0.9)
        s = GameState(killfeed=[entry])
        j = s.to_json()
        assert len(j["killfeed"]) == 1
        assert j["killfeed"][0]["raw_text"] == "Player1 killed Player2"

    def test_confidence_map(self) -> None:
        conf = ConfidenceMap(health=0.95, credits=0.8)
        s = GameState(confidence=conf)
        assert s.confidence.health == 0.95
        assert s.confidence.credits == 0.8
        assert s.confidence.armor == 0.0


class TestGameEvent:
    def test_event_type_values(self) -> None:
        assert EventType.ROUND_STARTED.value == "ROUND_STARTED"
        assert EventType.SPIKE_PLANTED.value == "SPIKE_PLANTED"
        assert EventType.LOW_ECONOMY.value == "LOW_ECONOMY"

    def test_event_to_json(self) -> None:
        ev = GameEvent(
            event_type=EventType.PLAYER_DIED,
            frame_id=100,
            confidence=0.95,
            payload={"weapon": "Vandal"},
        )
        j = ev.to_json()
        assert j["event_type"] == "PLAYER_DIED"
        assert j["frame_id"] == 100
        assert j["confidence"] == 0.95
        assert j["payload"]["weapon"] == "Vandal"

    def test_timestamp_auto_set(self) -> None:
        before = time.time()
        ev = GameEvent(event_type=EventType.ROUND_STARTED)
        after = time.time()
        assert before <= ev.timestamp <= after


class TestOcrResult:
    def test_basic(self) -> None:
        r = OcrResult(text="100", confidence=0.97, region="health")
        assert r.text == "100"
        assert r.confidence == pytest.approx(0.97)

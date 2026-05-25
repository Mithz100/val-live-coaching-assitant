"""
Stateful event detection engine.

Compares successive GameStates and emits discrete GameEvents when meaningful
transitions occur.  Events are deduplicated within a configurable time window
so a single real event never fires a burst of duplicates.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from config import settings
from models import EventType, GameEvent, GameState

logger = logging.getLogger(__name__)


class EventEngine:
    """
    Maintains previous GameState and emits events on transitions.

    Usage:
        engine = EventEngine()
        events = engine.process(new_state)
        # events is a (possibly empty) list of GameEvent
    """

    def __init__(self) -> None:
        self._prev: Optional[GameState] = None
        # Maps EventType → last emit timestamp (perf_counter)
        self._last_emit: dict[EventType, float] = {}

    def process(self, state: GameState) -> list[GameEvent]:
        events: list[GameEvent] = []

        if self._prev is None:
            self._prev = state
            return events

        prev = self._prev

        # ── Buy phase transitions ─────────────────────────────────────────────
        if state.buy_phase and not prev.buy_phase:
            self._emit(events, EventType.BUY_PHASE_STARTED, state)
        elif not state.buy_phase and prev.buy_phase:
            self._emit(events, EventType.BUY_PHASE_ENDED, state)
            self._emit(events, EventType.ROUND_STARTED, state)

        # ── Round ended ───────────────────────────────────────────────────────
        if state.round_result is not None and prev.round_result is None:
            self._emit(
                events,
                EventType.ROUND_ENDED,
                state,
                payload={"result": state.round_result},
            )

        # ── Player death / respawn ────────────────────────────────────────────
        if state.player_dead and not prev.player_dead:
            self._emit(events, EventType.PLAYER_DIED, state)
        elif not state.player_dead and prev.player_dead:
            self._emit(events, EventType.PLAYER_RESPAWNED, state)

        # ── Spike events ──────────────────────────────────────────────────────
        if state.spike_planted and not prev.spike_planted:
            self._emit(events, EventType.SPIKE_PLANTED, state)
        if state.spike_defused and not prev.spike_defused:
            self._emit(events, EventType.SPIKE_DEFUSED, state)

        # ── Economy events ────────────────────────────────────────────────────
        credits = state.credits
        prev_credits = prev.credits

        if credits is not None and not state.buy_phase:
            # LOW_ECONOMY: credits dropped into danger zone
            if credits < settings.low_economy_threshold:
                if prev_credits is None or prev_credits >= settings.low_economy_threshold:
                    self._emit(
                        events,
                        EventType.LOW_ECONOMY,
                        state,
                        payload={"credits": credits},
                    )

            # FORCE_BUY: credits between low and full-buy threshold
            elif credits < settings.force_buy_threshold:
                if prev_credits is None or prev_credits >= settings.force_buy_threshold:
                    self._emit(
                        events,
                        EventType.FORCE_BUY_DETECTED,
                        state,
                        payload={"credits": credits},
                    )

        # ── Health critical ───────────────────────────────────────────────────
        if (
            state.health is not None
            and state.health < 30
            and not state.player_dead
        ):
            if prev.health is None or prev.health >= 30:
                self._emit(
                    events,
                    EventType.HEALTH_CRITICAL,
                    state,
                    payload={"health": state.health},
                )

        self._prev = state
        return events

    # ── Internal ──────────────────────────────────────────────────────────────

    def _emit(
        self,
        bucket: list[GameEvent],
        event_type: EventType,
        state: GameState,
        *,
        payload: Optional[dict] = None,
        confidence: Optional[float] = None,
    ) -> None:
        """Append event to bucket after deduplication check."""
        now = time.perf_counter()
        last = self._last_emit.get(event_type, 0.0)

        if now - last < settings.event_dedup_window_s:
            logger.debug(
                "Deduped %s (%.2fs since last emit)", event_type, now - last
            )
            return

        self._last_emit[event_type] = now

        # Determine confidence from the relevant state field
        if confidence is None:
            conf_map = {
                EventType.BUY_PHASE_STARTED: state.confidence.buy_phase,
                EventType.BUY_PHASE_ENDED: state.confidence.buy_phase,
                EventType.ROUND_STARTED: 1.0,
                EventType.ROUND_ENDED: state.confidence.round_result,
                EventType.PLAYER_DIED: state.confidence.player_dead,
                EventType.PLAYER_RESPAWNED: state.confidence.player_dead,
                EventType.SPIKE_PLANTED: state.confidence.spike_planted,
                EventType.SPIKE_DEFUSED: state.confidence.spike_defused,
                EventType.LOW_ECONOMY: state.confidence.credits,
                EventType.FORCE_BUY_DETECTED: state.confidence.credits,
                EventType.HEALTH_CRITICAL: state.confidence.health,
            }
            confidence = conf_map.get(event_type, 1.0)

        event = GameEvent(
            event_type=event_type,
            frame_id=state.frame_id,
            confidence=confidence,
            payload=payload or {},
        )
        bucket.append(event)
        logger.info("EVENT %s conf=%.2f payload=%s", event_type, confidence, payload)

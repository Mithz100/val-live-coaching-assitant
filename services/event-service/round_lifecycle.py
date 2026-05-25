"""
Round lifecycle state machine.

States:
  IDLE ──► BUY_PHASE ──► COMBAT ──► [POST_PLANT] ──► ENDED ──► IDLE
                                        ↑                │
                                        └────────────────┘ (next round)

Timeout handling ensures the machine never gets stuck:
  - BUY_PHASE times out → COMBAT
  - COMBAT + ENDED times out → IDLE reset
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from config import settings
from models.schemas import RawEventType, RoundPhase, RoundResult, RoundState

logger = logging.getLogger(__name__)


class RoundLifecycleEngine:
    """
    Processes raw events and maintains the current RoundState.
    Emits callbacks when the phase changes so the pipeline can react.
    """

    def __init__(self) -> None:
        self._state = RoundState()
        self._timeout_task: Optional[asyncio.Task] = None

    @property
    def state(self) -> RoundState:
        return self._state

    def process_event(self, event_type: str, payload: dict) -> None:
        """Update round state in response to a raw event."""
        et = event_type

        if et == RawEventType.BUY_PHASE_STARTED:
            self._transition_to_buy_phase()

        elif et == RawEventType.BUY_PHASE_ENDED or et == RawEventType.ROUND_STARTED:
            self._transition_to_combat()

        elif et == RawEventType.SPIKE_PLANTED:
            self._transition_to_post_plant()

        elif et == RawEventType.ROUND_ENDED:
            result_str = payload.get("result", "UNKNOWN")
            try:
                result = RoundResult(result_str.upper())
            except ValueError:
                result = RoundResult.UNKNOWN
            self._transition_to_ended(result)

        elif et == RawEventType.PLAYER_DIED:
            self._state.death_count += 1

        elif et == RawEventType.FORCE_BUY_DETECTED:
            credits = payload.get("credits")
            if credits is not None:
                self._state.credits_at_buy = credits

        elif et == RawEventType.HEALTH_CRITICAL:
            pass  # tracked in rule context via game-state snapshot

    def record_semantic_event(self, event_type: str) -> None:
        if event_type not in self._state.semantic_events:
            self._state.semantic_events.append(event_type)

    def record_solo_peek(self) -> None:
        self._state.solo_peek_count += 1

    def mark_utility_used(self) -> None:
        self._state.utility_used = True

    # ── Transitions ───────────────────────────────────────────────────────────

    def _transition_to_buy_phase(self) -> None:
        if self._state.phase == RoundPhase.ENDED:
            self._state.round_number += 1
        self._state = RoundState(
            round_number=self._state.round_number,
            phase=RoundPhase.BUY_PHASE,
            phase_started_at=time.time(),
            buy_phase_started_at=time.time(),
        )
        logger.info("Round %d → BUY_PHASE", self._state.round_number)
        self._arm_timeout(settings.buy_phase_max_s, self._timeout_buy_phase)

    def _transition_to_combat(self) -> None:
        if self._state.phase not in (RoundPhase.BUY_PHASE, RoundPhase.IDLE):
            return
        now = time.time()
        self._state.phase = RoundPhase.COMBAT
        self._state.phase_started_at = now
        self._state.round_started_at = now
        self._state.combat_started_at = now
        logger.info("Round %d → COMBAT", self._state.round_number)
        self._arm_timeout(settings.round_timeout_s, self._timeout_round)

    def _transition_to_post_plant(self) -> None:
        if self._state.phase != RoundPhase.COMBAT:
            return
        now = time.time()
        self._state.phase = RoundPhase.POST_PLANT
        self._state.phase_started_at = now
        self._state.spike_planted_at = now
        logger.info("Round %d → POST_PLANT", self._state.round_number)

    def _transition_to_ended(self, result: RoundResult) -> None:
        now = time.time()
        self._state.phase = RoundPhase.ENDED
        self._state.phase_started_at = now
        self._state.ended_at = now
        self._state.result = result
        logger.info(
            "Round %d → ENDED (%s) survival=%.1fs",
            self._state.round_number,
            result,
            self._state.survival_time_s or 0,
        )
        self._cancel_timeout()

    # ── Timeout handling ──────────────────────────────────────────────────────

    def _arm_timeout(self, delay: float, callback) -> None:
        self._cancel_timeout()
        loop = asyncio.get_event_loop()
        self._timeout_task = loop.call_later(delay, callback)

    def _cancel_timeout(self) -> None:
        if self._timeout_task:
            self._timeout_task.cancel()
            self._timeout_task = None

    def _timeout_buy_phase(self) -> None:
        if self._state.phase == RoundPhase.BUY_PHASE:
            logger.warning("Buy phase timeout — forcing COMBAT transition")
            self._transition_to_combat()

    def _timeout_round(self) -> None:
        if self._state.phase in (RoundPhase.COMBAT, RoundPhase.POST_PLANT):
            logger.warning("Round timeout — forcing ENDED transition")
            self._transition_to_ended(RoundResult.UNKNOWN)

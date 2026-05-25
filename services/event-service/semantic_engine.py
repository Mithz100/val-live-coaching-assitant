"""
Semantic analysis engine.

Orchestrates:
  1. Build a RuleContext from the current raw event + world state.
  2. Pass context through the RuleEngine.
  3. Return semantic events for broadcasting and persistence.

This module is stateless — all mutable state lives in RoundLifecycleEngine
and PlayerProfile (passed in by the pipeline).
"""

from __future__ import annotations

import logging
import time

from config import settings
from consumer import EventConsumer
from models.schemas import (
    PlayerProfile,
    RawEvent,
    RoundState,
    RuleContext,
    SemanticEvent,
)
from rule_engine import RuleEngine

logger = logging.getLogger(__name__)


class SemanticEngine:
    def __init__(self, consumer: EventConsumer) -> None:
        self._consumer = consumer
        self._rule_engine = RuleEngine()

    def process(
        self,
        event: RawEvent,
        round_state: RoundState,
        player_profile: PlayerProfile,
    ) -> list[SemanticEvent]:
        """
        Build context and run all rules.  Returns a (possibly empty) list
        of SemanticEvents — never raises.
        """
        t0 = time.perf_counter()

        gs = self._consumer.latest_game_state
        ctx = RuleContext(
            triggering_event=event,
            round_state=round_state,
            player_profile=player_profile,
            recent_events=self._consumer.recent_events(10),
            health=gs.get("health"),
            armor=gs.get("armor"),
            credits=gs.get("credits"),
            ammo_current=gs.get("ammo_current"),
            buy_phase=gs.get("buy_phase", False),
            spike_planted=gs.get("spike_planted", False),
        )

        results = self._rule_engine.evaluate(ctx)

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if elapsed_ms > 100:
            logger.warning(
                "Semantic engine took %.1fms (target <100ms)", elapsed_ms
            )

        return results

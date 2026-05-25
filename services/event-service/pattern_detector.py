"""
Cross-round behavioral pattern detector.

Analyses a rolling window of recent RoundSummaries and semantic events
to identify repeated habits: consistent force buys, repeated solo peek
deaths, worsening economy trends, etc.

All detection is statistical — no ML model required.
"""

from __future__ import annotations

import logging
from collections import Counter, deque

from config import settings
from models.schemas import DetectedPattern, RoundSummary, SemanticEventType

logger = logging.getLogger(__name__)

_WINDOW = settings.pattern_window_rounds
_MIN    = settings.pattern_min_occurrences
_CONF   = settings.pattern_confidence_min


class PatternDetector:
    """
    Maintains a rolling deque of recent round summaries and emits
    DetectedPattern objects whenever a threshold is crossed.
    """

    def __init__(self) -> None:
        self._summaries: deque[RoundSummary] = deque(maxlen=_WINDOW)
        # semantic_event_type → list of round_numbers where it occurred
        self._event_rounds: dict[str, list[int]] = {}

    def add_round(self, summary: RoundSummary, semantic_events: list[str]) -> None:
        self._summaries.append(summary)
        for ev_type in semantic_events:
            self._event_rounds.setdefault(ev_type, []).append(summary.round_number)

    def detect(self) -> list[DetectedPattern]:
        """Run all pattern checks and return any newly confirmed patterns."""
        patterns: list[DetectedPattern] = []
        window = list(self._summaries)

        if len(window) < _MIN:
            return patterns

        patterns += self._check_repeated_semantic(window, SemanticEventType.SOLO_PEEK_DEATH,
            "REPEATED_SOLO_PEEK_DEATHS",
            "Consistently taking isolated, unsupported peeks resulting in early deaths.")

        patterns += self._check_repeated_semantic(window, SemanticEventType.LOW_VALUE_FORCE_BUY,
            "REPEATED_FORCE_BUYS",
            "Force buying multiple rounds in a row — economy never recovers.")

        patterns += self._check_repeated_semantic(window, SemanticEventType.EARLY_ROUND_DEATH,
            "REPEATED_EARLY_DEATHS",
            "Dying early in the round repeatedly, removing presence from key areas.")

        patterns += self._check_repeated_semantic(window, SemanticEventType.UNUSED_UTILITY_DEATH,
            "REPEATED_UNUSED_UTILITY",
            "Consistently dying without deploying utility — wasted investment each round.")

        patterns += self._check_repeated_semantic(window, SemanticEventType.HIGH_RISK_REPEEK,
            "REPEATED_LOW_HEALTH_FIGHTS",
            "Re-engaging when critically low on HP across multiple rounds.")

        patterns += self._check_aggression_trend(window)
        patterns += self._check_economy_trend(window)
        patterns += self._check_survival_trend(window)

        # Filter by confidence
        return [p for p in patterns if p.confidence >= _CONF]

    # ── Semantic-event pattern check ──────────────────────────────────────────

    def _check_repeated_semantic(
        self,
        window: list[RoundSummary],
        event_type: SemanticEventType,
        pattern_name: str,
        description: str,
    ) -> list[DetectedPattern]:
        key = event_type.value
        rounds_with_event = [
            s.round_number
            for s in window
            if key in s.semantic_events
        ]
        count = len(rounds_with_event)
        if count < _MIN:
            return []

        confidence = min(count / _WINDOW, 1.0)
        return [DetectedPattern(
            pattern_type=pattern_name,
            occurrences=count,
            window_rounds=_WINDOW,
            confidence=confidence,
            description=description,
            first_seen_round=rounds_with_event[0],
            last_seen_round=rounds_with_event[-1],
            metadata={"rounds": rounds_with_event},
        )]

    # ── Aggression trend ──────────────────────────────────────────────────────

    def _check_aggression_trend(
        self, window: list[RoundSummary]
    ) -> list[DetectedPattern]:
        if len(window) < _MIN:
            return []
        scores = [s.aggression_score for s in window]
        avg = sum(scores) / len(scores)
        if avg < 0.70:
            return []
        confidence = min(avg, 0.95)
        return [DetectedPattern(
            pattern_type="CONSISTENT_OVERAGGRESSION",
            occurrences=len(window),
            window_rounds=_WINDOW,
            confidence=confidence,
            description=f"Average aggression score {avg:.2f} — consistently overaggressive play style.",
            first_seen_round=window[0].round_number,
            last_seen_round=window[-1].round_number,
            metadata={"avg_aggression": round(avg, 3)},
        )]

    # ── Economy trend ─────────────────────────────────────────────────────────

    def _check_economy_trend(
        self, window: list[RoundSummary]
    ) -> list[DetectedPattern]:
        bad_econ = [
            s for s in window
            if s.economy_quality.value in ("force_buy", "unknown")
        ]
        count = len(bad_econ)
        if count < _MIN:
            return []
        confidence = count / _WINDOW
        return [DetectedPattern(
            pattern_type="POOR_ECONOMY_MANAGEMENT",
            occurrences=count,
            window_rounds=_WINDOW,
            confidence=confidence,
            description=f"Poor economy management in {count}/{_WINDOW} recent rounds.",
            first_seen_round=bad_econ[0].round_number,
            last_seen_round=bad_econ[-1].round_number,
            metadata={"bad_rounds": [s.round_number for s in bad_econ]},
        )]

    # ── Survival trend ────────────────────────────────────────────────────────

    def _check_survival_trend(
        self, window: list[RoundSummary]
    ) -> list[DetectedPattern]:
        if len(window) < _MIN:
            return []
        deaths = [s for s in window if not s.survived]
        rate = len(deaths) / len(window)
        if rate < 0.70:
            return []
        confidence = rate
        return [DetectedPattern(
            pattern_type="LOW_SURVIVAL_RATE",
            occurrences=len(deaths),
            window_rounds=len(window),
            confidence=confidence,
            description=f"Dying in {len(deaths)}/{len(window)} recent rounds — very low survival discipline.",
            first_seen_round=window[0].round_number,
            last_seen_round=window[-1].round_number,
            metadata={"survival_rate": round(1 - rate, 2)},
        )]

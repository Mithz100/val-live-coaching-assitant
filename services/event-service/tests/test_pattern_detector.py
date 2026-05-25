"""Tests for the cross-round pattern detector."""

from __future__ import annotations

import pytest

from models.schemas import (
    EconomyQuality,
    RoundResult,
    RoundSummary,
    SemanticEventType,
)
from pattern_detector import PatternDetector


def _summary(
    round_number: int,
    survived: bool = True,
    economy_quality: EconomyQuality = EconomyQuality.FULL_BUY,
    aggression_score: float = 0.3,
    semantic_events: list[str] = None,
) -> RoundSummary:
    return RoundSummary(
        round_number=round_number,
        survived=survived,
        economy_quality=economy_quality,
        aggression_score=aggression_score,
        result=RoundResult.DEFEAT if not survived else RoundResult.VICTORY,
        semantic_events=semantic_events or [],
    )


class TestPatternDetector:

    def test_no_patterns_below_min_occurrences(self):
        d = PatternDetector()
        d.add_round(_summary(1, semantic_events=["SOLO_PEEK_DEATH"]), ["SOLO_PEEK_DEATH"])
        patterns = d.detect()
        # only 1 occurrence — below min 2
        solo_patterns = [p for p in patterns if "SOLO_PEEK" in p.pattern_type]
        assert len(solo_patterns) == 0

    def test_detects_repeated_solo_peeks(self):
        d = PatternDetector()
        for i in range(1, 4):
            d.add_round(
                _summary(i, semantic_events=["SOLO_PEEK_DEATH"]),
                ["SOLO_PEEK_DEATH"],
            )
        patterns = d.detect()
        names = [p.pattern_type for p in patterns]
        assert "REPEATED_SOLO_PEEK_DEATHS" in names

    def test_detects_repeated_force_buys(self):
        d = PatternDetector()
        for i in range(1, 4):
            d.add_round(
                _summary(i, economy_quality=EconomyQuality.FORCE_BUY,
                         semantic_events=["LOW_VALUE_FORCE_BUY"]),
                ["LOW_VALUE_FORCE_BUY"],
            )
        patterns = d.detect()
        names = [p.pattern_type for p in patterns]
        assert "REPEATED_FORCE_BUYS" in names

    def test_detects_overaggression(self):
        d = PatternDetector()
        for i in range(1, 6):
            d.add_round(_summary(i, aggression_score=0.85), [])
        patterns = d.detect()
        names = [p.pattern_type for p in patterns]
        assert "CONSISTENT_OVERAGGRESSION" in names

    def test_detects_low_survival_rate(self):
        d = PatternDetector()
        for i in range(1, 6):
            d.add_round(_summary(i, survived=False), [])
        patterns = d.detect()
        names = [p.pattern_type for p in patterns]
        assert "LOW_SURVIVAL_RATE" in names

    def test_no_patterns_on_clean_play(self):
        d = PatternDetector()
        for i in range(1, 6):
            d.add_round(_summary(i, survived=True, aggression_score=0.2), [])
        patterns = d.detect()
        assert len(patterns) == 0

    def test_pattern_has_correct_round_range(self):
        d = PatternDetector()
        for i in [3, 4, 5]:
            d.add_round(
                _summary(i, semantic_events=["EARLY_ROUND_DEATH"]),
                ["EARLY_ROUND_DEATH"],
            )
        patterns = [p for p in d.detect() if p.pattern_type == "REPEATED_EARLY_DEATHS"]
        assert patterns
        p = patterns[0]
        assert p.first_seen_round == 3
        assert p.last_seen_round == 5

    def test_pattern_confidence_increases_with_occurrences(self):
        d1 = PatternDetector()
        d2 = PatternDetector()
        for i in range(1, 3):
            d1.add_round(_summary(i, semantic_events=["SOLO_PEEK_DEATH"]), ["SOLO_PEEK_DEATH"])
        for i in range(1, 6):
            d2.add_round(_summary(i, semantic_events=["SOLO_PEEK_DEATH"]), ["SOLO_PEEK_DEATH"])

        def _conf(d):
            ps = [p for p in d.detect() if p.pattern_type == "REPEATED_SOLO_PEEK_DEATHS"]
            return ps[0].confidence if ps else 0.0

        assert _conf(d2) >= _conf(d1)

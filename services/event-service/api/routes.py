"""REST API routes for the event service."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from memory import db_store
from pipeline import EventPipeline

router = APIRouter()

# Injected by server.py after pipeline is created
_pipeline: EventPipeline | None = None


def set_pipeline(p: EventPipeline) -> None:
    global _pipeline
    _pipeline = p


def _require_pipeline() -> EventPipeline:
    if _pipeline is None:
        raise HTTPException(503, "Pipeline not ready")
    return _pipeline


@router.get("/health")
async def health():
    p = _require_pipeline()
    profile = p._profile_mgr.profile
    return {
        "status": "ok",
        "session_id": p.session_id,
        "rounds_tracked": profile.rounds_tracked,
        "round_number": p._lifecycle.state.round_number,
        "round_phase": p._lifecycle.state.phase.value,
    }


@router.get("/round/current")
async def current_round():
    p = _require_pipeline()
    rs = p._lifecycle.state
    return {
        "round_number": rs.round_number,
        "phase": rs.phase.value,
        "death_count": rs.death_count,
        "solo_peek_count": rs.solo_peek_count,
        "utility_used": rs.utility_used,
        "credits_at_buy": rs.credits_at_buy,
        "survival_time_s": rs.survival_time_s,
        "semantic_events": rs.semantic_events,
    }


@router.get("/round/recent")
async def recent_rounds(limit: int = 5):
    p = _require_pipeline()
    rows = await db_store.get_recent_rounds(p.session_id, limit=min(limit, 20))
    return {"rounds": rows}


@router.get("/player/profile")
async def player_profile():
    p = _require_pipeline()
    return p._profile_mgr.profile.to_dict()


@router.get("/player/mistakes")
async def recent_mistakes(limit: int = 10):
    p = _require_pipeline()
    rows = await db_store.get_recent_semantic_events(p.session_id, limit=min(limit, 50))
    # Filter to mistakes only
    mistake_types = {
        "SOLO_PEEK_DEATH", "LOW_VALUE_FORCE_BUY", "UNUSED_UTILITY_DEATH",
        "HIGH_RISK_REPEEK", "EARLY_ROUND_DEATH", "LOW_ECON_IMPULSE_BUY",
        "AGGRESSIVE_OVEREXTENSION", "CONSISTENT_ECON_MISTAKE",
        "LOW_HEALTH_ENGAGEMENT", "REPEATED_DEATH_PATTERN",
    }
    return {
        "mistakes": [r for r in rows if r["event_type"] in mistake_types]
    }


@router.get("/player/tendencies")
async def player_tendencies():
    p = _require_pipeline()
    prof = p._profile_mgr.profile
    return {
        "aggression_level": _level(prof.avg_aggression_score, 0.35, 0.65),
        "economy_discipline": _level(prof.avg_economy_discipline, 0.4, 0.7),
        "survival_discipline": _level(prof.avg_survival_rate, 0.4, 0.65),
        "force_buy_frequency": prof.force_buy_frequency,
        "early_death_frequency": prof.early_death_frequency,
        "solo_peek_frequency": prof.solo_peek_frequency,
        "top_mistakes": _top_mistakes(prof.mistake_counts, n=3),
        "active_patterns": prof.active_patterns,
    }


@router.get("/analytics/economy")
async def economy_analytics():
    p = _require_pipeline()
    rounds = await db_store.get_recent_rounds(p.session_id, limit=10)
    eco_counts: dict[str, int] = {}
    for r in rounds:
        q = r.get("economy_quality", "unknown")
        eco_counts[q] = eco_counts.get(q, 0) + 1
    return {
        "round_count": len(rounds),
        "economy_distribution": eco_counts,
        "force_buy_total": p._profile_mgr.profile.total_force_buys,
    }


@router.get("/analytics/aggression")
async def aggression_analytics():
    p = _require_pipeline()
    rounds = await db_store.get_recent_rounds(p.session_id, limit=10)
    scores = [r.get("aggression_score", 0.0) for r in rounds]
    avg = sum(scores) / len(scores) if scores else 0.0
    return {
        "avg_aggression": round(avg, 3),
        "total_solo_peek_deaths": p._profile_mgr.profile.total_solo_peek_deaths,
        "aggression_trend": _trend(scores),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _level(value: float, low: float, high: float) -> str:
    if value < low:
        return "low"
    if value > high:
        return "high"
    return "medium"


def _top_mistakes(counts: dict[str, int], n: int) -> list[dict]:
    sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [{"type": k, "count": v} for k, v in sorted_items[:n]]


def _trend(values: list[float]) -> str:
    if len(values) < 3:
        return "insufficient_data"
    recent = sum(values[-3:]) / 3
    older = sum(values[:-3]) / max(len(values) - 3, 1)
    if recent > older + 0.1:
        return "increasing"
    if recent < older - 0.1:
        return "decreasing"
    return "stable"

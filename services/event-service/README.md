# Event Service — Phase 3

Converts raw gameplay events (from the vision service) into persistent
round memory, semantic insights, behavioral patterns, and a player profile.

> **No coaching output yet.** All output is machine-readable structured data
> consumed by the future coaching agent layer.

---

## Architecture

```
vision-service /events  ──WS──►  EventConsumer
vision-service /game-state ──WS──►  (state snapshot)
                                        │
                               RoundLifecycleEngine
                               (IDLE→BUY→COMBAT→POST_PLANT→ENDED)
                                        │
                                SemanticEngine
                                        │
                                  RuleEngine
                                (11 configurable rules)
                                        │
                               SemanticEvent[]
                                   │         │
                              DB persist   Broadcast
                                        │
                           (on ROUND_ENDED)
                                        │
                    ┌───────────────────┼────────────────────┐
                    ▼                   ▼                     ▼
              RoundSummary       PatternDetector       PlayerProfile
              (structured)      (rolling window)       (EMA metrics)
                    │                   │                     │
              DB persist          DB persist             DB persist
                    │                   │                     │
                    └───────────────────┴──────────── WS Broadcast ──► coaching-agent
```

### Module responsibilities

| Module | Role |
|---|---|
| `config.py` | All thresholds and settings via env vars |
| `models/schemas.py` | All Pydantic schemas: raw events, semantic events, round state, player profile |
| `models/db.py` | SQLAlchemy ORM — 8 tables |
| `memory/redis_store.py` | Hot k/v cache; falls back to in-memory dict when Redis absent |
| `memory/db_store.py` | All async DB read/write operations |
| `consumer.py` | Dual WS consumer (events + game-state) with dedup and reconnect |
| `round_lifecycle.py` | Round phase state machine with timeout safety |
| `rule_engine.py` | 11 pure-function gameplay rules → SemanticEvents |
| `semantic_engine.py` | Builds RuleContext, runs engine, tracks latency |
| `player_profile.py` | EMA-based behavioral metrics; persisted after each round |
| `pattern_detector.py` | Rolling-window cross-round pattern detection |
| `round_summary.py` | Structured round summary — no natural language |
| `pipeline.py` | Main async orchestration loop |
| `server.py` | FastAPI + WebSocket broadcast manager |
| `api/routes.py` | REST query endpoints |
| `api/ws_routes.py` | WebSocket streaming endpoints |
| `debug_dashboard.py` | Terminal live view of all channels |

---

## Quick Start

### Prerequisites

- capture-service running on `ws://localhost:8000/stream`
- vision-service running on `ws://localhost:8100`

### Install & Run

```powershell
pip install -r requirements.txt

cd services/event-service
python server.py
```

Service starts on port `8200`.

### Debug dashboard

```powershell
python debug_dashboard.py
```

Prints a live colour-coded terminal feed of all event channels.

---

## Semantic Events

Each raw event triggers rule evaluation. Rules that fire emit a `SemanticEvent`:

```json
{
  "event_type": "SOLO_PEEK_DEATH",
  "timestamp": 1716000100.0,
  "round_number": 5,
  "confidence": 0.75,
  "source_events": ["PLAYER_DIED"],
  "explanation": "Died with high health early in the round — likely an unsupported solo peek with poor trade potential.",
  "metadata": {"time_into_round": 18.4}
}
```

### All semantic event types

| Event | Trigger condition |
|---|---|
| `SOLO_PEEK_DEATH` | Died at high HP early in round, no prior HEALTH_CRITICAL |
| `LOW_VALUE_FORCE_BUY` | FORCE_BUY with credits < 2900 |
| `UNUSED_UTILITY_DEATH` | Died without utility_used flag set |
| `HIGH_RISK_REPEEK` | HEALTH_CRITICAL with HP ≤ 35 |
| `EARLY_ROUND_DEATH` | Died within first 45s |
| `LOW_ECON_IMPULSE_BUY` | LOW_ECONOMY during buy phase |
| `AGGRESSIVE_OVEREXTENSION` | ≥2 solo peeks in one round |
| `CONSISTENT_ECON_MISTAKE` | 2nd+ force buy in session |
| `LOW_HEALTH_ENGAGEMENT` | HEALTH_CRITICAL fires (re-engagement risk) |
| `ECO_ROUND_DETECTED` | BUY_PHASE_ENDED with credits < 1900 |
| `POST_PLANT_DISCIPLINE` | SPIKE_PLANTED — positive signal |

---

## Round Summary Schema

```json
{
  "round_number": 8,
  "economy_quality": "force_buy",
  "aggression_score": 0.82,
  "survival_time_seconds": 34.0,
  "survived": false,
  "spike_planted": false,
  "result": "DEFEAT",
  "credits_spent": null,
  "credits_remaining": 900,
  "major_mistakes": ["SOLO_PEEK_DEATH", "LOW_VALUE_FORCE_BUY"],
  "positive_behaviors": [],
  "semantic_events": ["SOLO_PEEK_DEATH", "LOW_VALUE_FORCE_BUY", "EARLY_ROUND_DEATH"],
  "raw_event_count": 7
}
```

---

## REST API

| Endpoint | Description |
|---|---|
| `GET /health` | Service status + session info |
| `GET /round/current` | Live round state |
| `GET /round/recent?limit=5` | Last N round summaries |
| `GET /player/profile` | Full player profile |
| `GET /player/mistakes?limit=10` | Recent semantic mistake events |
| `GET /player/tendencies` | High-level behavioral classification |
| `GET /analytics/economy` | Economy distribution last 10 rounds |
| `GET /analytics/aggression` | Aggression trend + totals |

## WebSocket Channels

| Endpoint | Fires when |
|---|---|
| `ws://.../semantic-events` | Any rule fires |
| `ws://.../round-state` | Every raw event processed |
| `ws://.../round-summary` | End of each round |
| `ws://.../patterns` | End of each round (non-empty only) |
| `ws://.../profile` | End of each round |

---

## Database Schema

8 tables in SQLite (default) or PostgreSQL (production):

| Table | Content |
|---|---|
| `matches` | One row per gameplay session |
| `rounds` | One row per completed round |
| `raw_events` | Every raw event ingested |
| `semantic_events` | Every semantic event emitted |
| `economy` | Per-round economy snapshot |
| `deaths` | Every player death with context |
| `player_profiles` | Periodic player profile snapshots |
| `patterns` | Detected behavioral patterns |

Switch to PostgreSQL:
```
EVENT_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/valorant_coach
```

---

## Rule Engine — Adding New Rules

1. Write a pure function `rule_<name>(ctx: RuleContext) -> Optional[SemanticEvent]`
2. Return `None` when conditions aren't met
3. Return `_event(SemanticEventType.YOUR_TYPE, ctx, explanation="...", **metadata)` when they are
4. Add the function to `_ALL_RULES` in `rule_engine.py`
5. Add the `SemanticEventType` enum member in `models/schemas.py`
6. Write tests in `tests/test_rule_engine.py`

Rules are evaluated in registration order. The cooldown system prevents
the same semantic event type from firing more than once per `RULE_COOLDOWN_S`.

---

## Pattern Detection Logic

The `PatternDetector` keeps a rolling deque of the last `N` round summaries
(default N=5) and checks for:

- **Repeated semantic events** — same mistake occurring in ≥2 of last 5 rounds
- **Aggression trend** — average aggression score > 0.70 across window
- **Poor economy** — force_buy or unknown economy in ≥2 rounds
- **Low survival** — died in ≥70% of window rounds

Confidence = `occurrences / window_size`, filtered to ≥ `PATTERN_CONFIDENCE_MIN`.

---

## How Coaching Agents Will Consume This

Future coaching agents connect to one or more WebSocket channels:

```python
# coaching-agent sketch
async for msg in ws.connect("ws://localhost:8200/semantic-events"):
    event = json.loads(msg)
    match event["event_type"]:
        case "SOLO_PEEK_DEATH":
            coaching_tip = generate_tip(event["explanation"], event["metadata"])
        case "LOW_VALUE_FORCE_BUY":
            coaching_tip = generate_economy_advice(event)
    await overlay.display(coaching_tip)
```

Or query REST for session-level insight:
```python
profile = requests.get("http://localhost:8200/player/profile").json()
tendencies = requests.get("http://localhost:8200/player/tendencies").json()
# Use in system prompt: "Player has high aggression, low economy discipline..."
```

The event service never blocks on coaching — it emits and moves on.

---

## Running Tests

```powershell
cd services/event-service
pytest tests/ -v
```

All tests are fully offline — no database, Redis, WebSocket, or game required.

---

## Scaling Considerations

| Concern | Current | Production path |
|---|---|---|
| Database | SQLite (local) | PostgreSQL + connection pool |
| Caching | In-memory dict | Redis cluster |
| DB writes | Sequential async | Batched writes, write queue |
| Pattern detection | In-memory rolling window | PostgreSQL windowed queries |
| Multiple players | Single session | Session isolation via session_id |
| Event throughput | ~10 events/s | Kafka/Redis Streams for fan-out |

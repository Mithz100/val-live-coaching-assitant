# Vision Service — Phase 2

Converts raw gameplay frames (from the capture service) into structured
game state + discrete coaching events in real-time.

> **Vanguard Safety:** only externally captured JPEG frames are analysed.
> No game memory is read. No process injection occurs.

---

## Architecture

```
capture-service  ──WS──►  FrameIngester
                               │
                               │  IngestedFrame (latest-only cache)
                               ▼
                          VisionPipeline  (async loop @ 5 FPS)
                               │
                    ┌──────────┴────────────┐
                    ▼                       ▼
             FrameExtractor          (next iteration)
                    │
          ┌─────────┼──────────┐
          ▼         ▼          ▼
       ROI crop  Template    OCR
       + preproc  Matching   (EasyOCR)
          │         │          │
          └────────►▼◄─────────┘
                 GameState
                    │
                    ▼
              EventEngine  (stateful diff)
                    │
               GameEvent[]
                    │
          ┌─────────┴──────────┐
          ▼                    ▼
    /game-state WS        /events WS
    (every frame)     (on transition only)
```

### Module responsibilities

| Module | Role |
|---|---|
| `config.py` | All settings via env vars / `.env` |
| `models.py` | Pydantic schemas: `GameState`, `GameEvent`, `OcrResult` |
| `rois.py` | Load, scale, and serve ROI definitions |
| `rois.yaml` | Coordinate definitions for every HUD element |
| `ingestion.py` | WebSocket consumer with reconnect + latest-frame cache |
| `preprocessing.py` | Grayscale / threshold / denoise presets per ROI type |
| `ocr.py` | EasyOCR wrapper — confidence filtering, retry, stats |
| `template_matcher.py` | OpenCV multi-scale template matching |
| `extractor.py` | Orchestrates ROI → preprocess → OCR/template → `GameState` |
| `event_engine.py` | Stateful diff → `GameEvent` with deduplication |
| `pipeline.py` | Main async loop: pace, extract, emit, debug |
| `server.py` | FastAPI + two WS endpoints + `/health` |
| `debug_overlay.py` | Optional cv2 annotated frame rendering |
| `calibration.py` | Interactive ROI calibration tool |

---

## Quick Start

### Prerequisites

1. **capture-service must be running** on `ws://localhost:8000/stream`
2. Python 3.12, virtual environment activated

### Install

```powershell
pip install -r requirements.txt
# EasyOCR downloads its model on first run (~100 MB)
```

### Configure

```powershell
Copy-Item ../../.env.example .env
# Key settings:
#   VISION_CAPTURE_WS_URL=ws://localhost:8000/stream
#   VISION_ANALYSIS_FPS=5
#   VISION_OCR_GPU=false   # set true if CUDA available
#   VISION_DEBUG_MODE=false
```

### Run

```powershell
cd services/vision-service
python server.py
```

Endpoints:
- `ws://localhost:8100/game-state` — full GameState JSON every frame
- `ws://localhost:8100/events`     — GameEvent JSON on transitions only
- `http://localhost:8100/health`   — service health + stats

---

## WebSocket Examples

### game-state stream

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://localhost:8100/game-state") as ws:
        async for msg in ws:
            state = json.loads(msg)
            print(state["health"], state["credits"], state["buy_phase"])

asyncio.run(main())
```

### events stream

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://localhost:8100/events") as ws:
        async for msg in ws:
            event = json.loads(msg)
            print(event["event_type"], event["payload"])

asyncio.run(main())
```

Or use the bundled example:

```powershell
python ws_client_example.py --endpoint game-state
python ws_client_example.py --endpoint events
```

---

## GameState Schema

```json
{
  "frame_id": 1042,
  "timestamp": 1716000000.0,
  "processing_ms": 38.4,
  "round_number": 0,
  "buy_phase": false,
  "match_timer": "1:22",
  "player_dead": false,
  "health": 85,
  "armor": 25,
  "credits": 3900,
  "weapon": null,
  "ammo_current": 25,
  "ammo_reserve": 75,
  "spike_planted": false,
  "spike_defused": false,
  "round_result": null,
  "killfeed": [
    {"raw_text": "Player1 killed Player2", "confidence": 0.87, "timestamp": 1716000000.0}
  ],
  "confidence": {
    "health": 0.94,
    "armor": 0.88,
    "credits": 0.91,
    "ammo": 0.82,
    "match_timer": 0.96,
    "buy_phase": 0.0,
    "player_dead": 0.0,
    "spike_planted": 0.0,
    "spike_defused": 0.0,
    "round_result": 0.0,
    "killfeed": 0.87
  }
}
```

## Event Types

| Event | Trigger |
|---|---|
| `ROUND_STARTED` | Buy phase → live |
| `ROUND_ENDED` | Victory/defeat banner detected |
| `BUY_PHASE_STARTED` | Buy phase template matched |
| `BUY_PHASE_ENDED` | Buy phase cleared |
| `PLAYER_DIED` | Death screen detected |
| `PLAYER_RESPAWNED` | Death screen cleared |
| `SPIKE_PLANTED` | Planted template matched |
| `SPIKE_DEFUSED` | Defused template matched |
| `LOW_ECONOMY` | Credits < 2000 (configurable) |
| `FORCE_BUY_DETECTED` | Credits < 3000 (configurable) |
| `HEALTH_CRITICAL` | Health < 30 |

---

## ROI Calibration

The default coordinates in `rois.yaml` target 1920×1080 with Valorant's
default HUD scale. If OCR results look wrong, calibrate interactively:

```powershell
# Make sure capture-service is running with the game visible
python calibration.py --roi health armor credits match_timer
```

Controls:
- **LMB drag** — draw a new rectangle over the HUD element
- **S** — save this ROI and move to the next
- **R** — reset current rectangle
- **Q / ESC** — quit

The tool prints a YAML block you paste into `rois.yaml`.

---

## Adding Templates

Templates enable fast binary detection (buy phase, victory, spike planted, etc.)
without OCR.

1. Take a screenshot of the UI element you want to detect.
2. Crop just that element (tight crop — avoid background noise).
3. Save as `services/vision-service/templates/<name>.png`.
4. Add matching logic in `extractor.py` referencing the name.

Tips:
- Grays only — templates are matched in grayscale.
- Tight crops outperform large context windows.
- Test with `template_matcher.matcher.match(frame, "your_template")`.

---

## Adding a New Detector

1. **Define the ROI** in `rois.yaml` with coordinates.
2. **Add preprocessing preset** in `preprocessing.py` if the element needs
   special treatment (e.g. colored text).
3. **Extend `FrameExtractor.extract()`** to crop → preprocess → OCR/match.
4. **Add the field** to `GameState` and `ConfidenceMap`.
5. **Add transition logic** in `EventEngine.process()` if a new event type is needed.
6. **Add tests** in `tests/`.

---

## Performance Tuning

| Knob | Env var | Default | Effect |
|---|---|---|---|
| Analysis FPS | `VISION_ANALYSIS_FPS` | `5` | Lower = less CPU; higher = lower latency |
| OCR GPU | `VISION_OCR_GPU` | `false` | `true` needs CUDA — 5-10× faster OCR |
| JPEG quality (upstream) | `CAPTURE_JPEG_QUALITY` | `75` | Lower quality = faster OCR (less noise) |
| Template multi-scale | `VISION_TEMPLATE_MULTI_SCALE` | `true` | `false` = faster, less robust |
| Frame skip | `VISION_SKIP_OCR_ON_TEMPLATE_MISS` | `false` | Skip OCR when buy/death banner absent |

Profiling tip: set `VISION_BENCHMARK_MODE=true` and watch the logs for
`[BENCH]` lines showing per-frame processing time.

---

## How Coaching Agents Will Consume Events

Future coaching agents connect to `ws://localhost:8100/events` and filter
for the event types they care about:

```python
# coaching-service sketch
async for msg in ws:
    event = json.loads(msg)
    if event["event_type"] == "LOW_ECONOMY":
        advice = await economy_agent.advise(event["payload"])
        await overlay.show(advice)
    elif event["event_type"] == "SPIKE_PLANTED":
        advice = await strategy_agent.post_plant(game_state)
        await overlay.show(advice)
```

The vision service never blocks on coaching logic — it just emits.
Agents subscribe independently and can have different latency budgets.

---

## Running Tests

```powershell
cd services/vision-service
pytest tests/ -v
```

All tests are fully mocked — no GPU, no camera, no Valorant required.

# Valorant AI Coach — Capture Service

Real-time, Vanguard-safe AI coaching assistant for Valorant.
**Phase 1** delivers a low-latency screen-capture pipeline that streams JPEG frames over WebSocket.

> **Vanguard Safety Guarantee**
> The system uses only external screen capture (`dxcam`). It never reads game memory, injects into the game process, or simulates input.

---

## Project Structure

```
valorant-ai-coach/
├── apps/               # Backend API, overlay UI, dashboard
├── services/
│   └── capture-service/    ← you are here (Phase 1)
├── agents/             # Future: combat, economy, strategy agents
├── shared/             # Shared types / utilities
├── models/             # Saved ML models
├── docker/             # Container configs
├── requirements.txt
└── .env.example
```

---

## Quick Start

### 1. Create & activate virtual environment

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure

```powershell
Copy-Item .env.example .env
# Edit .env as needed
```

### 4. Run the capture service

```powershell
cd services/capture-service
python server.py
```

The service starts at `ws://localhost:8000/stream` and `http://localhost:8000/health`.

### 5. Optional: enable benchmark or debug mode

```powershell
# In .env:
CAPTURE_BENCHMARK_MODE=true
CAPTURE_DEBUG_MODE=true        # saves frames to debug_frames/
```

---

## WebSocket Protocol

Each binary message has the layout:

```
[4 bytes LE uint32 = meta_len][meta_len bytes JSON][JPEG bytes]
```

**Metadata JSON fields:**

| Field | Type | Description |
|-------|------|-------------|
| `frame_id` | int | Monotonic frame counter |
| `timestamp` | float | `time.perf_counter()` at capture |
| `fps` | float | Current capture FPS |
| `age_ms` | float | Delay from capture to encode (ms) |

---

## Example Client

```powershell
python services/capture-service/ws_client_example.py
```

Or paste this minimal snippet anywhere:

```python
import asyncio, json, struct
import numpy as np, cv2, websockets

async def main():
    async with websockets.connect("ws://localhost:8000/stream") as ws:
        while True:
            msg = await ws.recv()
            meta_len = struct.unpack_from("<I", msg)[0]
            meta = json.loads(msg[4:4+meta_len])
            jpeg = msg[4+meta_len:]
            frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            print(meta)

asyncio.run(main())
```

---

## Running Tests

```powershell
cd services/capture-service
pytest tests/ -v
```

Run the FPS benchmark (5 seconds):

```powershell
python benchmark.py --duration 5
```

---

## Architecture

```
┌─────────────────────────────────────────┐
│            capture-service              │
│                                         │
│  ┌──────────────┐   asyncio.Queue       │
│  │ ScreenCaptu- │ ──────────────────►  │
│  │ rer (thread) │   RawFrame objects    │
│  └──────────────┘                       │
│         │                               │
│    dxcam (DXGI)                         │
│    win32gui window finder               │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │  _broadcast_loop (coroutine)    │    │
│  │  • dequeues RawFrame            │    │
│  │  • JPEG-encodes via OpenCV      │    │
│  │  • pushes to all WS clients     │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌──────────────────────────────────┐   │
│  │  FastAPI  /stream  /health       │   │
│  └──────────────────────────────────┘   │
└─────────────────────────────────────────┘
         │ WebSocket binary frames
         ▼
  vision-service / overlay / dashboard
```

**Thread model:** `ScreenCapturer` lives in its own OS thread so blocking dxcam calls never stall the asyncio event loop. Frames cross the thread boundary via `loop.call_soon_threadsafe(queue.put_nowait, frame)`.

---

## Performance Notes

| Bottleneck | Impact | Mitigation |
|---|---|---|
| JPEG encode (CPU) | ~2–5 ms/frame @ 1080p | Use `opencv-python-headless`; lower quality if needed |
| dxcam DXGI capture | ~1–3 ms/frame | Already GPU-accelerated; prefer borderless-window mode in Valorant |
| WS broadcast (N clients) | Linear with clients | Keep coaching pipeline internal; only overlay should connect |
| asyncio event loop contention | Low at 10 FPS | Increase target FPS gradually; profile with `asyncio` debug mode |

**Memory stability:** frames are numpy arrays that are garbage-collected once dequeued. The queue cap (`MAX_QUEUE_SIZE=5`) prevents unbounded growth during slow consumers.

---

## Future Services

Each downstream service connects to `ws://localhost:8000/stream` and processes the JPEG frames independently:

- **vision-service** — OpenCV-based minimap/HUD parsing
- **coaching-service** — Claude API integration for advice generation
- **event-service** — aggregates parsed events into a structured game state
- **overlay** — Electron transparent overlay rendering AI suggestions

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CAPTURE_TARGET_FPS` | `10` | Capture frame rate target |
| `CAPTURE_CAPTURE_WIDTH` | `1920` | Expected game resolution width |
| `CAPTURE_CAPTURE_HEIGHT` | `1080` | Expected game resolution height |
| `CAPTURE_GAME_WINDOW_TITLE` | `VALORANT` | Window title fragment to locate |
| `CAPTURE_JPEG_QUALITY` | `75` | JPEG quality (10–100) |
| `CAPTURE_WS_HOST` | `0.0.0.0` | WebSocket server bind host |
| `CAPTURE_WS_PORT` | `8000` | WebSocket server port |
| `CAPTURE_MAX_QUEUE_SIZE` | `5` | Internal frame queue depth |
| `CAPTURE_DEBUG_MODE` | `false` | Save annotated debug frames |
| `CAPTURE_FRAME_SAVE_INTERVAL` | `5.0` | Seconds between debug frame saves |
| `CAPTURE_FRAME_SAVE_DIR` | `debug_frames` | Debug frame output directory |
| `CAPTURE_BENCHMARK_MODE` | `false` | Emit benchmark logs periodically |
| `CAPTURE_BENCHMARK_LOG_INTERVAL` | `5.0` | Seconds between benchmark log lines |

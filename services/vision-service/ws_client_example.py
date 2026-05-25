"""
Example WebSocket clients for the vision service.

Usage:
    # Stream game state
    python ws_client_example.py --endpoint game-state

    # Stream events only
    python ws_client_example.py --endpoint events
"""

from __future__ import annotations

import argparse
import asyncio
import json

import websockets

BASE = "ws://localhost:8100"


async def listen(endpoint: str) -> None:
    url = f"{BASE}/{endpoint}"
    print(f"Connecting to {url} …\n")

    async with websockets.connect(url) as ws:
        print(f"Connected to /{endpoint}. Waiting for messages…\n")
        async for message in ws:
            data = json.loads(message)

            if endpoint == "game-state":
                print(
                    f"[frame {data.get('frame_id'):>6}] "
                    f"HP={data.get('health')}  "
                    f"armor={data.get('armor')}  "
                    f"credits={data.get('credits')}  "
                    f"timer={data.get('match_timer')}  "
                    f"buy={data.get('buy_phase')}  "
                    f"dead={data.get('player_dead')}  "
                    f"proc={data.get('processing_ms', 0):.1f}ms"
                )
            elif endpoint == "events":
                ev = data.get("event_type", "?")
                conf = data.get("confidence", 0)
                payload = data.get("payload", {})
                print(f"🔔  EVENT  {ev:<28}  conf={conf:.2f}  {payload}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoint",
        choices=["game-state", "events"],
        default="game-state",
    )
    args = parser.parse_args()
    asyncio.run(listen(args.endpoint))

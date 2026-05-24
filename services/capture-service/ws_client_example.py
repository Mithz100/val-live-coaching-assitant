"""
Example WebSocket client for the capture service.

Protocol
--------
Each binary message is:
  [4 bytes LE = meta_len][meta JSON bytes][JPEG bytes]

Run:
  python ws_client_example.py
"""

from __future__ import annotations

import asyncio
import json
import struct
import time

import cv2
import numpy as np
import websockets


URI = "ws://localhost:8000/stream"


async def receive_frames() -> None:
    print(f"Connecting to {URI} …")
    async with websockets.connect(URI, max_size=10 * 1024 * 1024) as ws:
        print("Connected. Press Ctrl+C to stop.\n")
        while True:
            message = await ws.recv()
            if not isinstance(message, bytes):
                continue

            meta_len = struct.unpack_from("<I", message, 0)[0]
            meta = json.loads(message[4 : 4 + meta_len])
            jpeg = message[4 + meta_len :]

            arr = np.frombuffer(jpeg, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)

            print(
                f"frame_id={meta['frame_id']:>8}  "
                f"fps={meta['fps']:>5.1f}  "
                f"age={meta['age_ms']:>5.1f}ms  "
                f"size={len(jpeg)//1024:>4}KB"
            )

            # Optionally display with OpenCV (comment out in headless environments)
            if frame is not None:
                cv2.imshow("Capture Stream", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    asyncio.run(receive_frames())

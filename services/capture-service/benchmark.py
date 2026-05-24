"""
Standalone benchmark runner.

Starts the capturer for N seconds and prints a summary report.
Run with:  python benchmark.py --duration 30
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from capturer import ScreenCapturer
from models import RawFrame

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("benchmark")


async def run(duration: int) -> None:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[RawFrame] = asyncio.Queue(maxsize=30)

    capturer = ScreenCapturer(loop, queue)
    capturer.start()

    logger.info("Benchmark running for %d seconds…", duration)
    t_end = time.perf_counter() + duration

    drained = 0
    while time.perf_counter() < t_end:
        try:
            _ = queue.get_nowait()
            drained += 1
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.01)

    capturer.stop()
    s = capturer.stats

    print("\n" + "=" * 50)
    print("BENCHMARK RESULTS")
    print("=" * 50)
    print(f"Duration         : {duration}s")
    print(f"Total captured   : {s.total_frames}")
    print(f"Dropped (queue)  : {s.dropped_frames}")
    print(f"Drop rate        : {s.dropped_frames / max(s.total_frames, 1) * 100:.2f}%")
    print(f"Avg FPS          : {s.fps_avg:.2f}")
    print(f"Last latency     : {s.latency_ms_last:.2f} ms")
    print("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=30)
    args = parser.parse_args()
    asyncio.run(run(args.duration))

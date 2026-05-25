"""
ROI Calibration Utility.

Captures a single frame from the capture service, displays it in a cv2 window,
and lets you interactively drag new ROI rectangles.  Prints the resulting YAML
block so you can paste it into rois.yaml.

Run:
    python calibration.py [--roi health]

Controls:
    LMB drag  → draw new ROI rectangle
    R         → reset current rectangle
    S         → save / print ROI YAML and move to next ROI
    Q / ESC   → quit without saving
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import struct
import sys

import cv2
import numpy as np
import websockets

from config import settings
from rois import ROI_PRESET_MAP, registry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("calibration")

# ROIs to calibrate when none specified
DEFAULT_ROI_ORDER = [
    "health",
    "armor",
    "credits",
    "ammo_current",
    "ammo_reserve",
    "match_timer",
    "killfeed",
    "buy_phase_banner",
    "round_result_banner",
    "spike_status",
]


async def fetch_frame() -> np.ndarray:
    """Grab a single frame from the capture service."""
    logger.info("Connecting to %s to grab a calibration frame…", settings.capture_ws_url)
    async with websockets.connect(settings.capture_ws_url, max_size=20 * 1024 * 1024) as ws:
        msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
        meta_len = struct.unpack_from("<I", msg)[0]
        jpeg = msg[4 + meta_len :]
        arr = np.frombuffer(jpeg, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("Failed to decode frame from capture service")
        logger.info("Got frame %dx%d", frame.shape[1], frame.shape[0])
        return frame


def calibrate_roi(frame: np.ndarray, roi_name: str) -> dict | None:
    """Interactive ROI selector.  Returns dict with x,y,w,h or None on cancel."""
    window = f"Calibrate: {roi_name} (drag rect, S=save, R=reset, Q=quit)"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, 1280, 720)

    # Show existing ROI if any
    existing = registry.get(roi_name)
    rect: list[int | None] = [None, None, None, None]  # x1, y1, x2, y2
    drawing = False

    # Scale factor for display vs actual
    dw, dh = 1280, 720
    fx = dw / frame.shape[1]
    fy = dh / frame.shape[0]

    def mouse_cb(event, x, y, flags, _):
        nonlocal drawing
        # Convert display coords → frame coords
        fx_ = frame.shape[1] / dw
        fy_ = frame.shape[0] / dh
        rx, ry = int(x * fx_), int(y * fy_)

        if event == cv2.EVENT_LBUTTONDOWN:
            drawing = True
            rect[0], rect[1] = rx, ry
            rect[2], rect[3] = rx, ry
        elif event == cv2.EVENT_MOUSEMOVE and drawing:
            rect[2], rect[3] = rx, ry
        elif event == cv2.EVENT_LBUTTONUP:
            drawing = False
            rect[2], rect[3] = rx, ry

    cv2.setMouseCallback(window, mouse_cb)

    while True:
        display = cv2.resize(frame.copy(), (dw, dh))

        # Draw existing ROI in blue
        if existing:
            x1e = int(existing.x * fx)
            y1e = int(existing.y * fy)
            x2e = int((existing.x + existing.w) * fx)
            y2e = int((existing.y + existing.h) * fy)
            cv2.rectangle(display, (x1e, y1e), (x2e, y2e), (255, 100, 0), 1)
            cv2.putText(display, f"current: {roi_name}", (x1e, max(0, y1e - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 100, 0), 1)

        # Draw new selection in green
        if rect[0] is not None and rect[2] is not None:
            x1d = int(rect[0] * fx)
            y1d = int(rect[1] * fy)
            x2d = int(rect[2] * fx)
            y2d = int(rect[3] * fy)
            cv2.rectangle(display, (x1d, y1d), (x2d, y2d), (0, 255, 0), 2)

        cv2.putText(display, f"ROI: {roi_name} | S=save R=reset Q=quit",
                    (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.imshow(window, display)

        key = cv2.waitKey(30) & 0xFF
        if key == ord("r"):
            rect[:] = [None, None, None, None]
        elif key == ord("s"):
            if rect[0] is not None and rect[2] is not None:
                x = min(rect[0], rect[2])
                y = min(rect[1], rect[3])
                w = abs(rect[2] - rect[0])
                h = abs(rect[3] - rect[1])
                cv2.destroyWindow(window)
                return {"x": x, "y": y, "w": w, "h": h}
        elif key in (ord("q"), 27):
            cv2.destroyWindow(window)
            return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate Valorant HUD ROIs")
    parser.add_argument("--roi", nargs="*", default=None, help="ROI name(s) to calibrate")
    args = parser.parse_args()

    roi_names = args.roi or DEFAULT_ROI_ORDER

    try:
        frame = asyncio.run(fetch_frame())
    except Exception as exc:
        logger.error("Could not fetch frame: %s", exc)
        logger.error("Make sure capture-service is running first.")
        sys.exit(1)

    yaml_lines: list[str] = []

    for name in roi_names:
        logger.info("\n── Calibrating: %s ──", name)
        result = calibrate_roi(frame, name)
        if result is None:
            logger.info("Skipped %s", name)
            continue
        desc = registry.get(name)
        description = desc.description if desc else ""
        preset = ROI_PRESET_MAP.get(name, "numeric")
        yaml_lines.append(
            f"{name}:\n"
            f"  x: {result['x']}\n"
            f"  y: {result['y']}\n"
            f"  w: {result['w']}\n"
            f"  h: {result['h']}\n"
            f"  enabled: true\n"
            f"  description: \"{description}\"\n"
        )
        logger.info("Saved %s → %s", name, result)

    if yaml_lines:
        print("\n\n# ── Paste into rois.yaml ─────────────────────────────────────")
        print("\n".join(yaml_lines))

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

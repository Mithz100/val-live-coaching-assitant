"""JPEG encoding helpers — kept separate so they're easy to swap."""

from __future__ import annotations

import cv2
import numpy as np

from config import settings


def encode_jpeg(image: np.ndarray) -> bytes:
    """Encode a BGR ndarray to JPEG bytes at the configured quality."""
    ok, buf = cv2.imencode(
        ".jpg",
        image,
        [cv2.IMWRITE_JPEG_QUALITY, settings.jpeg_quality],
    )
    if not ok:
        raise RuntimeError("cv2.imencode failed")
    return buf.tobytes()

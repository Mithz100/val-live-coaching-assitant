"""
Region-of-Interest (ROI) management.

Loads ROI coordinates from rois.yaml, scales them to the actual capture
resolution, and provides crop helpers used by the OCR and template pipelines.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import yaml

from config import settings

logger = logging.getLogger(__name__)

_REFERENCE_W = 1920
_REFERENCE_H = 1080


@dataclass(frozen=True)
class ROI:
    name: str
    x: int
    y: int
    w: int
    h: int
    enabled: bool
    description: str

    # ── derived ──────────────────────────────────────────────────────────────

    @property
    def rect(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) — same as constructor."""
        return self.x, self.y, self.w, self.h

    @property
    def slice(self) -> tuple[slice, slice]:
        """NumPy slice pair for direct array indexing: frame[roi.slice]."""
        return slice(self.y, self.y + self.h), slice(self.x, self.x + self.w)

    def crop(self, frame: np.ndarray) -> np.ndarray:
        """Return the sub-image for this ROI, clamped to frame bounds."""
        fh, fw = frame.shape[:2]
        x1 = max(0, self.x)
        y1 = max(0, self.y)
        x2 = min(fw, self.x + self.w)
        y2 = min(fh, self.y + self.h)
        return frame[y1:y2, x1:x2]


class ROIRegistry:
    """Singleton that loads, scales, and serves ROI definitions."""

    def __init__(self) -> None:
        self._rois: dict[str, ROI] = {}
        self._scale_x = settings.capture_width / _REFERENCE_W
        self._scale_y = settings.capture_height / _REFERENCE_H
        self._load()

    def _load(self) -> None:
        path = Path(settings.roi_config_path)
        if not path.exists():
            logger.warning("rois.yaml not found at %s — using defaults", path)
            return

        with path.open() as fh:
            raw: dict = yaml.safe_load(fh)

        for name, cfg in raw.items():
            if not isinstance(cfg, dict):
                continue
            enabled = cfg.get("enabled", True)
            roi = ROI(
                name=name,
                x=self._scale_coord(cfg["x"], self._scale_x),
                y=self._scale_coord(cfg["y"], self._scale_y),
                w=self._scale_coord(cfg["w"], self._scale_x),
                h=self._scale_coord(cfg["h"], self._scale_y),
                enabled=enabled,
                description=cfg.get("description", ""),
            )
            self._rois[name] = roi
            logger.debug("Loaded ROI '%s' → %s", name, roi.rect)

        logger.info("Loaded %d ROIs from %s", len(self._rois), path)

    @staticmethod
    def _scale_coord(value: int, factor: float) -> int:
        return max(1, round(value * factor))

    def get(self, name: str) -> Optional[ROI]:
        roi = self._rois.get(name)
        if roi and not roi.enabled:
            return None
        return roi

    def all_enabled(self) -> list[ROI]:
        return [r for r in self._rois.values() if r.enabled]

    def draw_debug(self, frame: np.ndarray) -> np.ndarray:
        """Return a copy of *frame* with all ROI boxes drawn on it."""
        out = frame.copy()
        for roi in self.all_enabled():
            cv2.rectangle(
                out,
                (roi.x, roi.y),
                (roi.x + roi.w, roi.y + roi.h),
                (0, 255, 0),
                1,
            )
            cv2.putText(
                out,
                roi.name,
                (roi.x + 2, roi.y + 12),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                (0, 255, 0),
                1,
            )
        return out


# Module-level singleton
registry = ROIRegistry()

"""
OpenCV template matching pipeline.

Templates are PNG files stored in services/vision-service/templates/.
The TemplateMatcher supports multi-scale matching for robust detection
even when the game UI scales slightly with different FoV / resolution settings.

Template naming convention:
  <event_name>.png
  e.g.  buy_phase.png, victory.png, defeat.png, spike_planted.png
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from config import settings

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True)
class MatchResult:
    template_name: str
    confidence: float          # normalised cross-correlation score 0–1
    location: tuple[int, int]  # top-left pixel in the searched image
    scale: float               # which scale factor produced this match

    @property
    def detected(self) -> bool:
        return self.confidence >= settings.template_confidence_min


class TemplateMatcher:
    """Loads templates once, matches on demand."""

    def __init__(self) -> None:
        self._templates: dict[str, np.ndarray] = {}
        self._load_templates()

    # ── Setup ────────────────────────────────────────────────────────────────

    def _load_templates(self) -> None:
        if not _TEMPLATE_DIR.exists():
            logger.warning("Template directory not found: %s", _TEMPLATE_DIR)
            return

        for path in _TEMPLATE_DIR.glob("*.png"):
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                logger.warning("Could not load template: %s", path)
                continue
            name = path.stem
            self._templates[name] = img
            logger.debug("Loaded template '%s' %s", name, img.shape)

        logger.info("Loaded %d templates from %s", len(self._templates), _TEMPLATE_DIR)

    def reload(self) -> None:
        """Hot-reload templates without restarting the service."""
        self._templates.clear()
        self._load_templates()

    # ── Matching ─────────────────────────────────────────────────────────────

    def match(
        self,
        frame: np.ndarray,
        template_name: str,
        *,
        search_region: Optional[np.ndarray] = None,
    ) -> MatchResult:
        """
        Match *template_name* against *frame* (or *search_region*).
        Returns a MatchResult even if nothing is found (confidence=0).
        """
        template = self._templates.get(template_name)
        if template is None:
            return MatchResult(
                template_name=template_name,
                confidence=0.0,
                location=(0, 0),
                scale=1.0,
            )

        haystack = search_region if search_region is not None else frame
        if haystack.ndim == 3:
            haystack = cv2.cvtColor(haystack, cv2.COLOR_BGR2GRAY)

        if settings.template_multi_scale:
            return self._multi_scale_match(haystack, template, template_name)
        else:
            return self._single_scale_match(haystack, template, template_name, 1.0)

    def match_any(
        self,
        frame: np.ndarray,
        template_names: list[str],
    ) -> dict[str, MatchResult]:
        """Match multiple templates and return a dict of results."""
        return {name: self.match(frame, name) for name in template_names}

    # ── Internal ─────────────────────────────────────────────────────────────

    def _single_scale_match(
        self,
        haystack: np.ndarray,
        template: np.ndarray,
        name: str,
        scale: float,
    ) -> MatchResult:
        th, tw = template.shape[:2]
        hh, hw = haystack.shape[:2]

        if tw > hw or th > hh:
            return MatchResult(name, 0.0, (0, 0), scale)

        result = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        return MatchResult(
            template_name=name,
            confidence=float(max_val),
            location=(int(max_loc[0]), int(max_loc[1])),
            scale=scale,
        )

    def _multi_scale_match(
        self,
        haystack: np.ndarray,
        template: np.ndarray,
        name: str,
    ) -> MatchResult:
        best = MatchResult(name, 0.0, (0, 0), 1.0)
        steps = settings.template_scale_steps
        lo = settings.template_scale_min
        hi = settings.template_scale_max

        for i in range(steps):
            if steps == 1:
                scale = 1.0
            else:
                scale = lo + (hi - lo) * i / (steps - 1)

            th = max(1, round(template.shape[0] * scale))
            tw = max(1, round(template.shape[1] * scale))
            resized = cv2.resize(template, (tw, th), interpolation=cv2.INTER_AREA)

            candidate = self._single_scale_match(haystack, resized, name, scale)
            if candidate.confidence > best.confidence:
                best = candidate

        return best

    def draw_debug(
        self,
        frame: np.ndarray,
        results: dict[str, MatchResult],
    ) -> np.ndarray:
        """Annotate detected templates on a copy of *frame*."""
        out = frame.copy()
        for name, result in results.items():
            if not result.detected:
                continue
            template = self._templates.get(name)
            if template is None:
                continue
            th, tw = template.shape[:2]
            x, y = result.location
            w = round(tw * result.scale)
            h = round(th * result.scale)
            cv2.rectangle(out, (x, y), (x + w, y + h), (0, 0, 255), 2)
            cv2.putText(
                out,
                f"{name} {result.confidence:.2f}",
                (x, max(0, y - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 255),
                1,
            )
        return out

    @property
    def template_names(self) -> list[str]:
        return list(self._templates.keys())


# Module-level singleton
matcher = TemplateMatcher()

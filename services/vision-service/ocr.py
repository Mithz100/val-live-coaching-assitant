"""
EasyOCR wrapper with confidence filtering, retry logic, and benchmarking.

EasyOCR is initialized once (expensive) and reused across all frames.
The Reader is not thread-safe; all calls must come from the same thread/task.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from config import settings
from models import OcrResult

logger = logging.getLogger(__name__)

_reader = None  # lazy-loaded singleton


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr  # import here so startup isn't blocked if OCR unused
        logger.info(
            "Initializing EasyOCR (gpu=%s, langs=%s) …",
            settings.ocr_gpu,
            settings.ocr_languages,
        )
        t0 = time.perf_counter()
        _reader = easyocr.Reader(
            settings.ocr_languages,
            gpu=settings.ocr_gpu,
            verbose=False,
        )
        logger.info("EasyOCR ready in %.2fs", time.perf_counter() - t0)
    return _reader


@dataclass
class OcrStats:
    total_calls: int = 0
    total_results: int = 0
    total_ms: float = 0.0
    low_confidence_rejected: int = 0

    @property
    def avg_ms(self) -> float:
        return self.total_ms / max(self.total_calls, 1)


_stats = OcrStats()


def ocr_region(
    image: np.ndarray,
    roi_name: str,
    *,
    min_confidence: Optional[float] = None,
    retries: int = 1,
) -> list[OcrResult]:
    """
    Run EasyOCR on a pre-processed image crop.

    Returns a list of OcrResult sorted by confidence descending.
    Filters results below min_confidence (defaults to settings value).
    """
    if min_confidence is None:
        min_confidence = settings.ocr_confidence_min

    reader = _get_reader()
    last_results: list[OcrResult] = []

    for attempt in range(max(1, retries)):
        t0 = time.perf_counter()
        try:
            raw = reader.readtext(
                image,
                detail=1,
                paragraph=False,
                batch_size=settings.ocr_batch_size,
            )
        except Exception:
            logger.debug("EasyOCR raised on roi=%s attempt=%d", roi_name, attempt, exc_info=True)
            continue
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            _stats.total_calls += 1
            _stats.total_ms += elapsed_ms

        results: list[OcrResult] = []
        for _bbox, text, conf in raw:
            text = text.strip()
            if not text:
                continue
            if conf < min_confidence:
                _stats.low_confidence_rejected += 1
                logger.debug("OCR '%s' conf=%.2f < %.2f — rejected", text, conf, min_confidence)
                continue
            results.append(OcrResult(text=text, confidence=conf, region=roi_name))

        results.sort(key=lambda r: r.confidence, reverse=True)
        _stats.total_results += len(results)
        last_results = results

        if results:
            break   # got something useful — no need to retry

    return last_results


def ocr_numeric(image: np.ndarray, roi_name: str) -> Optional[int]:
    """
    Convenience wrapper for numeric ROIs (health, credits, etc.).
    Returns the first parseable integer from the results, or None.
    """
    results = ocr_region(image, roi_name)
    for r in results:
        # Strip noise characters, keep digits
        cleaned = "".join(c for c in r.text if c.isdigit())
        if cleaned:
            return int(cleaned)
    return None


def ocr_text(image: np.ndarray, roi_name: str) -> Optional[str]:
    """Convenience wrapper returning the highest-confidence text string."""
    results = ocr_region(image, roi_name)
    return results[0].text if results else None


def get_stats() -> OcrStats:
    return _stats

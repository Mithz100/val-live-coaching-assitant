"""
Image preprocessing pipeline applied to ROI crops before OCR.

Each preset is tuned for a specific UI element type:
  - numeric      → health / armor / credits / ammo
  - timer        → match timer (colon-separated digits)
  - banner       → buy phase / round result banners (large white text)
  - killfeed     → small anti-aliased text on dark background
"""

from __future__ import annotations

import cv2
import numpy as np


def _ensure_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def preprocess_numeric(image: np.ndarray) -> np.ndarray:
    """
    Best for: health, armor, credits, ammo.
    These are bright white / yellow numbers on a semi-transparent dark bar.
    """
    gray = _ensure_gray(image)
    # Scale up for OCR accuracy
    scaled = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    # Sharpen
    kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
    sharpened = cv2.filter2D(scaled, -1, kernel)
    # Binary threshold — white text on dark bg
    _, binary = cv2.threshold(sharpened, 160, 255, cv2.THRESH_BINARY)
    # Light denoise
    denoised = cv2.medianBlur(binary, 3)
    return denoised


def preprocess_timer(image: np.ndarray) -> np.ndarray:
    """
    Best for: match timer ("1:22").
    White digits, slightly larger — similar to numeric but gentler threshold.
    """
    gray = _ensure_gray(image)
    scaled = cv2.resize(gray, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(scaled, 140, 255, cv2.THRESH_BINARY)
    return binary


def preprocess_banner(image: np.ndarray) -> np.ndarray:
    """
    Best for: BUY PHASE, VICTORY, DEFEAT — large bold centered text.
    These typically use colored backgrounds; OTSU handles varying BG colors.
    """
    gray = _ensure_gray(image)
    scaled = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    blurred = cv2.GaussianBlur(scaled, (3, 3), 0)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def preprocess_killfeed(image: np.ndarray) -> np.ndarray:
    """
    Best for: kill feed — small anti-aliased colored player names on dark BG.
    Adaptive threshold handles per-pixel brightness variation better.
    """
    gray = _ensure_gray(image)
    scaled = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_LINEAR)
    # Denoise first — kills JPEG artifacts
    denoised = cv2.fastNlMeansDenoising(scaled, h=10)
    binary = cv2.adaptiveThreshold(
        denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 2
    )
    return binary


# ── Registry ─────────────────────────────────────────────────────────────────

_PRESETS: dict[str, callable] = {
    "numeric": preprocess_numeric,
    "timer": preprocess_timer,
    "banner": preprocess_banner,
    "killfeed": preprocess_killfeed,
}

# Maps ROI name → preset name
ROI_PRESET_MAP: dict[str, str] = {
    "health": "numeric",
    "armor": "numeric",
    "credits": "numeric",
    "ammo_current": "numeric",
    "ammo_reserve": "numeric",
    "match_timer": "timer",
    "buy_phase_banner": "banner",
    "round_result_banner": "banner",
    "killfeed": "killfeed",
    "spike_status": "banner",
}


def preprocess(image: np.ndarray, roi_name: str) -> np.ndarray:
    """Apply the appropriate preprocessing preset for the given ROI name."""
    preset_name = ROI_PRESET_MAP.get(roi_name, "numeric")
    fn = _PRESETS.get(preset_name, preprocess_numeric)
    return fn(image)

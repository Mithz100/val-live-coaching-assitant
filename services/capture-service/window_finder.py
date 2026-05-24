"""Locate the Valorant game window on Windows using win32gui."""

from __future__ import annotations

import logging
from typing import Optional

import win32con
import win32gui

logger = logging.getLogger(__name__)


def find_game_window(title_fragment: str) -> Optional[tuple[int, int, int, int]]:
    """
    Return (left, top, right, bottom) client rect of the first window whose
    title contains *title_fragment* (case-insensitive), or None if not found.
    """
    found: list[tuple[int, tuple[int, int, int, int]]] = []

    def _enum(hwnd: int, _: None) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if title_fragment.lower() in title.lower():
            # Convert window rect to screen coords
            rect = win32gui.GetWindowRect(hwnd)
            found.append((hwnd, rect))

    win32gui.EnumWindows(_enum, None)

    if not found:
        logger.debug("Window containing '%s' not found", title_fragment)
        return None

    hwnd, (left, top, right, bottom) = found[0]
    logger.debug(
        "Found window '%s' hwnd=%d rect=(%d,%d,%d,%d)",
        win32gui.GetWindowText(hwnd),
        hwnd,
        left,
        top,
        right,
        bottom,
    )
    return left, top, right, bottom


def get_primary_monitor_resolution() -> tuple[int, int]:
    """Return (width, height) of the primary monitor."""
    width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)  # type: ignore[name-defined]
    height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)  # type: ignore[name-defined]
    return width, height

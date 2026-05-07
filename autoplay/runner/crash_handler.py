"""Detect a Civ 5 ``Game Crash`` window on Windows.

Civ 5 sometimes spawns a separate "Game Crash" / Send Crash Report dialog
when the main process is wedged but hasn't exited yet. From the runner's
perspective that's indistinguishable from a hang: the parent ``proc.poll()``
still returns ``None`` because the dialog is part of the same process tree.
This module exposes a tiny ``crash_handler_window_present()`` helper that
enumerates top-level windows and returns True if any visible window's title
contains ``Game Crash``.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

logger = logging.getLogger(__name__)

_TARGET_SUBSTRING = "game crash"


def _enumerate_windows_win32() -> list[str]:
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(  # type: ignore[attr-defined]
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )
    GetWindowTextLengthW = user32.GetWindowTextLengthW
    GetWindowTextW = user32.GetWindowTextW
    IsWindowVisible = user32.IsWindowVisible

    titles: list[str] = []

    def _cb(hwnd, _lparam):
        if not IsWindowVisible(hwnd):
            return True
        n = GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        GetWindowTextW(hwnd, buf, n + 1)
        titles.append(buf.value)
        return True

    EnumWindows(EnumWindowsProc(_cb), 0)
    return titles


def crash_handler_window_present() -> bool:
    """Return True if any visible top-level window's title contains "Game Crash".

    Always False on non-Windows platforms.
    """
    if sys.platform != "win32":
        return False
    try:
        titles = _enumerate_windows_win32()
    except OSError as exc:  # pragma: no cover - defensive
        logger.debug("EnumWindows failed: %s", exc)
        return False
    needle = _TARGET_SUBSTRING
    for t in titles:
        if t and needle in t.lower():
            return True
    return False

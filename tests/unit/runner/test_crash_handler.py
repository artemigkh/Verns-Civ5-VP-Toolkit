"""Tests for autoplay.runner.crash_handler.

Win32-specific code; we mock ctypes.windll so tests run on any platform.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from autoplay.runner import crash_handler


def _install_fake_windll(monkeypatch, titles: list[str]) -> None:
    """Replace ctypes.windll.user32 so EnumWindows yields ``titles``."""
    if sys.platform != "win32":
        # On non-Windows, ctypes.windll doesn't exist. The function short-
        # circuits to False on non-Windows; tests that need to drive
        # _enumerate_windows_win32 must monkeypatch sys.platform AND windll.
        monkeypatch.setattr(crash_handler.sys, "platform", "win32")

    user32 = MagicMock()

    def _enum_windows_impl(callback, _lparam):
        # Drive callback with synthetic HWND ints.
        for i, _t in enumerate(titles, start=1):
            callback(i, 0)
        return True

    user32.EnumWindows = MagicMock(side_effect=_enum_windows_impl)
    user32.IsWindowVisible = MagicMock(return_value=1)

    def _len(hwnd):
        return len(titles[hwnd - 1])

    def _text(hwnd, buf, _n):
        buf.value = titles[hwnd - 1]
        return len(titles[hwnd - 1])

    user32.GetWindowTextLengthW = MagicMock(side_effect=_len)
    user32.GetWindowTextW = MagicMock(side_effect=_text)

    fake_windll = MagicMock()
    fake_windll.user32 = user32
    # ctypes.windll only exists on Windows; install a stub.
    fake_ctypes = MagicMock(wraps=crash_handler.ctypes)
    fake_ctypes.windll = fake_windll
    fake_ctypes.WINFUNCTYPE = crash_handler.ctypes.WINFUNCTYPE
    fake_ctypes.create_unicode_buffer = crash_handler.ctypes.create_unicode_buffer
    monkeypatch.setattr(crash_handler, "ctypes", fake_ctypes)


def test_returns_false_on_non_windows(monkeypatch) -> None:
    monkeypatch.setattr(crash_handler.sys, "platform", "linux")
    assert crash_handler.crash_handler_window_present() is False


def test_returns_true_when_title_contains_game_crash(monkeypatch) -> None:
    _install_fake_windll(monkeypatch, ["Notepad", "Civilization V Game Crash"])
    assert crash_handler.crash_handler_window_present() is True


def test_case_insensitive_match(monkeypatch) -> None:
    _install_fake_windll(monkeypatch, ["GAME CRASH dialog"])
    assert crash_handler.crash_handler_window_present() is True


def test_no_matches(monkeypatch) -> None:
    _install_fake_windll(monkeypatch, ["Solitaire", "VS Code"])
    assert crash_handler.crash_handler_window_present() is False


def test_empty_titles_list(monkeypatch) -> None:
    _install_fake_windll(monkeypatch, [])
    assert crash_handler.crash_handler_window_present() is False

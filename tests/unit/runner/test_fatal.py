"""Tests for autoplay.runner.fatal."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from autoplay.runner import fatal


class TestFatalPermissionError:
    def test_calls_os_exit_with_1(self, monkeypatch) -> None:
        called = {}

        def _fake_exit(code):
            called["code"] = code
            raise SystemExit(code)  # so the test can resume

        monkeypatch.setattr(fatal.os, "_exit", _fake_exit)
        with pytest.raises(SystemExit):
            fatal.fatal_permission_error(PermissionError("nope"), where="reading X")
        assert called["code"] == 1


class TestWarnIfLowDiskSpace:
    def test_warns_below_threshold(self, tmp_path: Path, monkeypatch, caplog) -> None:
        usage = MagicMock()
        usage.free = 10 * 1024**3  # 10 GiB, below 50 GiB threshold
        monkeypatch.setattr(shutil, "disk_usage", lambda _p: usage)
        with caplog.at_level("WARNING"):
            fatal.warn_if_low_disk_space(tmp_path)
        assert any("LOW DISK SPACE" in r.message for r in caplog.records)

    def test_silent_above_threshold(self, tmp_path: Path, monkeypatch, caplog) -> None:
        usage = MagicMock()
        usage.free = 200 * 1024**3
        monkeypatch.setattr(shutil, "disk_usage", lambda _p: usage)
        with caplog.at_level("INFO"):
            fatal.warn_if_low_disk_space(tmp_path)
        assert not any("LOW DISK SPACE" in r.message for r in caplog.records)

    def test_disk_usage_error_logs_warning(
        self, tmp_path: Path, monkeypatch, caplog
    ) -> None:
        def _raise(_p):
            raise OSError("no such drive")

        monkeypatch.setattr(shutil, "disk_usage", _raise)
        with caplog.at_level("WARNING"):
            fatal.warn_if_low_disk_space(tmp_path)
        assert any("Cannot check free disk space" in r.message for r in caplog.records)

    def test_threshold_constant_is_50_gib(self) -> None:
        assert fatal.LOW_DISK_THRESHOLD_BYTES == 50 * 1024**3

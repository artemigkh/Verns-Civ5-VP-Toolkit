"""Tests for autoplay.common.logging_setup."""

from __future__ import annotations

from pathlib import Path

from autoplay.common.logging_setup import build_log_config


def test_creates_parent_directory(tmp_path: Path) -> None:
    log_file = tmp_path / "deep" / "nested" / "app.log"
    assert not log_file.parent.exists()
    build_log_config(log_file)
    assert log_file.parent.is_dir()


def test_returns_expected_keys(tmp_path: Path) -> None:
    cfg = build_log_config(tmp_path / "app.log")
    assert cfg["version"] == 1
    assert set(cfg["handlers"]) == {"console", "file"}
    assert cfg["handlers"]["file"]["filename"] == str(tmp_path / "app.log")
    # Rotation parameters are reasonable (exact values may evolve).
    assert cfg["handlers"]["file"]["maxBytes"] >= 1024 * 1024
    assert cfg["handlers"]["file"]["backupCount"] >= 1


def test_uvicorn_access_silenced(tmp_path: Path) -> None:
    cfg = build_log_config(tmp_path / "app.log")
    access = cfg["loggers"]["uvicorn.access"]
    assert access["level"] in {"WARNING", "ERROR", "CRITICAL"}
    assert access["propagate"] is False


def test_root_attaches_both_handlers(tmp_path: Path) -> None:
    cfg = build_log_config(tmp_path / "app.log")
    assert set(cfg["root"]["handlers"]) == {"console", "file"}

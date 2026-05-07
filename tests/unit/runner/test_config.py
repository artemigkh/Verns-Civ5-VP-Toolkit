"""Tests for autoplay.runner.config."""

from __future__ import annotations

from pathlib import Path

from autoplay.runner.config import RunnerConfig, load_config


def test_explicit_kwargs_override_defaults(tmp_path: Path) -> None:
    cfg = RunnerConfig(
        hypervisor_url="http://hv:6000",
        user_dir=tmp_path / "u",
        install_dir=tmp_path / "i",
        startup_timeout_sec=42,
        bind_host="127.0.0.1",
    )
    assert cfg.hypervisor_url == "http://hv:6000"
    assert cfg.user_dir == tmp_path / "u"
    assert cfg.startup_timeout_sec == 42


def test_env_var_loading(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AUTOPLAY_RUNNER_HYPERVISOR_URL", "http://envhost:1234")
    monkeypatch.setenv("AUTOPLAY_RUNNER_STARTUP_TIMEOUT_SEC", "999")
    monkeypatch.setenv("AUTOPLAY_RUNNER_USER_DIR", str(tmp_path / "envuser"))
    # Avoid triggering detect_lan_host (subprocess).
    monkeypatch.setenv("AUTOPLAY_RUNNER_BIND_HOST", "127.0.0.1")
    cfg = load_config()
    assert cfg.hypervisor_url == "http://envhost:1234"
    assert cfg.startup_timeout_sec == 999
    assert cfg.user_dir == tmp_path / "envuser"


def test_defaults_have_reasonable_types(monkeypatch) -> None:
    monkeypatch.setenv("AUTOPLAY_RUNNER_BIND_HOST", "127.0.0.1")
    cfg = load_config()
    assert isinstance(cfg.user_dir, Path)
    assert isinstance(cfg.install_dir, Path)
    assert isinstance(cfg.heartbeat_interval_sec, float)
    assert cfg.recovery_max_attempts >= 1
    assert cfg.crash_handler_poll_ms >= 0

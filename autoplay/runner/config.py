"""Runner configuration loaded from environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from autoplay.runner.net import detect_lan_host


def _default_user_dir() -> Path:
    return Path.home() / "Documents" / "My Games" / "Sid Meier's Civilization 5"


def _default_install_dir() -> Path:
    return Path.home() / "Desktop" / "pure_vp" / "Sid Meier's Civilization V"


class RunnerConfig(BaseSettings):
    """Runner runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="AUTOPLAY_RUNNER_",
        env_file=".env",
        extra="ignore",
    )

    hypervisor_url: str = Field(default="http://localhost:5000")
    user_dir: Path = Field(default_factory=_default_user_dir)
    install_dir: Path = Field(default_factory=_default_install_dir)
    startup_timeout_sec: int = Field(default=600)
    turn_timeout_sec: int = Field(default=1000)
    registration_timeout_sec: int = Field(default=180)
    heartbeat_interval_sec: float = Field(default=2.0)
    log_ignore_patterns: list[str] = Field(
        default_factory=lambda: ["CitySites_*", "TradePlayerRouteLog_*"]
    )
    bind_host: str = Field(default_factory=detect_lan_host)


def load_config() -> RunnerConfig:
    return RunnerConfig()

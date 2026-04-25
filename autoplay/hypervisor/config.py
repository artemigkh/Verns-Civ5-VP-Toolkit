"""Hypervisor configuration loaded from environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HypervisorConfig(BaseSettings):
    """Hypervisor runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="AUTOPLAY_HV_",
        env_file=".env",
        extra="ignore",
    )

    storage_root: Path = Field(
        default=Path("./data"),
        description="Root directory where runner state DB and log bundles are stored.",
    )
    port: int = Field(default=5000, description="HTTP port the hypervisor listens on.")
    host: str = Field(default="0.0.0.0", description="HTTP bind host.")
    runner_timeout_sec: int = Field(
        default=120,
        description="Seconds since last heartbeat after which a runner is considered dead.",
    )


def load_config() -> HypervisorConfig:
    return HypervisorConfig()

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
    turn_timeout_sec: int = Field(default=600)
    registration_timeout_sec: int = Field(default=180)
    heartbeat_interval_sec: float = Field(default=2.0)
    log_ignore_patterns: list[str] = Field(
        default_factory=lambda: ["CitySites_*", "TradePlayerRouteLog_*"]
    )
    recovery_max_attempts: int = Field(
        default=3,
        description=(
            "How many times the runner will attempt to recover a crashed game by "
            "relaunching the executable without ``-Automation`` (which loads the "
            "most recent autosave thanks to the patched FrontEnd/MainMenu). After "
            "this many attempts pass without any turn progression beyond the "
            "crashed turn, the game is finally marked as failed."
        ),
    )
    recovery_attempt_timeout_sec: int = Field(
        default=600,
        description=(
            "Per-recovery-attempt deadline. If no turn progresses past the "
            "crashed turn within this many seconds (or the process dies again), "
            "the attempt is counted as a failure and the next one is tried."
        ),
    )
    pending_uploads_dir: Path = Field(
        default_factory=lambda: Path.home() / ".civ5_autoplay_pending",
        description=(
            "Local directory used to stage log/crash bundles that could not be "
            "uploaded immediately (e.g. while the hypervisor is unreachable). "
            "A background loop drains this directory once the hypervisor is back."
        ),
    )
    crash_handler_poll_ms: int = Field(
        default=1000,
        description=(
            "How often (in milliseconds) the runner checks for a top-level "
            "window titled ``Crash Handler``. If one appears, the game's "
            "process tree is killed and the runner proceeds with the same "
            "crash flow as a process-died event. Set to 0 to disable."
        ),
    )
    use_blank_d3d9_proxy: bool = Field(
        default=False,
        description=(
            "When True, install ``patched_files/d3d9.dll`` over "
            "``<INSTALL_DIR>/d3d9.dll`` on startup (the historical behaviour). "
            "When False (the default), any existing ``d3d9.dll`` in the install "
            "dir is removed so the game uses the system DirectX runtime."
        ),
    )
    bind_host: str = Field(default_factory=detect_lan_host)


def load_config() -> RunnerConfig:
    return RunnerConfig()

"""Headless bridge configuration loaded from environment variables."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from autoplay.common.constants import MODPACK_FOLDER_REGEX
from autoplay.runner.net import detect_lan_host


def _default_c5h_dir() -> Path:
    return Path.home() / "Documents" / "civ5-headless"


def _default_job_defaults() -> dict[str, Any]:
    return {"noMods": True, "detail": "summary", "maxSeconds": 14400, "stallSeconds": 900}


class HeadlessConfig(BaseSettings):
    """Headless bridge runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="AUTOPLAY_HEADLESS_",
        env_file=".env",
        extra="ignore",
    )

    hypervisor_url: str = Field(default="http://localhost:5000")
    c5h_dir: Path = Field(
        default_factory=_default_c5h_dir,
        description=(
            "civ5-headless checkout or release kit: ``c5h.cmd`` runs from here, so its "
            "``civ5headless.toml`` (game database, DLL, localization) applies."
        ),
    )
    work_dir: Path = Field(
        default=Path("./headless_data"),
        description="Queue files, run folders, the upload ledger and logs.",
    )
    modpack: str = Field(
        default="MP_AUTOPLAY_VP_headless",
        description=(
            "Modpack name the games are reported and ingested under (``<storage_root>/<modpack>/`` on "
            "the hypervisor). Must start with ``MP_AUTOPLAY_VP_``."
        ),
    )
    modpack_folder: str | None = Field(
        default=None,
        description=(
            "DLC folder of the modpack the games play (``Assets\\DLC\\<name>``, e.g. "
            "``VP_MODPACK_5_4_8_NEUTRALS``). When set, the games play on the bridge's own copy of the game "
            "folder with that modpack (``autoplay.headless.game_copy``), made from ``game_source_dir`` "
            "once, so they hold no file of the Steam install. Unset: ``civ5headless.toml``'s "
            "``game_dir`` and ``dll`` apply."
        ),
    )
    game_source_dir: Path = Field(
        default=Path(r"C:\Program Files (x86)\Steam\steamapps\common\Sid Meier's Civilization V"),
        description="Game folder the copy is made from (only read while there is no copy yet).",
    )
    game_copy_dir: Path | None = Field(
        default=None,
        description="Where the game folder copies go (default ``<work_dir>/game``).",
    )
    spec: Path | None = Field(
        default=None,
        description="c5h game spec (map, size, speed, ...) every game plays; seeds are drawn per game.",
    )
    turns: int = Field(
        default=500, ge=1, description="Turn each game plays to, unless a start request caps it."
    )
    workers: int = Field(default=4, ge=1, description="Games played at once, one per worker slot.")
    affinity: str = Field(default="p-first", description="c5h worker pinning: ``p-first`` or ``none``.")
    games_per_batch: int = Field(default=100, ge=1, description="Games in each c5h queue the bridge writes.")
    continuous: bool = Field(
        default=True,
        description="Write and start a new batch when one finishes, until a stop request.",
    )
    job_defaults: dict[str, Any] = Field(
        default_factory=_default_job_defaults,
        description="Queue ``defaults`` for every game (any ``c5h run`` option by its JSON name).",
    )
    autostart: bool = Field(
        default=False, description="Start playing at bridge startup without a start request."
    )
    stop_queue_on_exit: bool = Field(
        default=True,
        description=(
            "Kill the c5h queue when the bridge exits (its running games are replayed from the start on "
            "the next start). When False the queue keeps playing and the next bridge adopts it."
        ),
    )
    keep_run_folders: bool = Field(
        default=False,
        description=(
            "Keep a completed game's run folder after its stats are handed to the hypervisor. Off by "
            "default: each is ~80 MB, mostly the stats.db the hypervisor already archives."
        ),
    )
    heartbeat_interval_sec: float = Field(default=2.0)
    poll_interval_sec: float = Field(default=2.0, description="How often run folders are checked.")
    pending_uploads_dir: Path | None = Field(
        default=None,
        description=(
            "Where uploads wait while the hypervisor is unreachable (default ``<work_dir>/pending``)."
        ),
    )
    bind_host: str = Field(default_factory=detect_lan_host)

    @field_validator("modpack")
    @classmethod
    def _modpack_name(cls, value: str) -> str:
        if not MODPACK_FOLDER_REGEX.match(value):
            raise ValueError(f"modpack must match {MODPACK_FOLDER_REGEX.pattern}, got {value!r}")
        return value

    @property
    def c5h_cmd(self) -> Path:
        return self.c5h_dir / "c5h.cmd"

    @property
    def pending_dir(self) -> Path:
        return self.pending_uploads_dir or self.work_dir / "pending"

    @property
    def game_copy_root(self) -> Path:
        return self.game_copy_dir or self.work_dir / "game"


def load_config() -> HeadlessConfig:
    return HeadlessConfig()

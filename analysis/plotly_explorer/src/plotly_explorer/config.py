"""Runtime configuration for the Plotly Explorer.

All knobs are supplied through environment variables (see
``plotly_explorer_debug.bat``) using the exact names from the design doc:
``DB_TYPE``, ``DB_PATH``, ``INTERMEDIATE_DATA_DIR``, ``PUBLISH_DIR``.

Paths are resolved against the current working directory, which the launcher
sets to the repo root, so repo-relative values like ``misc/building_yields/...``
work as written.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Repo root is four levels up from this file:
#   <repo>/analysis/plotly_explorer/src/plotly_explorer/config.py
REPO_ROOT = Path(__file__).resolve().parents[4]

# Reference metadata produced by db_util/db_export.py.
METADATA_DIR = REPO_ROOT / "db_util" / "out"
BUILDING_INFO_CSV = METADATA_DIR / "building_info.csv"
UNIQUE_BUILDINGS_JSON = METADATA_DIR / "unique_buildings.json"

ERA_TOTALS_CSV = "building_yields_era_totals_summary.csv"
TURN_AVERAGE_CSV = "building_yields_turn_average_summary.csv"
SOURCE_MTIME_FILE = ".source_mtime"

# Religion report.
RELIGION_TABLE = "ReligionBeliefYields"
RELIGION_ERA_TOTALS_CSV = "religion_yields_era_totals_summary.csv"
RELIGION_TURN_AVERAGE_CSV = "religion_yields_turn_average_summary.csv"
RELIGION_SOURCE_MTIME_FILE = ".religion_source_mtime"


@dataclass(frozen=True)
class Config:
    db_type: str
    db_path: Path
    intermediate_data_dir: Path
    publish_dir: Path

    @property
    def era_totals_path(self) -> Path:
        return self.intermediate_data_dir / ERA_TOTALS_CSV

    @property
    def turn_average_path(self) -> Path:
        return self.intermediate_data_dir / TURN_AVERAGE_CSV

    @property
    def source_mtime_path(self) -> Path:
        return self.intermediate_data_dir / SOURCE_MTIME_FILE

    @property
    def religion_era_totals_path(self) -> Path:
        return self.intermediate_data_dir / RELIGION_ERA_TOTALS_CSV

    @property
    def religion_turn_average_path(self) -> Path:
        return self.intermediate_data_dir / RELIGION_TURN_AVERAGE_CSV

    @property
    def religion_source_mtime_path(self) -> Path:
        return self.intermediate_data_dir / RELIGION_SOURCE_MTIME_FILE

    @property
    def index_html_path(self) -> Path:
        return self.publish_dir / "index.html"


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"Missing required environment variable {name}. "
            f"Run via build_yield_explorer_debug.bat or set it manually."
        )
    return value


def _resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (Path.cwd() / path)


def load_config() -> Config:
    db_type = os.environ.get("DB_TYPE", "sqlite").strip().lower()
    if db_type not in {"sqlite", "duckdb"}:
        raise SystemExit(f"DB_TYPE must be 'sqlite' or 'duckdb', got {db_type!r}")
    return Config(
        db_type=db_type,
        db_path=_resolve(_require("DB_PATH")),
        intermediate_data_dir=_resolve(_require("INTERMEDIATE_DATA_DIR")),
        publish_dir=_resolve(_require("PUBLISH_DIR")),
    )

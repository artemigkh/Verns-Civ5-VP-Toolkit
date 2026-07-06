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
UNIT_INFO_CSV = METADATA_DIR / "unit_info.csv"
CIV_COLORS_CSV = METADATA_DIR / "civ_colors.csv"

ERA_TOTALS_CSV = "building_yields_era_totals_summary.csv"
TURN_AVERAGE_CSV = "building_yields_turn_average_summary.csv"

# Religion report.
RELIGION_TABLE = "ReligionBeliefYields"
# Per-(GameId, Civ, Turn) era assignment; used to amortize sparse instant yields
# across every turn a civ actually spent in an era.
CIV_TURN_ERA_TABLE = "civ_turn_era"
RELIGION_ERA_TOTALS_CSV = "religion_yields_era_totals_summary.csv"
RELIGION_TURN_AVERAGE_CSV = "religion_yields_turn_average_summary.csv"

# Unit-composition report.
UNIT_SUMMARY_CSV = "unit_composition_summary.csv"

# Game-stats reports (analogous to the Scala Spark aggregator's outputs).
GAME_RESULT_CSV = "game_result.csv"
POWER_RANKING_CSV = "power_ranking.csv"
RELIGION_CHOICES_CSV = "religion_choices.csv"
RELIGION_STATS_CSV = "religion_stats.csv"
POLICY_CHOICES_CSV = "policy_choices.csv"

# Religion Performance report (attainment-time KDE + belief pick/win-rate bars).
RELIGION_ATTAINMENT_KDE_CSV = "religion_attainment_kde.csv"
RELIGION_ATTAINMENT_MOMENTS_CSV = "religion_attainment_moments.csv"
RELIGION_PICK_PERF_CSV = "religion_pick_performance.csv"

# Policies Performance report (branch opens + wins by victory type).
POLICY_BRANCH_OPENS_CSV = "policy_branch_opens.csv"
POLICY_BRANCH_WINS_CSV = "policy_branch_wins.csv"


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
    def religion_era_totals_path(self) -> Path:
        return self.intermediate_data_dir / RELIGION_ERA_TOTALS_CSV

    @property
    def religion_turn_average_path(self) -> Path:
        return self.intermediate_data_dir / RELIGION_TURN_AVERAGE_CSV

    @property
    def unit_summary_path(self) -> Path:
        return self.intermediate_data_dir / UNIT_SUMMARY_CSV

    @property
    def game_result_path(self) -> Path:
        return self.intermediate_data_dir / GAME_RESULT_CSV

    @property
    def power_ranking_path(self) -> Path:
        return self.intermediate_data_dir / POWER_RANKING_CSV

    @property
    def religion_choices_path(self) -> Path:
        return self.intermediate_data_dir / RELIGION_CHOICES_CSV

    @property
    def religion_stats_path(self) -> Path:
        return self.intermediate_data_dir / RELIGION_STATS_CSV

    @property
    def policy_choices_path(self) -> Path:
        return self.intermediate_data_dir / POLICY_CHOICES_CSV

    @property
    def religion_attainment_kde_path(self) -> Path:
        return self.intermediate_data_dir / RELIGION_ATTAINMENT_KDE_CSV

    @property
    def religion_attainment_moments_path(self) -> Path:
        return self.intermediate_data_dir / RELIGION_ATTAINMENT_MOMENTS_CSV

    @property
    def religion_pick_performance_path(self) -> Path:
        return self.intermediate_data_dir / RELIGION_PICK_PERF_CSV

    @property
    def policy_branch_opens_path(self) -> Path:
        return self.intermediate_data_dir / POLICY_BRANCH_OPENS_CSV

    @property
    def policy_branch_wins_path(self) -> Path:
        return self.intermediate_data_dir / POLICY_BRANCH_WINS_CSV

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

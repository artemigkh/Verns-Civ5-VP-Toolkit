"""The datasets one build renders, and which reports each of them can show.

A dataset is one autoplay run's stats DB plus the descriptors shown on its KPI
cards. The launcher's env vars (see :mod:`.config`) name the default one; the
rest come from ``datasets.toml`` (see the comments there).

Older runs predate some of the logging tables -- ``InstantYields`` arrived after
the first DuckDB runs, for instance -- so every aggregation step names the
source tables it reads and is skipped when any is missing. A report is then
unavailable when its tables are missing -- checked against the tables rather
than the cache, so a CSV left over in a cache directory from another DB cannot
pass as this one's -- or when a CSV it renders from was never built.
"""

from __future__ import annotations

import dataclasses
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .aggregate import (
    ensure_authority_summaries,
    ensure_game_summaries,
    ensure_instant_yields_summaries,
    ensure_policies_performance_summaries,
    ensure_religion_performance_summaries,
    ensure_religion_summaries,
    ensure_summaries,
    ensure_unit_summaries,
    ensure_wonders_summaries,
)
from .config import (
    CIV_TURN_ERA_TABLE,
    INSTANT_YIELDS_TABLE,
    RELIGION_TABLE,
    REPO_ROOT,
    Config,
)
from .db import list_tables

DATASETS_TOML = REPO_ROOT / "analysis" / "plotly_explorer" / "datasets.toml"

# Prefix every run directory shares; stripped to name a DB_PATH that matches no
# datasets.toml entry.
RUN_DIR_PREFIX = "MP_AUTOPLAY_VP_"

# Dataset ids go into URLs and file names, so keep them to a safe alphabet.
_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# Tables the game-stats summaries read. Religion Performance, Policies
# Performance and Wonders build on those summaries, so they need these too.
_GAME_TABLES = {"GameResult", "ReligionChoices", "PolicyChoices", "MapPlotsState"}

# Aggregation steps in run order (later steps read earlier steps' CSVs), each
# with the source tables it reads directly or through a step it builds on.
STEPS: list[tuple[Callable[..., None], set[str]]] = [
    (ensure_summaries, {"BuildingsOverview", "BuildingYields", "BuildingInstantYields"}),
    (ensure_religion_summaries, {RELIGION_TABLE, CIV_TURN_ERA_TABLE}),
    (ensure_unit_summaries, {"MapUnitsState", CIV_TURN_ERA_TABLE}),
    (ensure_game_summaries, _GAME_TABLES),
    (ensure_authority_summaries, _GAME_TABLES),
    (ensure_religion_performance_summaries, _GAME_TABLES),
    (ensure_policies_performance_summaries, _GAME_TABLES),
    (ensure_instant_yields_summaries, {INSTANT_YIELDS_TABLE, CIV_TURN_ERA_TABLE}),
    (ensure_wonders_summaries, _GAME_TABLES | {"BuildingsOverview"}),
]


def _report_sources(cfg: Config) -> dict[str, tuple[set[str], list[Path]]]:
    """Report key -> (source tables, intermediate CSVs its payload reads).

    Keys match the frontend's report keys. Leaders, Process Memory and the
    Interface Draw List Buffer render static reference data, not the stats DB,
    so every dataset has them and they are not listed.
    """
    building = (
        {"BuildingsOverview", "BuildingYields", "BuildingInstantYields"},
        [cfg.turn_average_path, cfg.era_totals_path],
    )
    return {
        "civs": (_GAME_TABLES, [cfg.game_result_path, cfg.power_ranking_path]),
        "building": building,
        "building_grouped": building,
        "religion": (
            {RELIGION_TABLE, CIV_TURN_ERA_TABLE},
            [
                cfg.religion_turn_average_path,
                cfg.religion_era_totals_path,
                cfg.religion_bucket_average_path,
                cfg.religion_bucket_totals_path,
            ],
        ),
        "units": ({"MapUnitsState", CIV_TURN_ERA_TABLE}, [cfg.unit_summary_path]),
        "religion_performance": (
            _GAME_TABLES,
            [
                cfg.religion_attainment_kde_path,
                cfg.religion_attainment_moments_path,
                cfg.religion_pick_performance_path,
                cfg.game_result_path,
            ],
        ),
        "policies_performance": (
            _GAME_TABLES,
            [cfg.policy_branch_opens_path, cfg.policy_branch_wins_path, cfg.game_result_path],
        ),
        "instant_yields": (
            {INSTANT_YIELDS_TABLE, CIV_TURN_ERA_TABLE},
            [cfg.instant_yields_summary_path],
        ),
        "wonders": (
            _GAME_TABLES | {"BuildingsOverview"},
            [cfg.wonder_builds_path, cfg.wonder_game_civs_path, cfg.game_result_path],
        ),
    }


@dataclass(frozen=True)
class Dataset:
    id: str
    label: str
    cfg: Config
    patch: str
    difficulty: str
    mapscript: str
    size: str
    is_default: bool = False

    def ensure_summaries(self, *, force: bool = False) -> None:
        """Run every aggregation step whose source tables this DB has."""
        tables = list_tables(self.cfg)
        for step, needs in STEPS:
            missing = sorted(needs - tables)
            if missing:
                print(f"[{self.id}] skipping {step.__name__}: no {', '.join(missing)} table")
                continue
            step(self.cfg, force=force)

    def unavailable_reports(self) -> dict[str, str]:
        """Report key -> why this dataset cannot show it (empty if it shows all)."""
        tables = list_tables(self.cfg)
        out: dict[str, str] = {}
        for key, (needs, csvs) in _report_sources(self.cfg).items():
            missing = sorted(needs - tables)
            if missing:
                out[key] = f"This dataset predates the {', '.join(missing)} logging this report needs."
            elif not all(p.exists() for p in csvs):
                out[key] = "This report's summaries were not built for this dataset."
        return out


def _resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _same_file(a: Path, b: Path) -> bool:
    return a.resolve() == b.resolve()


def load_datasets(
    default_cfg: Config, *, patch: str, difficulty: str, mapscript: str, size: str
) -> list[Dataset]:
    """The datasets to render, in dropdown order, with exactly one default.

    ``default_cfg`` (from the launcher's env vars) and the descriptor arguments
    (its CLI args) describe the default dataset, replacing the matching
    ``datasets.toml`` entry's paths and descriptors.
    """
    entries = []
    if DATASETS_TOML.exists():
        entries = tomllib.loads(DATASETS_TOML.read_text(encoding="utf-8")).get("dataset", [])

    default_kwargs = dict(
        cfg=default_cfg,
        patch=patch,
        difficulty=difficulty,
        mapscript=mapscript,
        size=size,
        is_default=True,
    )

    datasets: list[Dataset] = []
    have_default = False
    for entry in entries:
        ds_id = str(entry["id"])
        if not _ID_RE.match(ds_id):
            raise SystemExit(f"{DATASETS_TOML.name}: dataset id {ds_id!r} must match {_ID_RE.pattern}")
        label = str(entry.get("label", ds_id))
        db_path = _resolve(entry["db_path"])

        if not have_default and _same_file(db_path, default_cfg.db_path):
            datasets.append(Dataset(id=ds_id, label=label, **default_kwargs))
            have_default = True
            continue

        if not db_path.exists():
            print(f"[datasets] {ds_id}: {db_path} not found, leaving it out")
            continue
        cache_dir = entry.get("cache_dir")
        cfg = dataclasses.replace(
            default_cfg,
            db_type=str(entry.get("db_type", "duckdb" if db_path.suffix == ".duckdb" else "sqlite")),
            db_path=db_path,
            intermediate_data_dir=(
                _resolve(cache_dir) if cache_dir else db_path.parent / "plotly_explorer_cache"
            ),
        )
        datasets.append(
            Dataset(
                id=ds_id,
                label=label,
                cfg=cfg,
                patch=str(entry.get("patch", "")),
                difficulty=str(entry.get("difficulty", "")),
                mapscript=str(entry.get("mapscript", "")),
                size=str(entry.get("size", "")),
            )
        )

    if not have_default:
        run_dir = default_cfg.db_path.parent.name
        ds_id = re.sub(r"[^A-Za-z0-9_.-]", "_", run_dir.removeprefix(RUN_DIR_PREFIX)) or "default"
        if any(d.id == ds_id for d in datasets):
            ds_id += "_default"
        datasets.insert(0, Dataset(id=ds_id, label=f"VP {patch} {difficulty}", **default_kwargs))

    ids = [d.id for d in datasets]
    if len(set(ids)) != len(ids):
        raise SystemExit(f"{DATASETS_TOML.name}: duplicate dataset ids in {ids}")
    return datasets

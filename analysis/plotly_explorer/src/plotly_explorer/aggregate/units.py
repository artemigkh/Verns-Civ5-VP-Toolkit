"""Aggregate the stats DB into the unit-composition summary CSV.

The summary has the columns::

    Era, Civ, Unit, AvgCount

``AvgCount`` is the average number of a unit type a civ has on the map in an
average turn within an era::

    AvgCount(Civ, Era, Unit) =
        (# MapUnitsState rows for that Civ, Era, Unit)
        / (# distinct (GameId, Turn) snapshots that Civ spent in that Era)

Era comes from ``civ_turn_era`` (the game-state era of the snapshot turn), not
the unit's unlock era. The DB is only re-read when its mtime changes (tracked in
a sidecar file), so repeat runs are cheap.
"""

from __future__ import annotations

import os

import pandas as pd

from ..config import Config
from ..db import read_table
from ..metadata import db_era_to_name

# Columns of the emitted CSV, in order.
OUTPUT_COLUMNS = ["Era", "Civ", "Unit", "AvgCount"]


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def _source_mtime(cfg: Config) -> str:
    return f"{os.path.getmtime(cfg.db_path):.6f}"


def _cache_is_fresh(cfg: Config) -> bool:
    if not cfg.unit_summary_path.exists():
        return False
    if not cfg.unit_source_mtime_path.exists():
        return False
    return (
        cfg.unit_source_mtime_path.read_text(encoding="utf-8").strip()
        == _source_mtime(cfg)
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _build_summary(cfg: Config) -> pd.DataFrame:
    units = read_table(cfg, "MapUnitsState")
    eras = read_table(cfg, "civ_turn_era")

    # Attach the game-state era to each unit snapshot via (GameId, Turn, civ).
    joined = units.merge(
        eras[["GameId", "Turn", "civ", "era"]],
        left_on=["GameId", "Turn", "owner"],
        right_on=["GameId", "Turn", "civ"],
        how="inner",
    ).rename(columns={"owner": "Civ", "unitName": "Unit", "era": "Era"})

    # Numerator: how many of each unit the civ had, summed over all its era turns.
    counts = (
        joined.groupby(["Civ", "Era", "Unit"], as_index=False)
        .size()
        .rename(columns={"size": "TotalCount"})
    )

    # Denominator: distinct snapshot turns the civ spent in the era.
    turns = (
        joined[["Civ", "Era", "GameId", "Turn"]]
        .drop_duplicates()
        .groupby(["Civ", "Era"], as_index=False)
        .size()
        .rename(columns={"size": "CivTurns"})
    )

    merged = counts.merge(turns, on=["Civ", "Era"], how="left")
    merged["AvgCount"] = merged["TotalCount"] / merged["CivTurns"]

    return _finalize(merged)


def _finalize(df: pd.DataFrame) -> pd.DataFrame:
    """Map DB era -> display name, drop unmapped eras, order columns/rows."""
    df = df.copy()
    df["Era"] = df["Era"].map(db_era_to_name)
    df = df.dropna(subset=["Era"])
    df = df[OUTPUT_COLUMNS]
    return df.sort_values(["Civ", "Era", "Unit"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ensure_unit_summaries(cfg: Config, *, force: bool = False) -> None:
    """Generate the unit-composition summary CSV if the cache is stale (or ``force``)."""
    cfg.intermediate_data_dir.mkdir(parents=True, exist_ok=True)

    if not force and _cache_is_fresh(cfg):
        print(f"[units] cache fresh, reusing {cfg.intermediate_data_dir}")
        return

    print(f"[units] building summary from {cfg.db_path} ({cfg.db_type})")
    summary = _build_summary(cfg)
    summary.to_csv(cfg.unit_summary_path, index=False)
    cfg.unit_source_mtime_path.write_text(_source_mtime(cfg), encoding="utf-8")
    print(f"[units] wrote {len(summary)} rows")

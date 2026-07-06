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

import pandas as pd

from ..config import Config
from ..db import read_table
from ..metadata import db_era_to_name
from .cache import ensure_csv

# Columns of the emitted CSV, in order. ``N`` is the number of underlying data
# points ``AvgCount`` is averaged over — the distinct snapshot turns the civ
# spent in the era (the divisor) — and drives the tooltip's "n=…" sample line.
OUTPUT_COLUMNS = ["Era", "Civ", "Unit", "AvgCount", "N"]


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
    # Sample size = the divisor (snapshot turns the average is taken over).
    merged["N"] = merged["CivTurns"].fillna(0).astype(int)

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
    """Generate the unit-composition summary CSV if it is stale (or ``force``)."""
    ensure_csv(cfg, cfg.unit_summary_path, lambda: _build_summary(cfg), force=force)

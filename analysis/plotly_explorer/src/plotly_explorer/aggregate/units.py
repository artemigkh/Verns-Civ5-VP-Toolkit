"""Aggregate the stats DB into the unit-composition summary CSV.

The summary has the columns::

    Era, Civ, Unit, AvgCount

``AvgCount`` is the average number of a unit type a civ has on the map in an
average turn within an era::

    AvgCount(Civ, Era, Unit) =
        (# MapUnitsState rows for that Civ, Era, Unit)
        / (# distinct (GameId, Turn) snapshots that Civ spent in that Era)

Era comes from ``civ_turn_era`` (the game-state era of the snapshot turn), not
the unit's unlock era.

The join and both counts run in the DB — ``MapUnitsState`` is ~36M rows, far too
large to read whole (see :mod:`plotly_explorer.db`) — and only the per-(Civ, Era,
Unit) counts come back. The DB is only re-read when its mtime changes (tracked in
a sidecar file), so repeat runs are cheap.
"""

from __future__ import annotations

import pandas as pd

from ..config import CIV_TURN_ERA_TABLE, Config
from ..db import read_query
from ..metadata import db_era_to_name
from .cache import ensure_csv

# Columns of the emitted CSV, in order. ``N`` is the number of underlying data
# points ``AvgCount`` is averaged over — the distinct snapshot turns the civ
# spent in the era (the divisor) — and drives the tooltip's "n=…" sample line.
OUTPUT_COLUMNS = ["Era", "Civ", "Unit", "AvgCount", "N"]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

# ``joined`` attaches the game-state era to each unit snapshot via
# (GameId, Turn, civ); ``counts`` is the numerator (how many of each unit the civ
# had, summed over all its era turns) and ``turns`` the denominator (distinct
# snapshot turns the civ spent in the era). Both derive from the same join, so a
# civ-turn with no matching era row contributes to neither.
_SUMMARY_SQL = f"""
WITH joined AS (
    SELECT u."GameId" AS GameId,
           u."Turn"   AS Turn,
           u."owner"  AS Civ,
           u."unitName" AS Unit,
           e."era"    AS Era
    FROM "MapUnitsState" u
    JOIN "{CIV_TURN_ERA_TABLE}" e
      ON u."GameId" = e."GameId"
     AND u."Turn"   = e."Turn"
     AND u."owner"  = e."civ"
),
counts AS (
    SELECT Civ, Era, Unit, CAST(COUNT(*) AS BIGINT) AS TotalCount
    FROM joined
    GROUP BY Civ, Era, Unit
),
turns AS (
    SELECT Civ, Era, CAST(COUNT(*) AS BIGINT) AS CivTurns
    FROM (SELECT DISTINCT Civ, Era, GameId, Turn FROM joined) d
    GROUP BY Civ, Era
)
SELECT c.Civ, c.Era, c.Unit, c.TotalCount, t.CivTurns
FROM counts c
LEFT JOIN turns t ON t.Civ = c.Civ AND t.Era = c.Era
"""


def _build_summary(cfg: Config) -> pd.DataFrame:
    merged = read_query(cfg, _SUMMARY_SQL)
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

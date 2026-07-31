"""Aggregate the ``InstantYields`` table into a per-(Era, Type, Yield) summary.

Instant yields are one-off yield grants tagged with a trigger ``Type`` (Barb Camp,
Conquest, Tech, Spread Religion, …). One row is one grant of a yield; the raw table
holds ``GameId, Turn, Civ, Era, Type, Yield, YieldTimes100``.

The emitted CSV ``instant_yields_summary.csv`` has one row per (Era, Type, Yield):

    Era, Type, Yield, AvgYieldAmount, AvgTriggerAmount, AvgTimesTriggered

For each (era, type, yield), with ``total_yield = SUM(YieldTimes100)/100`` and
``trigger_count = COUNT(*)`` over the trigger rows, and ``N_era`` = the number of
distinct ``(GameId, Civ)`` player-instances that reached the era:

* ``AvgYieldAmount``   = total_yield / N_era      (amortized over ALL era-civ
                                                   instances, incl. those that
                                                   never fired this trigger)
* ``AvgTriggerAmount`` = total_yield / trigger_count  (mean per firing, over
                                                       triggers that happened)
* ``AvgTimesTriggered``= trigger_count / N_era    (mean firings per era, amortized
                                                   over ALL era-civ instances)

These satisfy ``AvgYieldAmount = AvgTriggerAmount * AvgTimesTriggered``.

Era comes from ``civ_turn_era`` (joined on GameId/Turn/Civ), **not** the raw
table's own ``Era`` column: the two use different indexing and disagree at era
boundaries, so deriving era from ``civ_turn_era`` keeps the numerator and the
``N_era`` denominator on one consistent era definition (as the Scala
``InstantYields.scala`` pipeline does). ``db_era_to_name`` then maps the 0-indexed
``civ_turn_era`` era to its display name.

The heavy join/group runs in the DB (the raw table has millions of rows) and only
a few-thousand-row aggregate comes back. The SQL is kept portable across SQLite
and DuckDB. The DB is only re-read when its mtime changes.
"""

from __future__ import annotations

import pandas as pd

from ..config import CIV_TURN_ERA_TABLE, INSTANT_YIELDS_TABLE, Config
from ..db import read_query
from ..metadata import db_era_to_name
from .cache import ensure_csv

OUTPUT_COLUMNS = [
    "Era",
    "Type",
    "Yield",
    "AvgYieldAmount",
    "AvgTriggerAmount",
    "AvgTimesTriggered",
]


def _build_summary(cfg: Config) -> pd.DataFrame:
    # Numerators: total yield + firing count per (era, type, yield), with era
    # taken from civ_turn_era so it matches the N_era denominator below.
    agg_sql = f"""
        SELECT e.era AS Era,
               iy."Type" AS Type,
               iy."Yield" AS Yield,
               SUM(iy."YieldTimes100") / 100.0 AS TotalYield,
               COUNT(*) AS TriggerCount
        FROM "{INSTANT_YIELDS_TABLE}" iy
        JOIN "{CIV_TURN_ERA_TABLE}" e
          ON iy."GameId" = e."GameId"
         AND iy."Turn" = e."Turn"
         AND iy."Civ" = e."civ"
        GROUP BY e.era, iy."Type", iy."Yield"
    """
    agg = read_query(cfg, agg_sql)

    # Denominator: distinct (GameId, Civ) player-instances present in each era.
    # CAST + '||' concatenation is portable across SQLite and DuckDB (avoids
    # DuckDB-only tuple COUNT(DISTINCT ...) syntax).
    denom_sql = f"""
        SELECT era AS Era,
               COUNT(DISTINCT CAST("GameId" AS VARCHAR) || '-' || "civ") AS NEra
        FROM "{CIV_TURN_ERA_TABLE}"
        GROUP BY era
    """
    denom = read_query(cfg, denom_sql)

    df = agg.merge(denom, on="Era", how="left")
    df = df[df["NEra"].fillna(0) > 0].copy()

    df["AvgYieldAmount"] = df["TotalYield"] / df["NEra"]
    df["AvgTriggerAmount"] = df["TotalYield"] / df["TriggerCount"]
    df["AvgTimesTriggered"] = df["TriggerCount"] / df["NEra"]

    df["Era"] = df["Era"].map(db_era_to_name)
    df = df.dropna(subset=["Era"])

    df = df[OUTPUT_COLUMNS]
    return df.sort_values(["Type", "Yield", "Era"]).reset_index(drop=True)


def ensure_instant_yields_summaries(cfg: Config, *, force: bool = False) -> None:
    """Generate the instant-yields summary CSV if stale (or ``force``)."""
    ensure_csv(
        cfg,
        cfg.instant_yields_summary_path,
        lambda: _build_summary(cfg),
        force=force,
    )

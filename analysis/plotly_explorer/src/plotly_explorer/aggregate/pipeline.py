"""Aggregate the stats DB into the two per-era yield summary CSVs.

Both summaries share the columns::

    Era, Building, Yield, BaseYields, BonusYields, InstantYields

* ``building_yields_turn_average_summary.csv`` divides yield sums by the number of
  building-turn instances (``BuildingTurns`` = ``sum(Count)`` = building copies ×
  turns each existed) — the per-turn yield of a **single copy** within an era.
* ``building_yields_era_totals_summary.csv`` scales that per-copy-per-turn rate by
  how long the average civ keeps the building in the era (``CivTurnsPresent /
  CivGames``, the mean number of turns a civ-game held it) — what one copy earns
  across the whole era for an average civ. Equivalently, it is the old all-copies
  era total divided by the average number of simultaneous copies, so a civ holding
  ~4 copies no longer looks like it earns four buildings' worth from one.

Both summaries therefore rest on the same per-copy-per-turn figure ``Total /
BuildingTurns``, which normalizes out how many copies a civ holds. Instant yields
fire on only a small fraction of a building's turns, but dividing by ``BuildingTurns``
amortizes them correctly: a sparse instant yield is spread across every building-turn
rather than concentrated on the few turns it fired, and it lands on the same
per-copy basis as the base/bonus yields it stacks with in the chart. This is why we
do **not** amortize instant yields over ``civ_turn_era`` the way the religion pipeline
does — beliefs have no "copies", so religion divides by turns-in-era, but a building
must additionally be normalized by how many copies a civ holds. (E.g. a civ with ~4
Harappan Reservoirs would otherwise show ~4× the instant yield of a civ with one.)

All five aggregations run in the DB and only the merged, few-thousand-row result
comes back (``BuildingYields`` alone is ~250M rows — reading it whole needs tens
of GiB and used to blow up in ``pd.DataFrame`` construction). See
:mod:`plotly_explorer.db` for the memory bound that gives.

The DB is only re-read when its mtime changes (tracked in a sidecar file), so
repeat runs are cheap.
"""

from __future__ import annotations

import pandas as pd

from ..config import Config
from ..db import read_query
from ..metadata import db_era_to_name
from .cache import ensure_group

# Columns of the emitted CSVs, in order. ``N`` is the sample size a row is averaged
# over: CivGames (civ-game instances that held the building) for the era-totals
# summary, BuildingTurns (building-turn instances) for the turn-average summary. It
# is the same across every yield/segment of a given (Building, Era) and drives the
# "n=…" sample-size line in the chart tooltips.
OUTPUT_COLUMNS = [
    "Era",
    "Building",
    "Yield",
    "BaseYields",
    "BonusYields",
    "InstantYields",
    "N",
]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

# The numerators (summed yields) and denominators (building-turn / civ-game
# counts), merged into one row per (Era, Building, Yield). Every step runs in the
# DB; the result is a few thousand rows. The CTEs, in order:
#
# 1. ``building_turns``    — total Building-Turn instances per (Building, Era) =
#    ``SUM(Count)``. ``Count`` is how many of the building a civ holds that turn,
#    so summing it over every (GameId, Turn, Civ) row yields building copies ×
#    turns — the denominator that makes the turn-average a per-building, per-turn
#    figure for all yield kinds (including the sparse instant yields).
# 2. ``civ_games``         — distinct (GameId, Civ) per (Building, Era).
# 2b.``civ_turns_present`` — distinct (GameId, Civ, Turn) the building was present
#    per (Building, Era). Unlike ``BuildingTurns`` (copy-turns) this is
#    copy-agnostic: it counts civ-turns the building existed at all, regardless of
#    how many copies. ``BuildingTurns / CivTurnsPresent`` is thus the average
#    number of simultaneous copies, and ``CivTurnsPresent / CivGames`` is the
#    average number of turns a civ-game held the building — the span used to turn
#    the single-copy per-turn yield into a single-copy era total.
# 3. ``base_bonus``        — summed base/bonus yields per (Era, Building, Yield),
#    converted from the DB's ×100 integers to real units.
# 4. ``instant``           — summed instant yields, all EventTypes pooled, per
#    (Era, Building, Yield). Pooled across the firing turns; the division by
#    ``BuildingTurns`` below is what amortizes this era total into a
#    per-building, per-turn average (see the module docstring).
#
# ``keys`` is the union of the base/bonus and instant key sets, which with the two
# LEFT JOINs reproduces a full outer join portably (SQLite only gained FULL OUTER
# JOIN in 3.39). The counts are CAST back to BIGINT because DuckDB widens SUM/
# COUNT over BIGINT to INT128, which pandas would otherwise surface as an object
# column. Denominators are LEFT JOINed and stay NULL when a (Building, Era) has no
# overview rows, exactly as the previous left merges did.
_MERGED_SQL = """
WITH building_turns AS (
    SELECT "Building", "Era", CAST(SUM("Count") AS BIGINT) AS BuildingTurns
    FROM "BuildingsOverview"
    GROUP BY "Building", "Era"
),
civ_games AS (
    SELECT "Building", "Era", CAST(COUNT(*) AS BIGINT) AS CivGames
    FROM (SELECT DISTINCT "Building", "Era", "GameId", "Civ" FROM "BuildingsOverview") d
    GROUP BY "Building", "Era"
),
civ_turns_present AS (
    SELECT "Building", "Era", CAST(COUNT(*) AS BIGINT) AS CivTurnsPresent
    FROM (SELECT DISTINCT "Building", "Era", "GameId", "Civ", "Turn" FROM "BuildingsOverview") d
    GROUP BY "Building", "Era"
),
base_bonus AS (
    SELECT "Era", "Building", "Yield",
           SUM("BaseYieldTimes100") / 100.0  AS BaseYields,
           SUM("BonusYieldTimes100") / 100.0 AS BonusYields
    FROM "BuildingYields"
    GROUP BY "Era", "Building", "Yield"
),
instant AS (
    SELECT "Era", "Building", "Yield",
           SUM("YieldTimes100") / 100.0 AS InstantYields
    FROM "BuildingInstantYields"
    GROUP BY "Era", "Building", "Yield"
),
keys AS (
    SELECT "Era", "Building", "Yield" FROM base_bonus
    UNION
    SELECT "Era", "Building", "Yield" FROM instant
)
SELECT k."Era", k."Building", k."Yield",
       COALESCE(bb.BaseYields, 0.0)   AS BaseYields,
       COALESCE(bb.BonusYields, 0.0)  AS BonusYields,
       COALESCE(i.InstantYields, 0.0) AS InstantYields,
       bt.BuildingTurns,
       cg.CivGames,
       ctp.CivTurnsPresent
FROM keys k
LEFT JOIN base_bonus bb
       ON bb."Era" = k."Era" AND bb."Building" = k."Building" AND bb."Yield" = k."Yield"
LEFT JOIN instant i
       ON i."Era" = k."Era" AND i."Building" = k."Building" AND i."Yield" = k."Yield"
LEFT JOIN building_turns bt     ON bt."Building" = k."Building"  AND bt."Era" = k."Era"
LEFT JOIN civ_games cg          ON cg."Building" = k."Building"  AND cg."Era" = k."Era"
LEFT JOIN civ_turns_present ctp ON ctp."Building" = k."Building" AND ctp."Era" = k."Era"
"""


def _build_summaries(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    # One row per (Era, Building, Yield) with its numerators and denominators.
    merged = read_query(cfg, _MERGED_SQL)

    value_cols = ["BaseYields", "BonusYields", "InstantYields"]

    def _assemble(values: dict[str, pd.Series], sample_size: pd.Series) -> pd.DataFrame:
        out = merged[["Era", "Building", "Yield"]].copy()
        for col in value_cols:
            out[col] = values[col].fillna(0.0)
        out["N"] = sample_size.fillna(0).astype(int)
        return out

    # Per-copy, per-turn yield: normalizes out how many copies a civ holds.
    copy_turns = merged["BuildingTurns"].replace(0, pd.NA)
    per_copy_per_turn = {col: merged[col] / copy_turns for col in value_cols}
    turn_average = _assemble(per_copy_per_turn, merged["BuildingTurns"])

    # Single-copy era total: the per-copy-per-turn rate times the average number of
    # turns a civ-game held the building. This replaces the old all-copies era total
    # (Total / CivGames), which summed every copy but divided only by civ-games.
    avg_turns_present = merged["CivTurnsPresent"] / merged["CivGames"].replace(0, pd.NA)
    era_values = {col: per_copy_per_turn[col] * avg_turns_present for col in value_cols}
    era_totals = _assemble(era_values, merged["CivGames"])

    return _finalize(era_totals), _finalize(turn_average)


def _finalize(df: pd.DataFrame) -> pd.DataFrame:
    """Map DB era -> display name, drop unmapped eras, order columns/rows."""
    df = df.copy()
    df["Era"] = df["Era"].map(db_era_to_name)
    df = df.dropna(subset=["Era"])
    df = df[OUTPUT_COLUMNS]
    return df.sort_values(["Yield", "Era", "Building"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ensure_summaries(cfg: Config, *, force: bool = False) -> None:
    """Generate the two building-yield summary CSVs if either is stale (or ``force``)."""
    ensure_group(
        cfg,
        [cfg.era_totals_path, cfg.turn_average_path],
        lambda: _build_summaries(cfg),
        force=force,
    )

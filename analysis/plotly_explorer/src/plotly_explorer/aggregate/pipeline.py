"""Aggregate the stats DB into the two per-era yield summary CSVs.

Both summaries share the columns::

    Era, Building, Yield, BaseYields, BonusYields, InstantYields

* ``building_yields_era_totals_summary.csv`` divides yield sums by the number of
  civ-game instances of the building in that era — what an average civ sees from
  one building in one city across an entire era.
* ``building_yields_turn_average_summary.csv`` divides yield sums by the number of
  building-turn instances in the dataset — the per-turn average within an era.

All three yield kinds (base, bonus, instant) share these two denominators. Instant
yields fire on only a small fraction of a building's turns, but ``BuildingTurns``
(``sum(Count)`` = building copies × turns each existed) already amortizes them
correctly: dividing by it is at once a per-turn *and* a per-building average, so a
sparse instant yield is spread across every building-turn rather than concentrated
on the few turns it fired. This is why we do **not** amortize instant yields over
``civ_turn_era`` the way the religion pipeline does — beliefs have no "copies", so
religion divides by turns-in-era, but a building must additionally be normalized by
how many copies a civ holds. (E.g. a civ with ~4 Harappan Reservoirs would otherwise
show ~4× the per-turn instant yield of a civ with one, implying every city grows
almost every turn.) Keeping instant on ``BuildingTurns`` also keeps it on the same
per-building basis as the base/bonus yields it stacks with in the chart.

The DB is only re-read when its mtime changes (tracked in a sidecar file), so
repeat runs are cheap.
"""

from __future__ import annotations

import os

import pandas as pd

from ..config import Config
from ..db import read_table
from ..metadata import db_era_to_name

# Columns of the emitted CSVs, in order.
OUTPUT_COLUMNS = ["Era", "Building", "Yield", "BaseYields", "BonusYields", "InstantYields"]


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def _source_mtime(cfg: Config) -> str:
    return f"{os.path.getmtime(cfg.db_path):.6f}"


def _cache_is_fresh(cfg: Config) -> bool:
    if not (cfg.era_totals_path.exists() and cfg.turn_average_path.exists()):
        return False
    if not cfg.source_mtime_path.exists():
        return False
    return cfg.source_mtime_path.read_text(encoding="utf-8").strip() == _source_mtime(cfg)


# ---------------------------------------------------------------------------
# Aggregation steps
# ---------------------------------------------------------------------------

def _building_turn_counts(overview: pd.DataFrame) -> pd.DataFrame:
    """Step 1: total Building-Turn instances per (Building, Era) = sum(Count).

    ``Count`` is how many of the building a civ holds that turn, so summing it over
    every (GameId, Turn, Civ) row yields building copies × turns — the denominator
    that makes the turn-average a per-building, per-turn figure for all yield kinds
    (including the sparse instant yields).
    """
    return (
        overview.groupby(["Building", "Era"], as_index=False)["Count"]
        .sum()
        .rename(columns={"Count": "BuildingTurns"})
    )


def _civ_game_counts(overview: pd.DataFrame) -> pd.DataFrame:
    """Step 2: distinct (GameId, Civ) per (Building, Era)."""
    distinct = overview[["Building", "Era", "GameId", "Civ"]].drop_duplicates()
    return (
        distinct.groupby(["Building", "Era"], as_index=False)
        .size()
        .rename(columns={"size": "CivGames"})
    )


def _base_bonus_yields(yields: pd.DataFrame) -> pd.DataFrame:
    """Step 3: summed base/bonus yields per (Era, Building, Yield) in real units."""
    agg = (
        yields.groupby(["Era", "Building", "Yield"], as_index=False)[
            ["BaseYieldTimes100", "BonusYieldTimes100"]
        ]
        .sum()
    )
    agg["BaseYields"] = agg["BaseYieldTimes100"] / 100.0
    agg["BonusYields"] = agg["BonusYieldTimes100"] / 100.0
    return agg[["Era", "Building", "Yield", "BaseYields", "BonusYields"]]


def _instant_yields(instant: pd.DataFrame) -> pd.DataFrame:
    """Step 4: summed instant yields (all EventTypes pooled) per (Era, Building, Yield).

    Pooled across the firing turns; the division by ``BuildingTurns`` in
    ``_build_summaries`` is what amortizes this era total into a per-building,
    per-turn average (see the module docstring).
    """
    agg = (
        instant.groupby(["Era", "Building", "Yield"], as_index=False)["YieldTimes100"]
        .sum()
    )
    agg["InstantYields"] = agg["YieldTimes100"] / 100.0
    return agg[["Era", "Building", "Yield", "InstantYields"]]


def _build_summaries(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    overview = read_table(cfg, "BuildingsOverview")
    yields = read_table(cfg, "BuildingYields")
    instant = read_table(cfg, "BuildingInstantYields")

    building_turns = _building_turn_counts(overview)
    civ_games = _civ_game_counts(overview)
    base_bonus = _base_bonus_yields(yields)
    instant_agg = _instant_yields(instant)

    # Outer-merge base/bonus with instant on (Era, Building, Yield).
    merged = base_bonus.merge(instant_agg, on=["Era", "Building", "Yield"], how="outer")
    for col in ("BaseYields", "BonusYields", "InstantYields"):
        merged[col] = merged[col].fillna(0.0)

    # Attach denominators (keyed in DB-era space).
    merged = merged.merge(building_turns, on=["Building", "Era"], how="left")
    merged = merged.merge(civ_games, on=["Building", "Era"], how="left")

    value_cols = ["BaseYields", "BonusYields", "InstantYields"]

    def _divide(denominator: pd.Series) -> pd.DataFrame:
        out = merged[["Era", "Building", "Yield"]].copy()
        denom = denominator.replace(0, pd.NA)
        for col in value_cols:
            out[col] = (merged[col] / denom).fillna(0.0)
        return out

    era_totals = _divide(merged["CivGames"])
    turn_average = _divide(merged["BuildingTurns"])

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
    """Generate the two summary CSVs if the cache is stale (or ``force``)."""
    cfg.intermediate_data_dir.mkdir(parents=True, exist_ok=True)

    if not force and _cache_is_fresh(cfg):
        print(f"[aggregate] cache fresh, reusing {cfg.intermediate_data_dir}")
        return

    print(f"[aggregate] building summaries from {cfg.db_path} ({cfg.db_type})")
    era_totals, turn_average = _build_summaries(cfg)
    era_totals.to_csv(cfg.era_totals_path, index=False)
    turn_average.to_csv(cfg.turn_average_path, index=False)
    cfg.source_mtime_path.write_text(_source_mtime(cfg), encoding="utf-8")
    print(
        f"[aggregate] wrote {len(era_totals)} era-total rows and "
        f"{len(turn_average)} turn-average rows"
    )

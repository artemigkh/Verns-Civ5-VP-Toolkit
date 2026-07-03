"""Aggregate the stats DB into the two per-era yield summary CSVs.

Both summaries share the columns::

    Era, Building, Yield, BaseYields, BonusYields, InstantYields

* ``building_yields_era_totals_summary.csv`` divides yield sums by the number of
  civ-game instances of the building in that era — what an average civ sees from
  one building in one city across an entire era.
* ``building_yields_turn_average_summary.csv`` divides yield sums by the number of
  building-turn instances in the dataset — the per-turn average within an era.

Instant yields are the exception. They are logged only on the turns a trigger
fires (building completion, and other event effects), so they appear on a small
fraction of a building's turns. Rather than dividing them by ``BuildingTurns``
(which mixes in building copies and only the turns a building existed), they are
amortized the same way the religion pipeline does: each ``(GameId, Civ)`` civ's
instant-yield era total is divided by the number of turns that civ actually spent
in the era (from ``civ_turn_era``), and those per-turn values are then averaged
across the present civ-game instances. The era-total column is unaffected — it is
already the mean of each instance's era total. Base and bonus yields are
continuous, so they keep the ``BuildingTurns`` / ``CivGames`` denominators.

The DB is only re-read when its mtime changes (tracked in a sidecar file), so
repeat runs are cheap.
"""

from __future__ import annotations

import os

import pandas as pd

from ..config import CIV_TURN_ERA_TABLE, Config
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
    """Step 1: total Building-Turn instances per (Building, Era) = sum(Count)."""
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


def _era_turn_counts(cfg: Config) -> pd.DataFrame:
    """Turns each ``(GameId, Civ)`` actually spent in each ``Era`` (from civ_turn_era).

    Instant yields fire on only a small fraction of a building's turns, so to
    amortize them fairly we need the true denominator — how many turns the civ
    spent in the era — which ``civ_turn_era`` provides. Mirrors the religion
    pipeline's ``_era_turn_counts``.
    """
    cte = read_table(cfg, CIV_TURN_ERA_TABLE)
    counts = cte.groupby(["GameId", "civ", "era"], as_index=False).agg(
        EraTurns=("Turn", "nunique")
    )
    return counts.rename(columns={"civ": "Civ", "era": "Era"})


def _instant_yields(cfg: Config, instant: pd.DataFrame) -> pd.DataFrame:
    """Step 4: instant yields (all EventTypes pooled) per (Era, Building, Yield).

    Returns two summed numerators, both later divided by ``CivGames`` (the count of
    present civ-game instances) to produce the era-total and turn-average values:

    * ``InstantEraTotalSum`` — Σ over ``(GameId, Civ)`` instances of that instance's
      era-total instant yield. ``/ CivGames`` gives the mean era total (unchanged
      from the previous pooled sum).
    * ``InstantPerTurnSum`` — Σ over instances of (era total ÷ the turns that civ
      spent in the era, from ``civ_turn_era``). ``/ CivGames`` gives the mean
      per-turn value, amortizing the sparse instant yields across every era turn
      the way the religion pipeline does.
    """
    # Per-instance era total (real units) for each (GameId, Civ, Era, Building, Yield).
    per_instance = (
        instant.groupby(
            ["GameId", "Civ", "Era", "Building", "Yield"], as_index=False
        )["YieldTimes100"]
        .sum()
    )
    per_instance["InstantEraTotal"] = per_instance["YieldTimes100"] / 100.0

    era_turns = _era_turn_counts(cfg)
    per_instance = per_instance.merge(
        era_turns, on=["GameId", "Civ", "Era"], how="left"
    )
    # Drop the rare firing instance with no civ_turn_era coverage (can't amortize).
    per_instance = per_instance[per_instance["EraTurns"].fillna(0) > 0].copy()
    per_instance["InstantPerTurn"] = (
        per_instance["InstantEraTotal"] / per_instance["EraTurns"]
    )

    return per_instance.groupby(["Era", "Building", "Yield"], as_index=False).agg(
        InstantEraTotalSum=("InstantEraTotal", "sum"),
        InstantPerTurnSum=("InstantPerTurn", "sum"),
    )


def _build_summaries(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    overview = read_table(cfg, "BuildingsOverview")
    yields = read_table(cfg, "BuildingYields")
    instant = read_table(cfg, "BuildingInstantYields")

    building_turns = _building_turn_counts(overview)
    civ_games = _civ_game_counts(overview)
    base_bonus = _base_bonus_yields(yields)
    instant_agg = _instant_yields(cfg, instant)

    # Outer-merge base/bonus with instant on (Era, Building, Yield).
    merged = base_bonus.merge(instant_agg, on=["Era", "Building", "Yield"], how="outer")
    for col in ("BaseYields", "BonusYields", "InstantEraTotalSum", "InstantPerTurnSum"):
        merged[col] = merged[col].fillna(0.0)

    # Attach denominators (keyed in DB-era space).
    merged = merged.merge(building_turns, on=["Building", "Era"], how="left")
    merged = merged.merge(civ_games, on=["Building", "Era"], how="left")

    civ_games_denom = merged["CivGames"].replace(0, pd.NA)
    building_turns_denom = merged["BuildingTurns"].replace(0, pd.NA)

    # Era totals: continuous and instant yields alike divide by the present civ-game
    # instances. For instant, InstantEraTotalSum / CivGames is the mean era total.
    era_totals = merged[["Era", "Building", "Yield"]].copy()
    era_totals["BaseYields"] = (merged["BaseYields"] / civ_games_denom).fillna(0.0)
    era_totals["BonusYields"] = (merged["BonusYields"] / civ_games_denom).fillna(0.0)
    era_totals["InstantYields"] = (
        merged["InstantEraTotalSum"] / civ_games_denom
    ).fillna(0.0)

    # Turn averages: continuous yields divide by building-turns; instant yields are
    # already amortized per-instance over civ_turn_era, so InstantPerTurnSum divides
    # by CivGames to average across the present instances (religion-style).
    turn_average = merged[["Era", "Building", "Yield"]].copy()
    turn_average["BaseYields"] = (merged["BaseYields"] / building_turns_denom).fillna(0.0)
    turn_average["BonusYields"] = (
        merged["BonusYields"] / building_turns_denom
    ).fillna(0.0)
    turn_average["InstantYields"] = (
        merged["InstantPerTurnSum"] / civ_games_denom
    ).fillna(0.0)

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

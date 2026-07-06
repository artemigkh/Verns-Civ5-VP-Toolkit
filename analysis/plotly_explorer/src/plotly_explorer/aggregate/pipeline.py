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

The DB is only re-read when its mtime changes (tracked in a sidecar file), so
repeat runs are cheap.
"""

from __future__ import annotations

import pandas as pd

from ..config import Config
from ..db import read_table
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


def _civ_turn_present_counts(overview: pd.DataFrame) -> pd.DataFrame:
    """Step 2b: distinct (GameId, Civ, Turn) the building was present per (Building, Era).

    Unlike ``BuildingTurns`` (``sum(Count)`` = copy-turns), this is copy-agnostic:
    it counts civ-turns the building existed at all, regardless of how many copies.
    ``BuildingTurns / CivTurnsPresent`` is thus the average number of simultaneous
    copies, and ``CivTurnsPresent / CivGames`` is the average number of turns a
    civ-game held the building — the span used to turn the single-copy per-turn
    yield into a single-copy era total.
    """
    distinct = overview[["Building", "Era", "GameId", "Civ", "Turn"]].drop_duplicates()
    return (
        distinct.groupby(["Building", "Era"], as_index=False)
        .size()
        .rename(columns={"size": "CivTurnsPresent"})
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
    civ_turns_present = _civ_turn_present_counts(overview)
    base_bonus = _base_bonus_yields(yields)
    instant_agg = _instant_yields(instant)

    # Outer-merge base/bonus with instant on (Era, Building, Yield).
    merged = base_bonus.merge(instant_agg, on=["Era", "Building", "Yield"], how="outer")
    for col in ("BaseYields", "BonusYields", "InstantYields"):
        merged[col] = merged[col].fillna(0.0)

    # Attach denominators (keyed in DB-era space).
    merged = merged.merge(building_turns, on=["Building", "Era"], how="left")
    merged = merged.merge(civ_games, on=["Building", "Era"], how="left")
    merged = merged.merge(civ_turns_present, on=["Building", "Era"], how="left")

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

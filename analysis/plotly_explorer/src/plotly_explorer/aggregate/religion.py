"""Aggregate the stats DB into the two religion belief-yield summary CSVs.

Both summaries share the columns::

    Era, BeliefType, Belief, Yield, YieldTotalForOwner, YieldTotalForFollower

The raw ``ReligionBeliefYields`` table holds one row per
(GameId, Turn, Era, Civ, Belief, BeliefType, IsReligionOwner, Source, Yield). Those
rows are logged via the game's instant-yield system, so a belief only shows up on
the turns a trigger actually fires — event sources (border growth, faith purchase,
spread, conversion, …) appear on a small fraction of a player's turns. The
aggregation runs in three stages:

1. Pool ``Source`` -> one player-turn's total of a yield from a belief
   (e.g. CityYield + AnySpecialist Science for the same player-turn).
2. Sum each ``(GameId, Civ)`` player's per-turn totals into their era total, then
   divide by the number of turns that player actually spent in the era. The turn
   count comes from ``civ_turn_era`` — **not** the count of turns that happened to
   fire a yield — so sparse instant yields are amortized across every era turn
   instead of being averaged over only the (far fewer) turns they appeared on,
   which previously inflated them.
3. Average across the ``(GameId, Civ)`` player-instances that held the belief in
   the era:

   * ``religion_yields_turn_average_summary.csv`` takes the mean of the per-turn
     values — what a single benefitting player can expect in the average turn of the era.
   * ``religion_yields_era_totals_summary.csv`` takes the mean of the era totals —
     what they can expect across all the turns of the era.

The ``...ForOwner`` / ``...ForFollower`` columns split on ``IsReligionOwner`` (1/0).
This mirrors the building pipeline's "present instances only" convention (only the
players that actually appear form the denominators).

The DB is only re-read when its mtime changes (tracked in a sidecar file), so repeat
runs are cheap.
"""

from __future__ import annotations

import os

import pandas as pd

from ..config import CIV_TURN_ERA_TABLE, RELIGION_TABLE, Config
from ..db import read_table
from ..metadata import db_era_to_name

# Columns of the emitted CSVs, in order.
OUTPUT_COLUMNS = [
    "Era",
    "BeliefType",
    "Belief",
    "Yield",
    "YieldTotalForOwner",
    "YieldTotalForFollower",
]


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def _source_mtime(cfg: Config) -> str:
    return f"{os.path.getmtime(cfg.db_path):.6f}"


def _cache_is_fresh(cfg: Config) -> bool:
    if not (
        cfg.religion_era_totals_path.exists()
        and cfg.religion_turn_average_path.exists()
    ):
        return False
    if not cfg.religion_source_mtime_path.exists():
        return False
    return (
        cfg.religion_source_mtime_path.read_text(encoding="utf-8").strip()
        == _source_mtime(cfg)
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _normalize_owner(series: pd.Series) -> pd.Series:
    """Coerce the IsReligionOwner BOOLEAN column to a plain 0/1 int."""
    if series.dtype == object:
        series = series.astype(str).str.strip().str.lower().map(
            {"1": 1, "true": 1, "0": 0, "false": 0}
        )
    return pd.to_numeric(series, errors="coerce").fillna(0).astype(int)


def _era_turn_counts(cfg: Config) -> pd.DataFrame:
    """Turns each ``(GameId, Civ)`` actually spent in each ``Era``.

    Belief yields are logged only on the turns a trigger fires, so instant-yield
    sources (border growth, faith purchase, spread, …) appear on a small fraction
    of a player's turns. To average them fairly we need the true denominator — how
    many turns the player spent in the era — which ``civ_turn_era`` provides.
    """
    cte = read_table(cfg, CIV_TURN_ERA_TABLE)
    counts = cte.groupby(["GameId", "civ", "era"], as_index=False).agg(
        EraTurns=("Turn", "nunique")
    )
    return counts.rename(columns={"civ": "Civ", "era": "Era"})


def _build_summaries(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = read_table(cfg, RELIGION_TABLE)

    raw = raw.assign(
        IsReligionOwner=_normalize_owner(raw["IsReligionOwner"]),
        YieldValue=pd.to_numeric(raw["YieldTimes100"], errors="coerce").fillna(0.0)
        / 100.0,
    )

    # Stage 1: pool Source -> one player-turn's total of a yield from a belief.
    s1_keys = [
        "GameId",
        "Turn",
        "Era",
        "Civ",
        "Belief",
        "BeliefType",
        "IsReligionOwner",
        "Yield",
    ]
    stage1 = raw.groupby(s1_keys, as_index=False)["YieldValue"].sum()

    # Stage 2: sum a player's per-turn totals into their era total, then divide by
    # the turns they actually spent in the era (from civ_turn_era). This amortizes
    # sparse instant yields across every era turn instead of only the turns that
    # fired, which is what previously inflated the per-turn average.
    s2_keys = [
        "GameId",
        "Civ",
        "Era",
        "Belief",
        "BeliefType",
        "IsReligionOwner",
        "Yield",
    ]
    stage2 = stage1.groupby(s2_keys, as_index=False)["YieldValue"].sum().rename(
        columns={"YieldValue": "PlayerEraTotal"}
    )

    era_turns = _era_turn_counts(cfg)
    stage2 = stage2.merge(era_turns, on=["GameId", "Civ", "Era"], how="left")
    # Drop the rare player-instance with no civ_turn_era coverage (can't amortize).
    stage2 = stage2[stage2["EraTurns"].fillna(0) > 0].copy()
    stage2["PlayerPerTurn"] = stage2["PlayerEraTotal"] / stage2["EraTurns"]

    # Stage 3: average across the (GameId, Civ) player-instances that held the
    # belief in the era ("present instances only" denominator).
    #   * turn_average -> mean per-turn value one benefitting player can expect.
    #   * era_totals   -> mean value across all the turns of the era.
    s3_keys = ["Era", "BeliefType", "Belief", "Yield", "IsReligionOwner"]
    turn_average = (
        stage2.groupby(s3_keys, as_index=False)["PlayerPerTurn"]
        .mean()
        .rename(columns={"PlayerPerTurn": "PerTurnAvg"})
    )
    era_totals = (
        stage2.groupby(s3_keys, as_index=False)["PlayerEraTotal"]
        .mean()
        .rename(columns={"PlayerEraTotal": "PerTurnAvg"})
    )

    return _finalize(era_totals), _finalize(turn_average)


def _finalize(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot owner flag into the two value columns, map era, order rows/cols."""
    pivot = df.pivot_table(
        index=["Era", "BeliefType", "Belief", "Yield"],
        columns="IsReligionOwner",
        values="PerTurnAvg",
        fill_value=0.0,
    ).reset_index()
    pivot.columns.name = None
    pivot = pivot.rename(columns={1: "YieldTotalForOwner", 0: "YieldTotalForFollower"})
    for col in ("YieldTotalForOwner", "YieldTotalForFollower"):
        if col not in pivot.columns:
            pivot[col] = 0.0

    pivot["Era"] = pivot["Era"].map(db_era_to_name)
    pivot = pivot.dropna(subset=["Era"])
    pivot = pivot[OUTPUT_COLUMNS]
    return pivot.sort_values(
        ["BeliefType", "Belief", "Yield", "Era"]
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ensure_religion_summaries(cfg: Config, *, force: bool = False) -> None:
    """Generate the two religion summary CSVs if the cache is stale (or ``force``)."""
    cfg.intermediate_data_dir.mkdir(parents=True, exist_ok=True)

    if not force and _cache_is_fresh(cfg):
        print(f"[religion] cache fresh, reusing {cfg.intermediate_data_dir}")
        return

    print(f"[religion] building summaries from {cfg.db_path} ({cfg.db_type})")
    era_totals, turn_average = _build_summaries(cfg)
    era_totals.to_csv(cfg.religion_era_totals_path, index=False)
    turn_average.to_csv(cfg.religion_turn_average_path, index=False)
    cfg.religion_source_mtime_path.write_text(_source_mtime(cfg), encoding="utf-8")
    print(
        f"[religion] wrote {len(era_totals)} era-total rows and "
        f"{len(turn_average)} turn-average rows"
    )

"""Aggregate the stats DB into the two religion belief-yield summary CSVs.

Both summaries share the columns::

    Era, BeliefType, Belief, Yield, YieldTotalForOwner, YieldTotalForFollower

The raw ``ReligionBeliefYields`` table holds one row per
(GameId, Turn, Era, Civ, Belief, BeliefType, IsReligionOwner, Source, Yield). The
aggregation runs in three stages:

1. Pool ``Source`` -> one player-turn's total of a yield from a belief
   (e.g. CityYield + AnySpecialist Science for the same player-turn).
2. Average across the (GameId, Civ) players present in each turn -> the per-turn
   value one benefitting player can expect.
3. Collapse the turns of an era:

   * ``religion_yields_turn_average_summary.csv`` takes the **mean** of the per-turn
     values — what a single benefitting player can expect in the average turn of the era.
   * ``religion_yields_era_totals_summary.csv`` takes the **sum** — what they can expect
     across all the turns of the era.

The ``...ForOwner`` / ``...ForFollower`` columns split on ``IsReligionOwner`` (1/0).
This mirrors the building pipeline's "present instances only" convention (only the
turns/players that actually appear form the denominators).

The DB is only re-read when its mtime changes (tracked in a sidecar file), so repeat
runs are cheap.
"""

from __future__ import annotations

import os

import pandas as pd

from ..config import RELIGION_TABLE, Config
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

    # Stage 2: average across the (GameId, Civ) players present in each turn.
    s2_keys = ["Era", "Turn", "Belief", "BeliefType", "IsReligionOwner", "Yield"]
    stage2 = stage1.groupby(s2_keys, as_index=False).agg(
        Total=("YieldValue", "sum"), Players=("YieldValue", "size")
    )
    stage2["PerTurnAvg"] = stage2["Total"] / stage2["Players"]

    # Stage 3: collapse the turns of each era (mean -> per-turn, sum -> era total).
    s3_keys = ["Era", "BeliefType", "Belief", "Yield", "IsReligionOwner"]
    turn_average = stage2.groupby(s3_keys, as_index=False)["PerTurnAvg"].mean()
    era_totals = stage2.groupby(s3_keys, as_index=False)["PerTurnAvg"].sum()

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

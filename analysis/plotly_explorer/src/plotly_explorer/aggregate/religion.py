"""Aggregate the stats DB into the religion belief-yield summary CSVs.

The belief yields are summarized twice over two alternative slicings of a game:

* by **era** — ``Era, BeliefType, Belief, Yield, YieldTotalForOwner, ...``
* by **10-turn bucket** — the same, with ``Bucket`` (the bucket's lower turn edge,
  0/10/.../290) in place of ``Era``. Turns outside ``[0, 300)`` are dropped.

Eras are per-player and variable length, so the bucket slicing is what lets a
belief be read against the game clock instead.

The raw ``ReligionBeliefYields`` table holds one row per
(GameId, Turn, Era, Civ, Belief, BeliefType, IsReligionOwner, Source, Yield). Those
rows are logged via the game's instant-yield system, so a belief only shows up on
the turns a trigger actually fires — event sources (border growth, faith purchase,
spread, conversion, …) appear on a small fraction of a player's turns. Each slicing
runs the same three stages:

1. Pool ``Source`` -> one player-turn's total of a yield from a belief
   (e.g. CityYield + AnySpecialist Science for the same player-turn).
2. Sum each ``(GameId, Civ)`` player's per-turn totals into their slice total, then
   divide by the number of turns that player actually spent in the slice. The turn
   count comes from ``civ_turn_era`` — **not** the count of turns that happened to
   fire a yield — so sparse instant yields are amortized across every turn of the
   slice instead of being averaged over only the (far fewer) turns they appeared on,
   which previously inflated them.
3. Average across the ``(GameId, Civ)`` player-instances that held the belief in
   the slice:

   * ``..._turn_average_summary.csv`` / ``..._turn_bucket_average_summary.csv`` take
     the mean of the per-turn values — what a single benefitting player can expect in
     the average turn of the era/bucket.
   * ``..._era_totals_summary.csv`` / ``..._turn_bucket_totals_summary.csv`` take the
     mean of the slice totals — what they can expect across all its turns.

The ``...ForOwner`` / ``...ForFollower`` columns split on ``IsReligionOwner`` (1/0).
This mirrors the building pipeline's "present instances only" convention (only the
players that actually appear form the denominators).

All three stages run in the DB (``ReligionBeliefYields`` is millions of rows) and
only the per-(slice, belief, yield, owner) result comes back; see
:mod:`plotly_explorer.db`. The DB is only re-read when its mtime changes (tracked
in a sidecar file), so repeat runs are cheap.
"""

from __future__ import annotations

import pandas as pd

from ..config import CIV_TURN_ERA_TABLE, RELIGION_TABLE, Config
from ..db import read_query
from ..metadata import (
    TURN_BUCKET_END,
    TURN_BUCKET_START,
    TURN_BUCKET_WIDTH,
    db_era_to_name,
)
from .cache import ensure_group

# Columns of the emitted CSVs, in order, after the leading slice column
# (``Era`` or ``Bucket``). ``NOwner`` / ``NFollower`` are the number of
# (GameId, Civ) player-instances averaged for the owner and follower columns
# respectively — the sample size behind each, surfaced as the tooltip's "n=…" line.
VALUE_COLUMNS = [
    "BeliefType",
    "Belief",
    "Yield",
    "YieldTotalForOwner",
    "YieldTotalForFollower",
    "NOwner",
    "NFollower",
]

ERA_COLUMN = "Era"
BUCKET_COLUMN = "Bucket"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

# Lower edge of a turn's bucket, and the window filter that drops turns outside
# ``[START, END)``. ``Turn - Turn % WIDTH`` stays integral in both SQLite and
# DuckDB (unlike ``Turn / WIDTH``, which DuckDB evaluates as float division).
_BUCKET_EXPR = f'({{t}}."Turn" - {{t}}."Turn" % {TURN_BUCKET_WIDTH})'
_BUCKET_FILTER = f'WHERE {{t}}."Turn" >= {TURN_BUCKET_START} AND {{t}}."Turn" < {TURN_BUCKET_END}'

# IsReligionOwner is a BOOLEAN in the schema but reaches us as 1.0/0.0, 1/0 or
# "true"/"false" depending on the exporter and DB engine; comparing its text form
# normalizes all of them to a plain 0/1 group key.
_OWNER_EXPR = (
    'CASE WHEN LOWER(CAST(r."IsReligionOwner" AS VARCHAR)) '
    "IN ('1', '1.0', 'true', 't') THEN 1 ELSE 0 END"
)


def _summary_sql(slice_col: str) -> str:
    """SQL for one slicing (era or turn bucket) -> one row per output group.

    Mirrors the three stages of the module docstring:

    * ``player_slice`` — stages 1 and 2 collapsed into a single ``GROUP BY``:
      pooling ``Source`` into a player-turn total and then summing those turn
      totals into a slice total is just one sum over the slice, since the
      stage-1 keys are the stage-2 keys plus ``Turn``.
    * ``slice_turns``  — the turns each ``(GameId, Civ)`` actually spent in the
      slice, from ``civ_turn_era``. Belief yields are logged only on the turns a
      trigger fires, so instant-yield sources (border growth, faith purchase,
      spread, …) appear on a small fraction of a player's turns; dividing by this
      true denominator amortizes them across every turn of the slice instead of
      only the turns that fired. The join is an inner one, which drops the rare
      player-instance with no ``civ_turn_era`` coverage (nothing to amortize
      over). For buckets it also accounts for players whose game covered only
      part of one.
    * the final ``SELECT`` — stage 3, averaging across the (GameId, Civ)
      player-instances that held the belief in the slice ("present instances
      only" denominator). ``SliceTotalAvg`` feeds the totals CSV,
      ``PerTurnAvg`` the per-turn-average CSV, and ``N`` (identical for both) is
      the sample size behind them.
    """
    if slice_col == BUCKET_COLUMN:
        raw_slice = _BUCKET_EXPR.format(t="r")
        era_slice = _BUCKET_EXPR.format(t="e")
        raw_filter = _BUCKET_FILTER.format(t="r")
        era_filter = _BUCKET_FILTER.format(t="e")
    else:
        raw_slice, era_slice = 'r."Era"', 'e."era"'
        raw_filter = era_filter = ""

    return f"""
WITH slice_turns AS (
    SELECT e."GameId" AS GameId,
           e."civ"    AS Civ,
           {era_slice} AS Slice,
           COUNT(DISTINCT e."Turn") AS SliceTurns
    FROM "{CIV_TURN_ERA_TABLE}" e
    {era_filter}
    GROUP BY e."GameId", e."civ", {era_slice}
),
normalized AS (
    SELECT r."GameId" AS GameId,
           r."Civ"    AS Civ,
           {raw_slice} AS Slice,
           r."Belief"     AS Belief,
           r."BeliefType" AS BeliefType,
           {_OWNER_EXPR} AS IsReligionOwner,
           r."Yield" AS Yield,
           COALESCE(r."YieldTimes100", 0) / 100.0 AS YieldValue
    FROM "{RELIGION_TABLE}" r
    {raw_filter}
),
player_slice AS (
    SELECT GameId, Civ, Slice, Belief, BeliefType, IsReligionOwner, Yield,
           SUM(YieldValue) AS PlayerSliceTotal
    FROM normalized
    GROUP BY GameId, Civ, Slice, Belief, BeliefType, IsReligionOwner, Yield
),
per_player AS (
    SELECT p.Slice, p.BeliefType, p.Belief, p.Yield, p.IsReligionOwner,
           p.PlayerSliceTotal,
           p.PlayerSliceTotal / t.SliceTurns AS PlayerPerTurn
    FROM player_slice p
    JOIN slice_turns t
      ON t.GameId = p.GameId AND t.Civ = p.Civ AND t.Slice = p.Slice
    WHERE t.SliceTurns > 0
)
SELECT Slice AS "{slice_col}", BeliefType, Belief, Yield, IsReligionOwner,
       AVG(PlayerSliceTotal) AS SliceTotalAvg,
       AVG(PlayerPerTurn)    AS PerTurnAvg,
       CAST(COUNT(*) AS BIGINT) AS N
FROM per_player
GROUP BY Slice, BeliefType, Belief, Yield, IsReligionOwner
"""


def _summarize(cfg: Config, slice_col: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate one slicing in the DB -> (totals, per-turn avg)."""
    agg = read_query(cfg, _summary_sql(slice_col))
    keys = [slice_col, "BeliefType", "Belief", "Yield", "IsReligionOwner", "N"]
    totals = agg[keys].assign(PerTurnAvg=agg["SliceTotalAvg"])
    turn_average = agg[keys].assign(PerTurnAvg=agg["PerTurnAvg"])
    return _finalize(totals, slice_col), _finalize(turn_average, slice_col)


def _build_summaries(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(era totals, era per-turn avg, bucket totals, bucket per-turn avg)."""
    era_totals, era_turn_average = _summarize(cfg, ERA_COLUMN)
    bucket_totals, bucket_turn_average = _summarize(cfg, BUCKET_COLUMN)
    return era_totals, era_turn_average, bucket_totals, bucket_turn_average


def _finalize(df: pd.DataFrame, slice_col: str) -> pd.DataFrame:
    """Pivot owner flag into the value + sample-count columns, map era, order."""
    index = [slice_col, "BeliefType", "Belief", "Yield"]
    values = df.pivot_table(
        index=index, columns="IsReligionOwner", values="PerTurnAvg", fill_value=0.0
    ).rename(columns={1: "YieldTotalForOwner", 0: "YieldTotalForFollower"})
    counts = df.pivot_table(
        index=index, columns="IsReligionOwner", values="N", fill_value=0
    ).rename(columns={1: "NOwner", 0: "NFollower"})

    pivot = values.join(counts).reset_index()
    pivot.columns.name = None
    for col, default in (
        ("YieldTotalForOwner", 0.0),
        ("YieldTotalForFollower", 0.0),
        ("NOwner", 0),
        ("NFollower", 0),
    ):
        if col not in pivot.columns:
            pivot[col] = default
    pivot["NOwner"] = pivot["NOwner"].astype(int)
    pivot["NFollower"] = pivot["NFollower"].astype(int)

    if slice_col == ERA_COLUMN:
        # Buckets are already display-ready (their integer lower edge; the "50-59"
        # label is applied when the payload is built).
        pivot[ERA_COLUMN] = pivot[ERA_COLUMN].map(db_era_to_name)
        pivot = pivot.dropna(subset=[ERA_COLUMN])

    pivot = pivot[[slice_col, *VALUE_COLUMNS]]
    return pivot.sort_values(
        ["BeliefType", "Belief", "Yield", slice_col]
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ensure_religion_summaries(cfg: Config, *, force: bool = False) -> None:
    """Generate the four religion summary CSVs if any is stale (or ``force``)."""
    ensure_group(
        cfg,
        [
            cfg.religion_era_totals_path,
            cfg.religion_turn_average_path,
            cfg.religion_bucket_totals_path,
            cfg.religion_bucket_average_path,
        ],
        lambda: _build_summaries(cfg),
        force=force,
        # Retuning the bucket window leaves the CSVs newer than the DB but wrong,
        # which the mtime check alone can't see.
        fingerprint=f"buckets={TURN_BUCKET_START}-{TURN_BUCKET_END}/{TURN_BUCKET_WIDTH}",
    )

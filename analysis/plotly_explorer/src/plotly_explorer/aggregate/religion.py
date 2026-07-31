"""Aggregate the stats DB into the religion belief-yield summary CSVs.

The belief yields are summarized twice over two alternative slicings of a game:

* by **era** — ``Era, BeliefType, Belief, Yield, YieldTotalForOwner, ...``
* by **10-turn bucket** — the same, with ``Bucket`` (the bucket's lower turn edge,
  50/60/.../140) in place of ``Era``. Turns outside ``[50, 150)`` are dropped.

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

The DB is only re-read when its mtime changes (tracked in a sidecar file), so repeat
runs are cheap.
"""

from __future__ import annotations

import pandas as pd

from ..config import CIV_TURN_ERA_TABLE, RELIGION_TABLE, Config
from ..db import read_table
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

def _normalize_owner(series: pd.Series) -> pd.Series:
    """Coerce the IsReligionOwner BOOLEAN column to a plain 0/1 int."""
    if series.dtype == object:
        series = series.astype(str).str.strip().str.lower().map(
            {"1": 1, "true": 1, "0": 0, "false": 0}
        )
    return pd.to_numeric(series, errors="coerce").fillna(0).astype(int)


def _turn_bucket(turns: pd.Series) -> pd.Series:
    """Lower edge of each turn's bucket; NaN outside ``[START, END)``."""
    turns = pd.to_numeric(turns, errors="coerce")
    inside = (turns >= TURN_BUCKET_START) & (turns < TURN_BUCKET_END)
    return ((turns // TURN_BUCKET_WIDTH) * TURN_BUCKET_WIDTH).where(inside)


def _slice_turn_counts(cfg: Config, slice_col: str) -> pd.DataFrame:
    """Turns each ``(GameId, Civ)`` actually spent in each era / turn bucket.

    Belief yields are logged only on the turns a trigger fires, so instant-yield
    sources (border growth, faith purchase, spread, …) appear on a small fraction
    of a player's turns. To average them fairly we need the true denominator — how
    many turns the player spent in the slice — which ``civ_turn_era`` provides. For
    buckets that also accounts for players whose game covered only part of one.
    """
    cte = read_table(cfg, CIV_TURN_ERA_TABLE).rename(columns={"civ": "Civ", "era": "Era"})
    if slice_col == BUCKET_COLUMN:
        cte = cte.assign(Bucket=_turn_bucket(cte["Turn"])).dropna(subset=[BUCKET_COLUMN])
        cte[BUCKET_COLUMN] = cte[BUCKET_COLUMN].astype(int)
    return cte.groupby(["GameId", "Civ", slice_col], as_index=False).agg(
        SliceTurns=("Turn", "nunique")
    )


def _summarize(
    raw: pd.DataFrame, slice_col: str, turn_counts: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the three aggregation stages over one slicing -> (totals, per-turn avg)."""
    # Stage 1: pool Source -> one player-turn's total of a yield from a belief.
    s1_keys = [
        "GameId",
        "Turn",
        slice_col,
        "Civ",
        "Belief",
        "BeliefType",
        "IsReligionOwner",
        "Yield",
    ]
    stage1 = raw.groupby(s1_keys, as_index=False)["YieldValue"].sum()

    # Stage 2: sum a player's per-turn totals into their slice total, then divide by
    # the turns they actually spent in it (from civ_turn_era). This amortizes sparse
    # instant yields across every turn of the slice instead of only the turns that
    # fired, which is what previously inflated the per-turn average.
    s2_keys = [
        "GameId",
        "Civ",
        slice_col,
        "Belief",
        "BeliefType",
        "IsReligionOwner",
        "Yield",
    ]
    stage2 = stage1.groupby(s2_keys, as_index=False)["YieldValue"].sum().rename(
        columns={"YieldValue": "PlayerSliceTotal"}
    )

    stage2 = stage2.merge(turn_counts, on=["GameId", "Civ", slice_col], how="left")
    # Drop the rare player-instance with no civ_turn_era coverage (can't amortize).
    stage2 = stage2[stage2["SliceTurns"].fillna(0) > 0].copy()
    stage2["PlayerPerTurn"] = stage2["PlayerSliceTotal"] / stage2["SliceTurns"]

    # Stage 3: average across the (GameId, Civ) player-instances that held the
    # belief in the slice ("present instances only" denominator).
    #   * turn_average -> mean per-turn value one benefitting player can expect.
    #   * totals       -> mean value across all the turns of the slice.
    s3_keys = [slice_col, "BeliefType", "Belief", "Yield", "IsReligionOwner"]
    turn_average = stage2.groupby(s3_keys, as_index=False).agg(
        PerTurnAvg=("PlayerPerTurn", "mean"),
        N=("PlayerPerTurn", "size"),
    )
    totals = stage2.groupby(s3_keys, as_index=False).agg(
        PerTurnAvg=("PlayerSliceTotal", "mean"),
        N=("PlayerSliceTotal", "size"),
    )

    return _finalize(totals, slice_col), _finalize(turn_average, slice_col)


def _build_summaries(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(era totals, era per-turn avg, bucket totals, bucket per-turn avg)."""
    raw = read_table(cfg, RELIGION_TABLE)

    raw = raw.assign(
        IsReligionOwner=_normalize_owner(raw["IsReligionOwner"]),
        YieldValue=pd.to_numeric(raw["YieldTimes100"], errors="coerce").fillna(0.0)
        / 100.0,
    )

    era_totals, era_turn_average = _summarize(
        raw, ERA_COLUMN, _slice_turn_counts(cfg, ERA_COLUMN)
    )

    bucketed = raw.assign(Bucket=_turn_bucket(raw["Turn"])).dropna(subset=[BUCKET_COLUMN])
    bucketed[BUCKET_COLUMN] = bucketed[BUCKET_COLUMN].astype(int)
    bucket_totals, bucket_turn_average = _summarize(
        bucketed, BUCKET_COLUMN, _slice_turn_counts(cfg, BUCKET_COLUMN)
    )

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
    )

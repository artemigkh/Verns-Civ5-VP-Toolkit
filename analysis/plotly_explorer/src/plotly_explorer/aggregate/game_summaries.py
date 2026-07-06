"""Game-level summary CSVs, analogous to the Scala Spark aggregator's outputs.

Reproduces five intermediate CSVs from the stats DB:

* ``game_result``     — one row per game: winner and one-hot victory flags.
* ``power_ranking``   — per-civ performance across all games (win rates, victory
  mix, end-of-game map ownership, average score).
* ``religion_choices``— every belief a civ adopted, with a normalized ``type``.
* ``religion_stats``  — per-(type, belief) adoption stats and how often the
  adopting civ won.
* ``policy_choices``  — every social-policy pick with its per-civ pick order.

Caching is per-CSV (see :mod:`.cache`). ``game_result`` and ``religion_choices``
double as shared intermediates: ``religion_stats`` consumes both as DataFrames
returned by ``ensure_csv`` rather than recomputing them. A per-run memoized
reader keeps each raw DB table (notably ``GameResult``, read by two builders)
from being loaded more than once.

Unlike the Scala outputs, ``game_id`` here is the integer ``GameId`` from the DB
(the Scala pipeline used per-game timestamp folder names, which the DB does not
store); it is only ever used as a grouping key.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from ..config import Config
from ..db import read_query, read_table
from .cache import ensure_csv

# Games that ended before this turn are manually-triggered test completions
# (a victory forced during development), not real autoplay results. They are
# dropped from every game-stats summary so they never reach the reports.
MIN_GAME_TURN = 100

# (output-column stem, VictoryType label in the DB) in emitted-column order.
VICTORY_TYPES = [
    ("culture", "Cultural"),
    ("diplomatic", "Diplomatic"),
    ("domination", "Domination"),
    ("science", "Science"),
    ("time", "Time"),
]

# ReligionChoices.Action -> normalized religion_choices.type.
# RELIGION_CONQUERED has no belief and is intentionally excluded.
ACTION_TO_TYPE = {
    "PANTHEON_FOUNDED": "pantheon",
    "RELIGION_FOUNDED": "religion_founded",
    "RELIGION_ENHANCED": "religion_enhanced",
    "RELIGION_REFORMED": "religion_reformed",
}


def _make_reader(cfg: Config) -> Callable[[str], pd.DataFrame]:
    """Return a memoized whole-table reader (each table loaded at most once)."""
    cache: dict[str, pd.DataFrame] = {}

    def read(table: str) -> pd.DataFrame:
        if table not in cache:
            cache[table] = read_table(cfg, table)
        return cache[table]

    return read


def _clean_str(series: pd.Series) -> pd.Series:
    """Trimmed string view of a column, with NaN treated as empty."""
    return series.fillna("").astype(str).str.strip()


def _valid_game_ids(gr: pd.DataFrame) -> set:
    """GameIds for real games, i.e. those ending on/after :data:`MIN_GAME_TURN`.

    ``GameResult`` records the game-end turn identically on every civ row, so the
    per-game max is that end turn. Games ending earlier are dev test completions.
    """
    end_turns = gr.groupby("GameId")["Turn"].max()
    return set(end_turns[end_turns >= MIN_GAME_TURN].index)


# ---------------------------------------------------------------------------
# 1. game_result
# ---------------------------------------------------------------------------

def build_game_result(read: Callable[[str], pd.DataFrame]) -> pd.DataFrame:
    gr = read("GameResult")  # GameId, Turn, Civ, Score, VictoryType

    # One row per game: the game-end turn (identical across civ rows) and the
    # number of civs that played it (used downstream to weight the completed-game
    # win-rate baseline).
    games = gr.groupby("GameId", as_index=False).agg(
        turn=("Turn", "max"),
        num_civs=("Civ", "nunique"),
    )
    # Drop dev test completions that ended before turn 100.
    games = games[games["GameId"].isin(_valid_game_ids(gr))]

    victory = _clean_str(gr["VictoryType"])
    winners = (
        gr[victory != ""][["GameId", "VictoryType", "Civ"]]
        .drop_duplicates("GameId")
        .rename(columns={"VictoryType": "victory_type", "Civ": "victory_civ"})
    )

    out = games.merge(winners, on="GameId", how="left").rename(
        columns={"GameId": "game_id"}
    )

    vt = out["victory_type"]
    for stem, label in VICTORY_TYPES:
        out[f"{stem}_victory"] = (vt == label).astype(int)

    columns = ["game_id", "turn", "num_civs", "victory_type", "victory_civ"] + [
        f"{stem}_victory" for stem, _ in VICTORY_TYPES
    ]
    return out[columns].sort_values("game_id").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 2. religion_choices
# ---------------------------------------------------------------------------

def build_religion_choices(read: Callable[[str], pd.DataFrame]) -> pd.DataFrame:
    rc = read("ReligionChoices").copy()  # GameId, Turn, Civ, Action, Belief, BeliefType

    rc["type"] = rc["Action"].map(ACTION_TO_TYPE)
    rc = rc[rc["type"].notna() & (_clean_str(rc["Belief"]) != "")]

    out = rc.rename(
        columns={"GameId": "game_id", "Civ": "civ", "Turn": "turn", "Belief": "belief"}
    )
    out = out[["game_id", "civ", "type", "turn", "belief"]]
    return out.sort_values(["game_id", "turn", "civ"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 3. power_ranking
# ---------------------------------------------------------------------------

_OWNERSHIP_SQL = """
WITH end_turns AS (
    SELECT GameId, MAX(Turn) AS end_turn FROM GameResult GROUP BY GameId
),
owned AS (
    SELECT m.GameId AS game_id, m.owner AS civ,
           COUNT(*) AS tiles,
           SUM(CASE WHEN m.cityName <> '' THEN 1 ELSE 0 END) AS cities
    FROM MapPlotsState m
    JOIN end_turns e ON m.GameId = e.GameId AND m.Turn = e.end_turn
    WHERE m.owner <> ''
    GROUP BY m.GameId, m.owner
),
totals AS (
    SELECT game_id, SUM(tiles) AS t, SUM(cities) AS c FROM owned GROUP BY game_id
)
SELECT o.game_id, o.civ,
       o.tiles * 1.0 / t.t             AS tiles_owned_percentage,
       o.cities * 1.0 / NULLIF(t.c, 0) AS cities_owned_percentage
FROM owned o JOIN totals t ON o.game_id = t.game_id
"""


def _ownership_percentages(cfg: Config) -> pd.DataFrame:
    """End-of-game tile/city ownership share per (game, civ).

    Pushed down to SQL because ``MapPlotsState`` is far too large to read whole.
    Only plots at each game's end turn are scanned; ``cityName`` is non-empty
    exactly on a city's center plot, so its count is the city count. Games whose
    map snapshot turn differs from the game-end turn produce no rows here and
    therefore contribute NaN (and drop out of the averages), matching the Scala
    strict-turn LEFT JOIN. There is no vassalage table, so owner == effective
    owner.
    """
    return read_query(cfg, _OWNERSHIP_SQL)


def build_power_ranking(cfg: Config, read: Callable[[str], pd.DataFrame]) -> pd.DataFrame:
    gr = read("GameResult")  # one row per (game, civ)
    df = gr.rename(columns={"GameId": "game_id", "Civ": "civ", "Score": "score"}).copy()

    # Drop dev test completions (games ending before turn 100), matching
    # build_game_result, so per-civ counts and win rates reflect only real games.
    df = df[df["game_id"].isin(_valid_game_ids(gr))]

    victory = _clean_str(df["VictoryType"])
    df["victory_type"] = victory.where(victory != "", other=np.nan)
    won = df["victory_type"].notna()
    df["won"] = won.astype(int)

    # Victory flags are NaN for non-winning (game, civ) rows so that pct_* is a
    # mean over a civ's *wins* (victories / wins), not over all its games.
    for stem, label in VICTORY_TYPES:
        flag = (df["victory_type"] == label).astype(float)
        flag[~won] = np.nan
        df[f"{stem}_victory"] = flag

    own = _ownership_percentages(cfg)
    df = df.merge(own, on=["game_id", "civ"], how="left")

    grp = df.groupby("civ")
    out = pd.DataFrame({"count_games": grp.size(), "winrate": grp["won"].mean()})
    for stem, _ in VICTORY_TYPES:
        # sum -> count of that-type wins; mean -> that share of the civ's wins.
        out[f"{stem}_victories"] = grp[f"{stem}_victory"].sum().astype(int)
    for stem, _ in VICTORY_TYPES:
        out[f"pct_{stem}_victories"] = grp[f"{stem}_victory"].mean()
    out["avg_tiles_owned_percentage"] = grp["tiles_owned_percentage"].mean()
    out["avg_cities_owned_percentage"] = grp["cities_owned_percentage"].mean()
    out["avg_score"] = grp["score"].mean()

    out = out.reset_index()  # civ column first
    columns = (
        ["civ", "count_games", "winrate"]
        + [f"{stem}_victories" for stem, _ in VICTORY_TYPES]
        + [f"pct_{stem}_victories" for stem, _ in VICTORY_TYPES]
        + ["avg_tiles_owned_percentage", "avg_cities_owned_percentage", "avg_score"]
    )
    return out[columns].sort_values("civ").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 4. religion_stats
# ---------------------------------------------------------------------------

def build_religion_stats(
    religion_choices_df: pd.DataFrame, game_result_df: pd.DataFrame
) -> pd.DataFrame:
    winners = (
        game_result_df[["game_id", "victory_civ"]]
        .dropna(subset=["victory_civ"])
        .drop_duplicates()
        .assign(won=1)
    )

    merged = religion_choices_df.merge(
        winners,
        left_on=["game_id", "civ"],
        right_on=["game_id", "victory_civ"],
        how="left",
    )
    merged["won"] = merged["won"].fillna(0).astype(int)

    out = merged.groupby(["type", "belief"], as_index=False).agg(
        avg_turn=("turn", "mean"),
        chosen_count=("turn", "size"),
        wins=("won", "sum"),
    )
    out = out[["type", "belief", "avg_turn", "chosen_count", "wins"]]
    return out.sort_values(["type", "belief"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 5. policy_choices
# ---------------------------------------------------------------------------

def build_policy_choices(read: Callable[[str], pd.DataFrame]) -> pd.DataFrame:
    pc = read("PolicyChoices").copy()  # GameId, Turn, Civ, Era, Branch, Policy

    policy = _clean_str(pc["Policy"])
    branch = _clean_str(pc["Branch"])
    # Keep the DB's human-readable branch name for branch-open rows (empty Policy).
    pc["item"] = policy.where(policy != "", other=branch)

    # Deterministic pick order; on a turn tie the branch-open row (empty Policy)
    # comes before the policy picked in the same branch that turn.
    pc["_is_policy"] = (policy != "").astype(int)
    pc = pc.sort_values(["GameId", "Civ", "Turn", "_is_policy"], kind="mergesort")
    pc["pick_order"] = pc.groupby(["GameId", "Civ"]).cumcount() + 1

    out = pc.rename(columns={"GameId": "game_id", "Turn": "turn", "Civ": "civ"})
    return out[["game_id", "turn", "civ", "item", "pick_order"]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ensure_game_summaries(cfg: Config, *, force: bool = False) -> None:
    """Generate the five game-stats CSVs, each cached independently by mtime."""
    read = _make_reader(cfg)

    game_result_df = ensure_csv(
        cfg, cfg.game_result_path, lambda: build_game_result(read), force=force
    )
    religion_choices_df = ensure_csv(
        cfg, cfg.religion_choices_path, lambda: build_religion_choices(read), force=force
    )
    ensure_csv(
        cfg, cfg.power_ranking_path, lambda: build_power_ranking(cfg, read), force=force
    )
    ensure_csv(
        cfg,
        cfg.religion_stats_path,
        lambda: build_religion_stats(religion_choices_df, game_result_df),
        force=force,
    )
    ensure_csv(
        cfg, cfg.policy_choices_path, lambda: build_policy_choices(read), force=force
    )

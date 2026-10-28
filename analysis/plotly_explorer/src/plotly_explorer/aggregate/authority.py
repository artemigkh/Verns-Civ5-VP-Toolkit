"""Synthetic "Authority Victory" variants of the game-level summaries.

The rule: the first turn any civ controls at least :data:`AUTHORITY_SHARE` of the
map's cities AND of its owned tiles, it is assigned an Authority victory and wins
on that turn. The game is re-scored as if it had ended there:

* ``authority_game_result`` -- ``game_result`` with every game the rule fires in
  (on or before its real end turn) re-assigned: ``turn`` becomes the authority
  turn, the winner the authority civ, ``victory_type`` ``"Authority"``. Games that
  ended earlier keep their real result; undecided games (turn cap) can be decided
  by it. A game whose real victory lands on the authority turn goes to Authority,
  since the rule wins "instantly" on that turn.
* ``authority_power_ranking`` -- ``power_ranking`` over those winners, with the
  ownership shares taken at the authority turn for re-assigned games. Score and
  finishing place are only logged at the real game end, so those two columns keep
  their real-game values.

Shares count every owner on the map, city-states included (as the end-of-game
ownership columns do); only major civs can win. ``MapPlotsState`` is logged every
turn and is far too large to read whole, so the per-turn shares are computed in
the DB and only each re-assigned game's shares at its authority turn come back.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Config
from ..db import read_query
from .cache import ensure_group
from .game_summaries import (
    VICTORY_TYPES,
    make_reader,
    power_ranking_rows,
    summarize_power_ranking,
)

# Minimum share of both the cities and the owned tiles on the map.
AUTHORITY_SHARE = 0.67

AUTHORITY_LABEL = "Authority"

# The real victory types plus Authority, in emitted-column order.
AUTHORITY_VICTORY_TYPES = VICTORY_TYPES + [("authority", AUTHORITY_LABEL)]

# Every owner's share of the map at each game's first authority turn. The CTEs:
#
# 1. ``per_civ`` -- tiles and cities (``cityName`` is set exactly on a city's
#    center plot) per (game, turn, owner).
# 2. ``shares``  -- each owner's share of that turn's owned tiles and cities.
# 3. ``majors``  -- the civs that played the game; city-states are owners on the
#    map but never in ``GameResult``, so they count toward the totals only.
# 4. ``firsts``  -- per game, the first turn a major civ clears both thresholds.
#
# Two civs can never both hold >= 67% of the cities, so ``authority_winner`` marks
# exactly one row per game.
_AUTHORITY_SQL = """
WITH per_civ AS (
    SELECT GameId, Turn, owner AS civ,
           COUNT(*) AS tiles,
           SUM(CASE WHEN cityName <> '' THEN 1 ELSE 0 END) AS cities
    FROM MapPlotsState
    WHERE owner <> ''
    GROUP BY GameId, Turn, owner
),
shares AS (
    SELECT GameId, Turn, civ,
           tiles * 1.0 / SUM(tiles) OVER (PARTITION BY GameId, Turn) AS tile_share,
           cities * 1.0 / NULLIF(SUM(cities) OVER (PARTITION BY GameId, Turn), 0) AS city_share
    FROM per_civ
),
majors AS (
    SELECT DISTINCT GameId, Civ FROM GameResult
),
firsts AS (
    SELECT s.GameId, MIN(s.Turn) AS turn
    FROM shares s
    JOIN majors m ON m.GameId = s.GameId AND m.Civ = s.civ
    WHERE s.tile_share >= {share} AND s.city_share >= {share}
    GROUP BY s.GameId
)
SELECT s.GameId AS game_id, f.turn AS authority_turn, s.civ,
       s.tile_share AS tiles_owned_percentage,
       s.city_share AS cities_owned_percentage,
       CASE WHEN m.Civ IS NOT NULL
                 AND s.tile_share >= {share} AND s.city_share >= {share}
            THEN 1 ELSE 0 END AS authority_winner
FROM shares s
JOIN firsts f ON f.GameId = s.GameId AND f.turn = s.Turn
LEFT JOIN majors m ON m.GameId = s.GameId AND m.Civ = s.civ
"""


def _authority_shares(cfg: Config) -> pd.DataFrame:
    return read_query(cfg, _AUTHORITY_SQL.format(share=AUTHORITY_SHARE))


def build_authority_game_result(
    game_result: pd.DataFrame, shares: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``game_result`` re-scored under the rule, and the (game_id, turn, civ) it awarded.

    Only authority turns on or before a game's real end turn count: past that the
    game was already over.
    """
    winners = shares.loc[
        shares["authority_winner"] == 1, ["game_id", "authority_turn", "civ"]
    ].merge(game_result[["game_id", "turn"]], on="game_id")
    awarded = winners[winners["authority_turn"] <= winners["turn"]][
        ["game_id", "authority_turn", "civ"]
    ]

    out = game_result.merge(awarded, on="game_id", how="left")
    hit = out["authority_turn"].notna()
    out.loc[hit, "turn"] = out.loc[hit, "authority_turn"].astype(int)
    out.loc[hit, "victory_type"] = AUTHORITY_LABEL
    out.loc[hit, "victory_civ"] = out.loc[hit, "civ"]
    out["turn"] = out["turn"].astype(int)

    vt = out["victory_type"]
    for stem, label in AUTHORITY_VICTORY_TYPES:
        out[f"{stem}_victory"] = (vt == label).astype(int)

    columns = ["game_id", "turn", "num_civs", "victory_type", "victory_civ"] + [
        f"{stem}_victory" for stem, _ in AUTHORITY_VICTORY_TYPES
    ]
    return out[columns], awarded


def build_authority_power_ranking(
    rows: pd.DataFrame, shares: pd.DataFrame, awarded: pd.DataFrame
) -> pd.DataFrame:
    """``power_ranking`` with the awarded games' winners and ownership replaced."""
    rows = rows.copy()
    games = set(awarded["game_id"])
    in_game = rows["game_id"].isin(games)

    # Re-assign the winner of every awarded game.
    rows.loc[in_game, "victory_type"] = np.nan
    won = rows.merge(
        awarded[["game_id", "civ"]].assign(_won=1), on=["game_id", "civ"], how="left"
    )["_won"].eq(1).to_numpy()
    rows.loc[won, "victory_type"] = AUTHORITY_LABEL

    # Ownership at the authority turn. Civs off the map by then get NaN, which
    # drops them from the averages exactly as the end-of-game shares do.
    at_turn = shares[shares["game_id"].isin(games)][
        ["game_id", "civ", "tiles_owned_percentage", "cities_owned_percentage"]
    ]
    own_cols = ["tiles_owned_percentage", "cities_owned_percentage"]
    replaced = rows[["game_id", "civ"]].merge(at_turn, on=["game_id", "civ"], how="left")
    for col in own_cols:
        rows[col] = np.where(in_game, replaced[col].to_numpy(), rows[col].to_numpy())

    return summarize_power_ranking(rows, AUTHORITY_VICTORY_TYPES)


def _build(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    shares = _authority_shares(cfg)
    game_result = pd.read_csv(cfg.game_result_path)
    synthetic_result, awarded = build_authority_game_result(game_result, shares)
    print(f"[aggregate] authority rule awards {len(awarded)} of {len(game_result)} games")
    ranking = build_authority_power_ranking(
        power_ranking_rows(cfg, make_reader(cfg)), shares, awarded
    )
    return synthetic_result, ranking


def ensure_authority_summaries(cfg: Config, *, force: bool = False) -> None:
    """Generate the synthetic Authority Victory CSVs (needs ``game_result.csv``)."""
    ensure_group(
        cfg,
        [cfg.authority_game_result_path, cfg.authority_power_ranking_path],
        lambda: _build(cfg),
        force=force,
        fingerprint=f"share={AUTHORITY_SHARE}",
    )

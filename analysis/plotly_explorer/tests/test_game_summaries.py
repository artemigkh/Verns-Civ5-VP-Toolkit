"""aggregate/game_summaries.py: the pure DataFrame builders, then the SQL end to end on SQLite."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from plotly_explorer.aggregate.game_summaries import (
    MIN_GAME_TURN,
    build_game_result,
    build_policy_choices,
    build_religion_choices,
    build_religion_stats,
    ensure_game_summaries,
    make_reader,
    summarize_power_ranking,
)
from plotly_explorer.db import list_tables, read_query, read_table


def reader_of(**tables: pd.DataFrame):
    return lambda name: tables[name]


def game_result_table() -> pd.DataFrame:
    return pd.DataFrame(
        [
            (1, 150, "Rome", 500, "Cultural"),
            (1, 150, "Egypt", 300, ""),
            (1, 150, "Siam", 0, None),
            (2, MIN_GAME_TURN - 1, "Rome", 100, "Domination"),  # dev test completion
            (3, 200, "Rome", 100, None),
            (3, 200, "Egypt", 400, None),
        ],
        columns=["GameId", "Turn", "Civ", "Score", "VictoryType"],
    )


def test_build_game_result_drops_dev_games_and_flags_the_winner():
    out = build_game_result(reader_of(GameResult=game_result_table()))
    assert out["game_id"].tolist() == [1, 3]
    by_game = out.set_index("game_id")
    g1 = by_game.loc[1]
    assert g1["turn"] == 150 and g1["num_civs"] == 3
    assert g1["victory_type"] == "Cultural" and g1["victory_civ"] == "Rome"
    assert g1["culture_victory"] == 1 and g1["domination_victory"] == 0
    g3 = by_game.loc[3]
    assert pd.isna(g3["victory_type"])
    assert g3[["culture_victory", "science_victory"]].sum() == 0
    assert list(out.columns)[:5] == ["game_id", "turn", "num_civs", "victory_type", "victory_civ"]


def test_build_religion_choices_normalizes_types_and_drops_conquests():
    rc = pd.DataFrame(
        [
            (1, 20, "Rome", "PANTHEON_FOUNDED", "Goddess of Beauty", "pantheon"),
            (1, 60, "Rome", "RELIGION_ENHANCED", "Scripture", " follower "),
            (1, 90, "Egypt", "RELIGION_CONQUERED", "", ""),
            (1, 95, "Egypt", "RELIGION_FOUNDED", "   ", "FOUNDER"),  # blank belief
        ],
        columns=["GameId", "Turn", "Civ", "Action", "Belief", "BeliefType"],
    )
    out = build_religion_choices(reader_of(ReligionChoices=rc))
    assert out["type"].tolist() == ["pantheon", "religion_enhanced"]
    assert out["belief_type"].tolist() == ["PANTHEON", "FOLLOWER"]
    assert list(out.columns) == ["game_id", "civ", "type", "turn", "belief", "belief_type"]


def test_build_policy_choices_orders_branch_open_before_same_turn_policy():
    pc = pd.DataFrame(
        [
            (1, 10, "Rome", 0, "Tradition", "Justice"),
            (1, 10, "Rome", 0, "Tradition", ""),
            (1, 30, "Rome", 0, "Tradition", "Sovereignty"),
            (1, 12, "Egypt", 0, "Progress", ""),
        ],
        columns=["GameId", "Turn", "Civ", "Era", "Branch", "Policy"],
    )
    out = build_policy_choices(reader_of(PolicyChoices=pc))
    rome = out[out["civ"] == "Rome"]
    assert rome["item"].tolist() == ["Tradition", "Justice", "Sovereignty"]
    assert rome["pick_order"].tolist() == [1, 2, 3]
    assert out[out["civ"] == "Egypt"]["pick_order"].tolist() == [1]


def test_build_religion_stats_counts_adoptions_and_adopter_wins():
    choices = pd.DataFrame(
        {
            "game_id": [1, 1, 2, 3],
            "civ": ["Rome", "Egypt", "Rome", "Siam"],
            "type": ["pantheon"] * 4,
            "turn": [20, 25, 22, 30],
            "belief": ["Sun", "Sun", "Sun", "Beauty"],
            "belief_type": ["PANTHEON"] * 4,
        }
    )
    gr = pd.DataFrame({"game_id": [1, 2, 3], "victory_civ": ["Rome", "Egypt", np.nan]})
    out = build_religion_stats(choices, gr).set_index("belief")
    assert out.loc["Sun", "chosen_count"] == 3 and out.loc["Sun", "wins"] == 1
    assert out.loc["Sun", "avg_turn"] == pytest.approx((20 + 25 + 22) / 3)
    assert out.loc["Beauty", "wins"] == 0


def test_summarize_power_ranking_pct_is_a_share_of_wins_not_games():
    rows = pd.DataFrame(
        {
            "game_id": [1, 2, 3, 1, 2, 3],
            "civ": ["Rome"] * 3 + ["Egypt"] * 3,
            "victory_type": ["Cultural", "Science", np.nan, np.nan, np.nan, np.nan],
            "score": [500, 400, 100, 300, 200, 350],
            "tiles_owned_percentage": [0.6, 0.5, np.nan, 0.4, 0.5, 0.3],
            "cities_owned_percentage": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
            "game_end_rank": [1, 1, 2, 2, 2, 1],
        }
    )
    out = summarize_power_ranking(rows).set_index("civ")
    assert out.loc["Rome", "winrate"] == pytest.approx(2 / 3)
    assert out.loc["Rome", "culture_victories"] == 1 and out.loc["Rome", "science_victories"] == 1
    assert out.loc["Rome", "pct_culture_victories"] == pytest.approx(0.5)
    assert out.loc["Rome", "avg_tiles_owned_percentage"] == pytest.approx(0.55)  # NaN dropped
    assert out.loc["Egypt", "winrate"] == 0
    assert math.isnan(out.loc["Egypt", "pct_culture_victories"])  # no wins -> no share
    assert out["culture_victories"].dtype.kind == "i"
    assert out.index.tolist() == ["Egypt", "Rome"]


# ---------------------------------------------------------------------------
# The SQL, against the SQLite fixture DB
# ---------------------------------------------------------------------------


def test_db_helpers_on_sqlite(sqlite_db):
    assert {"GameResult", "MapPlotsState", "civ_turn_era"} <= list_tables(sqlite_db)
    assert len(read_table(sqlite_db, "GameResult")) == 8
    assert read_query(sqlite_db, "SELECT COUNT(*) AS n FROM PolicyChoices")["n"].iloc[0] == 5


def test_read_table_refuses_huge_tables(sqlite_db, monkeypatch):
    monkeypatch.setenv("DB_MAX_TABLE_ROWS", "3")
    with pytest.raises(SystemExit, match="Refusing to read"):
        read_table(sqlite_db, "GameResult")


def test_missing_db_is_an_actionable_error(cfg):
    with pytest.raises(SystemExit, match="Source database not found"):
        list_tables(cfg)


def test_ensure_game_summaries_end_to_end(sqlite_db):
    ensure_game_summaries(sqlite_db)

    gr = pd.read_csv(sqlite_db.game_result_path)
    assert gr["game_id"].tolist() == [1, 3]  # game 2 ended before MIN_GAME_TURN

    pr = pd.read_csv(sqlite_db.power_ranking_path).set_index("civ")
    assert pr.index.tolist() == ["Egypt", "Rome", "Siam"]
    assert pr["count_games"].tolist() == [2, 2, 2]
    assert pr.loc["Rome", "winrate"] == 0.5 and pr.loc["Rome", "culture_victories"] == 1
    # Ownership at each game's end turn only: game 1 Rome 6/10 tiles, 2/3 cities;
    # game 3 Rome 2/10 tiles, 1/4 cities. Siam has no plots at game 1's end.
    assert pr.loc["Rome", "avg_tiles_owned_percentage"] == pytest.approx((0.6 + 0.2) / 2)
    assert pr.loc["Rome", "avg_cities_owned_percentage"] == pytest.approx((2 / 3 + 1 / 4) / 2)
    assert pr.loc["Siam", "avg_tiles_owned_percentage"] == pytest.approx(0.3)
    # Finishing place: game 1 Rome 1, Egypt 2, Siam 3 (dead); game 3 Egypt 1, Siam 2, Rome 3.
    assert pr.loc["Rome", "avg_rank_at_game_end"] == pytest.approx(2.0)
    assert pr.loc["Egypt", "avg_rank_at_game_end"] == pytest.approx(1.5)
    assert pr.loc["Siam", "avg_rank_at_game_end"] == pytest.approx(2.5)

    rc = pd.read_csv(sqlite_db.religion_choices_path)
    assert set(rc["type"]) == {"pantheon", "religion_founded"}
    assert "RELIGION_CONQUERED" not in rc.to_string()

    rs = pd.read_csv(sqlite_db.religion_stats_path).set_index(["type", "belief"])
    assert rs.loc[("pantheon", "Goddess of Beauty"), "chosen_count"] == 2  # games 1 and 2
    assert rs.loc[("pantheon", "Goddess of Beauty"), "wins"] == 1  # Rome won game 1

    pc = pd.read_csv(sqlite_db.policy_choices_path)
    rome = pc[(pc["civ"] == "Rome") & (pc["game_id"] == 1)]
    assert rome["item"].tolist() == ["Tradition", "Justice", "Sovereignty"]

    # Second run is a cache hit: nothing is rebuilt and the files are unchanged.
    before = sqlite_db.power_ranking_path.stat().st_mtime_ns
    ensure_game_summaries(sqlite_db)
    assert sqlite_db.power_ranking_path.stat().st_mtime_ns == before


def test_make_reader_memoizes(sqlite_db):
    read = make_reader(sqlite_db)
    assert read("GameResult") is read("GameResult")

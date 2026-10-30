"""The pure DataFrame steps of the policies, religion-performance and authority aggregations."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from plotly_explorer.aggregate.authority import (
    AUTHORITY_LABEL,
    build_authority_game_result,
    build_authority_power_ranking,
)
from plotly_explorer.aggregate.policies_performance import (
    OUTPUT_COLUMNS_OPENS,
    OUTPUT_COLUMNS_WINS,
    _branch_opens,
    _build_opens,
    _build_wins,
)
from plotly_explorer.aggregate.religion_performance import (
    KDE_GRID_POINTS,
    _attainment_samples,
    _build_attainment_kde,
    _build_attainment_moments,
    _build_pick_performance,
    _section_for,
)

# ---------------------------------------------------------------------------
# Policies performance
# ---------------------------------------------------------------------------


def _choices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "game_id": [1, 1, 1, 2, 9],
            "turn": [10, 10, 12, 11, 10],
            "civ": ["Rome", "Rome", "Egypt", "Rome", "Siam"],
            "item": ["Tradition", "Justice", "Progress", "Tradition", "Authority"],
            "pick_order": [1, 2, 1, 1, 1],
        }
    )


def test_branch_opens_keeps_only_branch_rows_of_real_games():
    opens = _branch_opens(_choices(), valid_games={1, 2})
    assert opens["branch"].tolist() == ["Tradition", "Progress", "Tradition"]  # no Justice, no game 9
    assert list(opens.columns) == ["game_id", "civ", "branch"]


def test_build_opens_counts_per_civ_and_branch():
    out = _build_opens(_branch_opens(_choices(), {1, 2}))
    counts = out.set_index(["civ", "branch"])["opens"].to_dict()
    assert counts == {("Egypt", "Progress"): 1, ("Rome", "Tradition"): 2}
    empty = _build_opens(pd.DataFrame(columns=["game_id", "civ", "branch"]))
    assert list(empty.columns) == OUTPUT_COLUMNS_OPENS


def test_build_wins_counts_shown_victory_types_only():
    gr = pd.DataFrame(
        {
            "game_id": [1, 2],
            "victory_civ": ["Rome", "Rome"],
            "victory_type": ["Cultural", "Time"],  # Time is not shown in the report
        }
    )
    out = _build_wins(_branch_opens(_choices(), {1, 2}), gr)
    assert out.to_dict("records") == [{"branch": "Tradition", "victory_type": "Cultural", "wins": 1}]
    empty = _build_wins(_branch_opens(_choices(), {1, 2}), gr.assign(victory_civ=np.nan))
    assert list(empty.columns) == OUTPUT_COLUMNS_WINS and empty.empty


# ---------------------------------------------------------------------------
# Religion performance
# ---------------------------------------------------------------------------


def _religion_choices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "game_id": [1, 1, 1, 1, 2, 2],
            "civ": ["Rome", "Rome", "Rome", "Egypt", "Rome", "Rome"],
            "type": [
                "pantheon",
                "religion_founded",
                "religion_founded",
                "pantheon",
                "pantheon",
                "religion_enhanced",
            ],
            "turn": [20, 60, 60, 25, 30, 120],
            "belief": ["Beauty", "Council", "Scripture", "Sun", "Beauty", "Scripture"],
            "belief_type": ["PANTHEON", "FOUNDER", "FOLLOWER", "pantheon ", "PANTHEON", "FOLLOWER"],
        }
    )


def test_attainment_samples_count_a_founding_once():
    samples = _attainment_samples(_religion_choices())
    # The two beliefs picked at Rome's founding (turn 60) collapse to one sample.
    assert samples[samples["type"] == "religion_founded"]["turn"].tolist() == [60]
    assert len(samples) == 5


def test_section_for_prefers_the_belief_category():
    assert _section_for("religion_founded", "PANTHEON") == "pantheon"  # stray action, right section
    assert _section_for("religion_founded", "FOLLOWER") == "follower_found"
    assert _section_for("religion_enhanced", "FOLLOWER") == "follower_enhance"
    assert _section_for("pantheon", "FOLLOWER") is None
    assert _section_for("religion_founded", "UNKNOWN") is None


def test_attainment_moments_and_kde():
    samples = pd.DataFrame({"type": ["pantheon"] * 3 + ["religion_founded"], "turn": [20, 30, 40, 60]})
    moments = _build_attainment_moments(samples).set_index("event_type")
    assert moments.loc["Pantheon Founded"].to_dict() == {"mean": 30.0, "median": 30.0, "n": 3}
    assert moments.loc["Religion Founded", "n"] == 1
    kde = _build_attainment_kde(samples)
    # Only the milestone with >= 2 distinct samples gets a curve, on the shared grid.
    assert set(kde["event_type"]) == {"Pantheon Founded"}
    assert len(kde) == KDE_GRID_POINTS
    assert kde["x"].iloc[0] == 0 and kde["x"].iloc[-1] == 60
    assert kde["density"].idxmax() == kde.iloc[(kde["x"] - 30).abs().argsort().iloc[0]].name


def test_pick_performance_sections_wins_and_sort():
    gr = pd.DataFrame({"game_id": [1, 2], "victory_civ": ["Rome", np.nan]})
    out = _build_pick_performance(_religion_choices(), gr)
    assert list(out.columns) == ["section", "belief", "chosen_count", "wins", "losses", "avg_turn"]
    by = out.set_index(["section", "belief"])
    assert by.loc[("pantheon", "Beauty"), "chosen_count"] == 2
    assert by.loc[("pantheon", "Beauty"), "wins"] == 1 and by.loc[("pantheon", "Beauty"), "losses"] == 1
    assert by.loc[("pantheon", "Sun"), "wins"] == 0  # the trailing-space category still maps
    assert ("follower_found", "Scripture") in by.index and ("follower_enhance", "Scripture") in by.index
    # Within a section the most-picked belief comes first.
    pantheon = out[out["section"] == "pantheon"]["belief"].tolist()
    assert pantheon == ["Beauty", "Sun"]


# ---------------------------------------------------------------------------
# Authority victory variant
# ---------------------------------------------------------------------------


def _game_result() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "game_id": [1, 2],
            "turn": [300, 250],
            "num_civs": [2, 2],
            "victory_type": ["Cultural", "Science"],
            "victory_civ": ["Rome", "Egypt"],
        }
    )


def _shares() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "game_id": [1, 1, 2],
            "authority_turn": [200, 200, 260],  # game 2's comes after its real end
            "civ": ["Rome", "Egypt", "Egypt"],
            "tiles_owned_percentage": [0.7, 0.3, 0.9],
            "cities_owned_percentage": [0.75, 0.25, 0.9],
            "authority_winner": [1, 0, 1],
        }
    )


def test_authority_game_result_rewrites_only_games_won_before_their_end():
    out, awarded = build_authority_game_result(_game_result(), _shares())
    assert awarded.to_dict("records") == [{"game_id": 1, "authority_turn": 200, "civ": "Rome"}]
    by = out.set_index("game_id")
    assert by.loc[1, "turn"] == 200 and by.loc[1, "victory_type"] == AUTHORITY_LABEL
    assert by.loc[1, "authority_victory"] == 1 and by.loc[1, "culture_victory"] == 0
    assert by.loc[2, "turn"] == 250 and by.loc[2, "victory_type"] == "Science"
    assert by.loc[2, "science_victory"] == 1 and by.loc[2, "authority_victory"] == 0
    assert out["turn"].dtype.kind == "i"


def test_authority_power_ranking_swaps_winner_and_ownership():
    rows = pd.DataFrame(
        {
            "game_id": [1, 1, 2, 2],
            "civ": ["Rome", "Egypt", "Rome", "Egypt"],
            "victory_type": ["Cultural", np.nan, np.nan, "Science"],
            "score": [500, 300, 200, 600],
            "tiles_owned_percentage": [0.5, 0.5, 0.2, 0.8],
            "cities_owned_percentage": [0.5, 0.5, 0.2, 0.8],
            "game_end_rank": [1, 2, 2, 1],
        }
    )
    _, awarded = build_authority_game_result(_game_result(), _shares())
    out = build_authority_power_ranking(rows, _shares(), awarded).set_index("civ")
    assert out.loc["Rome", "authority_victories"] == 1 and out.loc["Rome", "culture_victories"] == 0
    assert out.loc["Rome", "winrate"] == pytest.approx(0.5)
    assert out.loc["Egypt", "science_victories"] == 1  # game 2 untouched
    # Game 1 ownership comes from the authority turn; game 2 keeps its end-game shares.
    assert out.loc["Rome", "avg_tiles_owned_percentage"] == pytest.approx((0.7 + 0.2) / 2)
    assert out.loc["Egypt", "avg_tiles_owned_percentage"] == pytest.approx((0.3 + 0.8) / 2)

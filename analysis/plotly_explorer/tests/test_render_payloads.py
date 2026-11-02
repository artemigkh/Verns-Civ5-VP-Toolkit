"""render.py payload builders: tiny CSVs in, the dict each report module reads out."""

from __future__ import annotations

import pandas as pd
import pytest

from plotly_explorer import render as R

# ---------------------------------------------------------------------------
# Civs Overview
# ---------------------------------------------------------------------------


def test_avg_winrate_is_wins_over_participations_of_decided_games(game_stats_csvs):
    gr = pd.read_csv(game_stats_csvs.game_result_path)
    assert R._avg_winrate(gr) == pytest.approx(3 / 12)  # 3 decided games x 4 civs
    assert R._avg_winrate(gr.drop(columns=["num_civs"])) == 0.0
    assert R._avg_winrate(gr.assign(victory_type="")) == 0.0


def test_civs_variant_victory_mix_and_table(game_stats_csvs):
    gr = pd.read_csv(game_stats_csvs.game_result_path)
    pr = pd.read_csv(game_stats_csvs.power_ranking_path)
    out = R._civs_variant(gr, pr)

    assert out["victory"]["present"] == ["Cultural", "Science"]  # canonical order, Time absent
    assert out["victory"]["counts"] == [2, 1]
    assert out["victory"]["turns"] == {"Cultural": [300, 280], "Science": [350]}
    assert out["victory"]["victors"] == {"Cultural": ["Rome", "Rome"], "Science": ["Egypt"]}
    assert out["avgWinrate"] == pytest.approx(0.25)

    cols = out["table"]["columns"]
    assert cols[:3] == ["civ", "rank", "count_games"]
    rows = out["table"]["rows"]
    assert [r["civ"] for r in rows] == ["Rome", "Egypt", "Siam", "Zulu"]  # winrate desc, stable
    assert [r["rank"] for r in rows] == [1, 2, 3, 4]
    assert rows[2]["pct_culture_victories"] is None  # NaN -> null for a civ with no wins
    assert rows[0]["pct_culture_victories"] == 1.0


def test_build_civs_payload(game_stats_csvs):
    out = R.build_civs_payload(game_stats_csvs, "5.4.8", "Emperor", "Communitu 3.2.0", "Standard")
    assert out["kpis"] == {
        "patch": "5.4.8",
        "difficulty": "Emperor",
        "mapscript": "Communitu 3.2.0",
        "size": "Standard",
        "games": 4,
    }
    assert out["victoryOrder"] == R.VICTORY_ORDER
    assert {"victory", "avgWinrate", "table"} <= set(out)


# ---------------------------------------------------------------------------
# Policies Performance
# ---------------------------------------------------------------------------


def test_build_policies_performance_payload(game_stats_csvs, write_csv):
    cfg = game_stats_csvs
    write_csv(
        cfg.policy_branch_opens_path,
        [
            {"civ": "Rome", "branch": "Progress", "opens": 3},
            {"civ": "Rome", "branch": "Tradition", "opens": 1},
            {"civ": "Egypt", "branch": "Progress", "opens": 1},
        ],
    )
    write_csv(
        cfg.policy_branch_wins_path,
        [
            {"branch": "Progress", "victory_type": "Cultural", "wins": 2},
            {"branch": "Progress", "victory_type": "Science", "wins": 1},
        ],
    )
    out = R.build_policies_performance_payload(cfg)
    assert out["branches"] == ["Tradition", "Progress"]  # BRANCH_ORDER, not alphabetical
    assert out["civs"] == ["Egypt", "Rome"]
    assert out["opens"] == {"Rome": {"Progress": 3, "Tradition": 1}, "Egypt": {"Progress": 1}}
    assert out["totalOpens"] == {"Tradition": 1, "Progress": 4}
    assert out["victoryOrder"] == ["Cultural", "Science", "Domination", "Diplomatic"]
    assert out["winrate"]["Progress"] == {
        "Cultural": 0.5,
        "Science": 0.25,
        "Domination": 0.0,
        "Diplomatic": 0.0,
    }
    assert out["winrate"]["Tradition"]["Cultural"] == 0.0
    assert out["avgWinrate"] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Wonders
# ---------------------------------------------------------------------------


def test_build_wonders_payload_index_encoding(game_stats_csvs, write_csv):
    cfg = game_stats_csvs
    write_csv(
        cfg.wonder_game_civs_path,
        [
            {"game_id": 1, "civ": "Rome", "branches": "Tradition|Artistry", "won": 1},
            {"game_id": 1, "civ": "Egypt", "branches": "", "won": 0},
            {"game_id": 2, "civ": "Rome", "branches": "Progress", "won": 0},
        ],
    )
    write_csv(
        cfg.wonder_builds_path,
        [
            {"game_id": 1, "civ": "Rome", "wonder": "Stonehenge", "era": "Ancient", "turn": 40},
            {"game_id": 2, "civ": "Rome", "wonder": "Colossus", "era": "Classical", "turn": 90},
            {"game_id": 7, "civ": "Siam", "wonder": "Colossus", "era": "Classical", "turn": 80},  # no pair
        ],
    )
    out = R.build_wonders_payload(cfg)
    assert out["civs"] == ["Egypt", "Rome", "Siam"]
    assert out["branches"] == ["Tradition", "Progress", "Artistry"]  # BRANCH_ORDER, not first-seen
    assert out["wonders"] == [
        {"name": "Colossus", "era": "Classical"},
        {"name": "Stonehenge", "era": "Ancient"},
    ]
    assert out["eraOrder"] == ["Ancient", "Classical"]
    assert out["pairCiv"] == [1, 0, 1]
    assert out["pairGame"] == [0, 0, 1]
    assert out["pairMask"] == [0b101, 0, 0b010]  # Tradition=bit0, Progress=bit1, Artistry=bit2
    assert out["pairWon"] == [1, 0, 0]
    assert out["buildPair"] == [0, 2]  # the Siam build has no (game, civ) pair and is dropped
    assert out["buildWonder"] == [1, 0]
    assert out["buildTurn"] == [40, 90] and out["turnRange"] == [40, 90]
    assert out["avgWinrate"] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Religion Performance + Instant Yields
# ---------------------------------------------------------------------------


def test_build_religion_performance_payload(game_stats_csvs, write_csv):
    cfg = game_stats_csvs
    write_csv(
        cfg.religion_attainment_kde_path,
        [
            {"event_type": "Religion Founded", "x": 0.0, "density": 0.0},
            {"event_type": "Religion Founded", "x": 60.0, "density": 0.01234567891},
        ],
    )
    write_csv(
        cfg.religion_attainment_moments_path,
        [{"event_type": "Religion Founded", "mean": 61.5, "median": 60.0, "n": 7}],
    )
    write_csv(
        cfg.religion_pick_performance_path,
        [
            dict(section="founder", belief="Council", chosen_count=4, wins=1, losses=3, avg_turn=60),
            dict(section="pantheon", belief="Sun", chosen_count=0, wins=0, losses=0, avg_turn=0),
        ],
    )
    out = R.build_religion_performance_payload(cfg, "5.4.8", "Emperor", "Communitu 3.2.0", "Standard")
    assert out["eventOrder"] == ["Religion Founded"]
    assert out["kde"]["Religion Founded"]["mean"] == 61.5 and out["kde"]["Religion Founded"]["n"] == 7
    assert out["kde"]["Religion Founded"]["density"][1] == 0.01234568
    assert out["picks"]["founder"][0]["winrate"] == 25
    assert out["picks"]["pantheon"][0]["winrate"] == 0  # no division by zero
    assert out["caption"].startswith("4 Autoplay Games")


def test_build_instant_yields_payload(cfg, write_csv):
    def row(era, type_, yld, y, t, n):
        return {
            "Era": era,
            "Type": type_,
            "Yield": yld,
            "AvgYieldAmount": y,
            "AvgTriggerAmount": t,
            "AvgTimesTriggered": n,
        }

    write_csv(
        cfg.instant_yields_summary_path,
        [
            row("Ancient", "Birth", "Food", 1.23456, 2, 3),
            row("Ancient", "Growth", "Food", 4, 5, 6),
            row("Classical", "Birth", "Zeal", 7, 8, 9),
        ],
    )
    out = R.build_instant_yields_payload(cfg)
    assert out["yields"] == ["Food", "Zeal"]  # preferred order first, the rest A-Z
    assert out["defaultYield"] == "Food"
    assert out["maxTriggerTypes"] == 2 and out["defaultTopN"] == 2
    assert out["data"]["Food"]["types"] == ["Birth", "Growth"]
    assert out["data"]["Food"]["cells"]["Birth"]["Ancient"] == {"y": 1.2346, "t": 2.0, "n": 3.0}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def test_order_yields_prefers_then_sorts():
    ordered = R._order_yields({"Zeal", "Gold", "Apples", "Production"})
    assert ordered == ["Production", "Gold", "Apples", "Zeal"]


def test_nested_data_and_buildings_by_yield():
    df = pd.DataFrame(
        {
            "Yield": ["Gold", "Gold", "Food"],
            "Era": ["Ancient", "Ancient", "Classical"],
            "Building": ["Market", "Granary", "Granary"],
            "BaseYields": [2.00004, 0, 1],
            "BonusYields": [0.5, 0, 0],
            "InstantYields": [0, 0, 0],
            "N": [10, 10, 4],
        }
    )
    nested = R._nested_data(df)
    assert nested["Gold"]["Ancient"]["Market"] == {"base": 2.0, "bonus": 0.5, "instant": 0.0, "n": 10}
    # Granary has no Gold at all, so it is not offered under Gold.
    assert R._buildings_by_yield(df) == {"Food": ["Granary"], "Gold": ["Market"]}


def test_relabel_buckets():
    out = R._relabel_buckets(pd.DataFrame({"Bucket": [60, 290], "v": [1, 2]}))
    assert out["Era"].tolist() == ["60-69", "290-299"] and "Bucket" not in out.columns


def test_to_json_cannot_close_the_script_tag():
    assert "</script" not in R._to_json({"x": "</script><script>alert(1)</script>"})
    assert R._to_json({"a": "é"}) == '{"a": "é"}'

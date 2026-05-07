"""Tests for autoplay.hypervisor.game_stats_db."""

from __future__ import annotations

from pathlib import Path

from autoplay.hypervisor import game_stats_db


def test_init_creates_db(tmp_path: Path) -> None:
    game_stats_db.init(tmp_path)
    assert (tmp_path / "game_stats.sqlite").exists()


def test_update_game_creates_row(tmp_path: Path) -> None:
    game_stats_db.update_game(
        tmp_path, runner_uuid="u1", game_id="g1", modpack="mp",
        turn=10, time_elapsed_sec=100,
    )
    summary = game_stats_db.by_runner_summary(tmp_path)
    assert "u1" in summary
    assert summary["u1"]["games"] == 1
    assert summary["u1"]["totalTurns"] == 10


def test_update_game_keeps_max(tmp_path: Path) -> None:
    game_stats_db.update_game(
        tmp_path, runner_uuid="u1", game_id="g1", modpack="mp",
        turn=10, time_elapsed_sec=100,
    )
    # Lower turn — should not regress.
    game_stats_db.update_game(
        tmp_path, runner_uuid="u1", game_id="g1", modpack="mp",
        turn=5, time_elapsed_sec=50,
    )
    summary = game_stats_db.by_runner_summary(tmp_path)
    assert summary["u1"]["totalTurns"] == 10
    assert summary["u1"]["totalTimeSec"] == 100.0


def test_update_game_advances_max(tmp_path: Path) -> None:
    game_stats_db.update_game(
        tmp_path, runner_uuid="u1", game_id="g1", modpack="mp",
        turn=10, time_elapsed_sec=100,
    )
    game_stats_db.update_game(
        tmp_path, runner_uuid="u1", game_id="g1", modpack="mp",
        turn=20, time_elapsed_sec=300,
    )
    summary = game_stats_db.by_runner_summary(tmp_path)
    assert summary["u1"]["totalTurns"] == 20
    assert summary["u1"]["totalTimeSec"] == 300.0


def test_update_game_no_op_on_empty(tmp_path: Path) -> None:
    game_stats_db.update_game(
        tmp_path, runner_uuid="", game_id="g", modpack=None,
        turn=1, time_elapsed_sec=1,
    )
    game_stats_db.update_game(
        tmp_path, runner_uuid="u", game_id="", modpack=None,
        turn=1, time_elapsed_sec=1,
    )
    game_stats_db.update_game(
        tmp_path, runner_uuid="u", game_id="g", modpack=None,
        turn=None, time_elapsed_sec=None,
    )
    assert game_stats_db.by_runner_summary(tmp_path) == {}


def test_mark_finished_existing(tmp_path: Path) -> None:
    game_stats_db.update_game(
        tmp_path, runner_uuid="u", game_id="g", modpack="mp",
        turn=5, time_elapsed_sec=50,
    )
    game_stats_db.mark_finished(tmp_path, runner_uuid="u", game_id="g", success=True)
    summary = game_stats_db.by_runner_summary(tmp_path)
    assert summary["u"]["finished"] == 1


def test_mark_finished_inserts_placeholder(tmp_path: Path) -> None:
    game_stats_db.mark_finished(tmp_path, runner_uuid="u", game_id="g", success=False)
    summary = game_stats_db.by_runner_summary(tmp_path)
    assert summary["u"]["games"] == 1
    assert summary["u"]["finished"] == 1


def test_avg_sec_calculation(tmp_path: Path) -> None:
    # Game 1: 10 turns / 100 sec -> 10 sec/turn
    game_stats_db.update_game(
        tmp_path, runner_uuid="u", game_id="g1", modpack="mp",
        turn=10, time_elapsed_sec=100,
    )
    # Game 2: 20 turns / 400 sec -> 20 sec/turn
    game_stats_db.update_game(
        tmp_path, runner_uuid="u", game_id="g2", modpack="mp",
        turn=20, time_elapsed_sec=400,
    )
    summary = game_stats_db.by_runner_summary(tmp_path)
    # Mean of (10, 20) = 15
    assert summary["u"]["avgSec"] == 15.0


def test_summary_empty_when_no_db(tmp_path: Path) -> None:
    assert game_stats_db.by_runner_summary(tmp_path) == {}


def test_avg_sec_excludes_zero_turn_games(tmp_path: Path) -> None:
    game_stats_db.update_game(
        tmp_path, runner_uuid="u", game_id="g1", modpack="mp",
        turn=10, time_elapsed_sec=100,
    )
    game_stats_db.mark_finished(tmp_path, runner_uuid="u", game_id="g2", success=False)
    summary = game_stats_db.by_runner_summary(tmp_path)
    # avg only counts the game with turns > 0.
    assert summary["u"]["avgSec"] == 10.0

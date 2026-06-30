"""Tests for the SQLite-stats reader helpers in autoplay.runner.civ_io."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from autoplay.runner import civ_io


def _make_db(
    user_dir: Path,
    *,
    uuids: list[str],
    with_result_for_latest: bool = False,
    world_state_turns: dict[int, int] | None = None,
    military_turns: dict[int, int] | None = None,
) -> Path:
    db = civ_io.stats_db_path(user_dir)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE uuid_dictionary ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, uuid_hex TEXT UNIQUE NOT NULL)"
        )
        for u in uuids:
            conn.execute("INSERT INTO uuid_dictionary (uuid_hex) VALUES (?)", (u,))
        conn.execute("CREATE TABLE GameResult (GameId INTEGER, Turn INTEGER, Civ TEXT)")
        conn.execute("CREATE TABLE WorldStateLog (GameId INTEGER, Turn INTEGER)")
        conn.execute("CREATE TABLE MilitarySummary (GameId INTEGER, Turn INTEGER)")
        latest = len(uuids)
        if with_result_for_latest:
            conn.execute("INSERT INTO GameResult VALUES (?, ?, ?)", (latest, 200, "Rome"))
        for gid, turn in (world_state_turns or {}).items():
            conn.execute("INSERT INTO WorldStateLog VALUES (?, ?)", (gid, turn))
        for gid, turn in (military_turns or {}).items():
            conn.execute("INSERT INTO MilitarySummary VALUES (?, ?)", (gid, turn))
        conn.commit()
    finally:
        conn.close()
    return db


def test_stats_db_path_under_cache(tmp_path: Path) -> None:
    assert civ_io.stats_db_path(tmp_path) == tmp_path / "cache" / "stats.db"


def test_readers_tolerate_missing_db(tmp_path: Path) -> None:
    assert civ_io.latest_game_local_id(civ_io.stats_db_path(tmp_path)) is None
    assert civ_io.sqlite_game_complete(civ_io.stats_db_path(tmp_path)) is False
    assert civ_io.read_current_turn_sqlite(civ_io.stats_db_path(tmp_path)) is None


def test_latest_game_local_id(tmp_path: Path) -> None:
    db = _make_db(tmp_path, uuids=["AAAA", "BBBB"])
    assert civ_io.latest_game_local_id(db) == 2


def test_game_complete_false_without_result_rows(tmp_path: Path) -> None:
    db = _make_db(tmp_path, uuids=["AAAA"], with_result_for_latest=False)
    assert civ_io.sqlite_game_complete(db) is False


def test_game_complete_true_with_result_for_latest(tmp_path: Path) -> None:
    db = _make_db(tmp_path, uuids=["AAAA", "BBBB"], with_result_for_latest=True)
    assert civ_io.sqlite_game_complete(db) is True


def test_game_complete_only_for_latest_game(tmp_path: Path) -> None:
    # GameResult has a row for an older game (id 1) but not the latest (id 2).
    db = civ_io.stats_db_path(tmp_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE uuid_dictionary ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, uuid_hex TEXT UNIQUE NOT NULL)"
        )
        conn.execute("INSERT INTO uuid_dictionary (uuid_hex) VALUES ('A')")
        conn.execute("INSERT INTO uuid_dictionary (uuid_hex) VALUES ('B')")
        conn.execute("CREATE TABLE GameResult (GameId INTEGER, Turn INTEGER)")
        conn.execute("INSERT INTO GameResult VALUES (1, 200)")  # older game only
        conn.commit()
    finally:
        conn.close()
    assert civ_io.sqlite_game_complete(db) is False


def test_read_current_turn_prefers_world_state_log(tmp_path: Path) -> None:
    db = _make_db(
        tmp_path,
        uuids=["AAAA"],
        world_state_turns={1: 42},
        military_turns={1: 99},
    )
    assert civ_io.read_current_turn_sqlite(db) == 42


def test_read_current_turn_falls_back_to_military_summary(tmp_path: Path) -> None:
    db = _make_db(tmp_path, uuids=["AAAA"], military_turns={1: 17})
    assert civ_io.read_current_turn_sqlite(db) == 17


def test_read_current_turn_uses_latest_game_only(tmp_path: Path) -> None:
    db = _make_db(
        tmp_path,
        uuids=["AAAA", "BBBB"],
        world_state_turns={1: 500, 2: 30},
    )
    assert civ_io.read_current_turn_sqlite(db) == 30

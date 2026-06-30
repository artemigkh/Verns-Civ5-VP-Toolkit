"""Tests for autoplay.hypervisor.stats_ingest (SQLite -> DuckDB ingestion)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import duckdb

from autoplay.hypervisor import stats_ingest

MODPACK = "MP_AUTOPLAY_VP_1"


def _make_stats_db(
    path: Path,
    *,
    uuids: list[str],
    game_results: list[tuple[int, int, str, int, str]] | None = None,
    extra_gameresult_col: bool = False,
) -> None:
    """Build a minimal SQLite stats db mirroring the real schema.

    ``uuids`` become rows in ``uuid_dictionary`` (local ids 1..N). ``GameResult``
    rows are ``(GameId, Turn, Civ, Score, VictoryType)`` referencing those local
    ids. A single ``WorldStateLog`` row per uuid is also written.
    """
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE uuid_dictionary ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, uuid_hex TEXT UNIQUE NOT NULL)"
        )
        for u in uuids:
            conn.execute("INSERT INTO uuid_dictionary (uuid_hex) VALUES (?)", (u,))
        gr_cols = "GameId INTEGER, Turn INTEGER, Civ TEXT, Score INTEGER, VictoryType TEXT"
        if extra_gameresult_col:
            gr_cols += ", ExtraCol TEXT"
        conn.execute(f"CREATE TABLE GameResult ({gr_cols})")
        conn.execute("CREATE TABLE WorldStateLog (GameId INTEGER, Turn INTEGER, Gold REAL)")
        for local_id in range(1, len(uuids) + 1):
            conn.execute(
                "INSERT INTO WorldStateLog (GameId, Turn, Gold) VALUES (?, ?, ?)",
                (local_id, local_id * 10, 1.5),
            )
        if game_results:
            placeholders = "?, ?, ?, ?, ?"
            if extra_gameresult_col:
                placeholders += ", ?"
            for row in game_results:
                vals = row if not extra_gameresult_col else (*row, "x")
                conn.execute(f"INSERT INTO GameResult VALUES ({placeholders})", vals)
        conn.commit()
    finally:
        conn.close()


def _duckdb_rows(ddb_path: Path, sql: str) -> list[tuple]:
    con = duckdb.connect(str(ddb_path))
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_basic_ingest_translates_ids_and_mirrors_tables(tmp_path: Path) -> None:
    db = tmp_path / "g1.db"
    _make_stats_db(
        db,
        uuids=["AAAA"],
        game_results=[(1, 200, "Rome", 999, "Domination")],
    )
    result = stats_ingest.ingest_stats_db(tmp_path, MODPACK, "g1", db)

    assert result.ok
    assert result.error is None
    assert not db.exists()  # moved into complete/
    assert result.archived_path is not None and result.archived_path.exists()

    ddb = stats_ingest.duckdb_path(tmp_path, MODPACK)
    dict_rows = _duckdb_rows(ddb, "SELECT id, uuid_hex FROM uuid_dictionary")
    assert dict_rows == [(1, "AAAA")]
    # GameResult.GameId is rewritten from local id (1) to the global id (1).
    gr = _duckdb_rows(ddb, "SELECT GameId, Civ, VictoryType FROM GameResult")
    assert gr == [(1, "Rome", "Domination")]
    ws = _duckdb_rows(ddb, "SELECT GameId, Turn FROM WorldStateLog")
    assert ws == [(1, 10)]


def test_distinct_games_get_distinct_global_ids(tmp_path: Path) -> None:
    db1 = tmp_path / "g1.db"
    _make_stats_db(db1, uuids=["AAAA"], game_results=[(1, 100, "Rome", 1, "")])
    assert stats_ingest.ingest_stats_db(tmp_path, MODPACK, "g1", db1).ok

    db2 = tmp_path / "g2.db"
    _make_stats_db(db2, uuids=["BBBB"], game_results=[(1, 150, "Egypt", 2, "")])
    assert stats_ingest.ingest_stats_db(tmp_path, MODPACK, "g2", db2).ok

    ddb = stats_ingest.duckdb_path(tmp_path, MODPACK)
    dict_rows = _duckdb_rows(ddb, "SELECT id, uuid_hex FROM uuid_dictionary ORDER BY id")
    assert dict_rows == [(1, "AAAA"), (2, "BBBB")]
    gr = _duckdb_rows(ddb, "SELECT GameId, Civ FROM GameResult ORDER BY GameId")
    assert gr == [(1, "Rome"), (2, "Egypt")]


def test_reingesting_same_uuid_is_idempotent_for_dictionary(tmp_path: Path) -> None:
    db1 = tmp_path / "g1.db"
    _make_stats_db(db1, uuids=["AAAA"], game_results=[(1, 100, "Rome", 1, "")])
    stats_ingest.ingest_stats_db(tmp_path, MODPACK, "g1", db1)

    db2 = tmp_path / "g1b.db"
    _make_stats_db(db2, uuids=["AAAA"], game_results=[(1, 100, "Rome", 1, "")])
    stats_ingest.ingest_stats_db(tmp_path, MODPACK, "g1b", db2)

    ddb = stats_ingest.duckdb_path(tmp_path, MODPACK)
    dict_rows = _duckdb_rows(ddb, "SELECT id, uuid_hex FROM uuid_dictionary")
    assert dict_rows == [(1, "AAAA")]  # uuid deduped, no second global id minted


def test_schema_mismatch_quarantines_and_ingests_nothing(tmp_path: Path) -> None:
    db1 = tmp_path / "g1.db"
    _make_stats_db(db1, uuids=["AAAA"], game_results=[(1, 100, "Rome", 1, "")])
    stats_ingest.ingest_stats_db(tmp_path, MODPACK, "g1", db1)

    # Second db has an extra GameResult column -> schema mismatch.
    db2 = tmp_path / "g2.db"
    _make_stats_db(
        db2,
        uuids=["BBBB"],
        game_results=[(1, 150, "Egypt", 2, "")],
        extra_gameresult_col=True,
    )
    result = stats_ingest.ingest_stats_db(tmp_path, MODPACK, "g2", db2)

    assert not result.ok
    assert result.quarantine_path is not None and result.quarantine_path.exists()
    assert not db2.exists()  # moved into incomplete_processing/
    assert result.quarantine_path.parent.name == "incomplete_processing"

    ddb = stats_ingest.duckdb_path(tmp_path, MODPACK)
    # Nothing from the mismatched file was ingested: only the first game remains.
    dict_rows = _duckdb_rows(ddb, "SELECT uuid_hex FROM uuid_dictionary")
    assert dict_rows == [("AAAA",)]
    gr = _duckdb_rows(ddb, "SELECT Civ FROM GameResult")
    assert gr == [("Rome",)]


def test_ensure_duckdb_creates_store_and_dictionary(tmp_path: Path) -> None:
    ddb = stats_ingest.ensure_duckdb(tmp_path, MODPACK)
    assert ddb.exists()
    # uuid_dictionary exists and is empty.
    rows = _duckdb_rows(ddb, "SELECT COUNT(*) FROM uuid_dictionary")
    assert rows == [(0,)]

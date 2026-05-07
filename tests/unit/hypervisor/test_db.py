"""Tests for autoplay.hypervisor.db.RunnerDB."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from autoplay.common import RunnerRegistration, RunnerState
from autoplay.hypervisor.db import RunnerDB


@pytest.fixture
def db(tmp_path: Path) -> RunnerDB:
    d = RunnerDB(tmp_path / "runners.sqlite")
    d.init_schema()
    return d


def _reg(uuid: str = "u1", url: str = "http://r:1", modpack: str = "mp") -> RunnerRegistration:
    return RunnerRegistration(uuid=uuid, url=url, modpack=modpack)


def test_init_creates_db_file(tmp_path: Path) -> None:
    p = tmp_path / "x" / "runners.sqlite"
    db = RunnerDB(p)
    db.init_schema()
    assert p.exists()


def test_upsert_first_time_returns_true(db: RunnerDB) -> None:
    assert db.upsert_registration(_reg("u1")) is True


def test_upsert_existing_returns_false(db: RunnerDB) -> None:
    db.upsert_registration(_reg("u1", url="http://r:1"))
    assert db.upsert_registration(_reg("u1", url="http://r:2", modpack="mp2")) is False
    rows = db.list_live_runners(timeout_sec=999_999)
    assert len(rows) == 1
    assert rows[0].url == "http://r:2"
    assert rows[0].modpack == "mp2"


def test_record_heartbeat_unknown_runner(db: RunnerDB) -> None:
    ok, prev = db.record_heartbeat("unknown", RunnerState.idle, None, None, None)
    assert ok is False
    assert prev is None


def test_record_heartbeat_returns_prev(db: RunnerDB) -> None:
    db.upsert_registration(_reg("u1", modpack="mp"))
    db.record_heartbeat("u1", RunnerState.running, "g1", 5, 100)
    ok, prev = db.record_heartbeat("u1", RunnerState.running, "g1", 6, 110)
    assert ok is True
    assert prev["game_id"] == "g1"
    assert prev["turn"] == 5
    assert prev["time_elapsed_sec"] == 100
    assert prev["modpack"] == "mp"


def test_list_live_prunes_stale(db: RunnerDB) -> None:
    db.upsert_registration(_reg("u1"))
    db.upsert_registration(_reg("u2"))
    # Force u1 ancient.
    import sqlite3
    with sqlite3.connect(db._db_path) as conn:
        conn.execute(
            "UPDATE runners SET last_heartbeat_ts = ? WHERE uuid = 'u1'",
            (time.time() - 1_000_000,),
        )
    rows = db.list_live_runners(timeout_sec=60)
    assert {r.uuid for r in rows} == {"u2"}


def test_prune_timed_out_returns_uuids(db: RunnerDB) -> None:
    db.upsert_registration(_reg("u1"))
    import sqlite3
    with sqlite3.connect(db._db_path) as conn:
        conn.execute(
            "UPDATE runners SET last_heartbeat_ts = ? WHERE uuid = 'u1'",
            (time.time() - 1_000_000,),
        )
    pruned = db.prune_timed_out(timeout_sec=60)
    assert pruned == ["u1"]


def test_increment_counters(db: RunnerDB) -> None:
    db.upsert_registration(_reg("u1"))
    assert db.increment_success("u1") is True
    assert db.increment_failure("u1") is True
    assert db.increment_recovery("u1") is True
    assert db.increment_success("nope") is False
    rows = db.list_live_runners(timeout_sec=999_999)
    r = rows[0]
    assert r.success_count == 1
    assert r.failure_count == 1
    assert r.recovery_count == 1


def test_delete_runner(db: RunnerDB) -> None:
    db.upsert_registration(_reg("u1"))
    assert db.delete_runner("u1") is True
    assert db.delete_runner("u1") is False
    assert db.list_live_runners(timeout_sec=999_999) == []

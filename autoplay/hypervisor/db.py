"""SQLite-backed persistence layer for the hypervisor."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from autoplay.common import RunnerRegistration, RunnerState, RunnerStatusRow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runners (
    uuid              TEXT PRIMARY KEY,
    url               TEXT NOT NULL,
    modpack           TEXT,
    state             TEXT NOT NULL DEFAULT 'idle',
    game_id           TEXT,
    turn              INTEGER,
    time_elapsed_sec  INTEGER,
    last_heartbeat_ts REAL NOT NULL,
    success_count     INTEGER NOT NULL DEFAULT 0,
    failure_count     INTEGER NOT NULL DEFAULT 0
);
"""


class RunnerDB:
    """Thin wrapper around a SQLite connection for runner bookkeeping."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, isolation_level=None, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def upsert_registration(self, reg: RunnerRegistration) -> bool:
        """Upsert a runner registration. Returns True if this row is brand-new."""
        now = time.time()
        with self._connect() as conn:
            existed = conn.execute(
                "SELECT 1 FROM runners WHERE uuid = ?", (reg.uuid,)
            ).fetchone()
            conn.execute(
                """
                INSERT INTO runners (uuid, url, modpack, state, last_heartbeat_ts)
                VALUES (?, ?, ?, 'idle', ?)
                ON CONFLICT(uuid) DO UPDATE SET
                    url = excluded.url,
                    modpack = excluded.modpack,
                    last_heartbeat_ts = excluded.last_heartbeat_ts
                """,
                (reg.uuid, reg.url, reg.modpack, now),
            )
            return existed is None

    def record_heartbeat(
        self,
        uuid: str,
        state: RunnerState,
        game_id: str | None,
        turn: int | None,
        time_elapsed_sec: int | None,
    ) -> bool:
        """Update heartbeat fields for a runner. Returns False if runner is unknown."""
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE runners
                   SET state = ?,
                       game_id = ?,
                       turn = ?,
                       time_elapsed_sec = ?,
                       last_heartbeat_ts = ?
                 WHERE uuid = ?
                """,
                (state.value, game_id, turn, time_elapsed_sec, now, uuid),
            )
            return cur.rowcount > 0

    def list_live_runners(self, timeout_sec: int) -> list[RunnerStatusRow]:
        cutoff = time.time() - timeout_sec
        with self._connect() as conn:
            # Prune rows that have timed out, then return survivors.
            conn.execute("DELETE FROM runners WHERE last_heartbeat_ts < ?", (cutoff,))
            rows = conn.execute(
                "SELECT * FROM runners ORDER BY last_heartbeat_ts DESC"
            ).fetchall()
        return [
            RunnerStatusRow(
                uuid=r["uuid"],
                url=r["url"],
                modpack=r["modpack"],
                state=RunnerState(r["state"]),
                game_id=r["game_id"],
                turn=r["turn"],
                time_elapsed_sec=r["time_elapsed_sec"],
                last_heartbeat_ts=r["last_heartbeat_ts"],
                success_count=r["success_count"],
                failure_count=r["failure_count"],
            )
            for r in rows
        ]

    def prune_timed_out(self, timeout_sec: int) -> list[str]:
        """Delete rows older than the cutoff and return the pruned UUIDs."""
        cutoff = time.time() - timeout_sec
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT uuid FROM runners WHERE last_heartbeat_ts < ?", (cutoff,)
            ).fetchall()
            if rows:
                conn.execute(
                    "DELETE FROM runners WHERE last_heartbeat_ts < ?", (cutoff,)
                )
        return [r["uuid"] for r in rows]

    def increment_success(self, uuid: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE runners SET success_count = success_count + 1 WHERE uuid = ?",
                (uuid,),
            )
            return cur.rowcount > 0

    def increment_failure(self, uuid: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE runners SET failure_count = failure_count + 1 WHERE uuid = ?",
                (uuid,),
            )
            return cur.rowcount > 0

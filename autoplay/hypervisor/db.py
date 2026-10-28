"""SQLite-backed persistence layer for the hypervisor."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from autoplay.common import RunnerKind, RunnerRegistration, RunnerState, RunnerStatusRow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runners (
    uuid              TEXT PRIMARY KEY,
    url               TEXT NOT NULL,
    modpack           TEXT,
    state             TEXT NOT NULL DEFAULT 'idle',
    game_id           TEXT,
    turn              INTEGER,
    time_elapsed_sec  INTEGER,
    kind              TEXT NOT NULL DEFAULT 'client',
    last_turn_sec     REAL,
    turn_seen_elapsed_sec REAL,
    last_heartbeat_ts REAL NOT NULL,
    success_count     INTEGER NOT NULL DEFAULT 0,
    failure_count     INTEGER NOT NULL DEFAULT 0,
    recovery_count    INTEGER NOT NULL DEFAULT 0
);
"""


def _turn_timing(
    row: sqlite3.Row,
    game_id: str | None,
    turn: int | None,
    time_elapsed_sec: int | None,
    reported_last_turn_sec: float | None,
) -> tuple[float | None, float | None]:
    """``(last_turn_sec, turn_seen_elapsed_sec)`` to store for a heartbeat (see ``record_heartbeat``).

    ``turn_seen_elapsed_sec`` is the game time at which the current turn was first seen.
    """
    same_game = game_id is not None and row["game_id"] == game_id
    advanced = same_game and turn is not None and row["turn"] is not None and turn > row["turn"]
    if same_game and not advanced and turn == row["turn"]:
        seen = row["turn_seen_elapsed_sec"]
    else:
        seen = time_elapsed_sec
    if reported_last_turn_sec is not None:
        return reported_last_turn_sec, seen
    if not same_game:
        return None, seen
    if not advanced:
        return row["last_turn_sec"], seen
    start = row["turn_seen_elapsed_sec"]
    if time_elapsed_sec is None or start is None or time_elapsed_sec < start:
        return row["last_turn_sec"], seen
    return (time_elapsed_sec - start) / (turn - row["turn"]), seen


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
                INSERT INTO runners (uuid, url, modpack, kind, state, last_heartbeat_ts)
                VALUES (?, ?, ?, ?, 'idle', ?)
                ON CONFLICT(uuid) DO UPDATE SET
                    url = excluded.url,
                    modpack = excluded.modpack,
                    kind = excluded.kind,
                    last_heartbeat_ts = excluded.last_heartbeat_ts
                """,
                (reg.uuid, reg.url, reg.modpack, reg.kind.value, now),
            )
            return existed is None

    def record_heartbeat(
        self,
        uuid: str,
        state: RunnerState,
        game_id: str | None,
        turn: int | None,
        time_elapsed_sec: int | None,
        last_turn_sec: float | None = None,
        url: str | None = None,
    ) -> tuple[bool, dict | None]:
        """Update heartbeat fields for a runner.

        ``url``, when given, replaces the registered one: a headless bridge that restarts on a
        new port keeps its slot uuids, so the heartbeat is the only place the new address shows up.

        ``last_turn_sec`` is stored as reported when given. Runners that do not
        report it get it derived here: when the same game's turn advances, the
        game time since that turn was first seen divided by the turns advanced
        (so it is as precise as the heartbeat interval); while the turn stands
        still the previous value is kept; a new game clears it.

        Returns ``(ok, prev)`` where ``ok`` is False if the runner is unknown.
        ``prev`` is a snapshot of the row's ``(game_id, turn, time_elapsed_sec,
        modpack)`` *before* the update, or ``None`` if the runner was unknown.
        Used by callers to detect turn advances for turn-time logging.
        """
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT game_id, turn, time_elapsed_sec, modpack, last_turn_sec, turn_seen_elapsed_sec"
                " FROM runners WHERE uuid = ?",
                (uuid,),
            ).fetchone()
            turn_seen = time_elapsed_sec
            if row is not None:
                last_turn_sec, turn_seen = _turn_timing(row, game_id, turn, time_elapsed_sec, last_turn_sec)
            cur = conn.execute(
                """
                UPDATE runners
                   SET state = ?,
                       game_id = ?,
                       turn = ?,
                       time_elapsed_sec = ?,
                       last_turn_sec = ?,
                       turn_seen_elapsed_sec = ?,
                       last_heartbeat_ts = ?,
                       url = COALESCE(?, url)
                 WHERE uuid = ?
                """,
                (state.value, game_id, turn, time_elapsed_sec, last_turn_sec, turn_seen, now, url, uuid),
            )
            if cur.rowcount == 0:
                return False, None
            prev = {
                "game_id": row["game_id"] if row else None,
                "turn": row["turn"] if row else None,
                "time_elapsed_sec": row["time_elapsed_sec"] if row else None,
                "modpack": row["modpack"] if row else None,
            }
            return True, prev

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
                kind=RunnerKind(r["kind"]),
                last_turn_sec=r["last_turn_sec"],
                last_heartbeat_ts=r["last_heartbeat_ts"],
                success_count=r["success_count"],
                failure_count=r["failure_count"],
                recovery_count=r["recovery_count"],
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

    def increment_recovery(self, uuid: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE runners SET recovery_count = recovery_count + 1 WHERE uuid = ?",
                (uuid,),
            )
            return cur.rowcount > 0

    def delete_runner(self, uuid: str) -> bool:
        """Delete the row for ``uuid``. Returns True if a row was removed."""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM runners WHERE uuid = ?", (uuid,))
            return cur.rowcount > 0

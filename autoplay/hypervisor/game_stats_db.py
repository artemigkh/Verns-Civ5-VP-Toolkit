"""Per-game stats: one row per ``(runner_uuid, game_id)`` tracking the highest
turn observed and the largest ``time_elapsed_sec`` reported. Rows are kept
forever (active or finished) and used to derive each runner's average turn
duration as the mean across games of ``total_time_sec / turns``.

While a game is in progress, heartbeats continually update ``turns`` and
``total_time_sec`` to the latest snapshot, so the average reflects the
current pace. When the game ends (success or failure) the row is marked
``finished`` with its final snapshot and stays in history forever.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_FILENAME = "game_stats.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS game_stats (
    runner_uuid     TEXT NOT NULL,
    game_id         TEXT NOT NULL,
    modpack         TEXT,
    turns           INTEGER NOT NULL DEFAULT 0,
    total_time_sec  REAL    NOT NULL DEFAULT 0,
    finished        INTEGER NOT NULL DEFAULT 0,
    finished_status TEXT,
    first_seen_at   REAL NOT NULL,
    last_updated_at REAL NOT NULL,
    PRIMARY KEY (runner_uuid, game_id)
);
CREATE INDEX IF NOT EXISTS game_stats_runner_idx ON game_stats(runner_uuid);
"""


def _path(storage_root: Path) -> Path:
    return storage_root / _DB_FILENAME


def _connect(storage_root: Path) -> sqlite3.Connection:
    p = _path(storage_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(_SCHEMA)
    return conn


def init(storage_root: Path) -> None:
    """Ensure the schema exists on disk."""
    with _connect(storage_root) as _:
        pass


def update_game(
    storage_root: Path,
    *,
    runner_uuid: str,
    game_id: str,
    modpack: str | None,
    turn: int | None,
    time_elapsed_sec: float | int | None,
) -> None:
    """Upsert a game's running stats. Keeps the max ``turn`` and max
    ``time_elapsed_sec`` ever observed. Errors are logged and swallowed."""
    if not runner_uuid or not game_id:
        return
    if turn is None and time_elapsed_sec is None:
        return
    now = time.time()
    t = int(turn) if turn is not None else 0
    s = float(time_elapsed_sec) if time_elapsed_sec is not None else 0.0
    try:
        with _connect(storage_root) as conn:
            conn.execute(
                """
                INSERT INTO game_stats
                    (runner_uuid, game_id, modpack, turns, total_time_sec,
                     finished, finished_status, first_seen_at, last_updated_at)
                VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?)
                ON CONFLICT(runner_uuid, game_id) DO UPDATE SET
                    modpack         = COALESCE(excluded.modpack, game_stats.modpack),
                    turns           = MAX(game_stats.turns, excluded.turns),
                    total_time_sec  = MAX(game_stats.total_time_sec, excluded.total_time_sec),
                    last_updated_at = excluded.last_updated_at
                """,
                (runner_uuid, game_id, modpack, t, s, now, now),
            )
    except sqlite3.Error as exc:
        logger.warning("Failed to update game_stats: %s", exc)


def mark_finished(
    storage_root: Path,
    *,
    runner_uuid: str,
    game_id: str,
    success: bool,
) -> None:
    """Mark a game's row as finished. If no row exists yet (e.g. the runner
    never sent a heartbeat for this game), inserts a placeholder row so the
    finish event is still recorded."""
    if not runner_uuid or not game_id:
        return
    now = time.time()
    status_str = "success" if success else "failure"
    try:
        with _connect(storage_root) as conn:
            conn.execute(
                """
                INSERT INTO game_stats
                    (runner_uuid, game_id, modpack, turns, total_time_sec,
                     finished, finished_status, first_seen_at, last_updated_at)
                VALUES (?, ?, NULL, 0, 0, 1, ?, ?, ?)
                ON CONFLICT(runner_uuid, game_id) DO UPDATE SET
                    finished        = 1,
                    finished_status = excluded.finished_status,
                    last_updated_at = excluded.last_updated_at
                """,
                (runner_uuid, game_id, status_str, now, now),
            )
    except sqlite3.Error as exc:
        logger.warning("Failed to mark game_stats finished: %s", exc)


def by_runner_summary(storage_root: Path) -> dict[str, dict]:
    """Return per-runner summary stats.

    Output shape::

        {
          "<uuid>": {
            "games":        int,    # total games in history (active + finished)
            "finished":     int,    # subset that have been marked finished
            "totalTurns":   int,    # sum of per-game turns
            "totalTimeSec": float,  # sum of per-game total_time_sec
            "avgSec":       float | None,  # mean across games of (time/turns)
          }
        }

    ``avgSec`` only counts games with ``turns > 0``.
    """
    out: dict[str, dict] = {}
    p = _path(storage_root)
    if not p.exists():
        return out
    try:
        with _connect(storage_root) as conn:
            rows = conn.execute(
                """
                SELECT runner_uuid,
                       COUNT(*)                                          AS games,
                       SUM(CASE WHEN finished = 1 THEN 1 ELSE 0 END)     AS finished,
                       COALESCE(SUM(turns), 0)                           AS total_turns,
                       COALESCE(SUM(total_time_sec), 0.0)                AS total_time,
                       AVG(CASE WHEN turns > 0
                                THEN total_time_sec * 1.0 / turns
                                ELSE NULL END)                           AS avg_sec
                  FROM game_stats
                 GROUP BY runner_uuid
                """
            ).fetchall()
            for r in rows:
                out[r["runner_uuid"]] = {
                    "games":        int(r["games"]),
                    "finished":     int(r["finished"] or 0),
                    "totalTurns":   int(r["total_turns"] or 0),
                    "totalTimeSec": float(r["total_time"] or 0.0),
                    "avgSec":       float(r["avg_sec"]) if r["avg_sec"] is not None else None,
                }
    except sqlite3.Error as exc:
        logger.warning("Failed to query game_stats summary: %s", exc)
    return out

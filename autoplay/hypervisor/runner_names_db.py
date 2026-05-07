"""SQLite-backed persistence for user-friendly runner display names.

The mapping is keyed by the *host* portion of a runner's URL (i.e. the
IP/hostname without the port), since per-process UUIDs change when a
runner restarts but the host typically does not. This DB is **not**
recreated on hypervisor restart; it is the durable record of
operator-supplied tags so they survive across hypervisor processes and
even cross-machine moves of the storage root.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runner_names (
    host        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    updated_ts  REAL NOT NULL
);
"""


def _db_path(storage_root: Path) -> Path:
    return storage_root / "runner_names.sqlite"


def _connect(storage_root: Path) -> sqlite3.Connection:
    storage_root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path(storage_root), isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init(storage_root: Path) -> None:
    with _connect(storage_root) as conn:
        conn.executescript(_SCHEMA)


def all_names(storage_root: Path) -> dict[str, str]:
    with _connect(storage_root) as conn:
        rows = conn.execute("SELECT host, name FROM runner_names").fetchall()
    return {r["host"]: r["name"] for r in rows}


def set_name(storage_root: Path, host: str, name: str) -> None:
    with _connect(storage_root) as conn:
        conn.execute(
            "INSERT INTO runner_names (host, name, updated_ts) VALUES (?, ?, ?) "
            "ON CONFLICT(host) DO UPDATE SET name = excluded.name, "
            "updated_ts = excluded.updated_ts",
            (host, name, time.time()),
        )


def delete_name(storage_root: Path, host: str) -> bool:
    with _connect(storage_root) as conn:
        cur = conn.execute("DELETE FROM runner_names WHERE host = ?", (host,))
        return cur.rowcount > 0

"""Append-only per-modpack bundle metadata SQLite databases.

For each modpack version ``MP_AUTOPLAY_VP_<version>``, a sibling sqlite file
``<MODPACK_VERSION>_bundles.sqlite`` is maintained at ``STORAGE_ROOT``. Every
successful ``/submit-logs`` insert appends a row recording everything we know
about the bundle (file name, size, runner UUID, runner-supplied metadata, and
ingest timestamp). The DB is append-only — rows are never updated or deleted.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bundles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bundle_name     TEXT NOT NULL,
    game_id         TEXT NOT NULL,
    runner_uuid     TEXT,
    file_size_bytes INTEGER NOT NULL,
    ingested_at     REAL NOT NULL,
    metadata_json   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS bundles_game_id_idx ON bundles(game_id);
CREATE INDEX IF NOT EXISTS bundles_runner_uuid_idx ON bundles(runner_uuid);
"""


def _db_path(storage_root: Path, modpack: str) -> Path:
    return storage_root / f"{modpack}_bundles.sqlite"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.executescript(_SCHEMA)
    return conn


def record_bundle(
    storage_root: Path,
    *,
    modpack: str,
    bundle_name: str,
    game_id: str,
    runner_uuid: str | None,
    file_size_bytes: int,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append a row describing a freshly-ingested bundle.

    ``metadata`` may contain any extra fields the runner submitted alongside
    the file (e.g. final turn, time elapsed). It is JSON-serialized verbatim.
    Errors are logged and swallowed — bundle ingestion must not be blocked by
    a metadata DB hiccup.
    """
    path = _db_path(storage_root, modpack)
    payload = json.dumps(metadata or {}, sort_keys=True)
    try:
        with _connect(path) as conn:
            conn.execute(
                """
                INSERT INTO bundles
                    (bundle_name, game_id, runner_uuid, file_size_bytes,
                     ingested_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    bundle_name,
                    game_id,
                    runner_uuid,
                    int(file_size_bytes),
                    time.time(),
                    payload,
                ),
            )
    except sqlite3.Error as exc:
        logger.warning(
            "Failed to record bundle metadata in %s: %s", path.name, exc
        )

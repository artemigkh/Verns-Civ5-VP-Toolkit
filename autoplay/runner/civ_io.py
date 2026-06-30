"""Filesystem helpers for interacting with a Civ5 install."""

from __future__ import annotations

import csv
import logging
import sqlite3
from pathlib import Path

from autoplay.common.constants import (
    GAME_RESULT_TABLE,
    MILITARY_SUMMARY_TABLE,
    MODPACK_FOLDER_PREFIX,
    MODPACK_FOLDER_REGEX,
    STATS_DB_FILENAME,
    STATS_GAME_FK_COLUMN,
    UUID_DICTIONARY_TABLE,
    WORLD_STATE_LOG_TABLE,
)
from autoplay.runner.fatal import fatal_permission_error

logger = logging.getLogger(__name__)


def detect_installed_modpack(install_dir: Path) -> str | None:
    """Return the ``MP_AUTOPLAY_VP_<version>`` folder name installed, or None.

    Looks under ``<install_dir>/Assets/DLC/`` for a single autoplay modpack folder.
    If multiple match, returns the alphabetically last one (highest version).
    """
    dlc_dir = install_dir / "Assets" / "DLC"
    if not dlc_dir.is_dir():
        return None
    matches = sorted(
        p.name for p in dlc_dir.iterdir() if p.is_dir() and p.name.startswith(MODPACK_FOLDER_PREFIX)
    )
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning("Multiple modpack folders found: %s; using %s", matches, matches[-1])
    return matches[-1]


def parse_modpack_version(folder_name: str) -> str | None:
    m = MODPACK_FOLDER_REGEX.match(folder_name)
    return m.group("version") if m else None


def read_current_turn(logs_dir: Path) -> int | None:
    """Read the most recent turn from ``WorldState_Log.csv``, or None."""
    path = logs_dir / "WorldState_Log.csv"
    if not path.is_file():
        return None
    try:
        with path.open(newline="", encoding="utf-8", errors="replace") as fh:
            reader = csv.DictReader(fh)
            last_turn: int | None = None
            for row in reader:
                raw = (row.get("Turn") or "").strip()
                if not raw:
                    continue
                try:
                    last_turn = int(raw)
                except ValueError:
                    continue
            return last_turn
    except PermissionError as exc:
        fatal_permission_error(exc, where=f"reading {path}")
    except OSError as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return None


def game_result_present(logs_dir: Path) -> bool:
    return (logs_dir / "GameResult_Log.csv").is_file()


def find_most_recent_autosave(user_dir: Path) -> Path | None:
    autosave_dir = user_dir / "Saves" / "single" / "auto"
    if not autosave_dir.is_dir():
        return None
    saves = list(autosave_dir.glob("*.Civ5Save"))
    if not saves:
        return None
    return max(saves, key=lambda p: p.stat().st_mtime)


# --- SQLite-stats mode ------------------------------------------------------


def stats_db_path(user_dir: Path) -> Path:
    """Path to the SQLite stats database the Civ5 process writes to."""
    return user_dir / "cache" / STATS_DB_FILENAME


def _connect_stats_ro(db_path: Path) -> sqlite3.Connection | None:
    """Open the stats db read-only, or return None if it can't be opened."""
    if not db_path.is_file():
        return None
    try:
        uri = db_path.resolve().as_uri()
        return sqlite3.connect(f"{uri}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        logger.debug("Could not open stats db %s read-only: %s", db_path, exc)
        return None


def latest_game_local_id(db_path: Path) -> int | None:
    """Return the highest local game id in ``uuid_dictionary``, or None."""
    conn = _connect_stats_ro(db_path)
    if conn is None:
        return None
    try:
        cur = conn.execute(f"SELECT MAX(id) FROM {UUID_DICTIONARY_TABLE}")
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except sqlite3.Error as exc:
        logger.debug("Could not read latest game id from %s: %s", db_path, exc)
        return None
    finally:
        conn.close()


def sqlite_game_complete(db_path: Path) -> bool:
    """True when ``GameResult`` has at least one row for the latest game id."""
    conn = _connect_stats_ro(db_path)
    if conn is None:
        return False
    try:
        cur = conn.execute(f"SELECT MAX(id) FROM {UUID_DICTIONARY_TABLE}")
        row = cur.fetchone()
        if not row or row[0] is None:
            return False
        latest = int(row[0])
        cur = conn.execute(
            f"SELECT 1 FROM {GAME_RESULT_TABLE} WHERE {STATS_GAME_FK_COLUMN} = ? LIMIT 1",
            (latest,),
        )
        return cur.fetchone() is not None
    except sqlite3.Error as exc:
        logger.debug("Could not check game completion in %s: %s", db_path, exc)
        return False
    finally:
        conn.close()


def read_current_turn_sqlite(db_path: Path) -> int | None:
    """Read the most recent turn for the latest game from the stats db, or None.

    Uses ``WorldStateLog`` (one row per turn) and falls back to
    ``MilitarySummary`` when the former has no rows yet.
    """
    conn = _connect_stats_ro(db_path)
    if conn is None:
        return None
    try:
        cur = conn.execute(f"SELECT MAX(id) FROM {UUID_DICTIONARY_TABLE}")
        row = cur.fetchone()
        if not row or row[0] is None:
            return None
        latest = int(row[0])
        for table in (WORLD_STATE_LOG_TABLE, MILITARY_SUMMARY_TABLE):
            try:
                cur = conn.execute(
                    f"SELECT MAX(Turn) FROM {table} WHERE {STATS_GAME_FK_COLUMN} = ?",
                    (latest,),
                )
            except sqlite3.Error:
                continue
            res = cur.fetchone()
            if res and res[0] is not None:
                return int(res[0])
        return None
    except sqlite3.Error as exc:
        logger.debug("Could not read current turn from %s: %s", db_path, exc)
        return None
    finally:
        conn.close()

"""Filesystem helpers for interacting with a Civ5 install."""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from autoplay.common.constants import MODPACK_FOLDER_PREFIX, MODPACK_FOLDER_REGEX
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

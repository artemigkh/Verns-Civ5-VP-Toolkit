"""Modpack installer: unzips a modpack into the DLC folder, purges old modpacks."""

from __future__ import annotations

import logging
import shutil
import zipfile
from pathlib import Path

from autoplay.common.constants import MODPACK_FOLDER_PREFIX, MODPACK_FOLDER_REGEX
from autoplay.runner.fatal import fatal_permission_error

logger = logging.getLogger(__name__)


class ModpackZipError(ValueError):
    """Raised when a modpack zip is malformed."""


def peek_modpack_version(zip_path: Path) -> str:
    """Return the ``MP_AUTOPLAY_VP_<version>`` folder name at the top of ``zip_path``.

    Raises ``ModpackZipError`` if the zip does not contain exactly one top-level
    folder matching the pattern.
    """
    with zipfile.ZipFile(zip_path) as zf:
        tops: set[str] = set()
        for name in zf.namelist():
            parts = name.split("/")
            if parts and parts[0]:
                tops.add(parts[0])
    autoplay_tops = {t for t in tops if MODPACK_FOLDER_REGEX.match(t)}
    if len(autoplay_tops) != 1:
        raise ModpackZipError(
            f"Zip must contain exactly one top-level MP_AUTOPLAY_VP_* folder; "
            f"got {sorted(autoplay_tops) or sorted(tops)}"
        )
    return autoplay_tops.pop()


def install_modpack_zip(zip_path: Path, install_dir: Path) -> str:
    """Extract ``zip_path`` into ``<install_dir>/Assets/DLC/`` and purge other autoplay modpacks.

    Returns the installed modpack folder name.
    """
    dlc_dir = install_dir / "Assets" / "DLC"
    if not dlc_dir.parent.is_dir():
        raise FileNotFoundError(f"Install assets dir missing: {dlc_dir.parent}")
    dlc_dir.mkdir(parents=True, exist_ok=True)

    target = peek_modpack_version(zip_path)

    try:
        # Purge existing autoplay modpack folders (including the target, for clean overwrite).
        for child in dlc_dir.iterdir():
            if child.is_dir() and child.name.startswith(MODPACK_FOLDER_PREFIX):
                logger.info("Removing existing modpack folder: %s", child.name)
                shutil.rmtree(child, ignore_errors=True)

        logger.info("Extracting %s into %s", target, dlc_dir)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(dlc_dir)
    except PermissionError as exc:
        fatal_permission_error(exc, where=f"installing modpack into {dlc_dir}")

    if not (dlc_dir / target).is_dir():
        raise ModpackZipError(
            f"Zip extraction did not produce expected folder {dlc_dir / target}"
        )
    return target

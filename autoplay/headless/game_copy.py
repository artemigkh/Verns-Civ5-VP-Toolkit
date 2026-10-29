"""The bridge's own copy of the game folder, so its games never hold files of the Steam install.

A headless game loads the modpack's ``CvGameCore_Expansion2.dll`` and reads Lua, XML and map scripts
from ``<game_dir>\\Assets`` (every DLC package included) for as long as it plays. Played from the Steam
install, that keeps the modpack's DLC folder locked and in place. The copy holds what the host needs and
nothing else, as the remote workers' game folder does: the root DLLs, ``Locale\\`` (ICU data) and
``Assets\\`` without art, audio and video, with the configured modpack as the only one among the DLC
(other modpack folders the real game's runner installed are left out).

It is made once per modpack folder, at ``<copy_root>\\<modpack folder>\\Sid Meier's Civilization V``, and
reused from then on, so the Steam install's modpack folder can be removed once the copy exists. A copy
is only used when its marker file was written, which happens after everything else was copied.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from autoplay.common.constants import MODPACK_FOLDER_PREFIX

logger = logging.getLogger(__name__)

GAME_FOLDER_NAME = "Sid Meier's Civilization V"
MARKER_FILENAME = "headless-game-copy.json"
DLL_NAME = "CvGameCore_Expansion2.dll"

MEDIA_SUFFIXES = frozenset(
    {".ogg", ".dds", ".mp3", ".wmv", ".wav", ".tga", ".wma", ".gr2", ".binka", ".bik", ".pdb", ".psd"}
    | {".ani", ".png", ".bmp"}
)
"""Art, audio and video the host never reads (pack.sh leaves out the same)."""

MODPACK_PREFIXES = (MODPACK_FOLDER_PREFIX, "VP_MODPACK_")
"""DLC folder names of modpacks (the runner's ``MP_AUTOPLAY_VP_*`` and generated ``VP_MODPACK_*``)."""


@dataclass(frozen=True)
class GamePaths:
    """The game folder and the DLL a game plays (c5h queue ``gameDir`` and ``dll``)."""

    game_dir: Path
    dll: Path


def copy_dir(copy_root: Path, modpack_folder: str) -> Path:
    return copy_root / modpack_folder / GAME_FOLDER_NAME


def find_dll(game_dir: Path, modpack_folder: str) -> Path:
    """The modpack's game DLL (``.dll.orig`` and other backups do not count)."""
    found = sorted((game_dir / "Assets" / "DLC" / modpack_folder).rglob(DLL_NAME))
    if len(found) != 1:
        raise RuntimeError(
            f"expected one {DLL_NAME} in {game_dir / 'Assets' / 'DLC' / modpack_folder}, found {len(found)}"
        )
    return found[0]


def _ignore(source: Path, modpack_folder: str):
    dlc = source / "Assets" / "DLC"

    def ignore(folder: str, names: list[str]) -> set[str]:
        skipped = {n for n in names if Path(n).suffix.lower() in MEDIA_SUFFIXES}
        if Path(folder) == dlc:
            skipped |= {
                n
                for n in names
                if n.startswith(".") or (n != modpack_folder and n.upper().startswith(MODPACK_PREFIXES))
            }
        return skipped

    return ignore


def _copy(source: Path, dest: Path, modpack_folder: str) -> None:
    dest.mkdir(parents=True)
    for dll in source.glob("*.dll"):
        shutil.copy2(dll, dest / dll.name)
    ignore = _ignore(source, modpack_folder)
    for folder in ("Locale", "Assets"):
        shutil.copytree(source / folder, dest / folder, ignore=ignore)


def prepare(source: Path, modpack_folder: str, copy_root: Path) -> GamePaths:
    """The copy for ``modpack_folder``, made from ``source`` (the Steam game folder) if there is none yet."""
    # Absolute: c5h reads relative queue paths from the queue file's folder.
    dest = copy_dir(copy_root.resolve(), modpack_folder)
    if (dest / MARKER_FILENAME).is_file():
        return GamePaths(dest, find_dll(dest, modpack_folder))
    if not (source / "Assets" / "DLC" / modpack_folder).is_dir():
        raise RuntimeError(
            f"no copy of the game for {modpack_folder} at {dest}, and the game folder {source} has no "
            f"Assets\\DLC\\{modpack_folder} to make one from"
        )
    find_dll(source, modpack_folder)  # fail before copying anything
    staging = dest.with_name(dest.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(dest, ignore_errors=True)  # an unmarked copy is one that did not finish
    logger.info("Copying the game folder with %s from %s to %s", modpack_folder, source, dest)
    started = time.monotonic()
    _copy(source, staging, modpack_folder)
    staging.rename(dest)
    dll = find_dll(dest, modpack_folder)
    marker = {
        "source": str(source),
        "modpack": modpack_folder,
        "dll": str(dll.relative_to(dest)),
        "copiedAt": datetime.now(UTC).isoformat(),
    }
    (dest / MARKER_FILENAME).write_text(json.dumps(marker, indent=1) + "\n", encoding="utf-8")
    size = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())
    logger.info("Copied the game folder (%.0f MB) in %.1f s", size / 2**20, time.monotonic() - started)
    return GamePaths(dest, dll)

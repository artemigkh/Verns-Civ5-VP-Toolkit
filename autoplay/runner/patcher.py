"""Install runner-side patched files into the Civ 5 USER/INSTALL directories.

The runner ships a ``patched_files/`` directory containing files required for
automation (a Lua DLL replacement, modified menu/map scripts, and ini files).
On startup, the runner copies each one over its destination, creating parent
directories as needed. Failures are logged but non-fatal so the runner can
still register and accept ``/update-modpack`` calls in a degraded state.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_PATCHED_FILES_DIR = Path(__file__).parent / "patched_files"


def _copy(src: Path, dest: Path) -> None:
    if not src.is_file():
        logger.warning("Patched source missing, skipping: %s", src)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    logger.info("Patched file installed: %s -> %s", src.name, dest)


def install_patched_files(
    user_dir: Path, install_dir: Path, *, use_blank_d3d9_proxy: bool = False
) -> None:
    """Overwrite (or create) the patched files under USER_DIR / INSTALL_DIR.

    When ``use_blank_d3d9_proxy`` is True, ``patched_files/d3d9.dll`` is copied
    to ``<INSTALL_DIR>/d3d9.dll`` (the historical behaviour). When False (the
    default), any existing ``<INSTALL_DIR>/d3d9.dll`` is removed instead, so
    the game runs against the system DirectX runtime.

    Mapping:
        <USER_DIR>/config.ini                              <- patched_files/config.ini
        <USER_DIR>/UserSettings.ini                        <- patched_files/UserSettings.ini
        <USER_DIR>/GraphicsSettingsDX11.ini                <- patched_files/GraphicsSettingsDX11.ini
        <INSTALL_DIR>/lua51_Win32.dll                      <- patched_files/lua51_Win32.dll
        <INSTALL_DIR>/d3d9.dll                             <- patched_files/d3d9.dll  (if use_blank_d3d9_proxy)
        <INSTALL_DIR>/Assets/Maps/Communitu_79a.lua        <- patched_files/Communitu_79a.lua
        <INSTALL_DIR>/Assets/UI/FrontEnd/FrontEnd.lua      <- patched_files/FrontEnd.lua
        <INSTALL_DIR>/Assets/UI/FrontEnd/MainMenu.lua      <- patched_files/MainMenu.lua
        <INSTALL_DIR>/Assets/Automation/RunAutoplayGame.lua <- patched_files/RunAutoplayGame.lua
    """
    pf = _PATCHED_FILES_DIR
    targets: list[tuple[Path, Path]] = [
        (pf / "config.ini", user_dir / "config.ini"),
        (pf / "UserSettings.ini", user_dir / "UserSettings.ini"),
        (pf / "GraphicsSettingsDX11.ini", user_dir / "GraphicsSettingsDX11.ini"),
        (pf / "lua51_Win32.dll", install_dir / "lua51_Win32.dll"),
        (pf / "Communitu_79a.lua", install_dir / "Assets" / "Maps" / "Communitu_79a.lua"),
        (pf / "FrontEnd.lua", install_dir / "Assets" / "UI" / "FrontEnd" / "FrontEnd.lua"),
        (pf / "MainMenu.lua", install_dir / "Assets" / "UI" / "FrontEnd" / "MainMenu.lua"),
        (pf / "RunAutoplayGame.lua", install_dir / "Assets" / "Automation" / "RunAutoplayGame.lua"),
    ]
    if use_blank_d3d9_proxy:
        targets.append((pf / "d3d9.dll", install_dir / "d3d9.dll"))
    for src, dest in targets:
        try:
            _copy(src, dest)
        except OSError as exc:
            logger.warning("Failed to install patched file %s -> %s: %s", src, dest, exc)

    if not use_blank_d3d9_proxy:
        d3d9_dest = install_dir / "d3d9.dll"
        try:
            if d3d9_dest.exists():
                d3d9_dest.unlink()
                logger.info(
                    "Removed %s (USE_BLANK_D3D9_PROXY=False)", d3d9_dest
                )
        except OSError as exc:
            logger.warning("Failed to remove %s: %s", d3d9_dest, exc)


_MAIN_MENU_REL = Path("Assets") / "UI" / "FrontEnd" / "MainMenu.lua"


def set_load_on_start(install_dir: Path, *, enabled: bool) -> None:
    """Toggle the ``loadOnStart`` flag on the first line of the patched MainMenu.lua.

    The patched MainMenu.lua starts with ``local loadOnStart = false;`` (or ``true``).
    When ``enabled`` is True, the game will auto-load the most recent save on launch
    (used for crash recovery). When False, the menu behaves normally — required for
    fresh ``-Automation`` starts so they don't get hijacked by an autosave reload.
    """
    target = install_dir / _MAIN_MENU_REL
    desired = "true" if enabled else "false"
    new_first_line = f"local loadOnStart = {desired};"
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Cannot read MainMenu.lua to toggle loadOnStart: %s", exc)
        return
    lines = text.split("\n", 1)
    if not lines or "loadOnStart" not in lines[0]:
        logger.warning(
            "MainMenu.lua first line is not the expected loadOnStart declaration; "
            "skipping toggle (got: %r)",
            lines[0] if lines else "",
        )
        return
    if lines[0].strip() == new_first_line:
        logger.debug("MainMenu.lua loadOnStart already %s", desired)
        return
    rest = lines[1] if len(lines) > 1 else ""
    new_text = new_first_line + "\n" + rest
    try:
        target.write_text(new_text, encoding="utf-8")
        logger.info("MainMenu.lua loadOnStart set to %s", desired)
    except OSError as exc:
        logger.warning("Failed to write MainMenu.lua loadOnStart toggle: %s", exc)

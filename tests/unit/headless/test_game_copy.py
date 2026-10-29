"""Tests for autoplay.headless.game_copy and the bridge pointing its batches at the copy."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from autoplay.headless import game_copy
from autoplay.headless.batches import Batch, latest_batch
from autoplay.headless.bridge import Bridge
from autoplay.headless.config import HeadlessConfig
from tests.unit.headless.test_bridge import FakeQueue

MODPACK = "VP_MODPACK_9_NEUTRALS"
DLL_REL = Path("Assets/DLC") / MODPACK / "Mods" / "(1) Community Patch" / game_copy.DLL_NAME


def _touch(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def steam(tmp_path: Path) -> Path:
    """A fake Steam game folder with the modpack, an official DLC, another modpack and some media."""
    game = tmp_path / "steam" / game_copy.GAME_FOLDER_NAME
    _touch(game / "lua51_Win32.dll")
    _touch(game / "CivilizationV_DX11.exe")
    _touch(game / "Locale" / "icudt44l.dat")
    _touch(game / "Assets" / "Maps" / "Continents.lua")
    _touch(game / "Assets" / "UI" / "Art" / "icon.dds")
    _touch(game / "Assets" / "DLC" / "Expansion2" / "Expansion2.Civ5Pkg")
    _touch(game / "Assets" / "DLC" / "Expansion2" / "Sounds" / "music.MP3")
    _touch(game / DLL_REL, "patched")
    _touch(game / DLL_REL.with_name(game_copy.DLL_NAME + ".orig"), "official")
    _touch(game / "Assets" / "DLC" / MODPACK / "Override" / "CoreDefines.xml")
    _touch(game / "Assets" / "DLC" / "VP_MODPACK_8" / "Override" / "CoreDefines.xml")
    _touch(game / "Assets" / "DLC" / "MP_AUTOPLAY_VP_7" / "Override" / "CoreDefines.xml")
    _touch(game / "Assets" / "DLC" / ".idea" / "workspace.xml")
    return game


def test_prepare_copies_what_the_host_reads(steam: Path, tmp_path: Path) -> None:
    paths = game_copy.prepare(steam, MODPACK, tmp_path / "copies")

    dest = tmp_path / "copies" / MODPACK / game_copy.GAME_FOLDER_NAME
    assert paths == game_copy.GamePaths(dest, dest / DLL_REL)
    assert (dest / DLL_REL).read_text(encoding="utf-8") == "patched"
    for kept in ("lua51_Win32.dll", "Locale/icudt44l.dat", "Assets/Maps/Continents.lua"):
        assert (dest / kept).is_file(), kept
    assert (dest / "Assets/DLC/Expansion2/Expansion2.Civ5Pkg").is_file()
    assert sorted(p.name for p in (dest / "Assets/DLC").iterdir()) == ["Expansion2", MODPACK]
    assert not (dest / "CivilizationV_DX11.exe").exists()
    assert not list(dest.rglob("*.dds")) and not list(dest.rglob("*.MP3"))
    marker = json.loads((dest / game_copy.MARKER_FILENAME).read_text(encoding="utf-8"))
    assert marker["modpack"] == MODPACK


def test_prepare_reuses_the_copy_without_the_source(steam: Path, tmp_path: Path) -> None:
    first = game_copy.prepare(steam, MODPACK, tmp_path / "copies")
    shutil.rmtree(steam / "Assets" / "DLC" / MODPACK)  # the user removed the modpack from Steam

    assert game_copy.prepare(steam, MODPACK, tmp_path / "copies") == first


def test_prepare_redoes_an_unfinished_copy(steam: Path, tmp_path: Path) -> None:
    dest = game_copy.copy_dir(tmp_path / "copies", MODPACK)
    _touch(dest / "stale.txt")  # no marker: the copy was interrupted

    paths = game_copy.prepare(steam, MODPACK, tmp_path / "copies")

    assert paths.dll.is_file() and not (dest / "stale.txt").exists()


def test_prepare_without_copy_or_source_fails(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no copy of the game"):
        game_copy.prepare(tmp_path / "nowhere", MODPACK, tmp_path / "copies")


async def test_bridge_points_new_and_resumed_batches_at_the_copy(
    cfg: HeadlessConfig, steam: Path, batch: Batch
) -> None:
    cfg = cfg.model_copy(update={"modpack_folder": MODPACK, "game_source_dir": steam})
    queue = FakeQueue()
    bridge = Bridge(cfg, "http://127.0.0.1:7000", queue=queue)
    bridge.prepare_game()

    assert await bridge.start() == "started"

    assert queue.starts == [batch.name]  # the batch written before the copy existed is resumed
    defaults = latest_batch(cfg.work_dir).queue()["defaults"]
    assert Path(defaults["gameDir"]) == cfg.game_copy_root.resolve() / MODPACK / game_copy.GAME_FOLDER_NAME
    assert Path(defaults["dll"]) == Path(defaults["gameDir"]) / DLL_REL


async def test_bridge_without_modpack_folder_leaves_paths_to_c5h(cfg: HeadlessConfig) -> None:
    bridge = Bridge(cfg, "http://127.0.0.1:7000", queue=FakeQueue())
    bridge.prepare_game()

    await bridge.start()

    defaults = latest_batch(cfg.work_dir).queue()["defaults"]
    assert "gameDir" not in defaults and "dll" not in defaults

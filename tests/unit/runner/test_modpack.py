"""Tests for autoplay.runner.modpack."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from autoplay.runner.modpack import (
    ModpackZipError,
    install_modpack_zip,
    peek_modpack_version,
)


def _build_zip(zip_path: Path, file_map: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(zip_path, "w") as zf:
        for arcname, data in file_map.items():
            zf.writestr(arcname, data)
    return zip_path


class TestPeekModpackVersion:
    def test_single_match(self, tmp_path: Path) -> None:
        z = _build_zip(
            tmp_path / "mp.zip",
            {
                "MP_AUTOPLAY_VP_5_2_3/some_file.txt": b"x",
                "MP_AUTOPLAY_VP_5_2_3/sub/other.txt": b"y",
            },
        )
        assert peek_modpack_version(z) == "MP_AUTOPLAY_VP_5_2_3"

    def test_zero_matches(self, tmp_path: Path) -> None:
        z = _build_zip(tmp_path / "mp.zip", {"some_other_dir/x.txt": b"x"})
        with pytest.raises(ModpackZipError):
            peek_modpack_version(z)

    def test_two_matches(self, tmp_path: Path) -> None:
        z = _build_zip(
            tmp_path / "mp.zip",
            {
                "MP_AUTOPLAY_VP_1/x.txt": b"x",
                "MP_AUTOPLAY_VP_2/y.txt": b"y",
            },
        )
        with pytest.raises(ModpackZipError):
            peek_modpack_version(z)


class TestInstallModpackZip:
    def test_extracts_and_returns_target(
        self, tmp_path: Path, tmp_install_dir: Path
    ) -> None:
        z = _build_zip(
            tmp_path / "mp.zip",
            {
                "MP_AUTOPLAY_VP_9_0_0/manifest.txt": b"hello",
                "MP_AUTOPLAY_VP_9_0_0/sub/other.txt": b"world",
            },
        )
        target = install_modpack_zip(z, tmp_install_dir)
        assert target == "MP_AUTOPLAY_VP_9_0_0"
        installed = tmp_install_dir / "Assets" / "DLC" / "MP_AUTOPLAY_VP_9_0_0"
        assert installed.is_dir()
        assert (installed / "manifest.txt").read_bytes() == b"hello"
        assert (installed / "sub" / "other.txt").read_bytes() == b"world"

    def test_purges_existing_modpacks(
        self, tmp_path: Path, tmp_install_dir: Path
    ) -> None:
        dlc = tmp_install_dir / "Assets" / "DLC"
        # Pre-existing autoplay modpack should be purged.
        (dlc / "MP_AUTOPLAY_VP_OLD").mkdir()
        (dlc / "MP_AUTOPLAY_VP_OLD" / "stale.txt").write_text("stale")
        # Non-autoplay folder must NOT be purged.
        (dlc / "DLC_Polynesia").mkdir()
        (dlc / "DLC_Polynesia" / "keep.txt").write_text("keep")

        z = _build_zip(
            tmp_path / "mp.zip",
            {"MP_AUTOPLAY_VP_NEW/file.txt": b"new"},
        )
        install_modpack_zip(z, tmp_install_dir)

        assert not (dlc / "MP_AUTOPLAY_VP_OLD").exists()
        assert (dlc / "DLC_Polynesia" / "keep.txt").read_text() == "keep"
        assert (dlc / "MP_AUTOPLAY_VP_NEW" / "file.txt").read_bytes() == b"new"

    def test_rejects_invalid_zip_top_level(
        self, tmp_path: Path, tmp_install_dir: Path
    ) -> None:
        z = _build_zip(tmp_path / "mp.zip", {"random_top/x.txt": b"x"})
        with pytest.raises(ModpackZipError):
            install_modpack_zip(z, tmp_install_dir)

    def test_missing_assets_dir_raises(self, tmp_path: Path) -> None:
        # Install dir without Assets — install should refuse.
        bad_install = tmp_path / "no_assets"
        bad_install.mkdir()
        z = _build_zip(tmp_path / "mp.zip", {"MP_AUTOPLAY_VP_X/x": b"x"})
        with pytest.raises(FileNotFoundError):
            install_modpack_zip(z, bad_install)

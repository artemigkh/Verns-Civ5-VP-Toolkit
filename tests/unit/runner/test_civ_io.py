"""Tests for autoplay.runner.civ_io."""

from __future__ import annotations

from pathlib import Path

from autoplay.runner.civ_io import (
    detect_installed_modpack,
    find_most_recent_autosave,
    game_result_present,
    parse_modpack_version,
    read_current_turn,
)


class TestDetectInstalledModpack:
    def test_no_dlc_dir(self, tmp_path: Path) -> None:
        # Just an empty install dir, no Assets/DLC.
        assert detect_installed_modpack(tmp_path) is None

    def test_no_match(self, tmp_install_dir: Path) -> None:
        # tmp_install_dir has empty DLC.
        assert detect_installed_modpack(tmp_install_dir) is None

    def test_single_match(self, tmp_install_dir: Path) -> None:
        (tmp_install_dir / "Assets" / "DLC" / "MP_AUTOPLAY_VP_5_2_3").mkdir()
        assert detect_installed_modpack(tmp_install_dir) == "MP_AUTOPLAY_VP_5_2_3"

    def test_returns_alphabetic_last_when_many(self, tmp_install_dir: Path) -> None:
        for v in ("MP_AUTOPLAY_VP_5_2_3", "MP_AUTOPLAY_VP_5_2_4", "MP_AUTOPLAY_VP_5_2_2"):
            (tmp_install_dir / "Assets" / "DLC" / v).mkdir()
        assert detect_installed_modpack(tmp_install_dir) == "MP_AUTOPLAY_VP_5_2_4"

    def test_ignores_non_modpack_folders(self, tmp_install_dir: Path) -> None:
        (tmp_install_dir / "Assets" / "DLC" / "DLC_Polynesia").mkdir()
        (tmp_install_dir / "Assets" / "DLC" / "MP_AUTOPLAY_VP_1").mkdir()
        assert detect_installed_modpack(tmp_install_dir) == "MP_AUTOPLAY_VP_1"

    def test_ignores_files_only_dirs(self, tmp_install_dir: Path) -> None:
        # A file with the prefix shouldn't count.
        (tmp_install_dir / "Assets" / "DLC" / "MP_AUTOPLAY_VP_X").write_text("not a dir")
        assert detect_installed_modpack(tmp_install_dir) is None


class TestParseModpackVersion:
    def test_extracts_version(self) -> None:
        assert parse_modpack_version("MP_AUTOPLAY_VP_5_2_3") == "5_2_3"

    def test_returns_none_on_no_match(self) -> None:
        assert parse_modpack_version("NotAModpack") is None
        assert parse_modpack_version("") is None


class TestReadCurrentTurn:
    def test_missing_file(self, tmp_user_dir: Path) -> None:
        assert read_current_turn(tmp_user_dir / "Logs") is None

    def test_header_only(self, tmp_user_dir: Path) -> None:
        (tmp_user_dir / "Logs" / "WorldState_Log.csv").write_text(
            "Turn,Player,Other\n", encoding="utf-8"
        )
        assert read_current_turn(tmp_user_dir / "Logs") is None

    def test_returns_last_turn(self, tmp_user_dir: Path) -> None:
        (tmp_user_dir / "Logs" / "WorldState_Log.csv").write_text(
            "Turn,Player,Other\n1,A,x\n2,A,x\n3,A,x\n", encoding="utf-8"
        )
        assert read_current_turn(tmp_user_dir / "Logs") == 3

    def test_skips_non_integer_rows(self, tmp_user_dir: Path) -> None:
        (tmp_user_dir / "Logs" / "WorldState_Log.csv").write_text(
            "Turn,Player\n1,A\nbogus,A\n7,A\nfoo,A\n", encoding="utf-8"
        )
        assert read_current_turn(tmp_user_dir / "Logs") == 7

    def test_blank_turn_cell_ignored(self, tmp_user_dir: Path) -> None:
        (tmp_user_dir / "Logs" / "WorldState_Log.csv").write_text(
            "Turn,Player\n1,A\n,B\n2,C\n", encoding="utf-8"
        )
        assert read_current_turn(tmp_user_dir / "Logs") == 2


class TestGameResultPresent:
    def test_absent(self, tmp_user_dir: Path) -> None:
        assert game_result_present(tmp_user_dir / "Logs") is False

    def test_present(self, tmp_user_dir: Path) -> None:
        (tmp_user_dir / "Logs" / "GameResult_Log.csv").write_text("x", encoding="utf-8")
        assert game_result_present(tmp_user_dir / "Logs") is True


class TestFindMostRecentAutosave:
    def test_missing_dir(self, tmp_path: Path) -> None:
        assert find_most_recent_autosave(tmp_path / "no_user") is None

    def test_empty(self, tmp_user_dir: Path) -> None:
        assert find_most_recent_autosave(tmp_user_dir) is None

    def test_single_save(self, tmp_user_dir: Path) -> None:
        save = tmp_user_dir / "Saves" / "single" / "auto" / "auto_001.Civ5Save"
        save.write_bytes(b"sav")
        assert find_most_recent_autosave(tmp_user_dir) == save

    def test_picks_latest_mtime(self, tmp_user_dir: Path) -> None:
        d = tmp_user_dir / "Saves" / "single" / "auto"
        a = d / "auto_001.Civ5Save"
        b = d / "auto_002.Civ5Save"
        a.write_bytes(b"a")
        b.write_bytes(b"b")
        import os as _os
        _os.utime(a, (1000.0, 1000.0))
        _os.utime(b, (2000.0, 2000.0))
        assert find_most_recent_autosave(tmp_user_dir) == b
        # Reverse mtimes — picks the other one.
        _os.utime(a, (3000.0, 3000.0))
        assert find_most_recent_autosave(tmp_user_dir) == a

    def test_ignores_non_civ5save(self, tmp_user_dir: Path) -> None:
        d = tmp_user_dir / "Saves" / "single" / "auto"
        (d / "junk.txt").write_text("x")
        assert find_most_recent_autosave(tmp_user_dir) is None

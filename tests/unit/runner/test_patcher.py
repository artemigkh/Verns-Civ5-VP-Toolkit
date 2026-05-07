"""Tests for autoplay.runner.patcher (focusing on set_load_on_start)."""

from __future__ import annotations

from pathlib import Path

from autoplay.runner.patcher import install_patched_files, set_load_on_start


class TestSetLoadOnStart:
    def _read(self, p: Path) -> str:
        return p.read_text(encoding="utf-8")

    def test_toggles_false_to_true(self, tmp_install_dir: Path) -> None:
        target = tmp_install_dir / "Assets" / "UI" / "FrontEnd" / "MainMenu.lua"
        # Fixture writes "local loadOnStart = false;\n..."
        set_load_on_start(tmp_install_dir, enabled=True)
        text = self._read(target)
        assert text.startswith("local loadOnStart = true;\n")
        # Rest of file preserved exactly.
        assert "-- rest of the file" in text
        assert "function Foo() end" in text

    def test_toggles_true_to_false(self, tmp_install_dir: Path) -> None:
        target = tmp_install_dir / "Assets" / "UI" / "FrontEnd" / "MainMenu.lua"
        target.write_text(
            "local loadOnStart = true;\nrest of file\n", encoding="utf-8"
        )
        set_load_on_start(tmp_install_dir, enabled=False)
        assert self._read(target).startswith("local loadOnStart = false;\n")

    def test_idempotent_no_change(self, tmp_install_dir: Path) -> None:
        target = tmp_install_dir / "Assets" / "UI" / "FrontEnd" / "MainMenu.lua"
        before = self._read(target)
        set_load_on_start(tmp_install_dir, enabled=False)
        assert self._read(target) == before

    def test_skips_when_first_line_unexpected(self, tmp_install_dir: Path) -> None:
        target = tmp_install_dir / "Assets" / "UI" / "FrontEnd" / "MainMenu.lua"
        target.write_text("-- some other first line\nbody\n", encoding="utf-8")
        set_load_on_start(tmp_install_dir, enabled=True)
        # Untouched.
        assert self._read(target).startswith("-- some other first line")

    def test_missing_file_is_silent(self, tmp_install_dir: Path) -> None:
        (tmp_install_dir / "Assets" / "UI" / "FrontEnd" / "MainMenu.lua").unlink()
        # Should not raise.
        set_load_on_start(tmp_install_dir, enabled=True)


class TestInstallPatchedFiles:
    def test_creates_dest_dirs_and_copies(
        self, tmp_install_dir: Path, tmp_user_dir: Path, monkeypatch
    ) -> None:
        # Create a fake patched_files dir with all expected sources.
        from autoplay.runner import patcher

        fake_pf = tmp_install_dir.parent / "fake_patched"
        fake_pf.mkdir()
        names = [
            "config.ini",
            "UserSettings.ini",
            "GraphicsSettingsDX11.ini",
            "lua51_Win32.dll",
            "Communitu_79a.lua",
            "FrontEnd.lua",
            "MainMenu.lua",
            "RunAutoplayGame.lua",
        ]
        for n in names:
            (fake_pf / n).write_bytes(b"content-" + n.encode())
        monkeypatch.setattr(patcher, "_PATCHED_FILES_DIR", fake_pf)

        install_patched_files(
            tmp_user_dir, tmp_install_dir, use_blank_d3d9_proxy=False
        )

        assert (tmp_user_dir / "config.ini").read_bytes() == b"content-config.ini"
        assert (tmp_install_dir / "lua51_Win32.dll").read_bytes() == b"content-lua51_Win32.dll"
        assert (
            tmp_install_dir / "Assets" / "Maps" / "Communitu_79a.lua"
        ).read_bytes() == b"content-Communitu_79a.lua"
        assert (
            tmp_install_dir / "Assets" / "Automation" / "RunAutoplayGame.lua"
        ).read_bytes() == b"content-RunAutoplayGame.lua"

    def test_removes_d3d9_when_proxy_disabled(
        self, tmp_install_dir: Path, tmp_user_dir: Path, monkeypatch
    ) -> None:
        from autoplay.runner import patcher

        fake_pf = tmp_install_dir.parent / "fake_patched2"
        fake_pf.mkdir()
        for n in [
            "config.ini", "UserSettings.ini", "GraphicsSettingsDX11.ini",
            "lua51_Win32.dll", "Communitu_79a.lua", "FrontEnd.lua",
            "MainMenu.lua", "RunAutoplayGame.lua",
        ]:
            (fake_pf / n).write_bytes(b"x")
        monkeypatch.setattr(patcher, "_PATCHED_FILES_DIR", fake_pf)

        # Pre-existing d3d9.dll in install dir.
        (tmp_install_dir / "d3d9.dll").write_bytes(b"old proxy")
        install_patched_files(tmp_user_dir, tmp_install_dir, use_blank_d3d9_proxy=False)
        assert not (tmp_install_dir / "d3d9.dll").exists()

    def test_installs_d3d9_when_proxy_enabled(
        self, tmp_install_dir: Path, tmp_user_dir: Path, monkeypatch
    ) -> None:
        from autoplay.runner import patcher

        fake_pf = tmp_install_dir.parent / "fake_patched3"
        fake_pf.mkdir()
        for n in [
            "config.ini", "UserSettings.ini", "GraphicsSettingsDX11.ini",
            "lua51_Win32.dll", "Communitu_79a.lua", "FrontEnd.lua",
            "MainMenu.lua", "RunAutoplayGame.lua", "d3d9.dll",
        ]:
            (fake_pf / n).write_bytes(b"d3d9-" + n.encode())
        monkeypatch.setattr(patcher, "_PATCHED_FILES_DIR", fake_pf)

        install_patched_files(tmp_user_dir, tmp_install_dir, use_blank_d3d9_proxy=True)
        assert (tmp_install_dir / "d3d9.dll").read_bytes() == b"d3d9-d3d9.dll"

    def test_missing_source_is_logged_and_skipped(
        self, tmp_install_dir: Path, tmp_user_dir: Path, monkeypatch
    ) -> None:
        from autoplay.runner import patcher

        fake_pf = tmp_install_dir.parent / "fake_patched4"
        fake_pf.mkdir()
        # Only create a couple of files; the rest are missing.
        (fake_pf / "config.ini").write_bytes(b"ok")
        monkeypatch.setattr(patcher, "_PATCHED_FILES_DIR", fake_pf)
        # Should not raise.
        install_patched_files(tmp_user_dir, tmp_install_dir, use_blank_d3d9_proxy=False)
        assert (tmp_user_dir / "config.ini").read_bytes() == b"ok"
        assert not (tmp_install_dir / "lua51_Win32.dll").exists()

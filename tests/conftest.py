"""Shared pytest fixtures for autoplay tests.

Conventions:

* All filesystem fixtures use ``tmp_path`` (pytest builtin). pyfakefs is
  reserved for tests that need to manipulate ``shutil.disk_usage`` or
  fake absolute Windows paths.
* Every fixture that touches ``autoplay.runner.state._STATE`` resets it,
  since it is a module-level singleton.
* Subprocess / psutil / ctypes are mocked via ``unittest.mock.patch`` —
  no real Civ5 binary is launched.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock

import pytest

# Make sure the project root is importable when pytest is invoked from
# arbitrary cwd (works regardless of how it was launched).
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# --------------------------------------------------------------------------
# Civ5 directory layout fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def tmp_user_dir(tmp_path: Path) -> Path:
    """Fake Civ5 USER_DIR with the standard subdirs the runner expects."""
    user_dir = tmp_path / "user"
    (user_dir / "Logs").mkdir(parents=True)
    (user_dir / "Saves" / "single" / "auto").mkdir(parents=True)
    return user_dir


@pytest.fixture
def tmp_install_dir(tmp_path: Path) -> Path:
    """Fake Civ5 INSTALL_DIR with the patched-files target tree + a stub exe.

    Includes a stub ``MainMenu.lua`` that the patcher's ``set_load_on_start``
    expects (its first line must mention ``loadOnStart``).
    """
    install_dir = tmp_path / "install"
    (install_dir / "Assets" / "DLC").mkdir(parents=True)
    (install_dir / "Assets" / "UI" / "FrontEnd").mkdir(parents=True)
    (install_dir / "Assets" / "Maps").mkdir(parents=True)
    (install_dir / "Assets" / "Automation").mkdir(parents=True)
    # Stub exe file so PathBox.is_file() succeeds without a real binary.
    (install_dir / "CivilizationV_DX11.exe").write_bytes(b"MZ\x90fake\x00\x00")
    # MainMenu.lua first line must mention loadOnStart for the patcher toggle.
    (install_dir / "Assets" / "UI" / "FrontEnd" / "MainMenu.lua").write_text(
        "local loadOnStart = false;\n"
        "-- rest of the file\n"
        "function Foo() end\n",
        encoding="utf-8",
    )
    return install_dir


@pytest.fixture
def tmp_storage_root(tmp_path: Path) -> Path:
    """Hypervisor storage root."""
    storage = tmp_path / "storage"
    storage.mkdir()
    return storage


# --------------------------------------------------------------------------
# Config builders
# --------------------------------------------------------------------------


@pytest.fixture
def runner_config(tmp_user_dir: Path, tmp_install_dir: Path, tmp_path: Path):
    """Build a RunnerConfig pointed at the temp dirs.

    Bypasses env loading so tests are isolated from the developer's
    ``AUTOPLAY_RUNNER_*`` shell exports.
    """
    from autoplay.runner.config import RunnerConfig

    return RunnerConfig(
        hypervisor_url="http://hv.test",
        user_dir=tmp_user_dir,
        install_dir=tmp_install_dir,
        startup_timeout_sec=5,
        turn_timeout_sec=5,
        registration_timeout_sec=5,
        heartbeat_interval_sec=0.01,
        log_ignore_patterns=["CitySites_*", "TradePlayerRouteLog_*"],
        recovery_max_attempts=2,
        recovery_attempt_timeout_sec=5,
        pending_uploads_dir=tmp_path / "pending",
        crash_handler_poll_ms=1000,
        use_blank_d3d9_proxy=False,
        bind_host="127.0.0.1",
    )


@pytest.fixture
def hv_config(tmp_storage_root: Path):
    from autoplay.hypervisor.config import HypervisorConfig

    return HypervisorConfig(
        storage_root=tmp_storage_root,
        port=5000,
        host="127.0.0.1",
        runner_timeout_sec=120,
    )


# --------------------------------------------------------------------------
# Runner state singleton reset
# --------------------------------------------------------------------------


@pytest.fixture
def fresh_runner_state():
    """Reset the runner state singleton before and after the test."""
    import autoplay.runner.state as st

    saved = st._STATE
    st._STATE = None
    state = st.get_state()
    yield state
    st._STATE = saved


# --------------------------------------------------------------------------
# Mock subprocess.Popen
# --------------------------------------------------------------------------


class FakePopen:
    """Minimal ``subprocess.Popen`` stand-in for game_controller tests."""

    def __init__(self, pid: int = 4242, alive: bool = True) -> None:
        self.pid = pid
        self.returncode: int | None = None if alive else 0
        self._alive = alive

    def poll(self) -> int | None:
        return None if self._alive else (self.returncode or 0)

    def die(self, returncode: int = 1) -> None:
        self._alive = False
        self.returncode = returncode

    # Match the parts of subprocess.Popen[bytes] the controller touches.
    def terminate(self) -> None:  # pragma: no cover - controller uses psutil
        self.die()

    def kill(self) -> None:  # pragma: no cover
        self.die(returncode=137)

    def wait(self, timeout: float | None = None) -> int:
        self.die()
        return self.returncode or 0


@pytest.fixture
def fake_popen() -> FakePopen:
    return FakePopen()


# --------------------------------------------------------------------------
# Mock psutil.Process for _kill_process_tree
# --------------------------------------------------------------------------


@pytest.fixture
def mock_psutil(monkeypatch):
    """Patch psutil.Process / wait_procs to no-op happy path."""
    import autoplay.runner.game_controller as gc

    fake_proc = MagicMock()
    fake_proc.children.return_value = []
    fake_proc.terminate = MagicMock()
    fake_proc.kill = MagicMock()

    fake_psutil = MagicMock()
    fake_psutil.Process = MagicMock(return_value=fake_proc)
    fake_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
    fake_psutil.wait_procs = MagicMock(return_value=([fake_proc], []))

    monkeypatch.setattr(gc, "psutil", fake_psutil)
    return fake_psutil


# --------------------------------------------------------------------------
# Speed up sleeps in retry loops
# --------------------------------------------------------------------------


@pytest.fixture
def fast_sleep(monkeypatch):
    """Patch time.sleep AND asyncio.sleep to no-ops in a few hot modules."""
    import asyncio
    import time

    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)

    async def _no_sleep(_t=0):  # noqa: ARG001
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)


# --------------------------------------------------------------------------
# Fake clock helper
# --------------------------------------------------------------------------


class Clock:
    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self._t = start

    def time(self) -> float:
        return self._t

    def advance(self, dt: float) -> None:
        self._t += dt


@pytest.fixture
def clock() -> Clock:
    return Clock()


# --------------------------------------------------------------------------
# Lock helper for state inspection
# --------------------------------------------------------------------------


@pytest.fixture
def fresh_lock() -> threading.Lock:
    return threading.Lock()

"""Tests for GameController public lifecycle (start / stop / state machine).

These avoid spawning a real Civ5 by patching:
* ``subprocess.Popen`` -> FakePopen
* ``_kill_process_tree`` -> no-op
* ``set_load_on_start`` -> recording mock
* ``crash_handler_window_present`` -> False
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from autoplay.common import RunnerState
from autoplay.runner import game_controller as gc
from autoplay.runner.game_controller import (
    GameAlreadyRunningError,
    GameController,
    NoInstallError,
    NoModpackError,
)
from autoplay.runner.state import RunnerGlobalState
from tests.conftest import FakePopen


@pytest.fixture
def state() -> RunnerGlobalState:
    s = RunnerGlobalState()
    s.modpack = "MP_AUTOPLAY_VP_X"
    s.url = "http://r.test:1234"
    return s


@pytest.fixture
def patched(monkeypatch):
    """Patch out subprocess + side-effecty helpers for fast, deterministic tests."""
    popen = FakePopen()
    monkeypatch.setattr(
        subprocess, "Popen", MagicMock(return_value=popen)
    )
    monkeypatch.setattr(gc, "_kill_process_tree", MagicMock())
    monkeypatch.setattr(gc, "set_load_on_start", MagicMock())
    monkeypatch.setattr(gc, "crash_handler_window_present", lambda: False)
    return popen


# --------------------------------------------------------------------------
# .start()
# --------------------------------------------------------------------------


async def test_start_happy_path(runner_config, state, patched, monkeypatch) -> None:
    # Cancel the monitor task immediately so test doesn't hang.
    monkeypatch.setattr(gc, "_MONITOR_POLL_SEC", 0.01)

    ctrl = GameController(runner_config, state)
    game_id = await ctrl.start()
    assert state.state in {RunnerState.starting, RunnerState.running}
    assert state.current_game_id == game_id
    assert state.current_game_start_time is not None
    assert ctrl.is_running

    # Cleanup so the monitor task doesn't leak into other tests.
    await ctrl.stop()


async def test_start_raises_when_install_dir_missing(
    runner_config, state, tmp_path
) -> None:
    runner_config.install_dir = tmp_path / "no_such_install"
    ctrl = GameController(runner_config, state)
    with pytest.raises(NoInstallError):
        await ctrl.start()


async def test_start_raises_when_no_modpack(runner_config, state, patched) -> None:
    state.modpack = None
    ctrl = GameController(runner_config, state)
    with pytest.raises(NoModpackError):
        await ctrl.start()


async def test_start_raises_when_already_running(
    runner_config, state, patched, monkeypatch
) -> None:
    monkeypatch.setattr(gc, "_MONITOR_POLL_SEC", 0.01)
    ctrl = GameController(runner_config, state)
    await ctrl.start()
    try:
        with pytest.raises(GameAlreadyRunningError):
            await ctrl.start()
    finally:
        await ctrl.stop()


async def test_start_calls_set_load_on_start_false(
    runner_config, state, patched, monkeypatch
) -> None:
    monkeypatch.setattr(gc, "_MONITOR_POLL_SEC", 0.01)
    ctrl = GameController(runner_config, state)
    await ctrl.start()
    try:
        gc.set_load_on_start.assert_called()
        # Last call should have enabled=False (fresh start).
        kwargs = gc.set_load_on_start.call_args.kwargs
        assert kwargs.get("enabled") is False
    finally:
        await ctrl.stop()


# --------------------------------------------------------------------------
# .stop()
# --------------------------------------------------------------------------


async def test_stop_when_idle_is_noop(runner_config, state, patched) -> None:
    ctrl = GameController(runner_config, state)
    result = await ctrl.stop()
    assert result is False
    assert state.state == RunnerState.idle


async def test_stop_after_start(runner_config, state, patched, monkeypatch) -> None:
    monkeypatch.setattr(gc, "_MONITOR_POLL_SEC", 0.01)
    ctrl = GameController(runner_config, state)
    await ctrl.start()
    state.is_scheduling_games = True
    result = await ctrl.stop()
    assert result is True
    assert state.state == RunnerState.idle
    assert state.current_game_id is None
    assert state.is_scheduling_games is False
    # Process tree kill was called.
    assert gc._kill_process_tree.called


async def test_stop_clears_logs_and_segments(
    runner_config, state, patched, monkeypatch
) -> None:
    monkeypatch.setattr(gc, "_MONITOR_POLL_SEC", 0.01)
    # Pre-populate logs and segments.
    logs = runner_config.user_dir / "Logs"
    (logs / "stale.csv").write_text("x")
    seg_root = runner_config.user_dir / "AutoplayLogSegments" / "old_game"
    seg_root.mkdir(parents=True)
    (seg_root / "x.csv").write_text("y")

    ctrl = GameController(runner_config, state)
    await ctrl.start()
    await ctrl.stop()
    # Logs dir should be empty now.
    assert list(logs.iterdir()) == []
    # Segments root removed.
    assert not (runner_config.user_dir / "AutoplayLogSegments").exists()


# --------------------------------------------------------------------------
# is_running property
# --------------------------------------------------------------------------


async def test_is_running_false_initially(runner_config, state) -> None:
    ctrl = GameController(runner_config, state)
    assert ctrl.is_running is False


# --------------------------------------------------------------------------
# trigger_deferred_reschedule (no-op paths only — full flow in integration)
# --------------------------------------------------------------------------


def test_trigger_deferred_reschedule_noop_when_not_pending(
    runner_config, state
) -> None:
    state.pending_reschedule = False
    ctrl = GameController(runner_config, state)
    # Should not raise / not start anything.
    ctrl.trigger_deferred_reschedule()
    assert ctrl.is_running is False


def test_trigger_deferred_reschedule_clears_when_scheduling_off(
    runner_config, state
) -> None:
    state.pending_reschedule = True
    state.is_scheduling_games = False
    ctrl = GameController(runner_config, state)
    ctrl.trigger_deferred_reschedule()
    assert state.pending_reschedule is False


# --------------------------------------------------------------------------
# _wait_for_exe
# --------------------------------------------------------------------------


async def test_wait_for_exe_succeeds_immediately(runner_config, state) -> None:
    ctrl = GameController(runner_config, state)
    exe = await ctrl._wait_for_exe(timeout_sec=2)
    assert exe.is_file()


async def test_wait_for_exe_times_out_when_missing(
    runner_config, state, monkeypatch
) -> None:
    # Remove the stub exe.
    (runner_config.install_dir / "CivilizationV_DX11.exe").unlink()
    monkeypatch.setattr(gc, "_EXE_WAIT_POLL_SEC", 0.01)
    ctrl = GameController(runner_config, state)
    with pytest.raises(NoInstallError):
        await ctrl._wait_for_exe(timeout_sec=0.1)

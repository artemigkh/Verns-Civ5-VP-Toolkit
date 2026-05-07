"""Integration tests for game lifecycle: start/stop/scheduling combined.

Uses fakes for subprocess + helpers but exercises the GameController +
RunnerGlobalState wiring together to verify the state-machine transitions
and clean teardown.
"""

from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import MagicMock

import pytest

from autoplay.common import RunnerState
from autoplay.runner import game_controller as gc
from autoplay.runner.game_controller import GameController
from autoplay.runner.state import RunnerGlobalState
from tests.conftest import FakePopen


@pytest.fixture
def state() -> RunnerGlobalState:
    s = RunnerGlobalState()
    s.modpack = "MP_AUTOPLAY_VP_TEST"
    s.url = "http://r.test:1234"
    return s


@pytest.fixture
def patches(monkeypatch):
    popen = FakePopen()
    monkeypatch.setattr(subprocess, "Popen", MagicMock(return_value=popen))
    monkeypatch.setattr(gc, "_kill_process_tree", MagicMock())
    monkeypatch.setattr(gc, "set_load_on_start", MagicMock())
    monkeypatch.setattr(gc, "crash_handler_window_present", lambda: False)
    monkeypatch.setattr(gc, "_MONITOR_POLL_SEC", 0.01)
    return popen


async def test_start_stop_sequence_resets_state(runner_config, state, patches) -> None:
    ctrl = GameController(runner_config, state)
    gid = await ctrl.start()
    assert state.current_game_id == gid
    assert ctrl.is_running

    stopped = await ctrl.stop()
    assert stopped is True
    assert ctrl.is_running is False
    assert state.state == RunnerState.idle
    assert state.current_game_id is None


async def test_start_creates_logs_and_segments_layout(
    runner_config, state, patches
) -> None:
    # Pre-populate logs and segments with stale data; start must clear them.
    logs = runner_config.user_dir / "Logs"
    (logs / "stale.csv").write_text("old")
    seg = runner_config.user_dir / "AutoplayLogSegments" / "older_game"
    seg.mkdir(parents=True)
    (seg / "x.csv").write_text("old-seg")

    ctrl = GameController(runner_config, state)
    await ctrl.start()
    try:
        assert list(logs.iterdir()) == []
        # Segments root removed.
        assert not (runner_config.user_dir / "AutoplayLogSegments").exists()
    finally:
        await ctrl.stop()


async def test_consecutive_start_calls_rejected(runner_config, state, patches) -> None:
    from autoplay.runner.game_controller import GameAlreadyRunningError

    ctrl = GameController(runner_config, state)
    await ctrl.start()
    try:
        with pytest.raises(GameAlreadyRunningError):
            await ctrl.start()
    finally:
        await ctrl.stop()


async def test_stop_disables_scheduling(runner_config, state, patches) -> None:
    ctrl = GameController(runner_config, state)
    await ctrl.start()
    state.is_scheduling_games = True
    await ctrl.stop()
    assert state.is_scheduling_games is False

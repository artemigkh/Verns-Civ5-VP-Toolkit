"""Tests for autoplay.runner.state."""

from __future__ import annotations

import threading

from autoplay.common import RunnerState
from autoplay.runner.state import RunnerGlobalState, get_state


def test_singleton_returns_same_instance(fresh_runner_state: RunnerGlobalState) -> None:
    s1 = get_state()
    s2 = get_state()
    assert s1 is s2 is fresh_runner_state


def test_default_state_is_idle(fresh_runner_state: RunnerGlobalState) -> None:
    assert fresh_runner_state.state == RunnerState.idle
    assert fresh_runner_state.current_game_id is None
    assert fresh_runner_state.is_scheduling_games is False
    assert fresh_runner_state.uuid  # populated automatically


def test_snapshot_returns_copy(fresh_runner_state: RunnerGlobalState) -> None:
    fresh_runner_state.modpack = "MP_AUTOPLAY_VP_1"
    fresh_runner_state.state = RunnerState.running
    snap = fresh_runner_state.snapshot()
    assert snap is not fresh_runner_state
    assert snap.modpack == "MP_AUTOPLAY_VP_1"
    assert snap.state == RunnerState.running
    # Mutating the snapshot doesn't bleed back.
    snap.modpack = "OTHER"
    assert fresh_runner_state.modpack == "MP_AUTOPLAY_VP_1"


def test_concurrent_writers_dont_corrupt(fresh_runner_state: RunnerGlobalState) -> None:
    """100 threads incrementing turn under the lock — all increments visible."""
    state = fresh_runner_state
    state.current_game_turn = 0

    def _bump() -> None:
        for _ in range(100):
            with state.lock:
                state.current_game_turn = (state.current_game_turn or 0) + 1

    threads = [threading.Thread(target=_bump) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state.current_game_turn == 1000

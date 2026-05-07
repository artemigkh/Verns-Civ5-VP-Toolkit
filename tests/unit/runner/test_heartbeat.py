"""Tests for autoplay.runner.heartbeat.heartbeat_loop."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from autoplay.common import RunnerState
from autoplay.runner.heartbeat import heartbeat_loop
from autoplay.runner.state import RunnerGlobalState


@pytest.fixture
def state() -> RunnerGlobalState:
    s = RunnerGlobalState()
    s.modpack = "MP_AUTOPLAY_VP_X"
    s.state = RunnerState.idle
    return s


async def _run_for_iterations(coro_factory, n_iterations: int):
    """Run the heartbeat loop for ~n iterations by collapsing wait_for to no-op."""
    stop = asyncio.Event()
    counter = {"count": 0}

    async def _fake_wait_for(_aw, timeout=None):  # noqa: ARG001
        counter["count"] += 1
        if counter["count"] >= n_iterations:
            stop.set()
        # Return immediately so the loop spins another iteration.
        raise asyncio.TimeoutError

    import autoplay.runner.heartbeat as hb_mod

    orig = asyncio.wait_for
    asyncio.wait_for = _fake_wait_for  # type: ignore[assignment]
    try:
        await coro_factory(stop)
    finally:
        asyncio.wait_for = orig  # type: ignore[assignment]


async def test_posts_one_heartbeat(runner_config, state) -> None:
    with respx.mock() as mock:
        route = mock.post("http://hv.test/runner-heartbeat").mock(
            return_value=httpx.Response(204)
        )
        await _run_for_iterations(
            lambda stop: heartbeat_loop(
                runner_config, state, "http://r.test", stop, on_recovery=None
            ),
            n_iterations=1,
        )
        assert route.call_count >= 1
        body = json.loads(route.calls[0].request.read())
        assert body["uuid"] == state.uuid
        assert body["state"] == "idle"
        assert body["url"] == "http://r.test"
        assert body["modpack"] == "MP_AUTOPLAY_VP_X"


async def test_410_triggers_re_registration(runner_config, state, monkeypatch) -> None:
    register_calls = {"n": 0}

    async def _fake_register(cfg, st, url):  # noqa: ARG001
        register_calls["n"] += 1

    monkeypatch.setattr(
        "autoplay.runner.heartbeat.register_with_retry", _fake_register
    )
    with respx.mock() as mock:
        mock.post("http://hv.test/runner-heartbeat").mock(
            return_value=httpx.Response(410)
        )
        await _run_for_iterations(
            lambda stop: heartbeat_loop(
                runner_config, state, "http://r.test", stop, on_recovery=None
            ),
            n_iterations=1,
        )
    assert register_calls["n"] >= 1


async def test_recovery_callback_fires_on_first_success(
    runner_config, state
) -> None:
    cb = MagicMock()
    with respx.mock() as mock:
        mock.post("http://hv.test/runner-heartbeat").mock(
            return_value=httpx.Response(204)
        )
        await _run_for_iterations(
            lambda stop: heartbeat_loop(
                runner_config, state, "http://r.test", stop, on_recovery=cb
            ),
            n_iterations=1,
        )
    # last_successful_heartbeat_ts was None, so first success is "recovered".
    assert cb.call_count >= 1
    assert state.last_successful_heartbeat_ts is not None


async def test_transport_error_does_not_raise(runner_config, state) -> None:
    with respx.mock() as mock:
        mock.post("http://hv.test/runner-heartbeat").mock(
            side_effect=httpx.ConnectError("down")
        )
        # Just shouldn't crash.
        await _run_for_iterations(
            lambda stop: heartbeat_loop(
                runner_config, state, "http://r.test", stop, on_recovery=None
            ),
            n_iterations=1,
        )
    assert state.last_successful_heartbeat_ts is None

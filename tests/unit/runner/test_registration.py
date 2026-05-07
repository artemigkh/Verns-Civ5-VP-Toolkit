"""Tests for autoplay.runner.registration.register_with_retry."""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from autoplay.runner.registration import register_with_retry
from autoplay.runner.state import RunnerGlobalState


@pytest.fixture
def state() -> RunnerGlobalState:
    s = RunnerGlobalState()
    s.modpack = "MP_AUTOPLAY_VP_1"
    return s


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    async def _no(_t=0):  # noqa: ARG001
        return None

    monkeypatch.setattr(asyncio, "sleep", _no)


async def test_success_first_try(runner_config, state) -> None:
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("http://hv.test/runner-registration").mock(
            return_value=httpx.Response(204)
        )
        await register_with_retry(runner_config, state, "http://r.test")
        assert route.called


async def test_retries_on_5xx_then_succeeds(runner_config, state) -> None:
    with respx.mock() as mock:
        route = mock.post("http://hv.test/runner-registration").mock(
            side_effect=[
                httpx.Response(503, text="busy"),
                httpx.Response(204),
            ]
        )
        await register_with_retry(runner_config, state, "http://r.test")
        assert route.call_count == 2


async def test_retries_on_transport_error(runner_config, state) -> None:
    with respx.mock() as mock:
        route = mock.post("http://hv.test/runner-registration").mock(
            side_effect=[
                httpx.ConnectError("nope"),
                httpx.Response(204),
            ]
        )
        await register_with_retry(runner_config, state, "http://r.test")
        assert route.call_count == 2


async def test_deadline_exceeded_raises(runner_config, state, monkeypatch) -> None:
    # Simulate elapsed time progressing past the deadline immediately so the
    # retry loop gives up after one attempt.
    runner_config.registration_timeout_sec = 0
    with respx.mock() as mock:
        mock.post("http://hv.test/runner-registration").mock(
            return_value=httpx.Response(503)
        )
        with pytest.raises(RuntimeError, match="Could not register"):
            await register_with_retry(runner_config, state, "http://r.test")


async def test_payload_contains_uuid_url_modpack(runner_config, state) -> None:
    captured = {}

    def _capture(request):
        captured["body"] = request.read()
        return httpx.Response(204)

    with respx.mock() as mock:
        mock.post("http://hv.test/runner-registration").mock(side_effect=_capture)
        await register_with_retry(runner_config, state, "http://r.test:1234")
    import json
    body = json.loads(captured["body"])
    assert body["uuid"] == state.uuid
    assert body["url"] == "http://r.test:1234"
    assert body["modpack"] == "MP_AUTOPLAY_VP_1"

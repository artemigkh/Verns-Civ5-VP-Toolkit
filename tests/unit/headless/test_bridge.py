"""Tests for autoplay.headless.bridge scheduling and the bridge's HTTP endpoints (no c5h is launched)."""

from __future__ import annotations

import time

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from autoplay.common import RunnerKind, RunnerState
from autoplay.headless import bridge as bridge_module
from autoplay.headless.app import create_app
from autoplay.headless.batches import Batch, all_batches, latest_batch
from autoplay.headless.bridge import Bridge
from autoplay.headless.config import HeadlessConfig
from tests.unit.headless.conftest import finish_job, iso_ago, set_jobs


class FakeQueue:
    """Stands in for QueueProcess: records what the bridge asks of c5h."""

    def __init__(self) -> None:
        self.batch: Batch | None = None
        self.started_at: float | None = None
        self.is_running = False
        self.starts: list[str] = []
        self.stop_requested = False
        self.killed = False

    def running(self) -> bool:
        return self.is_running

    def returncode(self) -> int | None:
        return None if self.is_running else 1

    def start(self, batch: Batch) -> None:
        self.batch, self.started_at, self.is_running = batch, time.time(), True
        self.starts.append(batch.name)

    def adopt(self) -> bool:
        return False

    def request_stop(self) -> None:
        self.stop_requested = True

    def cancel_stop(self) -> None:
        self.stop_requested = False

    def kill(self) -> None:
        self.killed, self.is_running = True, False


@pytest.fixture
def queue() -> FakeQueue:
    return FakeQueue()


@pytest.fixture
def bridge(cfg: HeadlessConfig, queue: FakeQueue) -> Bridge:
    return Bridge(cfg, "http://127.0.0.1:7000", queue=queue)


def _finish_all(batch: Batch) -> None:
    set_jobs(
        batch,
        {
            n: {"state": "completed", "worker": 0, "started": iso_ago(50), "endTurn": 150}
            for n in batch.job_names()
        },
    )
    for n in batch.job_names():
        finish_job(batch, n)


async def test_start_writes_a_batch_and_is_idempotent(
    bridge: Bridge, queue: FakeQueue, cfg: HeadlessConfig
) -> None:
    assert await bridge.start(max_turn=80) == "started"
    assert await bridge.start(max_turn=80) == "running"
    assert len(queue.starts) == 1
    assert latest_batch(cfg.work_dir).queue()["defaults"]["turns"] == 80


async def test_start_resumes_an_unfinished_batch(bridge: Bridge, queue: FakeQueue, batch: Batch) -> None:
    assert await bridge.start() == "started"
    assert queue.starts == [batch.name]


async def test_stop_drains_then_scheduling_ends(bridge: Bridge, queue: FakeQueue) -> None:
    await bridge.start()
    assert await bridge.stop() == "stopping"
    assert queue.stop_requested and bridge.stopping
    assert {s.state for s in bridge.snapshots()} == {RunnerState.stopping}
    queue.is_running = False
    with respx.mock(assert_all_called=False):
        async with httpx.AsyncClient() as client:
            await bridge.supervise_once(client)
    assert not bridge.stopping and not bridge.scheduling
    assert len(queue.starts) == 1


async def test_start_during_a_drain_cancels_it(bridge: Bridge, queue: FakeQueue) -> None:
    await bridge.start()
    await bridge.stop()
    assert await bridge.start() == "resumed"
    assert not queue.stop_requested and bridge.scheduling and not bridge.stopping


async def test_finished_batch_is_harvested_then_the_next_one_starts(
    bridge: Bridge, queue: FakeQueue, cfg: HeadlessConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    await bridge.start()
    first = queue.batch
    _finish_all(first)
    queue.is_running = False
    queue.started_at = time.time() - 600
    monkeypatch.setattr(bridge_module, "write_batch", _later_batch(bridge_module.write_batch))
    with respx.mock() as mock:
        route = mock.post("http://hv.test/submit-stats").mock(return_value=httpx.Response(204))
        async with httpx.AsyncClient() as client:
            await bridge.supervise_once(client)
    assert route.call_count == cfg.games_per_batch
    assert len(all_batches(cfg.work_dir)) == 2 and queue.starts[-1] != first.name


def _later_batch(write):
    """write_batch with a distinct name even within the same second."""

    def wrapped(cfg, turns, rng=None):
        time.sleep(0.01)
        return write(cfg, turns, rng)

    return wrapped


async def test_queue_failing_at_start_turns_scheduling_off(bridge: Bridge, queue: FakeQueue) -> None:
    await bridge.start()
    async with httpx.AsyncClient() as client:
        for _ in range(bridge_module.MAX_QUICK_EXITS):
            queue.is_running = False
            await bridge.supervise_once(client)
    assert not bridge.scheduling and bridge.failed
    assert {s.state for s in bridge.snapshots()} == {RunnerState.failed}
    assert await bridge.start() in ("started", "running")
    assert bridge.failed is None


def test_heartbeats_are_headless_runners(bridge: Bridge, cfg: HeadlessConfig) -> None:
    beats = bridge.heartbeats()
    assert len(beats) == cfg.workers
    assert {b.kind for b in beats} == {RunnerKind.headless}
    assert beats[1].url == "http://127.0.0.1:7000/slots/1"
    assert beats[0].modpack == cfg.modpack
    assert len({b.uuid for b in beats}) == cfg.workers


def test_slot_endpoints(cfg: HeadlessConfig, queue: FakeQueue) -> None:
    cfg = cfg.model_copy(
        update={
            "hypervisor_url": "http://127.0.0.1:9",
            "heartbeat_interval_sec": 60.0,
            "poll_interval_sec": 60.0,
        }
    )
    b = Bridge(cfg, "http://127.0.0.1:7000", queue=queue)
    with TestClient(create_app(cfg, b)) as client:
        r = client.post("/slots/1/start-game", json={"maxTurn": 40})
        assert r.status_code == 200 and r.json()["status"] == "started"
        assert b.max_turn == 40
        assert client.post("/slots/0/resume-game").json()["status"] == "running"
        assert client.post("/slots/2/stop-game").json()["status"] == "stopping"
        assert client.post("/slots/0/update-modpack").status_code == 409
        assert client.post("/slots/7/start-game").status_code == 404
        status = client.get("/status").json()
        assert status["stopping"] is True and len(status["slots"]) == cfg.workers
    assert queue.killed  # stop_queue_on_exit


async def test_restart_resumes_scheduling(cfg: HeadlessConfig, queue: FakeQueue) -> None:
    await Bridge(cfg, "http://b", queue=queue).start(max_turn=30)
    again = FakeQueue()
    restarted = Bridge(cfg, "http://b", queue=again)
    await restarted.restore()
    assert restarted.scheduling and restarted.max_turn == 30 and len(again.starts) == 1


async def test_restart_after_stop_stays_stopped(cfg: HeadlessConfig, queue: FakeQueue) -> None:
    b = Bridge(cfg, "http://b", queue=queue)
    await b.start()
    await b.stop()
    again = FakeQueue()
    restarted = Bridge(cfg, "http://b", queue=again)
    await restarted.restore()
    assert not restarted.scheduling and again.starts == []


async def test_restart_adopts_a_running_queue(cfg: HeadlessConfig) -> None:
    adopting = FakeQueue()
    adopting.adopt = lambda: True  # type: ignore[method-assign]
    b = Bridge(cfg, "http://b", queue=adopting)
    await b.restore()
    assert b.scheduling and adopting.starts == []

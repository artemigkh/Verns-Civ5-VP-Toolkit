"""End-to-end integration: runner-side bundle staging+drain submitted against a
*real* in-memory hypervisor (FastAPI TestClient).

Bridges runner ``pending_uploads`` to a live hypervisor app via respx routing
to a TestClient transport. Verifies that:

* Successful submission ends up in ``<storage>/<modpack>/complete/<gameId>.tar``
* The bundles_db row is appended
* The runner's pending dir is drained empty
* Crash submission ends up in the failed dir and increments failure_count
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from autoplay.hypervisor.app import create_app
from autoplay.hypervisor.config import HypervisorConfig
from autoplay.runner.pending_uploads import (
    drain_loop,
    pending_count,
    stage_upload,
)


@pytest.fixture
def hv(tmp_storage_root: Path):
    cfg = HypervisorConfig(
        storage_root=tmp_storage_root,
        port=5999,
        host="127.0.0.1",
        runner_timeout_sec=120,
    )
    app = create_app(cfg)
    with TestClient(app) as tc:
        yield tc, tmp_storage_root


def _route_hv(mock: respx.MockRouter, hv_client: TestClient, base_url: str = "http://hv.test") -> None:
    """Route any POST to ``base_url`` through the FastAPI TestClient."""
    def _bridge(request: httpx.Request) -> httpx.Response:
        # Strip base_url to get the path the FastAPI app expects.
        path = request.url.raw_path.decode()
        # TestClient supports str body / files via a single request method.
        resp = hv_client.request(
            method=request.method,
            url=path,
            content=request.content,
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
        )
        return httpx.Response(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            content=resp.content,
        )

    mock.post(url__regex=rf"{base_url}/.*").mock(side_effect=_bridge)


async def test_submit_logs_drains_to_hypervisor(hv) -> None:
    hv_client, root = hv
    # Pre-register the runner so success_count is observable.
    hv_client.post(
        "/runner-registration",
        json={"uuid": "u1", "url": "http://r:1", "modpack": "MP_AUTOPLAY_VP_1"},
    )

    pending = root.parent / "runner_pending"
    stage_upload(
        pending,
        endpoint="/submit-logs",
        modpack="MP_AUTOPLAY_VP_1",
        game_id="gINTEG",
        runner_uuid="u1",
        filename="gINTEG.tar",
        content=b"INTEGRATION-TAR-BYTES",
        final=True,
        extra_fields={"turn": 50, "timeElapsedSec": 300},
    )
    assert pending_count(pending) == 1

    stop = asyncio.Event()
    with respx.mock(assert_all_called=False) as mock:
        _route_hv(mock, hv_client)
        task = asyncio.create_task(
            drain_loop(pending, "http://hv.test", stop, interval_sec=0.01)
        )
        # Wait for the queue to drain.
        for _ in range(200):
            await asyncio.sleep(0.01)
            if pending_count(pending) == 0:
                break
        stop.set()
        await task

    # File landed in the right place.
    assert (root / "MP_AUTOPLAY_VP_1" / "complete" / "gINTEG.tar").read_bytes() \
        == b"INTEGRATION-TAR-BYTES"
    # Bundle metadata recorded.
    db_path = root / "MP_AUTOPLAY_VP_1_bundles.sqlite"
    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM bundles").fetchone()[0]
    assert n == 1
    # Success counter incremented on the registered runner.
    rows = hv_client.get("/runner-status").json()
    assert rows[0]["successCount"] == 1


async def test_submit_crash_drains_and_marks_failure(hv) -> None:
    hv_client, root = hv
    hv_client.post(
        "/runner-registration",
        json={"uuid": "u1", "url": "http://r:1", "modpack": "MP_AUTOPLAY_VP_1"},
    )

    pending = root.parent / "runner_pending2"
    stage_upload(
        pending,
        endpoint="/submit-crash",
        modpack="MP_AUTOPLAY_VP_1",
        game_id="gCRASH",
        runner_uuid="u1",
        filename="gCRASH.tar",
        content=b"CRASH-DATA",
        final=True,
    )

    stop = asyncio.Event()
    with respx.mock(assert_all_called=False) as mock:
        _route_hv(mock, hv_client)
        task = asyncio.create_task(
            drain_loop(pending, "http://hv.test", stop, interval_sec=0.01)
        )
        for _ in range(200):
            await asyncio.sleep(0.01)
            if pending_count(pending) == 0:
                break
        stop.set()
        await task

    assert (root / "MP_AUTOPLAY_VP_1" / "failed" / "gCRASH.tar").read_bytes() \
        == b"CRASH-DATA"
    rows = hv_client.get("/runner-status").json()
    assert rows[0]["failureCount"] == 1


async def test_full_register_heartbeat_submit_flow(hv) -> None:
    """Simulate a full game lifecycle from the hypervisor's POV.

    register -> several heartbeats (advancing turn) -> submit-logs -> verify
    the runner row reflects the final state and game_stats has the row.
    """
    hv_client, root = hv

    # Register
    hv_client.post(
        "/runner-registration",
        json={"uuid": "u1", "url": "http://r:1", "modpack": "MP_AUTOPLAY_VP_1"},
    )

    # Heartbeats with advancing turns
    for turn, elapsed in [(0, 0), (1, 12), (5, 60), (10, 130), (25, 350)]:
        r = hv_client.post(
            "/runner-heartbeat",
            json={
                "uuid": "u1",
                "state": "running",
                "gameId": "gFULL",
                "turn": turn,
                "timeElapsedSec": elapsed,
                "url": "http://r:1",
                "modpack": "MP_AUTOPLAY_VP_1",
            },
        )
        assert r.status_code == 204

    # Submit final bundle
    r = hv_client.post(
        "/submit-logs",
        data={
            "modpack": "MP_AUTOPLAY_VP_1",
            "gameId": "gFULL",
            "runnerUuid": "u1",
            "turn": "50",
            "timeElapsedSec": "700",
        },
        files={"file": ("gFULL.tar", b"final-bundle")},
    )
    assert r.status_code == 204

    # Yield so background to_thread tasks (game_stats update) can flush.
    await asyncio.sleep(0.05)

    # Status reflects the success
    row = hv_client.get("/runner-status").json()[0]
    assert row["successCount"] == 1
    assert row["turn"] == 25  # last heartbeat snapshot

    # turn-times has u1
    tt = hv_client.get("/turn-times/by-runner").json()
    assert "u1" in tt
    # Final submitted snapshot updated game_stats to turn 50, total_time 700
    assert tt["u1"]["totalTurns"] >= 25

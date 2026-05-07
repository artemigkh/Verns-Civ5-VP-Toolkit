"""Tests for hypervisor /runner-* and /turn-times routes via TestClient."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autoplay.hypervisor.app import create_app
from autoplay.hypervisor.config import HypervisorConfig


@pytest.fixture
def client(tmp_storage_root: Path):
    cfg = HypervisorConfig(
        storage_root=tmp_storage_root,
        port=5999,
        host="127.0.0.1",
        runner_timeout_sec=120,
    )
    app = create_app(cfg)
    with TestClient(app) as c:
        yield c


def test_register_then_status(client: TestClient) -> None:
    body = {"uuid": "u1", "url": "http://r:1", "modpack": "MP_AUTOPLAY_VP_1"}
    r = client.post("/runner-registration", json=body)
    assert r.status_code == 204
    r = client.get("/runner-status")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["uuid"] == "u1"
    assert rows[0]["state"] == "idle"


def test_heartbeat_unknown_with_url_auto_registers(client: TestClient) -> None:
    payload = {
        "uuid": "newby",
        "state": "running",
        "gameId": "g1",
        "turn": 5,
        "timeElapsedSec": 60,
        "url": "http://r:2",
        "modpack": "MP_AUTOPLAY_VP_1",
    }
    r = client.post("/runner-heartbeat", json=payload)
    assert r.status_code == 204
    rows = client.get("/runner-status").json()
    assert any(row["uuid"] == "newby" for row in rows)


def test_heartbeat_unknown_no_url_returns_410(client: TestClient) -> None:
    payload = {"uuid": "ghost", "state": "idle"}
    r = client.post("/runner-heartbeat", json=payload)
    assert r.status_code == 410


def test_recovered_state_increments_recovery(client: TestClient) -> None:
    client.post(
        "/runner-registration",
        json={"uuid": "u1", "url": "http://r", "modpack": "MP_AUTOPLAY_VP_1"},
    )
    client.post(
        "/runner-heartbeat",
        json={"uuid": "u1", "state": "recovered", "gameId": "g1", "turn": 1},
    )
    rows = client.get("/runner-status").json()
    assert rows[0]["state"] == "running"
    assert rows[0]["recoveryCount"] == 1


def test_deregister_runner(client: TestClient) -> None:
    client.post(
        "/runner-registration",
        json={"uuid": "u1", "url": "http://r", "modpack": "MP_AUTOPLAY_VP_1"},
    )
    r = client.post("/deregister-runner", json={"uuid": "u1"})
    assert r.status_code == 204
    assert client.get("/runner-status").json() == []


def test_deregister_missing_uuid_returns_400(client: TestClient) -> None:
    r = client.post("/deregister-runner", json={})
    assert r.status_code == 400


def test_runner_names_crud(client: TestClient) -> None:
    assert client.get("/runner-names").json() == {}
    r = client.put("/runner-names/192.168.2.5", json={"name": "alpha"})
    assert r.status_code == 204
    assert client.get("/runner-names").json() == {"192.168.2.5": "alpha"}
    r = client.delete("/runner-names/192.168.2.5")
    assert r.status_code == 204
    assert client.get("/runner-names").json() == {}


def test_runner_names_invalid_host_rejected(client: TestClient) -> None:
    r = client.put("/runner-names/has spaces", json={"name": "x"})
    assert r.status_code == 400


def test_runner_names_empty_name_rejected(client: TestClient) -> None:
    r = client.put("/runner-names/host1", json={"name": "   "})
    assert r.status_code == 400


def test_turn_times_by_runner_initially_empty(client: TestClient) -> None:
    r = client.get("/turn-times/by-runner")
    assert r.status_code == 200
    assert r.json() == {}

"""Tests for hypervisor /control/* routes via TestClient + respx for outbound POSTs."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
import pytest
import respx
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


def _register(client: TestClient, uuid: str, url: str, modpack: str = "MP_AUTOPLAY_VP_1") -> None:
    client.post(
        "/runner-registration",
        json={"uuid": uuid, "url": url, "modpack": modpack},
    )


def test_start_one_404_when_no_runner(client: TestClient) -> None:
    r = client.post("/control/start/missing-uuid")
    assert r.status_code == 404


def test_start_one_returns_202(client: TestClient) -> None:
    _register(client, "u1", "http://r1.test")
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://r1.test/start-game").mock(return_value=httpx.Response(204))
        r = client.post("/control/start/u1")
        assert r.status_code == 202
        body = r.json()
        assert body == {"status": "scheduled", "uuid": "u1"}


def test_resume_one_404_when_no_runner(client: TestClient) -> None:
    r = client.post("/control/resume/missing-uuid")
    assert r.status_code == 404


def test_resume_one_returns_202(client: TestClient) -> None:
    _register(client, "u1", "http://r1.test")
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://r1.test/resume-game").mock(
            return_value=httpx.Response(202, json={"status": "resuming"})
        )
        r = client.post("/control/resume/u1")
        assert r.status_code == 202
        assert r.json() == {"status": "scheduled", "uuid": "u1"}


def test_resume_all_counts(client: TestClient) -> None:
    _register(client, "u1", "http://r1.test")
    _register(client, "u2", "http://r2.test")
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://r1.test/resume-game").mock(return_value=httpx.Response(204))
        mock.post("http://r2.test/resume-game").mock(return_value=httpx.Response(204))
        r = client.post("/control/resume-all")
        assert r.status_code == 202
        assert r.json() == {"status": "scheduled", "count": 2}


def test_stop_one_returns_202(client: TestClient) -> None:
    _register(client, "u1", "http://r1.test")
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://r1.test/stop-game").mock(return_value=httpx.Response(204))
        r = client.post("/control/stop/u1")
        assert r.status_code == 202


def test_start_all_counts(client: TestClient) -> None:
    _register(client, "u1", "http://r1.test")
    _register(client, "u2", "http://r2.test")
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://r1.test/start-game").mock(return_value=httpx.Response(204))
        mock.post("http://r2.test/start-game").mock(return_value=httpx.Response(204))
        r = client.post("/control/start-all")
        assert r.status_code == 202
        assert r.json() == {"status": "scheduled", "count": 2}


def test_stop_all_counts(client: TestClient) -> None:
    _register(client, "u1", "http://r1.test")
    _register(client, "u2", "http://r2.test")
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://r1.test/stop-game").mock(return_value=httpx.Response(204))
        mock.post("http://r2.test/stop-game").mock(return_value=httpx.Response(204))
        r = client.post("/control/stop-all")
        assert r.status_code == 202
        assert r.json() == {"status": "scheduled", "count": 2}


def test_install_modpack_one_404(client: TestClient) -> None:
    r = client.post(
        "/control/install-modpack/missing",
        files={"file": ("mp.zip", b"not-a-zip")},
    )
    assert r.status_code == 404


def test_install_modpack_zip_without_mp_folder_rejected(
    client: TestClient, tmp_path: Path
) -> None:
    """A valid zip lacking an MP_AUTOPLAY_VP_* top-level folder yields 400."""
    import zipfile

    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("RandomTop/file.txt", b"x")
    _register(client, "u1", "http://r1.test")
    r = client.post(
        "/control/install-modpack/u1",
        files={"file": ("mp.zip", z.read_bytes(), "application/zip")},
    )
    assert r.status_code == 400


def test_install_modpack_already_on_target(client: TestClient, tmp_path: Path) -> None:
    """If runner.modpack already matches the zip's target, return 304."""
    import zipfile
    z = tmp_path / "mp.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("MP_AUTOPLAY_VP_X/file.txt", b"x")
    _register(client, "u1", "http://r1.test", modpack="MP_AUTOPLAY_VP_X")
    r = client.post(
        "/control/install-modpack/u1",
        files={"file": ("mp.zip", z.read_bytes(), "application/zip")},
    )
    assert r.status_code == 200
    assert r.json()["status"] == 304


def _register_headless(client: TestClient, uuid: str, url: str) -> None:
    client.post(
        "/runner-registration",
        json={"uuid": uuid, "url": url, "modpack": "MP_AUTOPLAY_VP_X_headless", "kind": "headless"},
    )


def _modpack_zip(tmp_path: Path) -> bytes:
    import zipfile

    z = tmp_path / "mp.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("MP_AUTOPLAY_VP_Y/file.txt", b"x")
    return z.read_bytes()


def test_install_modpack_one_refuses_headless(client: TestClient, tmp_path: Path) -> None:
    _register_headless(client, "h1", "http://bridge.test/slots/0")
    r = client.post(
        "/control/install-modpack/h1",
        files={"file": ("mp.zip", _modpack_zip(tmp_path), "application/zip")},
    )
    assert r.status_code == 409


def test_install_modpack_all_skips_headless(client: TestClient, tmp_path: Path) -> None:
    _register(client, "u1", "http://r1.test", modpack="MP_AUTOPLAY_VP_X")
    _register_headless(client, "h1", "http://bridge.test/slots/0")
    with respx.mock(assert_all_called=False) as mock:
        runner = mock.post("http://r1.test/update-modpack").mock(return_value=httpx.Response(200, json={}))
        bridge = mock.post("http://bridge.test/slots/0/update-modpack").mock(return_value=httpx.Response(409))
        r = client.post(
            "/control/install-modpack",
            files={"file": ("mp.zip", _modpack_zip(tmp_path), "application/zip")},
        )
    assert r.status_code == 200
    results = r.json()["results"]
    assert runner.called and not bridge.called
    assert results["h1"]["status"] == 409


# --------------------------------------------------------------------------
# max_turn forwarding
# --------------------------------------------------------------------------


@pytest.fixture
def capped_client(tmp_storage_root: Path):
    cfg = HypervisorConfig(
        storage_root=tmp_storage_root,
        port=5999,
        host="127.0.0.1",
        runner_timeout_sec=120,
        max_turn=300,
    )
    app = create_app(cfg)
    with TestClient(app) as c:
        yield c


def _wait_for_calls(route: respx.Route, n: int, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while route.call_count < n and time.time() < deadline:
        time.sleep(0.02)
    assert route.call_count == n


@pytest.mark.parametrize(
    ("control_path", "runner_path"),
    [
        ("/control/start/u1", "/start-game"),
        ("/control/start-all", "/start-game"),
        ("/control/resume/u1", "/resume-game"),
        ("/control/resume-all", "/resume-game"),
    ],
)
def test_start_and_resume_forward_max_turn(
    capped_client: TestClient, control_path: str, runner_path: str
) -> None:
    import json

    _register(capped_client, "u1", "http://r1.test")
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(f"http://r1.test{runner_path}").mock(
            return_value=httpx.Response(202)
        )
        r = capped_client.post(control_path)
        assert r.status_code == 202
        _wait_for_calls(route, 1)
        assert json.loads(route.calls.last.request.content) == {"maxTurn": 300}


def test_start_sends_null_max_turn_when_uncapped(client: TestClient) -> None:
    import json

    _register(client, "u1", "http://r1.test")
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post("http://r1.test/start-game").mock(
            return_value=httpx.Response(202)
        )
        client.post("/control/start/u1")
        _wait_for_calls(route, 1)
        assert json.loads(route.calls.last.request.content) == {"maxTurn": None}

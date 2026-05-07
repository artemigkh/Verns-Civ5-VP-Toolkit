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

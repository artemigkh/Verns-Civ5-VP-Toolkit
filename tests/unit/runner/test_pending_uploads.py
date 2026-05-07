"""Tests for autoplay.runner.pending_uploads."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import respx

from autoplay.runner.pending_uploads import (
    _list_pending,
    _try_upload_one,
    drain_loop,
    pending_count,
    stage_upload,
)


def test_stage_upload_writes_pair(tmp_path: Path) -> None:
    pending = tmp_path / "pending"
    meta = stage_upload(
        pending,
        endpoint="/submit-logs",
        modpack="MP_AUTOPLAY_VP_1",
        game_id="g1",
        runner_uuid="u1",
        filename="g1.tar",
        content=b"\x00\x01\x02",
        final=True,
        extra_fields={"turn": 42},
    )
    assert meta.is_file()
    bin_file = meta.with_suffix("").with_suffix(".bin")
    assert bin_file.read_bytes() == b"\x00\x01\x02"
    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["endpoint"] == "/submit-logs"
    assert payload["modpack"] == "MP_AUTOPLAY_VP_1"
    assert payload["gameId"] == "g1"
    assert payload["runnerUuid"] == "u1"
    assert payload["final"] is True
    assert payload["extraFields"]["turn"] == 42


def test_stage_upload_filters_none_extra_fields(tmp_path: Path) -> None:
    pending = tmp_path / "pending"
    meta = stage_upload(
        pending,
        endpoint="/submit-logs",
        modpack="MP",
        game_id="g",
        runner_uuid="u",
        filename="x",
        content=b"x",
        final=True,
        extra_fields={"turn": None, "timeElapsedSec": 5},
    )
    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["extraFields"] == {"timeElapsedSec": 5}


def test_list_pending_pairs_only(tmp_path: Path) -> None:
    pending = tmp_path / "pending"
    pending.mkdir()
    # Orphan meta (no .bin)
    (pending / "orphan.meta.json").write_text("{}", encoding="utf-8")
    # Valid pair
    (pending / "good.bin").write_bytes(b"x")
    (pending / "good.meta.json").write_text("{}", encoding="utf-8")
    # Orphan bin
    (pending / "lost.bin").write_bytes(b"y")
    pairs = _list_pending(pending)
    assert len(pairs) == 1
    assert pairs[0][0].name == "good.meta.json"


def test_list_pending_missing_dir(tmp_path: Path) -> None:
    assert _list_pending(tmp_path / "nope") == []


def test_pending_count(tmp_path: Path) -> None:
    pending = tmp_path / "pending"
    assert pending_count(pending) == 0
    stage_upload(
        pending, endpoint="/x", modpack="m", game_id="g", runner_uuid="u",
        filename="f", content=b"a", final=True,
    )
    assert pending_count(pending) == 1


async def test_try_upload_one_success_removes_files(tmp_path: Path) -> None:
    pending = tmp_path / "pending"
    meta = stage_upload(
        pending, endpoint="/submit-logs", modpack="m", game_id="g",
        runner_uuid="u", filename="f.tar", content=b"abc", final=True,
    )
    bin_path = meta.with_suffix("").with_suffix(".bin")
    with respx.mock() as mock:
        mock.post("http://hv.test/submit-logs").mock(
            return_value=httpx.Response(204)
        )
        async with httpx.AsyncClient() as client:
            ok = await _try_upload_one(client, "http://hv.test", meta, bin_path)
    assert ok is True
    assert not meta.exists()
    assert not bin_path.exists()


async def test_try_upload_one_failure_keeps_files(tmp_path: Path) -> None:
    pending = tmp_path / "pending"
    meta = stage_upload(
        pending, endpoint="/submit-logs", modpack="m", game_id="g",
        runner_uuid="u", filename="f.tar", content=b"abc", final=True,
    )
    bin_path = meta.with_suffix("").with_suffix(".bin")
    with respx.mock() as mock:
        mock.post("http://hv.test/submit-logs").mock(
            return_value=httpx.Response(503)
        )
        async with httpx.AsyncClient() as client:
            ok = await _try_upload_one(client, "http://hv.test", meta, bin_path)
    assert ok is False
    assert meta.exists()
    assert bin_path.exists()


async def test_try_upload_one_transport_error(tmp_path: Path) -> None:
    pending = tmp_path / "pending"
    meta = stage_upload(
        pending, endpoint="/submit-logs", modpack="m", game_id="g",
        runner_uuid="u", filename="f.tar", content=b"abc", final=True,
    )
    bin_path = meta.with_suffix("").with_suffix(".bin")
    with respx.mock() as mock:
        mock.post("http://hv.test/submit-logs").mock(
            side_effect=httpx.ConnectError("nope")
        )
        async with httpx.AsyncClient() as client:
            ok = await _try_upload_one(client, "http://hv.test", meta, bin_path)
    assert ok is False
    assert meta.exists()


async def test_drain_loop_processes_pending(tmp_path: Path, monkeypatch) -> None:
    pending = tmp_path / "pending"
    for i in range(3):
        stage_upload(
            pending, endpoint="/submit-logs", modpack="m", game_id=f"g{i}",
            runner_uuid="u", filename=f"f{i}", content=b"x", final=True,
        )
    # Speed up the inter-iteration sleep.
    orig_wait_for = asyncio.wait_for

    async def _fast_wait_for(awaitable, timeout=None):  # noqa: ARG001
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", _fast_wait_for)

    stop = asyncio.Event()

    with respx.mock() as mock:
        mock.post("http://hv.test/submit-logs").mock(
            return_value=httpx.Response(204)
        )

        async def _stop_after():
            # Allow one iteration to run.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            stop.set()

        asyncio.wait_for = orig_wait_for  # restore for asyncio.sleep below
        # Run drain loop until pending dir is empty (it should drain in 1 iter).
        drain = asyncio.create_task(
            drain_loop(pending, "http://hv.test", stop, interval_sec=0.01)
        )
        # Yield a bit so drain can do work.
        for _ in range(50):
            await asyncio.sleep(0)
            if pending_count(pending) == 0:
                break
        stop.set()
        await drain

    assert pending_count(pending) == 0

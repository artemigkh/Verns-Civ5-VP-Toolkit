"""Broadcast control endpoints: fan-out start/stop/install-modpack to all runners."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status

from autoplay.common import RunnerStatusRow
from autoplay.hypervisor.db import RunnerDB
from autoplay.runner.modpack import ModpackZipError, peek_modpack_version

router = APIRouter(prefix="/control", tags=["control"])

logger = logging.getLogger(__name__)


def _db(request: Request) -> RunnerDB:
    return request.app.state.db


def _timeout(request: Request) -> int:
    return request.app.state.config.runner_timeout_sec


async def _post_to_runner(
    client: httpx.AsyncClient,
    runner: RunnerStatusRow,
    path: str,
    **post_kwargs,
) -> tuple[str, dict[str, object]]:
    url = f"{runner.url.rstrip('/')}{path}"
    try:
        r = await client.post(url, timeout=60.0, **post_kwargs)
        return runner.uuid, {"status": r.status_code, "detail": _safe_json(r)}
    except httpx.HTTPError as exc:
        return runner.uuid, {"status": 0, "detail": f"HTTP error: {exc}"}


def _safe_json(r: httpx.Response) -> object:
    try:
        return r.json()
    except ValueError:
        return r.text


def _find_runner(request: Request, uuid: str) -> RunnerStatusRow:
    runners = _db(request).list_live_runners(_timeout(request))
    for r in runners:
        if r.uuid == uuid:
            return r
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No live runner with UUID {uuid}",
    )


# How long to wait between successive ``/start-game`` POSTs in start-all.
# The Civ game engine seeds its RNG from the epoch timestamp at start, so
# games launched in the same wall-clock second can deterministically end up
# with identical maps. A one-second stagger keeps each runner's seed
# distinct.
_START_FANOUT_GAP_SEC = 1.0


def _spawn_bg(coro, name: str) -> None:
    """Schedule a fire-and-forget background task and log any exceptions."""

    async def _wrapped() -> None:
        try:
            await coro
        except Exception:  # noqa: BLE001
            logger.exception("Background control task %s failed", name)

    asyncio.create_task(_wrapped(), name=name)


@router.post("/start/{uuid}", status_code=status.HTTP_202_ACCEPTED)
async def start_one(request: Request, uuid: str) -> dict[str, object]:
    runner = _find_runner(request, uuid)

    async def _do() -> None:
        async with httpx.AsyncClient() as client:
            await _post_to_runner(client, runner, "/start-game")

    _spawn_bg(_do(), name=f"start-{uuid}")
    return {"status": "scheduled", "uuid": uuid}


@router.post("/stop/{uuid}", status_code=status.HTTP_202_ACCEPTED)
async def stop_one(request: Request, uuid: str) -> dict[str, object]:
    runner = _find_runner(request, uuid)

    async def _do() -> None:
        async with httpx.AsyncClient() as client:
            await _post_to_runner(client, runner, "/stop-game")

    _spawn_bg(_do(), name=f"stop-{uuid}")
    return {"status": "scheduled", "uuid": uuid}


@router.post("/install-modpack/{uuid}")
async def install_modpack_one(
    request: Request,
    uuid: str,
    file: UploadFile = File(...),
) -> dict[str, object]:
    runner = _find_runner(request, uuid)
    fd, tmp_path = tempfile.mkstemp(suffix="-modpack.zip", prefix="hv-")
    os.close(fd)
    tmp = Path(tmp_path)
    try:
        with tmp.open("wb") as fh:
            while chunk := await file.read(1024 * 1024):
                fh.write(chunk)
        try:
            target = peek_modpack_version(tmp)
        except ModpackZipError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        if runner.modpack == target:
            return {"status": 304, "detail": "already on target modpack", "targetModpack": target}
        data = tmp.read_bytes()
        files = {"file": (f"{target}.zip", data, "application/zip")}
        async with httpx.AsyncClient() as client:
            _, result = await _post_to_runner(client, runner, "/update-modpack", files=files)
        result["targetModpack"] = target
        return result
    finally:
        tmp.unlink(missing_ok=True)


@router.post("/start-all", status_code=status.HTTP_202_ACCEPTED)
async def start_all(request: Request) -> dict[str, object]:
    runners = _db(request).list_live_runners(_timeout(request))

    async def _do() -> None:
        # Stagger /start-game POSTs by one second so each runner seeds its
        # game RNG from a distinct wall-clock timestamp.
        async with httpx.AsyncClient() as client:
            for i, r in enumerate(runners):
                if i > 0:
                    await asyncio.sleep(_START_FANOUT_GAP_SEC)
                uuid, result = await _post_to_runner(client, r, "/start-game")
                logger.info("start-all -> %s: %s", uuid, result)

    _spawn_bg(_do(), name="start-all")
    return {"status": "scheduled", "count": len(runners)}


@router.post("/stop-all", status_code=status.HTTP_202_ACCEPTED)
async def stop_all(request: Request) -> dict[str, object]:
    runners = _db(request).list_live_runners(_timeout(request))

    async def _do() -> None:
        async with httpx.AsyncClient() as client:
            results = await asyncio.gather(
                *(_post_to_runner(client, r, "/stop-game") for r in runners)
            )
        for uuid, result in results:
            logger.info("stop-all -> %s: %s", uuid, result)

    _spawn_bg(_do(), name="stop-all")
    return {"status": "scheduled", "count": len(runners)}


@router.post("/install-modpack")
async def install_modpack_all(
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, object]:
    # Save upload to a temp file so it can be replayed to each runner.
    fd, tmp_path = tempfile.mkstemp(suffix="-modpack.zip", prefix="hv-")
    os.close(fd)
    tmp = Path(tmp_path)
    try:
        with tmp.open("wb") as fh:
            while chunk := await file.read(1024 * 1024):
                fh.write(chunk)

        try:
            target = peek_modpack_version(tmp)
        except ModpackZipError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

        runners = _db(request).list_live_runners(_timeout(request))
        targets = [r for r in runners if r.modpack != target]
        skipped = [r.uuid for r in runners if r.modpack == target]
        logger.info(
            "Installing %s to %d/%d runners (skipping %d already on it)",
            target,
            len(targets),
            len(runners),
            len(skipped),
        )

        per_runner: dict[str, dict[str, object]] = {}
        async with httpx.AsyncClient() as client:
            # Read bytes once; reuse per runner. Modpacks are small enough for this.
            data = tmp.read_bytes()
            tasks = []
            for r in targets:
                files = {"file": (f"{target}.zip", data, "application/zip")}
                tasks.append(_post_to_runner(client, r, "/update-modpack", files=files))
            for uuid, result in await asyncio.gather(*tasks):
                per_runner[uuid] = result
        for uuid in skipped:
            per_runner[uuid] = {"status": 304, "detail": "already on target modpack"}

        return {"targetModpack": target, "results": per_runner}
    finally:
        tmp.unlink(missing_ok=True)

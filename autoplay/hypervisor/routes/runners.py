"""Runner registration, heartbeat and status routes."""

from __future__ import annotations

import asyncio
import logging
import re

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from autoplay.common import HeartbeatPayload, RunnerRegistration, RunnerState, RunnerStatusRow
from autoplay.hypervisor import game_stats_db, runner_names_db
from autoplay.hypervisor.db import RunnerDB
router = APIRouter(tags=["runners"])
logger = logging.getLogger(__name__)


def _db(request: Request) -> RunnerDB:
    return request.app.state.db


def _timeout(request: Request) -> int:
    return request.app.state.config.runner_timeout_sec


def _maybe_update_game_stats(
    request: Request,
    *,
    payload: HeartbeatPayload,
    prev: dict | None,
) -> None:
    """Upsert this runner+game's running stats from the heartbeat snapshot.

    Records the highest turn and ``time_elapsed_sec`` ever observed for
    ``(runner_uuid, game_id)`` so the per-runner average reflects current
    in-progress games and finished games alike.
    """
    if payload.game_id is None:
        return
    if payload.turn is None and payload.time_elapsed_sec is None:
        return
    storage_root = request.app.state.config.storage_root
    modpack = (prev or {}).get("modpack") or payload.modpack
    # Off-thread to avoid blocking the heartbeat response on disk IO.
    asyncio.create_task(
        asyncio.to_thread(
            game_stats_db.update_game,
            storage_root,
            runner_uuid=payload.uuid,
            game_id=payload.game_id,
            modpack=modpack,
            turn=payload.turn,
            time_elapsed_sec=payload.time_elapsed_sec,
        )
    )


@router.post("/runner-registration", status_code=status.HTTP_204_NO_CONTENT)
async def register_runner(payload: RunnerRegistration, request: Request) -> None:
    is_new = _db(request).upsert_registration(payload)
    if is_new:
        logger.info(
            "New runner registered: uuid=%s url=%s modpack=%s",
            payload.uuid,
            payload.url,
            payload.modpack,
        )


@router.post("/deregister-runner", status_code=status.HTTP_204_NO_CONTENT)
async def deregister_runner(payload: dict, request: Request) -> None:
    """Remove a runner from the registry (called by the runner on shutdown).

    Body: ``{"uuid": "<runner-uuid>"}``. Returns 204 even when the runner was
    not present, since deregistration is idempotent from the runner's POV.
    """
    uuid = (payload or {}).get("uuid")
    if not isinstance(uuid, str) or not uuid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing 'uuid' in request body.",
        )
    removed = _db(request).delete_runner(uuid)
    if removed:
        logger.info("Runner deregistered (graceful shutdown): uuid=%s", uuid)
    else:
        logger.info("Deregister request for unknown runner uuid=%s (no-op)", uuid)


@router.post("/runner-heartbeat", status_code=status.HTTP_204_NO_CONTENT)
async def runner_heartbeat(payload: HeartbeatPayload, request: Request) -> None:
    db = _db(request)
    # ``recovered`` is a one-shot pulse: increment the recovery counter and
    # persist ``running`` instead so the UI doesn't sticky on it.
    state_to_store = payload.state
    if payload.state == RunnerState.recovered:
        if db.increment_recovery(payload.uuid):
            logger.info("Runner %s recovered a crashed game", payload.uuid)
        state_to_store = RunnerState.running
    ok = db.record_heartbeat(
        uuid=payload.uuid,
        state=state_to_store,
        game_id=payload.game_id,
        turn=payload.turn,
        time_elapsed_sec=payload.time_elapsed_sec,
    )
    if ok[0]:
        _maybe_update_game_stats(request, payload=payload, prev=ok[1])
        return
    # Unknown runner — auto-register from the heartbeat if it carried enough info.
    # This handles the case where the hypervisor was restarted while runners
    # kept running and sending heartbeats.
    if payload.url:
        reg = RunnerRegistration(
            uuid=payload.uuid, url=payload.url, modpack=payload.modpack
        )
        db.upsert_registration(reg)
        _ok2, _prev = db.record_heartbeat(
            uuid=payload.uuid,
            state=state_to_store,
            game_id=payload.game_id,
            turn=payload.turn,
            time_elapsed_sec=payload.time_elapsed_sec,
        )
        logger.info(
            "Auto-registered runner from heartbeat: uuid=%s url=%s modpack=%s state=%s",
            payload.uuid,
            payload.url,
            payload.modpack,
            payload.state.value,
        )
        return
    # No url available; ask runner to do an explicit registration.
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Runner not registered; please re-register.",
    )


@router.get("/runner-status", response_model=list[RunnerStatusRow])
async def runner_status(request: Request) -> list[RunnerStatusRow]:
    db = _db(request)
    timeout_sec = _timeout(request)
    pruned = db.prune_timed_out(timeout_sec)
    for u in pruned:
        logger.info("Runner timed out (>%ss since heartbeat): uuid=%s", timeout_sec, u)
    return db.list_live_runners(timeout_sec)


@router.get("/turn-times/by-runner")
async def turn_times_by_runner(request: Request) -> dict[str, dict]:
    """Per-runner turn-time stats: average across this runner's games of
    ``total_time_sec / turns`` (in-progress games included)."""
    storage_root = request.app.state.config.storage_root
    return await asyncio.to_thread(
        game_stats_db.by_runner_summary, storage_root
    )


# --- Runner display-name (tag) endpoints ----------------------------------

_HOST_RE = re.compile(r"^[A-Za-z0-9._:\-\[\]]+$")


def _validate_host(host: str) -> None:
    if not host or not _HOST_RE.match(host):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid host: {host!r}",
        )


class RunnerNamePayload(BaseModel):
    name: str = Field(min_length=1, max_length=64)


@router.get("/runner-names")
async def list_runner_names(request: Request) -> dict[str, str]:
    storage_root = request.app.state.config.storage_root
    return await asyncio.to_thread(runner_names_db.all_names, storage_root)


@router.put("/runner-names/{host}", status_code=status.HTTP_204_NO_CONTENT)
async def set_runner_name(host: str, payload: RunnerNamePayload, request: Request) -> None:
    _validate_host(host)
    # Preserve leading whitespace as a deliberate sort-override mechanism;
    # only reject names that are entirely whitespace or trail-padded.
    name = payload.name.rstrip()
    if not name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Name cannot be empty.",
        )
    storage_root = request.app.state.config.storage_root
    await asyncio.to_thread(runner_names_db.set_name, storage_root, host, name)
    logger.info("Runner display name set: host=%s name=%r", host, name)


@router.delete("/runner-names/{host}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_runner_name(host: str, request: Request) -> None:
    _validate_host(host)
    storage_root = request.app.state.config.storage_root
    removed = await asyncio.to_thread(runner_names_db.delete_name, storage_root, host)
    if removed:
        logger.info("Runner display name cleared: host=%s", host)

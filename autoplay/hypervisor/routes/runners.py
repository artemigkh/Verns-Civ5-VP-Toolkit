"""Runner registration, heartbeat and status routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from autoplay.common import HeartbeatPayload, RunnerRegistration, RunnerStatusRow
from autoplay.hypervisor.db import RunnerDB

router = APIRouter(tags=["runners"])
logger = logging.getLogger(__name__)


def _db(request: Request) -> RunnerDB:
    return request.app.state.db


def _timeout(request: Request) -> int:
    return request.app.state.config.runner_timeout_sec


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


@router.post("/runner-heartbeat", status_code=status.HTTP_204_NO_CONTENT)
async def runner_heartbeat(payload: HeartbeatPayload, request: Request) -> None:
    ok = _db(request).record_heartbeat(
        uuid=payload.uuid,
        state=payload.state,
        game_id=payload.game_id,
        turn=payload.turn,
        time_elapsed_sec=payload.time_elapsed_sec,
    )
    if not ok:
        # Unknown runner (e.g. pruned after timeout) — ask it to re-register.
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

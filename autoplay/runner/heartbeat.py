"""Async heartbeat loop posting state to the hypervisor."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from autoplay.common import HeartbeatPayload
from autoplay.runner.config import RunnerConfig
from autoplay.runner.registration import register_with_retry
from autoplay.runner.state import RunnerGlobalState

logger = logging.getLogger(__name__)


async def heartbeat_loop(
    cfg: RunnerConfig,
    state: RunnerGlobalState,
    runner_url: str,
    stop_event: asyncio.Event,
) -> None:
    """Send heartbeats until ``stop_event`` is set.

    If the hypervisor responds with 410 Gone (meaning our entry was pruned),
    we transparently re-register and continue.
    """
    url = f"{cfg.hypervisor_url.rstrip('/')}/runner-heartbeat"
    async with httpx.AsyncClient(timeout=10.0) as client:
        while not stop_event.is_set():
            snap = state.snapshot()
            payload = HeartbeatPayload(
                uuid=snap.uuid,
                state=snap.state,
                game_id=snap.current_game_id,
                turn=snap.current_game_turn,
                time_elapsed_sec=(
                    int(time.time() - snap.current_game_start_time)
                    if snap.current_game_start_time is not None
                    else None
                ),
            )
            try:
                r = await client.post(url, json=payload.model_dump(by_alias=True))
                if r.status_code == 410:
                    logger.warning("Hypervisor lost our registration; re-registering")
                    await register_with_retry(cfg, state, runner_url)
                elif r.status_code >= 400:
                    logger.warning("Heartbeat rejected: %s %s", r.status_code, r.text)
            except httpx.HTTPError as exc:
                logger.warning("Heartbeat failed: %s", exc)

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=cfg.heartbeat_interval_sec)
            except asyncio.TimeoutError:
                pass

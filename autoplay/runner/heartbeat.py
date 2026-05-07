"""Async heartbeat loop posting state to the hypervisor."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

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
    on_recovery: Callable[[], None] | None = None,
) -> None:
    """Send heartbeats until ``stop_event`` is set.

    Heartbeats include ``url`` and ``modpack`` so the hypervisor can
    transparently auto-register us if it has lost our row (e.g. hypervisor
    restart). Failures are logged at debug level so a downed hypervisor does
    not flood logs; the runner continues whatever it was doing and keeps
    trying.
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
                url=runner_url,
                modpack=snap.modpack,
            )
            now = time.time()
            try:
                r = await client.post(url, json=payload.model_dump(by_alias=True))
                if r.status_code == 410:
                    # Older hypervisor that does not auto-register from heartbeat.
                    logger.warning("Hypervisor lost our registration; re-registering")
                    try:
                        await register_with_retry(cfg, state, runner_url)
                    except Exception:  # noqa: BLE001
                        logger.warning("Re-registration attempt failed; will retry on next heartbeat")
                elif r.status_code >= 400:
                    logger.warning("Heartbeat rejected: %s %s", r.status_code, r.text)
                else:
                    was_down = state.last_successful_heartbeat_ts is None or (
                        now - (state.last_successful_heartbeat_ts or 0)
                        > max(cfg.heartbeat_interval_sec * 3, 10.0)
                    )
                    state.last_successful_heartbeat_ts = now
                    if was_down and on_recovery is not None:
                        try:
                            on_recovery()
                        except Exception:  # noqa: BLE001
                            logger.exception("on_recovery callback raised")
            except httpx.HTTPError as exc:
                logger.debug("Heartbeat to hypervisor failed: %s", exc)

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=cfg.heartbeat_interval_sec)
            except asyncio.TimeoutError:
                pass

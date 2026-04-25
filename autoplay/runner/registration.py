"""Runner → hypervisor registration with retry."""

from __future__ import annotations

import asyncio
import logging

import httpx

from autoplay.common import RunnerRegistration
from autoplay.runner.config import RunnerConfig
from autoplay.runner.state import RunnerGlobalState

logger = logging.getLogger(__name__)


async def register_with_retry(
    cfg: RunnerConfig,
    state: RunnerGlobalState,
    runner_url: str,
) -> None:
    """Attempt to register with the hypervisor, retrying with backoff."""
    payload = RunnerRegistration(uuid=state.uuid, url=runner_url, modpack=state.modpack)
    deadline = asyncio.get_event_loop().time() + cfg.registration_timeout_sec
    backoff = 1.0

    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                r = await client.post(
                    f"{cfg.hypervisor_url.rstrip('/')}/runner-registration",
                    json=payload.model_dump(by_alias=True),
                )
                if r.status_code < 400:
                    logger.info("Registered with hypervisor at %s", cfg.hypervisor_url)
                    return
                logger.warning(
                    "Registration rejected (status %s): %s", r.status_code, r.text
                )
            except httpx.HTTPError as exc:
                logger.warning("Registration attempt failed: %s", exc)

            now = asyncio.get_event_loop().time()
            if now >= deadline:
                raise RuntimeError(
                    f"Could not register with hypervisor at {cfg.hypervisor_url} "
                    f"within {cfg.registration_timeout_sec}s"
                )
            await asyncio.sleep(min(backoff, max(1.0, deadline - now)))
            backoff = min(backoff * 2, 30.0)

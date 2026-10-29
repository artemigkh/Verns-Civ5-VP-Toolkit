"""FastAPI application of the headless bridge.

Each worker slot answers the runner control endpoints the hypervisor calls, at
``/slots/<k>/start-game`` and so on (a slot's runner URL is ``<bridge>/slots/<k>``). A queue plays all
slots at once, so start, resume and stop on any slot act on the whole bridge; a modpack install is
refused (the games play a pinned copy of the modpack's database, configured in civ5-headless).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, status

from autoplay.common import StartGameRequest
from autoplay.headless.bridge import Bridge, deregister_slots, heartbeat_loop, supervise_loop
from autoplay.headless.config import HeadlessConfig, load_config
from autoplay.runner import pending_uploads

logger = logging.getLogger(__name__)

_PORT_ENV = "AUTOPLAY_HEADLESS_ALLOCATED_PORT"


def create_app(config: HeadlessConfig | None = None, bridge: Bridge | None = None) -> FastAPI:
    cfg = config or load_config()
    port = os.environ.get(_PORT_ENV, "0")
    bridge = bridge or Bridge(cfg, f"http://{cfg.bind_host}:{port}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg.work_dir.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(bridge.prepare_game)
        await bridge.restore()
        stop_event = asyncio.Event()
        tasks = [
            asyncio.create_task(heartbeat_loop(bridge, stop_event), name="heartbeat"),
            asyncio.create_task(supervise_loop(bridge, stop_event), name="supervise"),
            asyncio.create_task(
                pending_uploads.drain_loop(cfg.pending_dir, cfg.hypervisor_url, stop_event), name="drain"
            ),
        ]
        logger.info(
            "Headless bridge ready: %d slots at %s/slots/<k>, modpack %s, work dir %s",
            cfg.workers,
            bridge.base_url,
            cfg.modpack,
            cfg.work_dir.resolve(),
        )
        try:
            yield
        finally:
            stop_event.set()
            for t in tasks:
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
            if cfg.stop_queue_on_exit:
                bridge.queue.kill()
            await deregister_slots(bridge)

    app = FastAPI(title="Civ5 VP Autoplay Headless Bridge", lifespan=lifespan)
    app.state.bridge = bridge

    def _slot(slot: int) -> None:
        if not 0 <= slot < cfg.workers:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No slot {slot}")

    @app.post("/slots/{slot}/start-game")
    async def start_game(slot: int, body: StartGameRequest | None = Body(default=None)) -> dict[str, object]:
        _slot(slot)
        try:
            result = await bridge.start(body.max_turn if body else None)
        except (OSError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return {"status": result, "batch": bridge.queue.batch.name if bridge.queue.batch else None}

    @app.post("/slots/{slot}/resume-game")
    async def resume_game(slot: int, body: StartGameRequest | None = Body(default=None)) -> dict[str, object]:
        # c5h resumes a batch where it stopped; there is no autosave to reload.
        return await start_game(slot, body)

    @app.post("/slots/{slot}/stop-game")
    async def stop_game(slot: int) -> dict[str, object]:
        _slot(slot)
        return {"status": await bridge.stop()}

    @app.post("/slots/{slot}/update-modpack")
    async def update_modpack(slot: int) -> None:
        _slot(slot)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Headless games play a pinned copy of the modpack's database; re-pin it in civ5-headless.",
        )

    @app.get("/status")
    async def bridge_status() -> dict:
        return bridge.status()

    return app


app = create_app() if os.environ.get(_PORT_ENV) else None

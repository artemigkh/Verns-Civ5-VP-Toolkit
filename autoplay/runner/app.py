"""FastAPI application entrypoint for the runner."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, status

from autoplay.runner.civ_io import detect_installed_modpack
from autoplay.runner.config import RunnerConfig, load_config
from autoplay.runner.game_controller import (
    GameAlreadyRunningError,
    GameController,
    NoInstallError,
    NoModpackError,
)
from autoplay.runner.heartbeat import heartbeat_loop
from autoplay.runner.modpack import ModpackZipError, install_modpack_zip
from autoplay.runner.registration import register_with_retry
from autoplay.runner.state import get_state

logger = logging.getLogger(__name__)

_PORT_ENV = "AUTOPLAY_RUNNER_ALLOCATED_PORT"


def create_app(config: RunnerConfig | None = None) -> FastAPI:
    cfg = config or load_config()
    state = get_state()
    controller = GameController(cfg, state)

    if cfg.install_dir.is_dir():
        state.modpack = detect_installed_modpack(cfg.install_dir)
        if state.modpack:
            logger.info("Detected installed modpack: %s", state.modpack)
        else:
            logger.info("No modpack found under %s/Assets/DLC", cfg.install_dir)
    else:
        logger.warning(
            "INSTALL_DIR %s does not exist; runner will register as idle but "
            "cannot start games until the install is configured.",
            cfg.install_dir,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        port = int(os.environ.get(_PORT_ENV, "0"))
        if port == 0:
            raise RuntimeError(
                f"Runner port not set via ${_PORT_ENV}; launch via "
                "`python -m autoplay.runner` so the port is allocated first."
            )
        runner_url = f"http://{cfg.bind_host}:{port}"
        with state.lock:
            state.url = runner_url
        logger.info("Runner UUID=%s URL=%s", state.uuid, runner_url)

        await register_with_retry(cfg, state, runner_url)

        stop_event = asyncio.Event()
        hb_task = asyncio.create_task(
            heartbeat_loop(cfg, state, runner_url, stop_event),
            name="runner-heartbeat",
        )
        try:
            yield
        finally:
            stop_event.set()
            hb_task.cancel()
            try:
                await hb_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            await controller.stop()

    app = FastAPI(title="Civ5 VP Autoplay Runner", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        snap = state.snapshot()
        return {"uuid": snap.uuid, "state": snap.state.value, "modpack": snap.modpack or ""}

    @app.post("/start-game", status_code=status.HTTP_202_ACCEPTED)
    async def start_game_endpoint() -> dict[str, str]:
        try:
            game_id = await controller.start()
        except GameAlreadyRunningError as exc:
            # Even if a game is already running, an operator POSTing /start-game
            # clearly wants scheduling on.
            with state.lock:
                state.is_scheduling_games = True
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except NoInstallError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except NoModpackError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        with state.lock:
            state.is_scheduling_games = True
        return {"status": "started", "gameId": game_id}

    @app.post("/stop-game", status_code=status.HTTP_200_OK)
    async def stop_game_endpoint() -> dict[str, bool]:
        # Turn scheduling off *before* stopping so the in-flight monitor's
        # upload cleanup won't race and re-launch another game.
        with state.lock:
            state.is_scheduling_games = False
        stopped = await controller.stop()
        return {"stopped": stopped}

    @app.post("/update-modpack", status_code=status.HTTP_200_OK)
    async def update_modpack_endpoint(file: UploadFile = File(...)) -> dict[str, str]:
        if controller.is_running:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot update modpack while a game is in progress.",
            )
        if not cfg.install_dir.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"INSTALL_DIR does not exist: {cfg.install_dir}",
            )

        # Stream upload to a temp file. mkstemp returns an open fd we must close
        # before reopening the path for writing on Windows.
        fd, tmp_path = tempfile.mkstemp(suffix=".zip", prefix="modpack-")
        os.close(fd)
        tmp = Path(tmp_path)
        try:
            with tmp.open("wb") as fh:
                while chunk := await file.read(1024 * 1024):
                    fh.write(chunk)

            with state.lock:
                previous_state = state.state
                from autoplay.common import RunnerState as _RS

                state.state = _RS.updating_modpack
            try:
                target = await asyncio.to_thread(install_modpack_zip, tmp, cfg.install_dir)
            except ModpackZipError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            finally:
                with state.lock:
                    # Refresh detected modpack and return to idle unless we were already running.
                    state.modpack = detect_installed_modpack(cfg.install_dir)
                    state.state = (
                        previous_state
                        if previous_state.value in {"idle"}
                        else state.state
                    )
                    from autoplay.common import RunnerState as _RS2

                    if state.state == _RS2.updating_modpack:
                        state.state = _RS2.idle
        finally:
            tmp.unlink(missing_ok=True)

        return {"status": "installed", "modpack": target}

    return app


app = create_app()

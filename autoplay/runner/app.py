"""FastAPI application entrypoint for the runner."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, status

from autoplay.runner.civ_io import detect_installed_modpack
from autoplay.runner.config import RunnerConfig, load_config
from autoplay.runner.fatal import fatal_permission_error, warn_if_low_disk_space
from autoplay.runner.game_controller import (
    GameAlreadyRunningError,
    GameController,
    NoInstallError,
    NoModpackError,
)
from autoplay.runner.heartbeat import heartbeat_loop
from autoplay.runner.modpack import ModpackZipError, install_modpack_zip
from autoplay.runner.patcher import install_patched_files
from autoplay.runner.registration import register_with_retry
from autoplay.runner.state import get_state

logger = logging.getLogger(__name__)

_PORT_ENV = "AUTOPLAY_RUNNER_ALLOCATED_PORT"


def _refresh_civ5_exe(install_dir: Path) -> None:
    """Re-create ``CivilizationV_DX11.exe`` from a sibling ``.bak`` at startup.

    Procedure:
      1. If ``CivilizationV_DX11.exe.bak`` does not yet exist, copy the
         current exe to it (one-time backup capture).
      2. Delete ``CivilizationV_DX11.exe``.
      3. Copy ``CivilizationV_DX11.exe.bak`` -> ``CivilizationV_DX11.exe``.

    The point is to defeat AV / Steam states that have flagged the live exe
    by giving the runner a known-good copy on every boot. Failures are logged
    and swallowed so the runner can still start in a degraded mode (the
    later ``_wait_for_exe`` gate in the controller will surface a hard error
    if the exe ends up missing).
    """
    exe = install_dir / "CivilizationV_DX11.exe"
    bak = install_dir / "CivilizationV_DX11.exe.bak"
    try:
        if not bak.is_file():
            if not exe.is_file():
                logger.warning(
                    "Cannot refresh Civ5 exe: neither %s nor %s exists; skipping.",
                    exe,
                    bak,
                )
                return
            logger.info("Creating one-time backup %s from %s", bak, exe)
            shutil.copy2(exe, bak)
        if exe.is_file():
            exe.unlink()
        shutil.copy2(bak, exe)
        logger.info("Refreshed %s from %s", exe, bak)
    except PermissionError as exc:
        fatal_permission_error(exc, where=f"refreshing Civ5 exe at {exe}")
    except OSError as exc:
        logger.warning("Failed to refresh Civ5 exe (%s); continuing.", exc)


def create_app(config: RunnerConfig | None = None) -> FastAPI:
    cfg = config or load_config()
    state = get_state()
    controller = GameController(cfg, state)

    warn_if_low_disk_space(cfg.user_dir / "Logs")

    try:
        install_patched_files(
            cfg.user_dir,
            cfg.install_dir,
            use_blank_d3d9_proxy=cfg.use_blank_d3d9_proxy,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to install patched files; runner will continue in degraded state.")

    if cfg.install_dir.is_dir():
        _refresh_civ5_exe(cfg.install_dir)

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

        # Best-effort initial registration. The heartbeat loop carries url+modpack
        # and will auto-register against the hypervisor as soon as it is
        # reachable, so a transient hypervisor outage at startup is recoverable.
        try:
            await register_with_retry(cfg, state, runner_url)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Initial registration to %s failed (%s); will keep trying via heartbeats.",
                cfg.hypervisor_url,
                exc,
            )

        stop_event = asyncio.Event()
        hb_task = asyncio.create_task(
            heartbeat_loop(
                cfg, state, runner_url, stop_event,
                on_recovery=controller.trigger_deferred_reschedule,
            ),
            name="runner-heartbeat",
        )
        from autoplay.runner.pending_uploads import drain_loop as _drain_loop

        drain_task = asyncio.create_task(
            _drain_loop(cfg.pending_uploads_dir, cfg.hypervisor_url, stop_event),
            name="pending-upload-drain",
        )
        try:
            yield
        finally:
            stop_event.set()
            for t in (hb_task, drain_task):
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            await controller.stop()
            # Final best-effort deregistration so the hypervisor immediately
            # removes us from the live runner list rather than waiting for the
            # heartbeat-timeout grace window to expire.
            try:
                import httpx as _httpx

                async with _httpx.AsyncClient(timeout=5.0) as _client:
                    await _client.post(
                        f"{cfg.hypervisor_url.rstrip('/')}/deregister-runner",
                        json={"uuid": state.uuid},
                    )
                logger.info("Deregistered from hypervisor at %s", cfg.hypervisor_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Deregister POST failed (%s); hypervisor will time us out instead.",
                    exc,
                )

    app = FastAPI(title="Civ5 VP Autoplay Runner", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        snap = state.snapshot()
        return {"uuid": snap.uuid, "state": snap.state.value, "modpack": snap.modpack or ""}

    @app.post("/start-game", status_code=status.HTTP_202_ACCEPTED)
    async def start_game_endpoint() -> dict[str, str]:
        # Validate cheap preconditions synchronously so the operator gets an
        # immediate 4xx for misconfiguration; defer the actual launch (which
        # waits on the exe and spawns the game process) to a background task
        # so this endpoint returns instantly.
        from autoplay.common import RunnerState as _RS

        if not cfg.install_dir.is_dir():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"INSTALL_DIR does not exist: {cfg.install_dir}",
            )
        with state.lock:
            if not state.modpack:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No modpack installed on this runner.",
                )
            # Reject if a launch / game is already in flight. Anything other
            # than ``idle``/``failed`` means something is actively happening.
            if state.state not in {_RS.idle, _RS.failed}:
                # Honor scheduling intent regardless: an operator pressing
                # Start while a game is running clearly wants scheduling on.
                state.is_scheduling_games = True
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot start: runner state is {state.state.value!r}.",
                )
            # Claim the launch synchronously so a second start request races
            # against this state rather than against the controller itself.
            state.state = _RS.starting
            state.is_scheduling_games = True

        async def _launch_in_background() -> None:
            try:
                game_id = await controller.start()
                logger.info("Background launch complete: gameId=%s", game_id)
            except GameAlreadyRunningError:
                # Lost the race vs. another launcher; that's fine.
                logger.info("Background launch skipped: game already running.")
            except (NoInstallError, NoModpackError) as exc:
                logger.warning("Background launch aborted: %s", exc)
                with state.lock:
                    if state.state == _RS.starting:
                        state.state = _RS.idle
            except Exception:  # noqa: BLE001
                logger.exception("Background launch failed")
                with state.lock:
                    if state.state == _RS.starting:
                        state.state = _RS.failed

        asyncio.create_task(_launch_in_background(), name="start-game-bg")
        return {"status": "starting"}

    @app.post("/stop-game", status_code=status.HTTP_202_ACCEPTED)
    async def stop_game_endpoint() -> dict[str, str]:
        # Flip scheduling off and mark the runner as stopping synchronously so
        # the heartbeat loop reports the new state immediately, then run the
        # actual teardown (process kill, log cleanup) on a background task so
        # the endpoint returns without waiting on those.
        from autoplay.common import RunnerState as _RS

        with state.lock:
            state.is_scheduling_games = False
            # Only override state when we have something to stop; if we are
            # already idle, stay idle.
            if state.state != _RS.idle:
                state.state = _RS.stopping

        async def _stop_in_background() -> None:
            try:
                await controller.stop()
            except Exception:  # noqa: BLE001
                logger.exception("Background stop failed")
                with state.lock:
                    state.state = _RS.idle

        asyncio.create_task(_stop_in_background(), name="stop-game-bg")
        return {"status": "stopping"}

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
            try:
                with tmp.open("wb") as fh:
                    while chunk := await file.read(1024 * 1024):
                        fh.write(chunk)
            except PermissionError as exc:
                fatal_permission_error(exc, where=f"writing modpack zip to {tmp}")

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

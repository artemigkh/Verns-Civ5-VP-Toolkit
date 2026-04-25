"""Game controller: launches Civ5, watches logs, uploads artifacts to the hypervisor.

Owns a single ``GameController`` instance bound to the runner's global state. The
public API is:

* ``start()`` — launch the game and spawn an async monitor task
* ``stop()`` — kill the running game tree and clean the logs directory

The monitor task updates turn state, detects completion / process death /
timeouts, harvests a tar.gz, and uploads to the hypervisor.
"""

from __future__ import annotations

import asyncio
import fnmatch
import gzip
import io
import logging
import shutil
import subprocess
import sys
import tarfile
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import httpx
import psutil

from autoplay.common import RunnerState
from autoplay.runner.civ_io import (
    find_most_recent_autosave,
    game_result_present,
    read_current_turn,
)
from autoplay.runner.config import RunnerConfig
from autoplay.runner.state import RunnerGlobalState

logger = logging.getLogger(__name__)

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_MONITOR_POLL_SEC = 5.0


class GameAlreadyRunningError(RuntimeError):
    pass


class NoInstallError(RuntimeError):
    pass


class NoModpackError(RuntimeError):
    pass


def _make_game_id() -> str:
    return datetime.now().isoformat().replace(":", ".")


def _should_include(path: Path, ignore_patterns: Iterable[str]) -> bool:
    return not any(fnmatch.fnmatch(path.name, pat) for pat in ignore_patterns)


def _make_tar_gz(logs_dir: Path, ignore_patterns: Iterable[str]) -> bytes:
    """Create an in-memory tarball of the logs dir.

    Each log file is individually gzip-compressed (its name gains a ``.gz``
    suffix) and the compressed blobs are packed into an *uncompressed* ``.tar``
    archive. This lets consumers stream-decompress any single entry without
    inflating the whole bundle.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        if logs_dir.is_dir():
            for entry in sorted(logs_dir.iterdir()):
                if not (entry.is_file() and _should_include(entry, ignore_patterns)):
                    continue
                raw = entry.read_bytes()
                compressed = gzip.compress(raw)
                info = tarfile.TarInfo(name=f"{entry.name}.gz")
                info.size = len(compressed)
                info.mtime = int(entry.stat().st_mtime)
                tar.addfile(info, io.BytesIO(compressed))
    return buf.getvalue()


def _kill_process_tree(pid: int, timeout: float = 10.0) -> None:
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    procs = [parent, *parent.children(recursive=True)]
    for p in procs:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(procs, timeout=timeout)
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass


def _clear_logs_dir(logs_dir: Path) -> None:
    try:
        if logs_dir.is_dir():
            for child in logs_dir.iterdir():
                try:
                    if child.is_dir() and not child.is_symlink():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        child.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("Could not remove %s: %s", child, exc)
        else:
            logs_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Failed to clean logs dir %s: %s", logs_dir, exc)


class GameController:
    def __init__(self, cfg: RunnerConfig, state: RunnerGlobalState) -> None:
        self._cfg = cfg
        self._state = state
        self._proc: subprocess.Popen[bytes] | None = None
        self._monitor_task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        return self._monitor_task is not None and not self._monitor_task.done()

    def _maybe_reschedule(self) -> None:
        """If scheduling is enabled, launch another game after the current one."""
        with self._state.lock:
            should = self._state.is_scheduling_games
        if not should:
            return
        logger.info("Scheduling next game (is_scheduling_games=True)")

        async def _relaunch() -> None:
            try:
                await self.start()
            except GameAlreadyRunningError:
                pass
            except Exception:  # noqa: BLE001
                logger.exception("Auto-restart failed")

        asyncio.create_task(_relaunch(), name="auto-restart")

    def _spawn_civ5(self, exe: Path) -> subprocess.Popen[bytes]:
        """Spawn Civ5, retrying briefly on transient FileNotFoundError.

        After a crashed Civ5 process exits, Windows (often combined with
        antivirus / Steam overlay) can briefly cause ``CreateProcess`` to
        return ``ERROR_FILE_NOT_FOUND`` for the very same exe that will
        succeed a moment later. We retry up to a few times with a short
        delay. Passing ``executable=`` explicitly avoids any command-line
        parsing of the quoted, space- and apostrophe-containing path.
        """
        last_exc: Exception | None = None
        for attempt in range(1, 6):
            try:
                return subprocess.Popen(  # noqa: S603
                    [str(exe), "-Automation", "RunAutoplayGame.lua"],
                    executable=str(exe),
                    cwd=str(self._cfg.install_dir),
                    creationflags=_CREATE_NO_WINDOW,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError as exc:
                last_exc = exc
                logger.warning(
                    "Civ5 launch attempt %d failed (FileNotFoundError); "
                    "exe.is_file()=%s, cwd.is_dir()=%s; retrying...",
                    attempt,
                    exe.is_file(),
                    self._cfg.install_dir.is_dir(),
                )
                time.sleep(2.0)
        assert last_exc is not None
        raise last_exc

    async def start(self) -> str:
        if self.is_running:
            raise GameAlreadyRunningError("A game is already in progress.")
        if not self._cfg.install_dir.is_dir():
            raise NoInstallError(f"INSTALL_DIR does not exist: {self._cfg.install_dir}")
        if not self._state.modpack:
            raise NoModpackError("No modpack installed on this runner.")

        logs_dir = self._cfg.user_dir / "Logs"
        await asyncio.to_thread(_clear_logs_dir, logs_dir)

        game_id = _make_game_id()
        exe = self._cfg.install_dir / "CivilizationV.exe"
        if not exe.is_file():
            alt = self._cfg.install_dir / "CivilizationV"
            exe = alt if alt.is_file() else exe
        logger.info(
            "Launching %s (gameId=%s, exists=%s)", exe, game_id, exe.is_file()
        )

        self._proc = await asyncio.to_thread(self._spawn_civ5, exe)

        with self._state.lock:
            self._state.state = RunnerState.starting
            self._state.current_game_id = game_id
            self._state.current_game_start_time = time.time()
            self._state.current_game_turn = None

        self._monitor_task = asyncio.create_task(
            self._monitor(logs_dir, game_id), name="game-monitor"
        )
        logger.info("Game started: gameId=%s modpack=%s", game_id, self._state.modpack)
        return game_id

    async def stop(self) -> bool:
        """Kill any running game process tree and clean the logs dir. Idempotent.

        Also clears ``is_scheduling_games`` so any in-flight monitor task that
        finishes after us does not auto-restart a new game.
        """
        stopped_something = False
        with self._state.lock:
            self._state.is_scheduling_games = False
        task = self._monitor_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            stopped_something = True
        self._monitor_task = None

        if self._proc is not None and self._proc.poll() is None:
            logger.info("Terminating Civ5 process tree (pid=%s)", self._proc.pid)
            await asyncio.to_thread(_kill_process_tree, self._proc.pid)
            stopped_something = True
        self._proc = None

        await asyncio.to_thread(_clear_logs_dir, self._cfg.user_dir / "Logs")

        with self._state.lock:
            self._state.state = RunnerState.idle
            self._state.current_game_id = None
            self._state.current_game_start_time = None
            self._state.current_game_turn = None
        if stopped_something:
            logger.info("Game stopped")
        return stopped_something

    async def _monitor(self, logs_dir: Path, game_id: str) -> None:
        cfg = self._cfg
        state = self._state
        start_time = time.time()
        last_turn = 0
        last_turn_ts = start_time
        got_any_log = False

        try:
            while True:
                await asyncio.sleep(_MONITOR_POLL_SEC)

                proc = self._proc
                if proc is None:
                    return
                proc_alive = proc.poll() is None
                now = time.time()

                if game_result_present(logs_dir):
                    logger.info("GameResult_Log.csv detected; harvesting logs")
                    await self._harvest_and_submit_complete(logs_dir, game_id)
                    return

                if not proc_alive:
                    logger.error("Civ5 process has exited unexpectedly")
                    await self._harvest_and_submit_crash(logs_dir, game_id, reason="process_died")
                    return

                turn = read_current_turn(logs_dir)
                if turn is not None:
                    got_any_log = True
                    with state.lock:
                        state.current_game_turn = turn
                        if state.state == RunnerState.starting:
                            state.state = RunnerState.running
                    if turn > last_turn:
                        last_turn = turn
                        last_turn_ts = now

                if not got_any_log and (now - start_time) > cfg.startup_timeout_sec:
                    logger.error("Startup timeout after %ss", cfg.startup_timeout_sec)
                    await self._harvest_and_submit_crash(logs_dir, game_id, reason="startup_timeout")
                    return

                if got_any_log and (now - last_turn_ts) > cfg.turn_timeout_sec:
                    logger.error(
                        "Turn timeout: no progress in %ss (last turn=%s)",
                        cfg.turn_timeout_sec,
                        last_turn,
                    )
                    await self._harvest_and_submit_crash(logs_dir, game_id, reason="turn_timeout")
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Game monitor crashed; marking as failed")
            with state.lock:
                state.state = RunnerState.failed
            raise

    async def _harvest_and_submit_complete(self, logs_dir: Path, game_id: str) -> None:
        state = self._state
        cfg = self._cfg
        modpack = state.modpack or "unknown"

        with state.lock:
            state.state = RunnerState.harvesting_logs
        bundle = await asyncio.to_thread(_make_tar_gz, logs_dir, cfg.log_ignore_patterns)
        logger.info(
            "Logs harvested: gameId=%s bytes=%s", game_id, len(bundle)
        )

        if self._proc is not None and self._proc.poll() is None:
            await asyncio.to_thread(_kill_process_tree, self._proc.pid)

        with state.lock:
            state.state = RunnerState.uploading_logs
        await self._upload(
            endpoint="/submit-logs",
            modpack=modpack,
            game_id=game_id,
            filename=f"{game_id}.tar",
            content=bundle,
            final=True,
        )
        logger.info("Logs uploaded: gameId=%s", game_id)

        with state.lock:
            state.state = RunnerState.idle
            state.current_game_id = None
            state.current_game_start_time = None
            state.current_game_turn = None

        self._maybe_reschedule()

    async def _harvest_and_submit_crash(
        self,
        logs_dir: Path,
        game_id: str,
        *,
        reason: str,
    ) -> None:
        state = self._state
        cfg = self._cfg
        modpack = state.modpack or "unknown"

        with state.lock:
            state.state = RunnerState.failed

        # Pre-read both artifacts so we know which upload will be the last.
        try:
            bundle = await asyncio.to_thread(_make_tar_gz, logs_dir, cfg.log_ignore_patterns)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to build partial log bundle for crashed game")
            bundle = b""
        autosave_path: Path | None = None
        autosave_bytes: bytes | None = None
        try:
            autosave_path = find_most_recent_autosave(cfg.user_dir)
            if autosave_path is not None:
                autosave_bytes = await asyncio.to_thread(autosave_path.read_bytes)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to read crash autosave")
            autosave_path = None
            autosave_bytes = None

        have_autosave = autosave_path is not None and autosave_bytes is not None

        if bundle:
            try:
                await self._upload(
                    endpoint="/submit-crash",
                    modpack=modpack,
                    game_id=game_id,
                    filename=f"{game_id}.tar",
                    content=bundle,
                    final=not have_autosave,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to upload partial log bundle for crashed game")

        if have_autosave:
            assert autosave_path is not None and autosave_bytes is not None
            try:
                await self._upload(
                    endpoint="/submit-crash",
                    modpack=modpack,
                    game_id=game_id,
                    filename=autosave_path.name,
                    content=autosave_bytes,
                    final=True,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to upload crash autosave")

        if self._proc is not None and self._proc.poll() is None:
            await asyncio.to_thread(_kill_process_tree, self._proc.pid)

        logger.info("Crash-path upload complete (reason=%s)", reason)
        await asyncio.sleep(2)
        with state.lock:
            state.state = RunnerState.idle
            state.current_game_id = None
            state.current_game_start_time = None
            state.current_game_turn = None

        self._maybe_reschedule()

    async def _upload(
        self,
        *,
        endpoint: str,
        modpack: str,
        game_id: str,
        filename: str,
        content: bytes,
        final: bool = True,
    ) -> None:
        url = f"{self._cfg.hypervisor_url.rstrip('/')}{endpoint}"
        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.post(
                url,
                data={
                    "modpack": modpack,
                    "gameId": game_id,
                    "runnerUuid": self._state.uuid,
                    "final": "true" if final else "false",
                },
                files={"file": (filename, content, "application/octet-stream")},
            )
            if r.status_code >= 400:
                logger.error("%s upload rejected: %s %s", endpoint, r.status_code, r.text)
            else:
                logger.info("%s upload OK (%s bytes)", endpoint, len(content))

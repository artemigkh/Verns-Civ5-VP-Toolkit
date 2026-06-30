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
import sqlite3
import subprocess
import sys
import tarfile
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import psutil

from autoplay.common import RunnerState
from autoplay.runner.civ_io import (
    find_most_recent_autosave,
    game_result_present,
    read_current_turn,
    read_current_turn_sqlite,
    sqlite_game_complete,
    stats_db_path,
)
from autoplay.runner.config import RunnerConfig
from autoplay.runner.crash_handler import crash_handler_window_present
from autoplay.runner.fatal import fatal_permission_error
from autoplay.runner.patcher import set_load_on_start
from autoplay.runner.state import RunnerGlobalState

logger = logging.getLogger(__name__)

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_MONITOR_POLL_SEC = 1.0
_PROC_START_WAIT_SEC = 30.0
# How long to wait for CivilizationV_DX11.exe to become accessible before
# giving up. Covers transient Steam / antivirus locks after a crash.
_EXE_WAIT_TIMEOUT_SEC = 30.0
_EXE_WAIT_POLL_SEC = 1.0

# CSV log files that have a single header row. When concatenating multiple
# crash-recovery segments back into a single file, all but the first
# segment's header row must be stripped.
_HEADERED_CSVS = frozenset(
    {
        "WorldState_Log.csv",
        "Score_Log.csv",
        "GameResult_Log.csv",
    }
)

# Directory (sibling of the game's ``Logs`` dir) where per-recovery snapshots
# of CSV log files are staged. Civ5 overwrites these files when it restarts
# from an autosave, so we copy them aside before each recovery attempt and
# splice them back together at harvest time.
_SEGMENTS_DIRNAME = "AutoplayLogSegments"


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
    try:
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
    except PermissionError as exc:
        fatal_permission_error(exc, where=f"reading log files in {logs_dir}")
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


# Backoff schedule (seconds) for retrying log-file deletions when Civ5 (or an
# antivirus / indexer) still has the file open after the process tree has been
# terminated. The full sequence sums to 16s before we declare a fatal error.
_REMOVE_RETRY_BACKOFF_SEC: tuple[float, ...] = (1.0, 5.0, 10.0)


def _remove_path_with_retry(child: Path) -> None:
    """Delete ``child`` (file or dir), retrying on PermissionError with backoff.

    Raises ``PermissionError`` if every attempt fails so callers can decide
    whether to escalate to ``fatal_permission_error``.
    """
    last_exc: PermissionError | None = None
    for attempt, delay in enumerate((0.0, *_REMOVE_RETRY_BACKOFF_SEC)):
        if delay:
            logger.warning(
                "Retrying delete of %s in %.0fs (attempt %d/%d) after PermissionError: %s",
                child,
                delay,
                attempt,
                len(_REMOVE_RETRY_BACKOFF_SEC),
                last_exc,
            )
            time.sleep(delay)
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
                if child.exists():
                    # rmtree with ignore_errors=True silently leaves locked
                    # files behind; force a real delete to surface the error.
                    shutil.rmtree(child)
            else:
                child.unlink(missing_ok=True)
            return
        except PermissionError as exc:
            last_exc = exc
    assert last_exc is not None
    raise last_exc


def _clear_logs_dir(logs_dir: Path) -> None:
    try:
        if logs_dir.is_dir():
            for child in logs_dir.iterdir():
                try:
                    _remove_path_with_retry(child)
                except PermissionError as exc:
                    fatal_permission_error(exc, where=f"removing {child}")
                except OSError as exc:
                    logger.warning("Could not remove %s: %s", child, exc)
        else:
            logs_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        fatal_permission_error(exc, where=f"cleaning logs dir {logs_dir}")
    except OSError as exc:
        logger.warning("Failed to clean logs dir %s: %s", logs_dir, exc)


def _segments_root(user_dir: Path) -> Path:
    return user_dir / _SEGMENTS_DIRNAME


def _segments_dir_for(user_dir: Path, game_id: str) -> Path:
    return _segments_root(user_dir) / game_id


def _clear_segments_root(user_dir: Path) -> None:
    """Remove every staged segment dir for this runner. Idempotent."""
    root = _segments_root(user_dir)
    try:
        if root.is_dir():
            shutil.rmtree(root, ignore_errors=True)
    except OSError as exc:
        logger.warning("Failed to clean segments root %s: %s", root, exc)


# --- SQLite-stats mode helpers ---------------------------------------------


def _stats_db_sidecars(user_dir: Path) -> list[Path]:
    """The stats db and its WAL/SHM sidecar files."""
    db = stats_db_path(user_dir)
    return [db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")]


def _reset_stats_db(user_dir: Path) -> None:
    """Ensure the cache dir exists and delete any stale stats db + WAL sidecars."""
    db = stats_db_path(user_dir)
    db.parent.mkdir(parents=True, exist_ok=True)
    for p in _stats_db_sidecars(user_dir):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Could not delete stats db file %s: %s", p, exc)


def _checkpoint_and_read_stats_db(user_dir: Path) -> bytes | None:
    """Checkpoint the WAL and return the stats db bytes, or None if absent.

    The caller MUST have stopped the Civ5 process first so the file is
    unlocked and the WAL can be folded back into the main db file, producing a
    single self-contained ``.db`` safe to upload.
    """
    db = stats_db_path(user_dir)
    if not db.is_file():
        return None
    try:
        conn = sqlite3.connect(str(db), timeout=10.0)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("WAL checkpoint failed for %s: %s; reading as-is", db, exc)
    try:
        return db.read_bytes()
    except OSError as exc:
        logger.error("Could not read stats db %s: %s", db, exc)
        return None


# Per-file copy retry schedule (seconds). Civ5 / antivirus / Steam can hold
# log files briefly after the game process exits; a few short retries are
# almost always enough to get a clean copy. Kept short because it runs
# serially across every CSV in the Logs dir.
_SNAPSHOT_RETRY_BACKOFF_SEC: tuple[float, ...] = (0.25, 1.0)


def _copy_csv_with_retry(src: Path, dst: Path) -> bool:
    """Copy ``src`` to ``dst``, retrying briefly on PermissionError/OSError.

    Returns True on success, False if every attempt failed. Failures are
    logged but never raised — losing one segment file must not abort the
    whole snapshot (we still want to capture every other CSV).
    """
    last_exc: OSError | None = None
    for attempt, delay in enumerate((0.0, *_SNAPSHOT_RETRY_BACKOFF_SEC)):
        if delay:
            time.sleep(delay)
        try:
            shutil.copy2(src, dst)
            if attempt > 0:
                logger.info(
                    "Snapshot copy of %s succeeded after %d retr%s",
                    src.name,
                    attempt,
                    "y" if attempt == 1 else "ies",
                )
            return True
        except (PermissionError, OSError) as exc:
            last_exc = exc
    logger.warning(
        "Failed to snapshot CSV %s after %d attempts: %s",
        src,
        len(_SNAPSHOT_RETRY_BACKOFF_SEC) + 1,
        last_exc,
    )
    return False


def _snapshot_csv_segment(
    logs_dir: Path, game_id: str, user_dir: Path, *, label: str = "recovery"
) -> Path | None:
    """Copy every ``*.csv`` file in ``logs_dir`` into a fresh segment dir.

    Returns the new segment dir, or ``None`` if there were no CSVs to snapshot
    (e.g. recovery before turn 1). Segment dirs are numbered ``seg_000``,
    ``seg_001``, ... in chronological order so :func:`_consolidate_csv_segments`
    can splice them back together deterministically.

    Per-file copy errors are logged and skipped: losing one CSV must not
    abort the entire snapshot, since the other CSVs may be the only record
    we have of the turns played before this crash.
    """
    if not logs_dir.is_dir():
        logger.warning(
            "Snapshot (%s): logs_dir %s does not exist; nothing to capture",
            label,
            logs_dir,
        )
        return None
    try:
        csv_files = [p for p in logs_dir.iterdir() if p.is_file() and p.suffix.lower() == ".csv"]
    except OSError as exc:
        logger.warning("Snapshot (%s): failed to list %s: %s", label, logs_dir, exc)
        return None
    if not csv_files:
        logger.info(
            "Snapshot (%s): no CSV files in %s; nothing to capture",
            label,
            logs_dir,
        )
        return None
    seg_root = _segments_dir_for(user_dir, game_id)
    try:
        seg_root.mkdir(parents=True, exist_ok=True)
        existing = sorted(p.name for p in seg_root.iterdir() if p.is_dir())
        seg_dir = seg_root / f"seg_{len(existing):03d}"
        seg_dir.mkdir()
    except PermissionError as exc:
        fatal_permission_error(exc, where=f"creating segment dir under {seg_root}")
    except OSError as exc:
        logger.warning(
            "Snapshot (%s): failed to create segment dir under %s: %s",
            label,
            seg_root,
            exc,
        )
        return None
    copied = 0
    failed = 0
    for src in csv_files:
        if _copy_csv_with_retry(src, seg_dir / src.name):
            copied += 1
        else:
            failed += 1
    logger.info(
        "Snapshot (%s): captured %d/%d CSV log file(s) to %s (%d failed)",
        label,
        copied,
        len(csv_files),
        seg_dir,
        failed,
    )
    if copied == 0:
        # Empty segment dirs are harmless to consolidation but pollute the
        # numbering; clean up so the next snapshot reuses this index.
        try:
            seg_dir.rmdir()
        except OSError:
            pass
        return None
    return seg_dir


def _consolidate_csv_segments(logs_dir: Path, game_id: str, user_dir: Path) -> int:
    """Splice prior segment snapshots back into the current ``logs_dir`` CSVs.

    The current ``logs_dir`` content is treated as the *final* segment. For
    files in :data:`_HEADERED_CSVS` only the first segment's header row is
    kept; for all other CSVs the segments are concatenated raw.

    Returns the number of CSV files that were rewritten. Safe to call when
    no segments exist (returns 0).
    """
    seg_root = _segments_dir_for(user_dir, game_id)
    if not seg_root.is_dir():
        logger.info(
            "Consolidate: no segment root at %s for gameId=%s; nothing to splice",
            seg_root,
            game_id,
        )
        return 0
    seg_dirs = sorted(p for p in seg_root.iterdir() if p.is_dir())
    if not seg_dirs:
        logger.info(
            "Consolidate: segment root %s is empty for gameId=%s",
            seg_root,
            game_id,
        )
        return 0
    if not logs_dir.is_dir():
        logger.warning(
            "Consolidate: logs_dir %s missing; cannot write consolidated CSVs",
            logs_dir,
        )
        return 0

    # Collect every CSV name across all segments + current logs_dir.
    names: set[str] = set()
    for d in seg_dirs:
        for p in d.iterdir():
            if p.is_file() and p.suffix.lower() == ".csv":
                names.add(p.name)
    for p in logs_dir.iterdir():
        if p.is_file() and p.suffix.lower() == ".csv":
            names.add(p.name)

    logger.info(
        "Consolidate: %d segment(s) %s + current logs_dir; %d distinct CSV name(s)",
        len(seg_dirs),
        [d.name for d in seg_dirs],
        len(names),
    )

    rewritten = 0
    for name in sorted(names):
        sources: list[Path] = []
        for d in seg_dirs:
            cand = d / name
            if cand.is_file():
                sources.append(cand)
        current = logs_dir / name
        current_present = current.is_file()
        if current_present:
            sources.append(current)
        if not sources:
            continue
        if len(sources) == 1 and current_present:
            # Only the current logs_dir copy exists — nothing to splice in.
            continue
        has_header = name in _HEADERED_CSVS
        out = bytearray()
        for i, src in enumerate(sources):
            try:
                data = src.read_bytes()
            except OSError as exc:
                logger.warning(
                    "Skipping segment %s while consolidating %s: %s",
                    src,
                    name,
                    exc,
                )
                continue
            if has_header and i > 0:
                nl = data.find(b"\n")
                if nl >= 0:
                    data = data[nl + 1 :]
                else:
                    # Header-only file with no newline — drop it entirely.
                    data = b""
            if data and not data.endswith((b"\n", b"\r")) and i < len(sources) - 1:
                data = data + b"\n"
            out.extend(data)
        try:
            (logs_dir / name).write_bytes(bytes(out))
            rewritten += 1
            logger.debug(
                "Consolidate: wrote %s (%d bytes from %d source(s); current_present=%s)",
                name,
                len(out),
                len(sources),
                current_present,
            )
        except OSError as exc:
            logger.warning("Failed to write consolidated %s: %s", name, exc)

    if rewritten:
        logger.info(
            "Consolidated %d CSV file(s) across %d segment(s) for gameId=%s",
            rewritten,
            len(seg_dirs),
            game_id,
        )
    return rewritten


class GameController:
    def __init__(self, cfg: RunnerConfig, state: RunnerGlobalState) -> None:
        self._cfg = cfg
        self._state = state
        self._proc: subprocess.Popen[bytes] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._sqlite_mode = cfg.stats_mode == "sqlite"

    async def _completion_present(self, logs_dir: Path) -> bool:
        """True when the current game has finished (mode-aware)."""
        if self._sqlite_mode:
            return await asyncio.to_thread(sqlite_game_complete, stats_db_path(self._cfg.user_dir))
        return await asyncio.to_thread(game_result_present, logs_dir)

    async def _read_turn(self, logs_dir: Path) -> int | None:
        """Read the latest turn for the current game (mode-aware)."""
        if self._sqlite_mode:
            return await asyncio.to_thread(read_current_turn_sqlite, stats_db_path(self._cfg.user_dir))
        return await asyncio.to_thread(read_current_turn, logs_dir)

    def _resolve_exe(self) -> Path:
        """Return the path to ``CivilizationV_DX11.exe`` under the install dir.

        Does no waiting/availability check; callers that need the exe to be
        readable should use :meth:`_wait_for_exe`.
        """
        return self._cfg.install_dir / "CivilizationV_DX11.exe"

    def _log_exe_state(self, label: str) -> None:
        """Log a one-line snapshot of the exe's existence/size/mtime.

        Used to debug "exe vanishes between runs" issues — comparing these
        log lines pinpoints exactly which lifecycle step lost the file
        (typical real-world cause: antivirus quarantining the d3d9.dll
        side-loading pattern, Steam auto-update, or OneDrive offloading).

        Synchronous: only call from non-async paths or via
        :meth:`_log_exe_state_async` from inside the event loop.
        """
        exe = self._resolve_exe()
        try:
            st = exe.stat()
            logger.info(
                "EXE_STATE [%s] %s exists=True size=%d mtime=%s",
                label,
                exe,
                st.st_size,
                datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            )
        except FileNotFoundError:
            # Also log a directory listing so the user can see what's left.
            try:
                siblings = sorted(p.name for p in self._cfg.install_dir.iterdir())
            except OSError:
                siblings = []
            logger.error(
                "EXE_STATE [%s] %s exists=False  install_dir contents=%s",
                label,
                exe,
                siblings,
            )
        except OSError as exc:
            logger.warning("EXE_STATE [%s] %s stat failed: %s", label, exe, exc)

    async def _log_exe_state_async(self, label: str) -> None:
        """Async wrapper around :meth:`_log_exe_state` so we never stall the loop."""
        await asyncio.to_thread(self._log_exe_state, label)

    async def _wait_for_exe(self, timeout_sec: float = _EXE_WAIT_TIMEOUT_SEC) -> Path:
        """Resolve the exe and wait up to ``timeout_sec`` for it to be readable.

        Raises :class:`NoInstallError` if ``CivilizationV_DX11.exe`` is still
        missing / not readable when the deadline expires. Logs the cause of
        each failed probe so operators can distinguish "file missing" from
        "file locked / wrong permissions".
        """
        exe = self._resolve_exe()
        deadline = time.time() + timeout_sec
        last_reason: str | None = None
        while True:
            try:
                if exe.is_file():
                    # Open for read to confirm we actually have permission.
                    with exe.open("rb"):
                        pass
                    if last_reason is not None:
                        logger.info("Civ5 exe became accessible after waiting: %s", exe)
                    return exe
                last_reason = "file does not exist"
            except PermissionError as exc:
                last_reason = f"PermissionError: {exc}"
            except OSError as exc:
                last_reason = f"OSError: {exc}"

            if time.time() >= deadline:
                logger.error(
                    "Civ5 exe %s still not accessible after %.0fs (last reason: %s)",
                    exe,
                    timeout_sec,
                    last_reason,
                )
                raise NoInstallError(
                    f"CivilizationV_DX11.exe not accessible at {exe} after {timeout_sec:.0f}s ({last_reason})"
                )
            logger.warning(
                "Civ5 exe not yet accessible (%s); waiting up to %.0fs",
                last_reason,
                deadline - time.time(),
            )
            await asyncio.sleep(_EXE_WAIT_POLL_SEC)

    async def _await_process_started(self, proc: subprocess.Popen[bytes], timeout_sec: float) -> None:
        """Confirm the spawned process either persists or dies within ``timeout_sec``.

        Polls ``proc.poll()`` once per second. If the process exits during this
        window the caller will pick up the death and react. This gives a
        single, clearly-logged "did the OS actually start the exe?" gate
        before the long-running monitor loop takes over.
        """
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            await asyncio.sleep(1.0)
            if proc.poll() is not None:
                logger.warning("Civ5 process exited within startup window (rc=%s)", proc.returncode)
                return
        logger.info("Civ5 process startup window elapsed (pid=%s alive)", proc.pid)

    @property
    def is_running(self) -> bool:
        return self._monitor_task is not None and not self._monitor_task.done()

    def _maybe_reschedule(self) -> None:
        """If scheduling is enabled, launch another game after the current one.

        If the runner has pending uploads queued locally (i.e. the hypervisor
        was unreachable when the previous game's artifacts were submitted),
        the relaunch is *deferred*: the runner stays idle and sets
        ``state.pending_reschedule = True``. The heartbeat loop will trigger
        the deferred relaunch the next time a heartbeat succeeds (i.e. as
        soon as the hypervisor is back online and our pending uploads can be
        drained).
        """
        from autoplay.runner.pending_uploads import pending_count

        with self._state.lock:
            should = self._state.is_scheduling_games
        if not should:
            return

        if pending_count(self._cfg.pending_uploads_dir) > 0:
            with self._state.lock:
                self._state.pending_reschedule = True
            logger.info(
                "Hypervisor appears down (pending uploads queued); "
                "staying idle, will resume scheduling once it returns."
            )
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

    def trigger_deferred_reschedule(self) -> None:
        """Public hook for the heartbeat loop to call when the hypervisor recovers."""
        with self._state.lock:
            if not self._state.pending_reschedule:
                return
            if self.is_running:
                return
            if not self._state.is_scheduling_games:
                self._state.pending_reschedule = False
                return
            self._state.pending_reschedule = False
        logger.info("Hypervisor recovered; resuming deferred game schedule.")
        self._maybe_reschedule()

    def _spawn_civ5(self, exe: Path, args: list[str] | None = None) -> subprocess.Popen[bytes]:
        """Spawn Civ5, retrying briefly on transient FileNotFoundError.

        ``args`` are passed to the executable. Pass ``["-Automation",
        "RunAutoplayGame.lua"]`` to start a fresh autoplay game, or ``None``/
        ``[]`` to launch the menu — which the patched FrontEnd/MainMenu Lua
        files configure to auto-load the most recent autosave (used for
        crash recovery).

        After a crashed Civ5 process exits, Windows (often combined with
        antivirus / Steam overlay) can briefly cause ``CreateProcess`` to
        return ``ERROR_FILE_NOT_FOUND`` for the very same exe that will
        succeed a moment later. We retry up to a few times with a short
        delay. Passing ``executable=`` explicitly avoids any command-line
        parsing of the quoted, space- and apostrophe-containing path.
        """
        cmd = [str(exe), *(args or [])]
        last_exc: Exception | None = None
        for attempt in range(1, 6):
            try:
                return subprocess.Popen(  # noqa: S603
                    cmd,
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
        # Drop any leftover CSV segment snapshots from a prior game so they
        # cannot bleed into this run's harvest.
        await asyncio.to_thread(_clear_segments_root, self._cfg.user_dir)
        # SQLite-stats mode: ensure the cache dir exists and remove any stale
        # stats.db so a previous game's GameResult rows can't be mistaken for
        # this run's completion.
        if self._sqlite_mode:
            await asyncio.to_thread(_reset_stats_db, self._cfg.user_dir)

        game_id = _make_game_id()
        await self._log_exe_state_async("start:before-wait")
        exe = await self._wait_for_exe()
        logger.info("Launching %s (gameId=%s, exists=%s)", exe, game_id, exe.is_file())

        # Fresh starts must NOT auto-load the most recent autosave; ensure the
        # patched MainMenu.lua has ``loadOnStart = false`` before launching.
        await asyncio.to_thread(set_load_on_start, self._cfg.install_dir, enabled=False)
        self._proc = await asyncio.to_thread(self._spawn_civ5, exe, ["-Automation", "RunAutoplayGame.lua"])
        # Fire-and-forget startup-window watcher: logs early-death within 30s
        # so the process-launch-vs-game-startup distinction is visible in
        # logs. The main monitor task below also polls proc death every 1s.
        asyncio.create_task(
            self._await_process_started(self._proc, _PROC_START_WAIT_SEC),
            name="proc-startup-watch",
        )

        with self._state.lock:
            self._state.state = RunnerState.starting
            self._state.current_game_id = game_id
            self._state.current_game_start_time = time.time()
            self._state.current_game_turn = None

        self._monitor_task = asyncio.create_task(self._monitor(logs_dir, game_id), name="game-monitor")
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
        await asyncio.to_thread(_clear_segments_root, self._cfg.user_dir)
        if self._sqlite_mode:
            await asyncio.to_thread(_reset_stats_db, self._cfg.user_dir)

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
        last_crash_check_ts = 0.0
        last_exe_check_ts = 0.0
        exe_path = self._resolve_exe()
        exe_was_present = await asyncio.to_thread(exe_path.is_file)

        try:
            while True:
                await asyncio.sleep(_MONITOR_POLL_SEC)

                proc = self._proc
                if proc is None:
                    return
                proc_alive = proc.poll() is None
                now = time.time()

                # Periodic exe-existence audit. The exe sometimes disappears
                # mid-game (typically antivirus quarantine of the d3d9.dll
                # side-loading pattern, or Steam auto-update). Logging the
                # exact moment makes the cause traceable.
                if now - last_exe_check_ts >= 30.0:
                    last_exe_check_ts = now
                    exe_present = await asyncio.to_thread(exe_path.is_file)
                    if exe_was_present and not exe_present:
                        logger.error(
                            "EXE_STATE [monitor] %s VANISHED at game elapsed %.0fs "
                            "(game_id=%s, last_turn=%s, proc_alive=%s) — likely "
                            "antivirus/Steam/OneDrive interference",
                            exe_path,
                            now - start_time,
                            game_id,
                            last_turn,
                            proc_alive,
                        )
                    elif not exe_was_present and exe_present:
                        logger.info(
                            "EXE_STATE [monitor] %s reappeared at game elapsed %.0fs",
                            exe_path,
                            now - start_time,
                        )
                    exe_was_present = exe_present

                # Throttled "Game Crash" window check. If the game has
                # popped its in-process crash dialog, the parent process is
                # technically still alive, so we have to detect it by window
                # title and force-kill the tree to enter the recovery flow.
                poll_ms = max(0, int(cfg.crash_handler_poll_ms))
                if proc_alive and poll_ms > 0 and (now - last_crash_check_ts) * 1000.0 >= poll_ms:
                    last_crash_check_ts = now
                    if await asyncio.to_thread(crash_handler_window_present):
                        logger.error(
                            "Detected 'Game Crash' window after %.0fs (game_id=%s, "
                            "last_turn=%s, pid=%s); killing process tree and "
                            "entering recovery flow.",
                            now - start_time,
                            game_id,
                            last_turn,
                            getattr(proc, "pid", None),
                        )
                        await asyncio.to_thread(_kill_process_tree, proc.pid)
                        proc_alive = False

                if await self._completion_present(logs_dir):
                    logger.info("Game completion detected; harvesting results")
                    await self._harvest_and_submit_complete(logs_dir, game_id)
                    return

                if not proc_alive:
                    rc = getattr(proc, "returncode", None)
                    logger.error(
                        "Civ5 process exited unexpectedly after %.0fs "
                        "(game_id=%s, last_turn=%s, exitcode=%s); "
                        "starting recovery flow",
                        now - start_time,
                        game_id,
                        last_turn,
                        rc,
                    )
                    recovered = await self._attempt_recovery(logs_dir, game_id, crashed_turn=last_turn)
                    if not recovered:
                        await self._harvest_and_submit_crash(logs_dir, game_id, reason="process_died")
                        return
                    # Recovery succeeded — refresh local tracking from state
                    # and continue monitoring this same game_id.
                    snap = state.snapshot()
                    last_turn = snap.current_game_turn or last_turn
                    last_turn_ts = time.time()
                    got_any_log = True
                    continue

                turn = await self._read_turn(logs_dir)
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
                    logger.error(
                        "Startup timeout: no log output within %ss (game_id=%s, proc_alive=%s, exitcode=%s)",
                        cfg.startup_timeout_sec,
                        game_id,
                        proc_alive,
                        getattr(proc, "returncode", None),
                    )
                    await self._harvest_and_submit_crash(logs_dir, game_id, reason="startup_timeout")
                    return

                if got_any_log and (now - last_turn_ts) > cfg.turn_timeout_sec:
                    logger.error(
                        "Turn timeout: no progress in %ss (game_id=%s, last_turn=%s, "
                        "proc_alive=%s, pid=%s); treating as a freeze and "
                        "entering recovery flow.",
                        cfg.turn_timeout_sec,
                        game_id,
                        last_turn,
                        proc_alive,
                        getattr(proc, "pid", None),
                    )
                    # Kill the wedged process tree before recovery can
                    # spawn a fresh one.
                    if proc_alive:
                        await asyncio.to_thread(_kill_process_tree, proc.pid)
                    recovered = await self._attempt_recovery(logs_dir, game_id, crashed_turn=last_turn)
                    if not recovered:
                        await self._harvest_and_submit_crash(logs_dir, game_id, reason="turn_timeout")
                        return
                    snap = state.snapshot()
                    last_turn = snap.current_game_turn or last_turn
                    last_turn_ts = time.time()
                    got_any_log = True
                    continue
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Game monitor crashed; marking as failed")
            with state.lock:
                state.state = RunnerState.failed
            raise

    async def _attempt_recovery(
        self,
        logs_dir: Path,
        game_id: str,
        *,
        crashed_turn: int,
    ) -> bool:
        """Try to recover a crashed game by relaunching the exe without -Automation.

        The patched ``FrontEnd.lua`` / ``MainMenu.lua`` files configured by
        :func:`autoplay.runner.patcher.install_patched_files` cause the game
        to auto-load the most recent autosave when launched with no arguments,
        so this is exactly what a crash recovery looks like.

        Returns True if any attempt observed turn progression beyond
        ``crashed_turn`` (in which case the runner state is set back to
        ``running`` and the caller should keep monitoring); returns False if
        every attempt either died again or made no progress within the
        configured per-attempt timeout.

        On success a single ``recovered`` heartbeat pulse is sent
        out-of-band so the hypervisor can bump its ``recovery_count``
        without waiting for the heartbeat loop's next tick.
        """
        cfg = self._cfg
        state = self._state
        max_attempts = max(0, cfg.recovery_max_attempts)
        if max_attempts == 0 or crashed_turn <= 0:
            # Nothing meaningful to recover from (game never reached turn 1).
            logger.warning(
                "Skipping recovery (max_attempts=%d, crashed_turn=%d): no autosave to reload from.",
                max_attempts,
                crashed_turn,
            )
            return False

        # Snapshot the live CSV log files RIGHT NOW, before _wait_for_exe
        # potentially blocks for tens of seconds and before any recovery
        # process can truncate them. This is the only chance we have to
        # capture the data from the run that just crashed. In SQLite-stats
        # mode there are no CSV segments — the persistent stats.db in
        # ``cache/`` survives the recovery relaunch — so this is skipped.
        if not self._sqlite_mode:
            await asyncio.to_thread(
                _snapshot_csv_segment,
                logs_dir,
                game_id,
                cfg.user_dir,
                label=f"crash@turn{crashed_turn}",
            )

        try:
            await self._log_exe_state_async("recovery:before-wait")
            exe = await self._wait_for_exe()
        except NoInstallError as exc:
            logger.error("Recovery aborted: %s", exc)
            with state.lock:
                state.state = RunnerState.failed
            return False
        for attempt in range(1, max_attempts + 1):
            with state.lock:
                state.state = RunnerState.attempting_recovery
            logger.info(
                "Recovery attempt %d/%d for gameId=%s (crashed_turn=%s)",
                attempt,
                max_attempts,
                game_id,
                crashed_turn,
            )

            # Make sure no leftover process is still around.
            if self._proc is not None and self._proc.poll() is None:
                await asyncio.to_thread(_kill_process_tree, self._proc.pid)
            self._proc = None

            # On retry attempts, snapshot again — the previous failed
            # attempt's Civ5 may have truncated/partially-overwritten the
            # CSVs before dying, and any progress it made (even a few
            # turns) is still worth capturing for the consolidated bundle.
            # Skip on attempt 1 because we already snapshotted above
            # before _wait_for_exe.
            if attempt > 1:
                await asyncio.to_thread(
                    _snapshot_csv_segment,
                    logs_dir,
                    game_id,
                    cfg.user_dir,
                    label=f"retry{attempt}@turn{crashed_turn}",
                )

            # Recovery launches must auto-load the most recent autosave; flip
            # the patched MainMenu.lua's ``loadOnStart`` flag to true.
            await asyncio.to_thread(set_load_on_start, cfg.install_dir, enabled=True)
            try:
                self._proc = await asyncio.to_thread(self._spawn_civ5, exe, [])
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Recovery attempt %d/%d for gameId=%s failed to spawn %s: %s",
                    attempt,
                    max_attempts,
                    game_id,
                    exe,
                    exc,
                )
                continue
            logger.info(
                "Recovery attempt %d/%d spawned recovery process pid=%s",
                attempt,
                max_attempts,
                getattr(self._proc, "pid", None),
            )

            recovered = await self._watch_recovery(logs_dir, crashed_turn, cfg.recovery_attempt_timeout_sec)
            if recovered:
                with state.lock:
                    state.state = RunnerState.recovered
                # Pulse a single ``recovered`` heartbeat out-of-band so the
                # hypervisor's recovery counter ticks exactly once per
                # successful recovery.
                await self._send_pulse_heartbeat(RunnerState.recovered)
                with state.lock:
                    state.state = RunnerState.running
                logger.info(
                    "Recovery succeeded on attempt %d (turn now %s, was %s)",
                    attempt,
                    state.current_game_turn,
                    crashed_turn,
                )
                return True

            logger.warning(
                "Recovery attempt %d/%d made no turn progress; will retry",
                attempt,
                max_attempts,
            )

        logger.error(
            "All %d recovery attempts exhausted for gameId=%s; marking as failed",
            max_attempts,
            game_id,
        )
        return False

    async def _watch_recovery(self, logs_dir: Path, crashed_turn: int, timeout_sec: int) -> bool:
        """Poll until the recovered game progresses past ``crashed_turn`` or dies/times out."""
        deadline = time.time() + timeout_sec
        poll_ms = max(0, int(self._cfg.crash_handler_poll_ms))
        last_crash_check_ts = 0.0
        while time.time() < deadline:
            await asyncio.sleep(_MONITOR_POLL_SEC)
            proc = self._proc
            if proc is None:
                return False
            if proc.poll() is not None:
                logger.warning(
                    "Recovery process pid=%s exited (rc=%s) before progressing past turn %s",
                    getattr(proc, "pid", None),
                    getattr(proc, "returncode", None),
                    crashed_turn,
                )
                return False
            now = time.time()
            if poll_ms > 0 and (now - last_crash_check_ts) * 1000.0 >= poll_ms:
                last_crash_check_ts = now
                if await asyncio.to_thread(crash_handler_window_present):
                    logger.warning(
                        "Detected 'Game Crash' window during recovery "
                        "(pid=%s); killing process tree to fail this attempt",
                        getattr(proc, "pid", None),
                    )
                    await asyncio.to_thread(_kill_process_tree, proc.pid)
                    return False
            turn = read_current_turn(logs_dir)
            if turn is not None:
                with self._state.lock:
                    self._state.current_game_turn = turn
                if turn > crashed_turn:
                    return True
        logger.warning(
            "Recovery attempt timed out after %ss without passing turn %s",
            timeout_sec,
            crashed_turn,
        )
        return False

    async def _send_pulse_heartbeat(self, pulse_state: RunnerState) -> None:
        """Best-effort one-shot heartbeat with a specific state value."""
        from autoplay.common import HeartbeatPayload

        snap = self._state.snapshot()
        time_elapsed = (
            int(time.time() - snap.current_game_start_time)
            if snap.current_game_start_time is not None
            else None
        )
        payload = HeartbeatPayload(
            uuid=snap.uuid,
            state=pulse_state,
            game_id=snap.current_game_id,
            turn=snap.current_game_turn,
            time_elapsed_sec=time_elapsed,
            url=snap.url,
            modpack=snap.modpack,
        )
        url = f"{self._cfg.hypervisor_url.rstrip('/')}/runner-heartbeat"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json=payload.model_dump(by_alias=True))
        except httpx.HTTPError as exc:
            logger.warning("Pulse heartbeat (%s) failed: %s", pulse_state.value, exc)

    async def _harvest_and_submit_complete(self, logs_dir: Path, game_id: str) -> None:
        if self._sqlite_mode:
            await self._harvest_and_submit_complete_sqlite(game_id)
            return
        state = self._state
        cfg = self._cfg
        modpack = state.modpack or "unknown"

        with state.lock:
            state.state = RunnerState.harvesting_logs
        # Splice any per-recovery CSV snapshots back into the live logs dir
        # so the harvested bundle reflects every turn played, not just those
        # since the most recent restart.
        await asyncio.to_thread(_consolidate_csv_segments, logs_dir, game_id, cfg.user_dir)
        bundle = await asyncio.to_thread(_make_tar_gz, logs_dir, cfg.log_ignore_patterns)
        logger.info("Logs harvested: gameId=%s bytes=%s", game_id, len(bundle))

        if self._proc is not None and self._proc.poll() is None:
            await asyncio.to_thread(_kill_process_tree, self._proc.pid)

        with state.lock:
            state.state = RunnerState.uploading_logs
        snap = state.snapshot()
        time_elapsed = (
            int(time.time() - snap.current_game_start_time)
            if snap.current_game_start_time is not None
            else None
        )
        await self._upload(
            endpoint="/submit-logs",
            modpack=modpack,
            game_id=game_id,
            filename=f"{game_id}.tar",
            content=bundle,
            final=True,
            extra_fields={
                "turn": snap.current_game_turn,
                "timeElapsedSec": time_elapsed,
                "runnerUrl": snap.url,
            },
        )
        logger.info("Logs uploaded: gameId=%s", game_id)
        await self._log_exe_state_async("complete-end")

        with state.lock:
            state.state = RunnerState.idle
            state.current_game_id = None
            state.current_game_start_time = None
            state.current_game_turn = None

        await asyncio.to_thread(_clear_segments_root, cfg.user_dir)
        self._maybe_reschedule()

    async def _harvest_and_submit_complete_sqlite(self, game_id: str) -> None:
        """SQLite-stats completion: stop Civ5, checkpoint+upload stats.db, delete local."""
        state = self._state
        cfg = self._cfg
        modpack = state.modpack or "unknown"

        with state.lock:
            state.state = RunnerState.harvesting_logs
        # Civ5 must be fully stopped before we touch the SQLite file so the WAL
        # is flushed back into the main db and the file is unlocked.
        if self._proc is not None and self._proc.poll() is None:
            await asyncio.to_thread(_kill_process_tree, self._proc.pid)
        self._proc = None

        content = await asyncio.to_thread(_checkpoint_and_read_stats_db, cfg.user_dir)
        if content is None:
            logger.error(
                "Stats db missing at completion (gameId=%s); nothing to upload",
                game_id,
            )
        else:
            logger.info("Stats db harvested: gameId=%s bytes=%s", game_id, len(content))
            with state.lock:
                state.state = RunnerState.uploading_logs
            snap = state.snapshot()
            time_elapsed = (
                int(time.time() - snap.current_game_start_time)
                if snap.current_game_start_time is not None
                else None
            )
            await self._upload(
                endpoint="/submit-stats",
                modpack=modpack,
                game_id=game_id,
                filename=f"{game_id}.db",
                content=content,
                final=True,
                extra_fields={
                    "turn": snap.current_game_turn,
                    "timeElapsedSec": time_elapsed,
                    "runnerUrl": snap.url,
                },
            )
            logger.info("Stats uploaded: gameId=%s", game_id)
            # The bytes are now either accepted by the hypervisor or staged in
            # pending_uploads, so the local copy is safe to drop.
            await asyncio.to_thread(_reset_stats_db, cfg.user_dir)

        await self._log_exe_state_async("complete-end")
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
        if self._sqlite_mode:
            await self._harvest_and_submit_crash_sqlite(game_id, reason=reason)
            return
        state = self._state
        cfg = self._cfg
        modpack = state.modpack or "unknown"

        with state.lock:
            state.state = RunnerState.failed

        # Pre-read both artifacts so we know which upload will be the last.
        try:
            await asyncio.to_thread(_consolidate_csv_segments, logs_dir, game_id, cfg.user_dir)
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
        except PermissionError as exc:
            fatal_permission_error(exc, where=f"reading crash autosave under {cfg.user_dir}")
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
        await self._log_exe_state_async(f"crash-end:{reason}")
        await asyncio.sleep(2)
        with state.lock:
            state.state = RunnerState.idle
            state.current_game_id = None
            state.current_game_start_time = None
            state.current_game_turn = None

        await asyncio.to_thread(_clear_segments_root, cfg.user_dir)
        self._maybe_reschedule()

    async def _harvest_and_submit_crash_sqlite(self, game_id: str, *, reason: str) -> None:
        """SQLite-stats crash path: upload the partial stats.db (NOT ingested) + autosave."""
        state = self._state
        cfg = self._cfg
        modpack = state.modpack or "unknown"

        with state.lock:
            state.state = RunnerState.failed

        # Stop Civ5 before reading the SQLite file so it is unlocked.
        if self._proc is not None and self._proc.poll() is None:
            await asyncio.to_thread(_kill_process_tree, self._proc.pid)
        self._proc = None

        db_bytes = await asyncio.to_thread(_checkpoint_and_read_stats_db, cfg.user_dir)

        autosave_path: Path | None = None
        autosave_bytes: bytes | None = None
        try:
            autosave_path = find_most_recent_autosave(cfg.user_dir)
            if autosave_path is not None:
                autosave_bytes = await asyncio.to_thread(autosave_path.read_bytes)
        except PermissionError as exc:
            fatal_permission_error(exc, where=f"reading crash autosave under {cfg.user_dir}")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to read crash autosave")
            autosave_path = None
            autosave_bytes = None

        have_autosave = autosave_path is not None and autosave_bytes is not None

        if db_bytes:
            try:
                await self._upload(
                    endpoint="/submit-crash",
                    modpack=modpack,
                    game_id=game_id,
                    filename=f"{game_id}.db",
                    content=db_bytes,
                    final=not have_autosave,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to upload partial stats db for crashed game")

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

        await asyncio.to_thread(_reset_stats_db, cfg.user_dir)
        logger.info("Crash-path upload complete (reason=%s)", reason)
        await self._log_exe_state_async(f"crash-end:{reason}")
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
        extra_fields: dict[str, Any] | None = None,
    ) -> None:
        """Upload an artifact, falling back to local staging if the hypervisor is unreachable.

        Network/transport errors and 5xx responses cause the bundle to be
        written to ``cfg.pending_uploads_dir`` instead. A background drain
        loop will retry it later. 4xx responses are treated as terminal
        rejections and only logged (not staged).
        """
        from autoplay.runner.pending_uploads import stage_upload

        url = f"{self._cfg.hypervisor_url.rstrip('/')}{endpoint}"
        form: dict[str, str] = {
            "modpack": modpack,
            "gameId": game_id,
            "runnerUuid": self._state.uuid,
            "final": "true" if final else "false",
        }
        if extra_fields:
            for k, v in extra_fields.items():
                if v is not None:
                    form[k] = str(v)
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                r = await client.post(
                    url,
                    data=form,
                    files={"file": (filename, content, "application/octet-stream")},
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "%s upload transport failure (%s); staging for later retry",
                endpoint,
                exc,
            )
            stage_upload(
                self._cfg.pending_uploads_dir,
                endpoint=endpoint,
                modpack=modpack,
                game_id=game_id,
                runner_uuid=self._state.uuid,
                filename=filename,
                content=content,
                final=final,
                extra_fields=extra_fields,
            )
            return

        if r.status_code >= 500:
            logger.warning(
                "%s upload server error (%s); staging for later retry",
                endpoint,
                r.status_code,
            )
            stage_upload(
                self._cfg.pending_uploads_dir,
                endpoint=endpoint,
                modpack=modpack,
                game_id=game_id,
                runner_uuid=self._state.uuid,
                filename=filename,
                content=content,
                final=final,
                extra_fields=extra_fields,
            )
        elif r.status_code >= 400:
            logger.error("%s upload rejected: %s %s", endpoint, r.status_code, r.text)
        else:
            logger.info("%s upload OK (%s bytes)", endpoint, len(content))

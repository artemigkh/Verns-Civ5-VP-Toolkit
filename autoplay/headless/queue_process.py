"""The ``c5h queue run`` process that plays a batch.

c5h needs only the Python standard library (3.11+), so it runs on the release kit's own
``runtime\\python.exe`` when there is one, else on this interpreter, with ``<c5h_dir>\\python`` on
``PYTHONPATH`` (what ``c5h.cmd`` does, without ``cmd /c`` quoting). Its working folder is ``c5h_dir``,
so the checkout's ``civ5headless.toml`` applies.

The process gets its own process group, so a Ctrl-C in the bridge's console does not reach it, and
``<work_dir>/queue.pid.json`` names it, so a restarted bridge can adopt a queue that kept playing.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

from autoplay.headless.batches import Batch
from autoplay.headless.config import HeadlessConfig

logger = logging.getLogger(__name__)

PID_FILENAME = "queue.pid.json"

_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000


def c5h_command(cfg: HeadlessConfig, batch: Batch) -> tuple[list[str], dict[str, str]]:
    """(argv, environment) of ``c5h queue run <batch>``."""
    kit_python = cfg.c5h_dir / "runtime" / "python.exe"
    python = str(kit_python) if kit_python.is_file() else sys.executable
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(cfg.c5h_dir / "python"), env.get("PYTHONPATH")) if p)
    env["PYTHONUNBUFFERED"] = "1"
    return [python, "-m", "civ5headless", "queue", "run", str(batch.path)], env


class QueueProcess:
    """The one c5h queue process the bridge runs (or adopted)."""

    def __init__(self, cfg: HeadlessConfig) -> None:
        self.cfg = cfg
        self.batch: Batch | None = None
        self.started_at: float | None = None
        self._popen: subprocess.Popen | None = None
        self._proc: psutil.Process | None = None

    @property
    def pid_path(self) -> Path:
        return self.cfg.work_dir / PID_FILENAME

    def running(self) -> bool:
        if self._popen is not None:
            return self._popen.poll() is None
        if self._proc is not None:
            try:
                return self._proc.is_running() and self._proc.status() != psutil.STATUS_ZOMBIE
            except psutil.Error:
                return False
        return False

    def returncode(self) -> int | None:
        return self._popen.poll() if self._popen is not None else None

    def start(self, batch: Batch) -> None:
        if self.running():
            raise RuntimeError("a c5h queue is already running")
        batch.stop_path.unlink(missing_ok=True)  # a stop left by an earlier drain would end it at once
        argv, env = c5h_command(self.cfg, batch)
        log_dir = self.cfg.work_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / f"{batch.name}.out").open("ab") as out:
            self._popen = subprocess.Popen(
                argv,
                cwd=str(self.cfg.c5h_dir),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=_CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW,
            )
        self._proc = None
        self.batch = batch
        self.started_at = time.time()
        try:
            create_time = psutil.Process(self._popen.pid).create_time()
        except psutil.Error:
            create_time = None
        self.pid_path.write_text(
            json.dumps({"pid": self._popen.pid, "createTime": create_time, "batch": str(batch.path)}),
            encoding="utf-8",
        )
        logger.info("Started c5h queue %s (pid %d): %s", batch.name, self._popen.pid, " ".join(argv))

    def adopt(self) -> bool:
        """Take over a queue a previous bridge left running. Returns True if one was adopted."""
        try:
            info = json.loads(self.pid_path.read_text(encoding="utf-8"))
            proc = psutil.Process(int(info["pid"]))
            if info.get("createTime") is not None and abs(proc.create_time() - float(info["createTime"])) > 1:
                return False  # the pid was reused
            if not proc.is_running():
                return False
        except (OSError, ValueError, KeyError, TypeError, psutil.Error):
            return False
        self._proc, self._popen = proc, None
        self.batch = Batch(Path(info["batch"]))
        self.started_at = proc.create_time()
        logger.info("Adopted running c5h queue %s (pid %d)", self.batch.name, proc.pid)
        return True

    def request_stop(self) -> None:
        """Let the queue drain: c5h starts no new game, running games finish, then it exits."""
        if self.batch is not None:
            self.batch.stop_path.touch()

    def cancel_stop(self) -> None:
        if self.batch is not None:
            self.batch.stop_path.unlink(missing_ok=True)

    def kill(self) -> None:
        """End the queue and its games now (c5h re-queues the games it was playing at its next start)."""
        pid = (
            self._popen.pid if self._popen is not None else self._proc.pid if self._proc is not None else None
        )
        if pid is None or not self.running():
            return
        try:
            root = psutil.Process(pid)
            procs = root.children(recursive=True) + [root]
        except psutil.Error:
            procs = []
        for p in procs:
            with contextlib.suppress(psutil.Error):
                p.kill()
        psutil.wait_procs(procs, timeout=10)
        logger.info("Killed c5h queue (pid %d) and %d game(s)", pid, max(len(procs) - 1, 0))

"""Fatal-error helpers for the runner.

The runner is stateless and worthless once the OS denies it access to the
log/install/save directories: any in-flight game cannot be harvested, and any
new game would crash the same way. When that happens, log a clear message and
forcibly terminate the process so the operator (or whatever supervises the
.bat launcher) is notified immediately rather than letting the runner spin in
a permission-error loop.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import NoReturn

logger = logging.getLogger(__name__)

# Free-space threshold (bytes) below which we emit a startup warning.
LOW_DISK_THRESHOLD_BYTES = 50 * 1024 * 1024 * 1024  # 50 GiB


def fatal_permission_error(exc: PermissionError, where: str) -> NoReturn:
    """Log ``exc`` with context and abort the process.

    Uses ``os._exit`` so that no atexit / shutdown hooks can swallow the
    failure; the supervising launcher will see a non-zero exit code.
    """
    logger.critical(
        "FATAL: file permission error while %s: %s. "
        "Runner cannot continue and is shutting down.",
        where,
        exc,
    )
    # Flush stdio/log handlers best-effort before _exit.
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:  # noqa: BLE001
            pass
    os._exit(1)


def warn_if_low_disk_space(logs_dir: Path) -> None:
    """Emit a warning if the drive holding ``logs_dir`` has < 50 GiB free."""
    probe = logs_dir if logs_dir.exists() else logs_dir.parent
    while probe and not probe.exists():
        probe = probe.parent
    if probe is None or not probe.exists():
        logger.warning(
            "Cannot check free disk space; neither %s nor any parent exists.",
            logs_dir,
        )
        return
    try:
        usage = shutil.disk_usage(probe)
    except OSError as exc:
        logger.warning("Cannot check free disk space on %s: %s", probe, exc)
        return
    free_gib = usage.free / (1024 ** 3)
    if usage.free < LOW_DISK_THRESHOLD_BYTES:
        logger.warning(
            "LOW DISK SPACE: only %.1f GiB free on the drive containing %s "
            "(threshold: 50 GiB). Autoplay logs may fail to harvest.",
            free_gib,
            probe,
        )
    else:
        logger.info("Disk free on %s: %.1f GiB", probe, free_gib)

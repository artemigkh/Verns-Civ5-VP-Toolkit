"""Shared logging configuration for hypervisor and runner.

Builds a uvicorn-compatible ``log_config`` dict that:

* writes to both stderr and a rotating file
* silences ``uvicorn.access`` (HTTP request access log)
* uses a consistent ``%(asctime)s [%(levelname)s] %(name)s: %(message)s`` format
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_log_config(log_file: Path) -> dict[str, Any]:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stderr",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "filename": str(log_file),
                "maxBytes": 10 * 1024 * 1024,  # 10 MiB
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
        "root": {"level": "INFO", "handlers": ["console", "file"]},
        "loggers": {
            # Disable HTTP access logging (uvicorn.access) entirely.
            "uvicorn.access": {
                "level": "WARNING",
                "propagate": False,
                "handlers": [],
            },
            # Silence httpx's INFO-level outbound request logs.
            "httpx": {"level": "WARNING", "propagate": True, "handlers": []},
            "httpcore": {"level": "WARNING", "propagate": True, "handlers": []},
            "uvicorn": {"propagate": True, "handlers": []},
            "uvicorn.error": {"propagate": True, "handlers": []},
        },
    }

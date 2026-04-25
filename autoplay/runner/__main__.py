"""Entrypoint: ``python -m autoplay.runner`` — allocates a free port and launches uvicorn."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import uvicorn

from autoplay.common.logging_setup import build_log_config
from autoplay.runner.config import load_config


def _allocate_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def main() -> None:
    cfg = load_config()
    port = _allocate_port(cfg.bind_host)
    os.environ["AUTOPLAY_RUNNER_ALLOCATED_PORT"] = str(port)
    log_dir = Path(".") / "logs"
    log_config = build_log_config(log_dir / "runner.log")
    uvicorn.run(
        "autoplay.runner.app:app",
        host=cfg.bind_host,
        port=port,
        log_config=log_config,
        access_log=False,
    )


if __name__ == "__main__":
    main()

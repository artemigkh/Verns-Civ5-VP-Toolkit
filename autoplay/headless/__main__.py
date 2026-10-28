"""Entrypoint: ``python -m autoplay.headless`` — allocates a free port and launches uvicorn."""

from __future__ import annotations

import argparse
import os
import socket

import uvicorn

from autoplay.common.logging_setup import build_log_config
from autoplay.headless.config import load_config


def _allocate_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def main() -> None:
    parser = argparse.ArgumentParser(prog="autoplay.headless")
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="Start playing at once instead of waiting for a start request from the hypervisor.",
    )
    parser.add_argument("--port", type=int, default=0, help="HTTP port (default: any free port).")
    args = parser.parse_args()
    # Set before load_config()/app import so HeadlessConfig picks them up.
    if args.autostart:
        os.environ["AUTOPLAY_HEADLESS_AUTOSTART"] = "true"

    cfg = load_config()
    port = args.port or _allocate_port(cfg.bind_host)
    os.environ["AUTOPLAY_HEADLESS_ALLOCATED_PORT"] = str(port)
    log_config = build_log_config(cfg.work_dir / "logs" / "bridge.log")
    uvicorn.run(
        "autoplay.headless.app:app",
        host=cfg.bind_host,
        port=port,
        log_config=log_config,
        access_log=False,
    )


if __name__ == "__main__":
    main()

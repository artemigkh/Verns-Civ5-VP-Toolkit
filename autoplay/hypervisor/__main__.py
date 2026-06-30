"""Entrypoint: ``python -m autoplay.hypervisor``."""

from __future__ import annotations

import argparse
import os

import uvicorn

from autoplay.common.logging_setup import build_log_config
from autoplay.hypervisor.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(prog="autoplay.hypervisor")
    parser.add_argument(
        "--legacy-logs",
        action="store_true",
        help=(
            "Run in legacy CSV-log mode (archive tar bundles) instead of the "
            "default SQLite-stats DuckDB ingestion mode."
        ),
    )
    args = parser.parse_args()
    if args.legacy_logs:
        # Set before load_config()/app import so HypervisorConfig picks it up.
        os.environ["AUTOPLAY_HV_STATS_MODE"] = "legacy_logs"

    cfg = load_config()
    log_config = build_log_config(cfg.storage_root / "hypervisor.log")
    uvicorn.run(
        "autoplay.hypervisor.app:app",
        host=cfg.host,
        port=cfg.port,
        log_config=log_config,
        access_log=False,
    )


if __name__ == "__main__":
    main()

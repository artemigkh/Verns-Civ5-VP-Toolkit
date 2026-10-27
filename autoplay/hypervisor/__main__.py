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
    parser.add_argument(
        "--max-turn",
        "--max_turn",
        dest="max_turn",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Cap game length at N turns. Sent to runners with every start/resume "
            "request; a runner ends the game at turn N and uploads its stats as "
            "a normal completion. Omit to play games to their natural end."
        ),
    )
    args = parser.parse_args()
    if args.max_turn is not None and args.max_turn < 1:
        parser.error("--max-turn must be a positive integer")
    # Set before load_config()/app import so HypervisorConfig picks them up.
    if args.legacy_logs:
        os.environ["AUTOPLAY_HV_STATS_MODE"] = "legacy_logs"
    if args.max_turn is not None:
        os.environ["AUTOPLAY_HV_MAX_TURN"] = str(args.max_turn)

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

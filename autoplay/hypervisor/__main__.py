"""Entrypoint: ``python -m autoplay.hypervisor``."""

from __future__ import annotations

import uvicorn

from autoplay.common.logging_setup import build_log_config
from autoplay.hypervisor.config import load_config


def main() -> None:
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

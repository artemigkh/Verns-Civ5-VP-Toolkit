"""Network helpers for the runner."""

from __future__ import annotations

import logging
import re
import subprocess

logger = logging.getLogger(__name__)

_TARGET_GATEWAY = "192.168.2.1"
_TARGET_PREFIX = "192.168.2."


def detect_lan_host() -> str:
    """Return the LAN IPv4 address to bind to / advertise.

    Selection rules:

    1. If an adapter has Default Gateway ``192.168.2.1``, return its IPv4 address.
    2. Otherwise log a warning and return the first IPv4 starting with
       ``192.168.2.``.
    3. Otherwise log a warning and return ``"localhost"``.
    """
    try:
        out = subprocess.check_output(
            ["ipconfig"], text=True, encoding="utf-8", errors="replace"
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("ipconfig failed (%s); using localhost", exc)
        return "localhost"

    # Split on blank lines so each adapter is one block.
    blocks = re.split(r"(?:\r?\n){2,}", out)
    prefix_match: str | None = None

    for block in blocks:
        ipv4: str | None = None
        gateway: str | None = None
        for line in block.splitlines():
            m = re.search(r"IPv4 Address[^:]*:\s*([\d.]+)", line)
            if m:
                ipv4 = m.group(1)
                continue
            m = re.search(r"Default Gateway[^:]*:\s*([\d.]+)", line)
            if m:
                gateway = m.group(1)
        if ipv4 and gateway == _TARGET_GATEWAY:
            return ipv4
        if ipv4 and ipv4.startswith(_TARGET_PREFIX) and prefix_match is None:
            prefix_match = ipv4

    if prefix_match is not None:
        logger.warning(
            "No adapter with default gateway %s; falling back to first %s* address: %s",
            _TARGET_GATEWAY,
            _TARGET_PREFIX,
            prefix_match,
        )
        return prefix_match

    logger.warning(
        "No adapter with IPv4 starting %s found; using localhost",
        _TARGET_PREFIX,
    )
    return "localhost"

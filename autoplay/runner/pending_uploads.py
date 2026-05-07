"""Local persistent queue of artifacts awaiting upload to the hypervisor.

If the hypervisor is unreachable when a game finishes (or crashes), the
runner stages the bundle on disk under ``USER_DIR/Logs/../autoplay_pending``
and a background loop retries upload until it succeeds. This lets games keep
running through hypervisor outages without losing data.

Each pending item is a pair of files:

    <stem>.bin       — the raw payload bytes
    <stem>.meta.json — JSON dict of upload form fields (endpoint, modpack,
                       gameId, runnerUuid, filename, final)

Items are processed oldest-first.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid as uuid_module
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _next_stem(pending_dir: Path) -> str:
    return f"{int(time.time() * 1000)}-{uuid_module.uuid4().hex[:8]}"


def stage_upload(
    pending_dir: Path,
    *,
    endpoint: str,
    modpack: str,
    game_id: str,
    runner_uuid: str,
    filename: str,
    content: bytes,
    final: bool,
    extra_fields: dict[str, Any] | None = None,
) -> Path:
    """Persist a pending upload to ``pending_dir``. Returns the meta-file path."""
    pending_dir.mkdir(parents=True, exist_ok=True)
    stem = _next_stem(pending_dir)
    bin_path = pending_dir / f"{stem}.bin"
    meta_path = pending_dir / f"{stem}.meta.json"
    bin_path.write_bytes(content)
    meta_path.write_text(
        json.dumps(
            {
                "endpoint": endpoint,
                "modpack": modpack,
                "gameId": game_id,
                "runnerUuid": runner_uuid,
                "filename": filename,
                "final": bool(final),
                "extraFields": {k: v for k, v in (extra_fields or {}).items() if v is not None},
                "stagedAt": time.time(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info(
        "Staged pending upload: %s (%d bytes) endpoint=%s game=%s",
        bin_path.name,
        len(content),
        endpoint,
        game_id,
    )
    return meta_path


def _list_pending(pending_dir: Path) -> list[tuple[Path, Path]]:
    if not pending_dir.is_dir():
        return []
    pairs: list[tuple[Path, Path]] = []
    for meta in sorted(pending_dir.glob("*.meta.json")):
        bin_path = meta.with_suffix("").with_suffix(".bin")
        if bin_path.is_file():
            pairs.append((meta, bin_path))
    return pairs


async def _try_upload_one(
    client: httpx.AsyncClient,
    hypervisor_url: str,
    meta_path: Path,
    bin_path: Path,
) -> bool:
    try:
        meta: dict[str, Any] = json.loads(meta_path.read_text(encoding="utf-8"))
        content = bin_path.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Cannot read pending item %s: %s", meta_path.name, exc)
        return False
    url = f"{hypervisor_url.rstrip('/')}{meta['endpoint']}"
    form = {
        "modpack": meta["modpack"],
        "gameId": meta["gameId"],
        "runnerUuid": meta["runnerUuid"],
        "final": "true" if meta.get("final", True) else "false",
    }
    for k, v in (meta.get("extraFields") or {}).items():
        if v is not None:
            form[k] = str(v)
    try:
        r = await client.post(
            url,
            data=form,
            files={"file": (meta["filename"], content, "application/octet-stream")},
        )
    except httpx.HTTPError as exc:
        logger.debug("Pending upload %s failed (transport): %s", meta_path.name, exc)
        return False
    if r.status_code >= 400:
        logger.warning(
            "Pending upload %s rejected: %s %s",
            meta_path.name,
            r.status_code,
            r.text[:200],
        )
        return False
    bin_path.unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)
    logger.info("Pending upload drained: game=%s endpoint=%s", meta["gameId"], meta["endpoint"])
    return True


async def drain_loop(
    pending_dir: Path,
    hypervisor_url: str,
    stop_event: asyncio.Event,
    interval_sec: float = 5.0,
) -> None:
    """Background loop that retries pending uploads until they succeed."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        while not stop_event.is_set():
            for meta_path, bin_path in _list_pending(pending_dir):
                if stop_event.is_set():
                    break
                ok = await _try_upload_one(client, hypervisor_url, meta_path, bin_path)
                if not ok:
                    # Stop draining for now; back off until next tick.
                    break
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
            except asyncio.TimeoutError:
                pass


def pending_count(pending_dir: Path) -> int:
    return len(_list_pending(pending_dir))

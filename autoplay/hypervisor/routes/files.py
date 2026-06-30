"""File submission (logs, crash saves) and file-status routes."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid as uuid_module
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from starlette.requests import ClientDisconnect

from autoplay.common import FileStatus
from autoplay.common.constants import MODPACK_FOLDER_REGEX
from autoplay.hypervisor import game_stats_db
from autoplay.hypervisor.bundles_db import record_bundle
from autoplay.hypervisor.stats_ingest import ingest_stats_db

router = APIRouter(tags=["files"])
logger = logging.getLogger(__name__)

_CHUNK = 1024 * 1024  # 1 MiB streaming chunks


def _storage_root(request: Request) -> Path:
    return request.app.state.config.storage_root


def _validate_modpack(modpack: str) -> None:
    if not MODPACK_FOLDER_REGEX.match(modpack):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid modpack folder name: {modpack!r}",
        )


def _validate_game_id(game_id: str) -> None:
    # Allow letters, digits, dot, dash, colon-replacement, T. Reject path separators.
    if not game_id or "/" in game_id or "\\" in game_id or ".." in game_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid gameId: {game_id!r}",
        )


def _resolve_unique_game_id(complete_dir: Path, game_id: str) -> str:
    """Return a game_id whose ``<id>.tar`` does not yet exist in ``complete_dir``.

    Two runners can occasionally start a game in the same millisecond and end
    up with identical millisecond-based game IDs. To avoid clobbering the
    earlier bundle, append ``-1``, ``-2`` … to the supplied ``game_id`` until
    the resulting ``<id>.tar`` filename is unused.
    """
    candidate = game_id
    suffix = 1
    while (complete_dir / f"{candidate}.tar").exists():
        candidate = f"{game_id}-{suffix}"
        suffix += 1
    return candidate


async def _stream_to_disk(upload: UploadFile, dest: Path) -> bool:
    """Stream ``upload`` to ``dest`` via a sibling ``.part`` file.

    Returns ``True`` on a successful, complete upload. If the client
    disconnects mid-upload (or the temp file otherwise vanishes before the
    final rename), this is treated as a benign interruption: the partial
    file is cleaned up, an informational log line is emitted, and ``False``
    is returned so the caller can short-circuit any post-processing.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    def _write_chunk(data: bytes) -> None:
        with tmp.open("ab") as fh:
            fh.write(data)

    def _cleanup_tmp() -> None:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    # Ensure fresh tmp file
    if tmp.exists():
        tmp.unlink()

    try:
        while chunk := await upload.read(_CHUNK):
            await asyncio.to_thread(_write_chunk, chunk)
    except (ClientDisconnect, ConnectionError, OSError) as exc:
        logger.info("Upload interrupted while streaming to %s: %s", dest.name, exc)
        await asyncio.to_thread(_cleanup_tmp)
        return False

    # Empty upload (e.g. client disconnected before sending any bytes): the
    # tmp file was never created, so there is nothing to rename. Treat as an
    # interrupted upload rather than an error.
    if not tmp.exists():
        logger.info("Upload to %s produced no bytes; treating as interrupted.", dest.name)
        return False

    try:
        await asyncio.to_thread(tmp.replace, dest)
    except FileNotFoundError as exc:
        logger.info("Partial upload for %s vanished before finalize: %s", dest.name, exc)
        await asyncio.to_thread(_cleanup_tmp)
        return False
    return True


def _count_files(root: Path, suffix: str) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for p in root.iterdir() if p.is_file() and p.name.endswith(suffix))


def _count_failed_unique(root: Path) -> int:
    """Count unique game-id stems in the failed directory.

    A crashed game may deposit multiple artifacts (``<gameId>.tar`` and
    ``<gameId>.Civ5Save``). Only the distinct gameId prefixes should count.
    """
    if not root.is_dir():
        return 0
    stems: set[str] = set()
    for p in root.iterdir():
        if p.is_file():
            stems.add(p.stem)
    return len(stems)


async def _refresh_file_status(storage_root: Path) -> FileStatus:
    status_obj = FileStatus()
    if storage_root.is_dir():
        for modpack_dir in storage_root.iterdir():
            if not modpack_dir.is_dir():
                continue
            if not MODPACK_FOLDER_REGEX.match(modpack_dir.name):
                continue
            # Completed games are stored as ``<gameId>.tar`` (legacy CSV-log
            # mode) or ``<gameId>.db`` (SQLite-stats mode); count both.
            complete = _count_files(modpack_dir / "complete", ".tar") + _count_files(
                modpack_dir / "complete", ".db"
            )
            failed = _count_failed_unique(modpack_dir / "failed")
            status_obj.complete[modpack_dir.name] = complete
            status_obj.failed[modpack_dir.name] = failed

    cache_path = storage_root / "file-status.json"
    await asyncio.to_thread(
        cache_path.write_text,
        json.dumps(status_obj.model_dump(), indent=2),
        "utf-8",
    )
    return status_obj


@router.post("/submit-logs", status_code=status.HTTP_204_NO_CONTENT)
async def submit_logs(
    request: Request,
    modpack: str = Form(...),
    game_id: str = Form(..., alias="gameId"),
    file: UploadFile = File(...),
    runner_uuid: str | None = Form(default=None, alias="runnerUuid"),
    turn: int | None = Form(default=None),
    time_elapsed_sec: int | None = Form(default=None, alias="timeElapsedSec"),
    runner_url: str | None = Form(default=None, alias="runnerUrl"),
) -> None:
    _validate_modpack(modpack)
    _validate_game_id(game_id)
    complete_dir = _storage_root(request) / modpack / "complete"
    unique_game_id = _resolve_unique_game_id(complete_dir, game_id)
    dest = complete_dir / f"{unique_game_id}.tar"
    if not await _stream_to_disk(file, dest):
        # Client disconnected mid-upload; nothing to record.
        return
    await _refresh_file_status(_storage_root(request))
    try:
        size = dest.stat().st_size
    except OSError:
        size = 0
    metadata = {
        "turn": turn,
        "timeElapsedSec": time_elapsed_sec,
        "runnerUrl": runner_url,
        "originalFilename": file.filename,
    }
    if unique_game_id != game_id:
        metadata["originalGameId"] = game_id
        logger.warning(
            "Game ID collision: %r already exists; renamed to %r",
            game_id,
            unique_game_id,
        )
    await asyncio.to_thread(
        record_bundle,
        _storage_root(request),
        modpack=modpack,
        bundle_name=dest.name,
        game_id=unique_game_id,
        runner_uuid=runner_uuid,
        file_size_bytes=size,
        metadata=metadata,
    )
    logger.info(
        "Game result received: runner=%s modpack=%s game=%s",
        runner_uuid or "?",
        modpack,
        unique_game_id,
    )
    if runner_uuid:
        request.app.state.db.increment_success(runner_uuid)
        # Record a final-turn snapshot before marking the game finished, so
        # games that finish without a final heartbeat still contribute their
        # full turn count and elapsed time to the per-runner average.
        await asyncio.to_thread(
            game_stats_db.update_game,
            _storage_root(request),
            runner_uuid=runner_uuid,
            game_id=game_id,
            modpack=modpack,
            turn=turn,
            time_elapsed_sec=time_elapsed_sec,
        )
        await asyncio.to_thread(
            game_stats_db.mark_finished,
            _storage_root(request),
            runner_uuid=runner_uuid,
            game_id=game_id,
            success=True,
        )


def _incoming_dir(storage_root: Path) -> Path:
    return storage_root / "incoming"


@router.post("/submit-stats", status_code=status.HTTP_204_NO_CONTENT)
async def submit_stats(
    request: Request,
    modpack: str = Form(...),
    game_id: str = Form(..., alias="gameId"),
    file: UploadFile = File(...),
    runner_uuid: str | None = Form(default=None, alias="runnerUuid"),
    turn: int | None = Form(default=None),
    time_elapsed_sec: int | None = Form(default=None, alias="timeElapsedSec"),
    runner_url: str | None = Form(default=None, alias="runnerUrl"),
) -> None:
    """Accept an uploaded SQLite ``stats.db`` and queue it for DuckDB ingestion.

    The file is streamed into ``<storage_root>/incoming/`` alongside a sidecar
    ``.json`` of submission metadata, then handed to the single background
    ingest worker. Returns immediately; ingestion happens asynchronously.
    """
    _validate_modpack(modpack)
    _validate_game_id(game_id)
    queue = getattr(request.app.state, "stats_queue", None)
    if queue is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hypervisor is not running in SQLite-stats mode.",
        )
    incoming = _incoming_dir(_storage_root(request))
    stem = f"{int(time.time() * 1000)}-{uuid_module.uuid4().hex[:8]}"
    dest = incoming / f"{stem}.db"
    if not await _stream_to_disk(file, dest):
        # Client disconnected mid-upload; nothing to record.
        return
    meta = {
        "modpack": modpack,
        "gameId": game_id,
        "runnerUuid": runner_uuid,
        "turn": turn,
        "timeElapsedSec": time_elapsed_sec,
        "runnerUrl": runner_url,
        "originalFilename": file.filename,
        "stagedAt": time.time(),
    }
    sidecar = dest.with_suffix(".json")
    await asyncio.to_thread(sidecar.write_text, json.dumps(meta, indent=2), "utf-8")
    await queue.put(dest)
    logger.info(
        "Stats db staged for ingest: runner=%s modpack=%s game=%s file=%s",
        runner_uuid or "?",
        modpack,
        game_id,
        dest.name,
    )


async def process_stats_upload(app, db_path: Path) -> None:
    """Ingest one staged SQLite stats db into DuckDB and run success bookkeeping.

    Invoked by the hypervisor's single background ingest worker (one file at a
    time). On a successful ingest the raw db is archived to ``complete/`` by
    :func:`ingest_stats_db`; here we record the bundle, bump the runner's
    success counter, mark the game finished, and refresh the file-status cache.
    A schema mismatch quarantines the file (handled inside ``ingest_stats_db``)
    and is logged without success bookkeeping.
    """
    storage_root: Path = app.state.config.storage_root
    sidecar = db_path.with_suffix(".json")
    try:
        meta = json.loads(await asyncio.to_thread(sidecar.read_text, "utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Cannot read sidecar for %s: %s; skipping.", db_path.name, exc)
        meta = {}

    modpack = meta.get("modpack")
    game_id = meta.get("gameId")
    runner_uuid = meta.get("runnerUuid")
    turn = meta.get("turn")
    time_elapsed_sec = meta.get("timeElapsedSec")
    runner_url = meta.get("runnerUrl")

    if not modpack or not game_id or not db_path.is_file():
        logger.error(
            "Skipping ingest of %s: missing modpack/gameId or file vanished.",
            db_path.name,
        )
        await asyncio.to_thread(sidecar.unlink, True)
        return

    result = await asyncio.to_thread(ingest_stats_db, storage_root, modpack, game_id, db_path)

    if result.ok:
        await asyncio.to_thread(
            record_bundle,
            storage_root,
            modpack=modpack,
            bundle_name=result.bundle_name or f"{game_id}.db",
            game_id=game_id,
            runner_uuid=runner_uuid,
            file_size_bytes=result.file_size_bytes,
            metadata={
                "turn": turn,
                "timeElapsedSec": time_elapsed_sec,
                "runnerUrl": runner_url,
                "originalFilename": meta.get("originalFilename"),
                "rowsIngested": result.rows_ingested,
                "tablesIngested": list(result.tables_ingested),
                "format": "sqlite-duckdb",
            },
        )
        if runner_uuid:
            app.state.db.increment_success(runner_uuid)
            await asyncio.to_thread(
                game_stats_db.update_game,
                storage_root,
                runner_uuid=runner_uuid,
                game_id=game_id,
                modpack=modpack,
                turn=turn,
                time_elapsed_sec=time_elapsed_sec,
            )
            await asyncio.to_thread(
                game_stats_db.mark_finished,
                storage_root,
                runner_uuid=runner_uuid,
                game_id=game_id,
                success=True,
            )
        await _refresh_file_status(storage_root)
        logger.info(
            "Stats ingest complete: runner=%s modpack=%s game=%s rows=%d",
            runner_uuid or "?",
            modpack,
            game_id,
            result.rows_ingested,
        )
    else:
        logger.error(
            "Stats ingest failed (quarantined): modpack=%s game=%s reason=%s path=%s",
            modpack,
            game_id,
            result.error,
            result.quarantine_path,
        )

    await asyncio.to_thread(sidecar.unlink, True)


@router.post("/submit-crash", status_code=status.HTTP_204_NO_CONTENT)
async def submit_crash(
    request: Request,
    modpack: str = Form(...),
    game_id: str = Form(..., alias="gameId"),
    file: UploadFile = File(...),
    runner_uuid: str | None = Form(default=None, alias="runnerUuid"),
    final: bool = Form(default=False),
) -> None:
    _validate_modpack(modpack)
    _validate_game_id(game_id)
    # Choose extension based on uploaded filename (.tar for partial logs, .Civ5Save for saves).
    original = file.filename or ""
    if original.endswith(".tar"):
        ext = ".tar"
    elif original.endswith(".Civ5Save"):
        ext = ".Civ5Save"
    else:
        ext = Path(original).suffix or ".bin"
    dest = _storage_root(request) / modpack / "failed" / f"{game_id}{ext}"
    if not await _stream_to_disk(file, dest):
        # Client disconnected mid-upload; nothing to record.
        return
    await _refresh_file_status(_storage_root(request))
    logger.info(
        "Crash artifact received: runner=%s modpack=%s game=%s file=%s final=%s",
        runner_uuid or "?",
        modpack,
        game_id,
        dest.name,
        final,
    )
    if final and runner_uuid:
        request.app.state.db.increment_failure(runner_uuid)
        await asyncio.to_thread(
            game_stats_db.mark_finished,
            _storage_root(request),
            runner_uuid=runner_uuid,
            game_id=game_id,
            success=False,
        )


@router.get("/file-status", response_model=FileStatus)
async def file_status(request: Request) -> FileStatus:
    storage_root = _storage_root(request)
    cache_path = storage_root / "file-status.json"
    if cache_path.is_file():
        try:
            data = json.loads(await asyncio.to_thread(cache_path.read_text, "utf-8"))
            return FileStatus.model_validate(data)
        except (json.JSONDecodeError, ValueError):
            pass
    return await _refresh_file_status(storage_root)

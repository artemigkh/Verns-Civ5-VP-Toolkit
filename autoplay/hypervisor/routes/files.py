"""File submission (logs, crash saves) and file-status routes."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from autoplay.common import FileStatus
from autoplay.common.constants import MODPACK_FOLDER_REGEX

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


async def _stream_to_disk(upload: UploadFile, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    def _write_chunk(data: bytes) -> None:
        with tmp.open("ab") as fh:
            fh.write(data)

    # Ensure fresh tmp file
    if tmp.exists():
        tmp.unlink()

    while chunk := await upload.read(_CHUNK):
        await asyncio.to_thread(_write_chunk, chunk)

    await asyncio.to_thread(tmp.replace, dest)


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
            complete = _count_files(modpack_dir / "complete", ".tar")
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
) -> None:
    _validate_modpack(modpack)
    _validate_game_id(game_id)
    dest = _storage_root(request) / modpack / "complete" / f"{game_id}.tar"
    await _stream_to_disk(file, dest)
    await _refresh_file_status(_storage_root(request))
    logger.info(
        "Game result received: runner=%s modpack=%s game=%s",
        runner_uuid or "?",
        modpack,
        game_id,
    )
    if runner_uuid:
        request.app.state.db.increment_success(runner_uuid)


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
    await _stream_to_disk(file, dest)
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

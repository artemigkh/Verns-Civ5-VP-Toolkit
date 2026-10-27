"""Hand finished games to the hypervisor, exactly once each.

A game that completed is uploaded to ``/submit-stats`` (ingested into the modpack's DuckDB); one that
failed goes to ``/submit-crash`` with ``final=true`` (kept under ``failed/``, never ingested, and counted
as the slot's failure). The file is the game's own ``<run>/cache/stats.db``: civ5-headless gives every
game its own cache folder, and c5h marks a job finished only after the game's process has exited, so the
database is complete and closed by then.

``<work_dir>/uploads.jsonl`` records every game handed over (one JSON line each), so a game is never
uploaded twice, across bridge restarts too. When the hypervisor cannot be reached the upload is staged
with the runner's pending-upload queue, which retries it until the hypervisor takes it.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from autoplay.common.constants import STATS_DB_FILENAME
from autoplay.headless.batches import FINISHED_STATES, Batch
from autoplay.headless.slots import game_id, slot_uuid
from autoplay.runner import pending_uploads

logger = logging.getLogger(__name__)

LEDGER_FILENAME = "uploads.jsonl"


def ledger_key(batch: Batch, job: str, started: str | None) -> str:
    return f"{batch.name}/{job}/{started or ''}"


class Ledger:
    """Append-only record of the games handed to the hypervisor."""

    def __init__(self, work_dir: Path) -> None:
        self.path = work_dir / LEDGER_FILENAME
        self._keys: set[str] = set()
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    self._keys.add(json.loads(line)["key"])
                except (ValueError, KeyError):
                    continue

    def __contains__(self, key: str) -> bool:
        return key in self._keys

    def __len__(self) -> int:
        return len(self._keys)

    def add(self, key: str, **values: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {"key": key, "ts": time.time(), **values}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        self._keys.add(key)


@dataclass
class Handover:
    """One finished game to hand over."""

    key: str
    batch: Batch
    job: str
    game_id: str
    slot: int
    runner_uuid: str
    completed: bool
    end_turn: int | None
    seconds: int | None
    run_dir: Path

    @property
    def stats_db(self) -> Path:
        return self.run_dir / "cache" / STATS_DB_FILENAME


def finished_games(batch: Batch, ledger: Ledger, work_dir: Path) -> list[Handover]:
    """The batch's finished games not handed over yet."""
    out = []
    for name, job in batch.jobs().items():
        if job.get("state") not in FINISHED_STATES:
            continue
        key = ledger_key(batch, name, job.get("started"))
        if key in ledger:
            continue
        worker = job.get("worker") if isinstance(job.get("worker"), int) else 0
        seconds = job.get("seconds")
        out.append(
            Handover(
                key=key,
                batch=batch,
                job=name,
                game_id=game_id(name, job.get("started")),
                slot=worker,
                runner_uuid=slot_uuid(work_dir, worker),
                completed=job.get("state") == "completed",
                end_turn=job.get("endTurn"),
                seconds=int(seconds) if isinstance(seconds, (int, float)) else None,
                run_dir=batch.run_dir(name),
            )
        )
    return out


def _upload_parts(h: Handover, modpack: str, runner_url: str) -> tuple[str, str, bytes, dict[str, str]]:
    """(endpoint, filename, content, form fields) for a handover."""
    form = {"modpack": modpack, "gameId": h.game_id, "runnerUuid": h.runner_uuid}
    if h.completed and h.stats_db.is_file():
        endpoint, filename, content = "/submit-stats", f"{h.game_id}.db", h.stats_db.read_bytes()
        form.update(runnerUrl=runner_url)
        if h.end_turn is not None:
            form["turn"] = str(h.end_turn)
        if h.seconds is not None:
            form["timeElapsedSec"] = str(h.seconds)
    elif h.stats_db.is_file():
        endpoint, filename, content = "/submit-crash", f"{h.game_id}.db", h.stats_db.read_bytes()
        form["final"] = "true"
    else:
        # No stats at all (the game failed before it logged anything): send the run's status instead.
        status = h.run_dir / "status.json"
        content = status.read_bytes() if status.is_file() else b"{}"
        endpoint, filename = "/submit-crash", f"{h.game_id}.json"
        form["final"] = "true"
    return endpoint, filename, content, form


async def hand_over(
    client: httpx.AsyncClient,
    h: Handover,
    *,
    hypervisor_url: str,
    modpack: str,
    runner_url: str,
    pending_dir: Path,
    ledger: Ledger,
) -> str:
    """Upload one finished game; returns the outcome recorded in the ledger:
    ``uploaded``, ``staged`` (hypervisor unreachable, retried from ``pending_dir``) or ``rejected``."""
    endpoint, filename, content, form = _upload_parts(h, modpack, runner_url)
    url = f"{hypervisor_url.rstrip('/')}{endpoint}"
    try:
        r = await client.post(url, data=form, files={"file": (filename, content, "application/octet-stream")})
    except httpx.HTTPError as exc:
        logger.warning("Hypervisor unreachable for %s (%s); staging the upload", h.game_id, exc)
        pending_uploads.stage_upload(
            pending_dir,
            endpoint=endpoint,
            modpack=modpack,
            game_id=h.game_id,
            runner_uuid=h.runner_uuid,
            filename=filename,
            content=content,
            final=True,
            extra_fields={
                k: v for k, v in form.items() if k not in ("modpack", "gameId", "runnerUuid", "final")
            },
        )
        outcome = "staged"
    else:
        if r.status_code >= 400:
            # A rejection will not change on retry (bad modpack name, bad game id): keep the run folder,
            # record why, and move on.
            logger.error(
                "Hypervisor rejected %s at %s: %s %s", h.game_id, endpoint, r.status_code, r.text[:300]
            )
            outcome = "rejected"
        else:
            outcome = "uploaded"
    ledger.add(
        h.key,
        gameId=h.game_id,
        job=h.job,
        batch=h.batch.name,
        runnerUuid=h.runner_uuid,
        completed=h.completed,
        endTurn=h.end_turn,
        endpoint=endpoint,
        outcome=outcome,
        runDir=str(h.run_dir),
    )
    logger.info(
        "Game %s (%s, turn %s) -> %s: %s",
        h.game_id,
        "completed" if h.completed else "failed",
        h.end_turn,
        endpoint,
        outcome,
    )
    return outcome

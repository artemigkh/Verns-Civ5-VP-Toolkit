"""Worker slots: each c5h queue worker shows up on the hypervisor as one runner.

A slot's identity is stable across bridge restarts (a UUID derived from the host, the work folder and
the slot number), so the hypervisor's per-runner history keeps adding up. What a slot is doing comes from
c5h's queue state (which job runs on which worker, since when) and from the running game's
``turn-times.jsonl`` (the turn reached and the seconds of play, one line per turn).
"""

from __future__ import annotations

import json
import socket
import uuid as uuid_module
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from autoplay.common import RunnerState
from autoplay.headless.batches import Batch


def slot_uuid(work_dir: Path, slot: int) -> str:
    """Stable runner UUID of a worker slot."""
    key = f"civ5-headless|{socket.gethostname()}|{Path(work_dir).resolve()}|{slot}"
    return str(uuid_module.uuid5(uuid_module.NAMESPACE_URL, key))


def game_id(job: str, started: str | None) -> str:
    """Hypervisor game id of one attempt at a job: ``<start time>-<job>``, e.g.
    ``2026-10-27T16.05.39-hl-m1101-s2101`` (an ISO time with dots, like the runner's ids)."""
    if started:
        try:
            stamp = datetime.fromisoformat(started).strftime("%Y-%m-%dT%H.%M.%S")
            return f"{stamp}-{job}"
        except ValueError:
            pass
    return job


@dataclass
class TurnProgress:
    turn: int | None = None
    last_turn_sec: float | None = None


def read_turn_progress(run_dir: Path) -> TurnProgress:
    """Turn reached and the last turn's seconds, from the game's ``turn-times.jsonl``.

    Each line is ``{"turn": N, "seconds": S}`` with S the seconds of play when turn N began, so the turn
    before N took the difference of the last two lines.
    """
    try:
        lines = (run_dir / "turn-times.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return TurnProgress()
    rows: list[dict[str, Any]] = []
    for line in lines[-2:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue  # a line still being written
    if not rows:
        return TurnProgress()
    last = rows[-1]
    seconds = float(last["seconds"]) - (float(rows[0]["seconds"]) if len(rows) == 2 else 0.0)
    return TurnProgress(turn=int(last["turn"]), last_turn_sec=round(max(seconds, 0.0), 3))


@dataclass
class SlotSnapshot:
    """What one worker slot reports in its heartbeat."""

    slot: int
    state: RunnerState
    job: str | None = None
    game_id: str | None = None
    turn: int | None = None
    time_elapsed_sec: int | None = None
    last_turn_sec: float | None = None


def snapshot_slots(
    batch: Batch | None,
    workers: int,
    *,
    queue_running: bool,
    stopping: bool,
    now: float,
) -> list[SlotSnapshot]:
    """One snapshot per worker slot from the batch's c5h state and its running games."""
    running: dict[int, tuple[str, dict[str, Any]]] = {}
    if batch is not None and queue_running:
        for name, job in batch.jobs().items():
            if job.get("state") == "running" and isinstance(job.get("worker"), int):
                running[job["worker"]] = (name, job)
    out = []
    for slot in range(workers):
        if slot not in running:
            out.append(SlotSnapshot(slot=slot, state=RunnerState.stopping if stopping else RunnerState.idle))
            continue
        name, job = running[slot]
        progress = read_turn_progress(batch.run_dir(name)) if batch is not None else TurnProgress()
        started = job.get("started")
        elapsed = None
        if started:
            try:
                elapsed = max(0, int(now - datetime.fromisoformat(started).timestamp()))
            except ValueError:
                elapsed = None
        if stopping:
            state = RunnerState.stopping
        elif progress.turn is None:
            state = RunnerState.starting
        else:
            state = RunnerState.running
        out.append(
            SlotSnapshot(
                slot=slot,
                state=state,
                job=name,
                game_id=game_id(name, started),
                turn=progress.turn,
                time_elapsed_sec=elapsed,
                last_turn_sec=progress.last_turn_sec,
            )
        )
    return out

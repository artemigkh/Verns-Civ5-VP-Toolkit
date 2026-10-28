"""Fixtures for the headless bridge: a config in tmp_path and helpers that fake what c5h writes."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autoplay.headless.batches import Batch, write_batch
from autoplay.headless.config import HeadlessConfig


@pytest.fixture
def cfg(tmp_path: Path) -> HeadlessConfig:
    spec = tmp_path / "spec.json"
    spec.write_text('{"map": {"script": "Assets/Maps/Continents.lua"}}', encoding="utf-8")
    return HeadlessConfig(
        hypervisor_url="http://hv.test",
        c5h_dir=tmp_path / "c5h",
        work_dir=tmp_path / "work",
        modpack="MP_AUTOPLAY_VP_9_headless",
        spec=spec,
        turns=150,
        workers=3,
        games_per_batch=4,
        bind_host="127.0.0.1",
    )


@pytest.fixture
def batch(cfg: HeadlessConfig) -> Batch:
    return write_batch(cfg, cfg.turns, random.Random(7))


def iso_ago(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


def set_jobs(batch: Batch, jobs: dict[str, dict]) -> None:
    """Write c5h's state file for the batch: every job pending unless given."""
    state = {"jobs": {name: {"state": "pending", "attempts": 0} for name in batch.job_names()}}
    state["jobs"].update(jobs)
    batch.state_path.write_text(json.dumps(state), encoding="utf-8")


def write_turns(run_dir: Path, rows: list[tuple[int, float]]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "turn-times.jsonl").write_text(
        "".join(json.dumps({"turn": t, "seconds": s}) + "\n" for t, s in rows), encoding="utf-8"
    )


def finish_job(batch: Batch, job: str, *, stats: bytes | None = b"SQLite format 3\x00fake") -> Path:
    run = batch.run_dir(job)
    (run / "cache").mkdir(parents=True, exist_ok=True)
    if stats is not None:
        (run / "cache" / "stats.db").write_bytes(stats)
    (run / "status.json").write_text('{"state": "completed"}', encoding="utf-8")
    return run

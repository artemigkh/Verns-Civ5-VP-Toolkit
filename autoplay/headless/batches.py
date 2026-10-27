"""c5h queue files ("batches") the bridge writes, and what c5h records while it plays them.

A batch is one c5h queue: ``<work_dir>/queues/<name>.json`` with ``games_per_batch`` jobs, each a fresh
pair of random seeds. c5h writes its state beside it (``<name>.state.json``, ``.stop``, ``.log``) and
each game's run folder to ``<work_dir>/runs/<name>/<job>/``. The bridge only reads those files, so it
works against any c5h version with the same queue format, and a bridge restart loses nothing.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from autoplay.headless.config import HeadlessConfig

VARIANT = "hl"
"""The batch's single variant; c5h names jobs ``<variant>-m<map seed>-s<sync seed>``."""

FINISHED_STATES = frozenset({"completed", "failed"})
"""c5h job states after which the job's run folder is final."""

_SEED_MAX = 2**31 - 1


def queues_dir(work_dir: Path) -> Path:
    return work_dir / "queues"


def runs_dir(work_dir: Path) -> Path:
    return work_dir / "runs"


@dataclass(frozen=True)
class Batch:
    """One c5h queue file and its c5h state."""

    path: Path

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def state_path(self) -> Path:
        return self.path.with_suffix(".state.json")

    @property
    def stop_path(self) -> Path:
        return self.path.with_suffix(".stop")

    def queue(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def out_dir(self) -> Path:
        out = self.queue().get("out")
        return (self.path.parent / out).resolve() if out else runs_dir(self.path.parent.parent) / self.name

    def job_names(self) -> list[str]:
        return [f"{VARIANT}-m{m}-s{s}" for m, s in self.queue().get("seeds", [])]

    def run_dir(self, job: str) -> Path:
        return self.out_dir() / job

    def state(self) -> dict[str, Any]:
        """c5h's job states (``{"jobs": {name: {...}}}``); empty until c5h first starts the batch."""
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def jobs(self) -> dict[str, dict[str, Any]]:
        return self.state().get("jobs") or {}

    def unfinished(self) -> list[str]:
        """Jobs that have not completed or failed (never started, running, interrupted)."""
        jobs = self.jobs()
        return [n for n in self.job_names() if (jobs.get(n) or {}).get("state") not in FINISHED_STATES]


def write_batch(cfg: HeadlessConfig, turns: int, rng: random.Random | None = None) -> Batch:
    """Write a new batch of ``cfg.games_per_batch`` games with fresh random seeds."""
    if cfg.spec is None:
        raise ValueError("no game spec configured (AUTOPLAY_HEADLESS_SPEC)")
    rng = rng or random.SystemRandom()
    qdir = queues_dir(cfg.work_dir)
    qdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = qdir / f"batch-{stamp}.json"
    n = 2
    while path.exists():
        path = qdir / f"batch-{stamp}-{n}.json"
        n += 1
    seeds: list[list[int]] = []
    seen: set[tuple[int, int]] = set()
    while len(seeds) < cfg.games_per_batch:
        pair = (rng.randint(1, _SEED_MAX), rng.randint(1, _SEED_MAX))
        if pair not in seen:
            seen.add(pair)
            seeds.append(list(pair))
    queue = {
        "comment": f"autoplay headless bridge batch for {cfg.modpack}",
        "out": f"../runs/{path.stem}",
        "workers": cfg.workers,
        "affinity": cfg.affinity,
        "defaults": {**cfg.job_defaults, "spec": str(Path(cfg.spec).resolve()), "turns": turns},
        "variants": {VARIANT: {}},
        "seeds": seeds,
    }
    path.write_text(json.dumps(queue, indent=1) + "\n", encoding="utf-8")
    return Batch(path)


def all_batches(work_dir: Path) -> list[Batch]:
    """Every batch the bridge wrote, oldest first (names carry their creation time)."""
    qdir = queues_dir(work_dir)
    if not qdir.is_dir():
        return []
    return [
        Batch(p)
        for p in sorted(qdir.glob("batch-*.json"))
        if not p.name.endswith((".state.json", ".summary.json"))
    ]


def latest_batch(work_dir: Path) -> Batch | None:
    """The most recently written batch, if any."""
    batches = all_batches(work_dir)
    return batches[-1] if batches else None

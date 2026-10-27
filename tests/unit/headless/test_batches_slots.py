"""Tests for autoplay.headless.batches and autoplay.headless.slots."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from autoplay.common import RunnerState
from autoplay.headless.batches import Batch, latest_batch, write_batch
from autoplay.headless.config import HeadlessConfig
from autoplay.headless.slots import game_id, read_turn_progress, slot_uuid, snapshot_slots
from tests.unit.headless.conftest import iso_ago, set_jobs, write_turns


def test_write_batch_is_a_c5h_queue(cfg: HeadlessConfig, batch: Batch) -> None:
    q = json.loads(batch.path.read_text(encoding="utf-8"))
    assert q["workers"] == 3 and q["affinity"] == "p-first"
    assert q["defaults"]["turns"] == 150
    assert q["defaults"]["noMods"] is True
    assert Path(q["defaults"]["spec"]) == Path(cfg.spec).resolve()
    assert q["variants"] == {"hl": {}}
    assert len(q["seeds"]) == 4 and len({tuple(s) for s in q["seeds"]}) == 4
    assert batch.out_dir() == (cfg.work_dir / "runs" / batch.name).resolve()
    assert batch.job_names() == [f"hl-m{m}-s{s}" for m, s in q["seeds"]]


def test_write_batch_needs_a_spec(cfg: HeadlessConfig) -> None:
    with pytest.raises(ValueError):
        write_batch(cfg.model_copy(update={"spec": None}), 10)


def test_latest_batch_and_unfinished(cfg: HeadlessConfig, batch: Batch) -> None:
    assert latest_batch(cfg.work_dir) == batch
    names = batch.job_names()
    assert batch.unfinished() == names  # c5h has not started it
    set_jobs(
        batch,
        {names[0]: {"state": "completed"}, names[1]: {"state": "failed"}, names[2]: {"state": "interrupted"}},
    )
    assert batch.unfinished() == names[2:]


def test_modpack_name_must_be_an_autoplay_modpack(cfg: HeadlessConfig) -> None:
    with pytest.raises(ValueError):
        HeadlessConfig(**{**cfg.model_dump(), "modpack": "VP_MODPACK_5_4_7"})


def test_slot_uuid_is_stable_and_distinct(tmp_path: Path) -> None:
    assert slot_uuid(tmp_path, 0) == slot_uuid(tmp_path, 0)
    assert slot_uuid(tmp_path, 0) != slot_uuid(tmp_path, 1)
    assert slot_uuid(tmp_path / "a", 0) != slot_uuid(tmp_path / "b", 0)


def test_game_id_uses_the_start_time() -> None:
    assert game_id("hl-m1-s2", "2026-10-27T16:05:39.509747+00:00") == "2026-10-27T16.05.39-hl-m1-s2"
    assert game_id("hl-m1-s2", None) == "hl-m1-s2"


def test_read_turn_progress(tmp_path: Path) -> None:
    assert read_turn_progress(tmp_path).turn is None
    write_turns(tmp_path, [(1, 1.0)])
    p = read_turn_progress(tmp_path)
    assert (p.turn, p.last_turn_sec) == (1, 1.0)
    write_turns(tmp_path, [(1, 1.0), (2, 1.5), (3, 3.75)])
    p = read_turn_progress(tmp_path)
    assert (p.turn, p.last_turn_sec) == (3, 2.25)
    # A half-written last line is skipped.
    with (tmp_path / "turn-times.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"turn": 4, "sec')
    assert read_turn_progress(tmp_path).turn == 3


def test_snapshot_slots(batch: Batch) -> None:
    names = batch.job_names()
    set_jobs(
        batch,
        {
            names[0]: {"state": "running", "worker": 0, "started": iso_ago(100)},
            names[1]: {"state": "running", "worker": 2, "started": iso_ago(5)},
            names[2]: {"state": "completed", "worker": 1, "started": iso_ago(300)},
        },
    )
    write_turns(batch.run_dir(names[0]), [(9, 40.0), (10, 42.5)])
    snaps = snapshot_slots(batch, 3, queue_running=True, stopping=False, now=time.time())
    assert [s.state for s in snaps] == [RunnerState.running, RunnerState.idle, RunnerState.starting]
    assert (snaps[0].job, snaps[0].turn, snaps[0].last_turn_sec) == (names[0], 10, 2.5)
    assert 99 <= snaps[0].time_elapsed_sec <= 102
    assert snaps[0].game_id.endswith(names[0])
    assert snaps[2].turn is None and snaps[2].job == names[1]
    # Draining: running games show as stopping; no queue: everything idle.
    assert {
        s.state for s in snapshot_slots(batch, 3, queue_running=True, stopping=True, now=time.time())
    } == {RunnerState.stopping}
    assert {
        s.state for s in snapshot_slots(batch, 3, queue_running=False, stopping=False, now=time.time())
    } == {RunnerState.idle}

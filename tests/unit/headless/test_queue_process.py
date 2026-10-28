"""Tests for autoplay.headless.queue_process."""

from __future__ import annotations

import json
import logging
import os

import psutil
import pytest

from autoplay.headless.batches import Batch
from autoplay.headless.config import HeadlessConfig
from autoplay.headless.queue_process import QueueProcess, c5h_command


def test_c5h_command_takes_workers_and_affinity_from_the_config(cfg: HeadlessConfig, batch: Batch) -> None:
    resumed = cfg.model_copy(update={"workers": 32, "affinity": "none"})  # the batch was written with 3
    argv, env = c5h_command(resumed, batch)
    assert argv[1:6] == ["-m", "civ5headless", "queue", "run", str(batch.path)]
    assert argv[6:] == ["--workers", "32", "--affinity", "none"]
    assert str(cfg.c5h_dir / "python") in env["PYTHONPATH"]


def test_adopt_warns_when_the_queue_plays_another_worker_count(
    cfg: HeadlessConfig, batch: Batch, caplog: pytest.LogCaptureFixture
) -> None:
    me = psutil.Process(os.getpid())
    batch.state_path.write_text(json.dumps({"jobs": {}, "queue": {"workers": 16}}), encoding="utf-8")
    queue = QueueProcess(cfg)
    queue.pid_path.parent.mkdir(parents=True, exist_ok=True)
    queue.pid_path.write_text(
        json.dumps({"pid": me.pid, "createTime": me.create_time(), "batch": str(batch.path)}),
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="autoplay.headless.queue_process"):
        assert queue.adopt()
    assert "plays 16 games at once; WORKERS=3" in caplog.text

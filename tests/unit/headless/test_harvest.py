"""Tests for autoplay.headless.harvest: finished games go to the hypervisor exactly once."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx

from autoplay.headless import harvest
from autoplay.headless.batches import Batch
from autoplay.headless.config import HeadlessConfig
from autoplay.headless.slots import slot_uuid
from autoplay.runner.pending_uploads import pending_count
from tests.unit.headless.conftest import finish_job, iso_ago, set_jobs


def _form(request: httpx.Request) -> dict[str, str]:
    """Plain form fields of a multipart request (the file part left out)."""
    body = request.content.decode("latin-1")
    out = {}
    for part in body.split("--" + request.headers["content-type"].split("boundary=")[1]):
        if 'name="' in part and "filename=" not in part:
            name = part.split('name="')[1].split('"')[0]
            out[name] = part.split("\r\n\r\n", 1)[1].rsplit("\r\n", 1)[0]
    return out


async def _hand_over_all(
    cfg: HeadlessConfig, batch: Batch, ledger: harvest.Ledger, *, prune: bool = False
) -> list[str]:
    async with httpx.AsyncClient() as client:
        return [
            await harvest.hand_over(
                client,
                h,
                hypervisor_url=cfg.hypervisor_url,
                modpack=cfg.modpack,
                runner_url="http://bridge/slots/0",
                pending_dir=cfg.pending_dir,
                ledger=ledger,
                prune=prune,
            )
            for h in harvest.finished_games(batch, ledger, cfg.work_dir)
        ]


async def test_completed_game_goes_to_submit_stats_once(cfg: HeadlessConfig, batch: Batch) -> None:
    job = batch.job_names()[0]
    started = iso_ago(400)
    set_jobs(
        batch,
        {job: {"state": "completed", "worker": 2, "started": started, "endTurn": 150, "seconds": 342.0}},
    )
    finish_job(batch, job)
    ledger = harvest.Ledger(cfg.work_dir)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("http://hv.test/submit-stats").mock(return_value=httpx.Response(204))
        assert await _hand_over_all(cfg, batch, ledger) == ["uploaded"]
        form = _form(route.calls.last.request)
        assert b"SQLite format 3" in route.calls.last.request.content
    assert form["modpack"] == "MP_AUTOPLAY_VP_9_headless"
    assert form["gameId"].endswith(job)
    assert form["runnerUuid"] == slot_uuid(cfg.work_dir, 2)
    assert (form["turn"], form["timeElapsedSec"]) == ("150", "342")
    # Already handed over: nothing more to do, also for a fresh ledger read from disk.
    assert harvest.finished_games(batch, ledger, cfg.work_dir) == []
    assert harvest.finished_games(batch, harvest.Ledger(cfg.work_dir), cfg.work_dir) == []
    row = json.loads((cfg.work_dir / "uploads.jsonl").read_text(encoding="utf-8"))
    assert row["outcome"] == "uploaded" and row["endpoint"] == "/submit-stats"


async def test_failed_game_goes_to_submit_crash_as_final(cfg: HeadlessConfig, batch: Batch) -> None:
    a, b = batch.job_names()[:2]
    set_jobs(
        batch,
        {
            a: {"state": "failed", "worker": 0, "started": iso_ago(60)},
            b: {"state": "failed", "worker": 1, "started": iso_ago(60)},
        },
    )
    finish_job(batch, a)
    finish_job(batch, b, stats=None)  # failed before logging anything
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("http://hv.test/submit-crash").mock(return_value=httpx.Response(204))
        assert await _hand_over_all(cfg, batch, harvest.Ledger(cfg.work_dir)) == ["uploaded", "uploaded"]
        forms = [_form(c.request) for c in route.calls]
        names = [c.request.content.split(b'filename="')[1].split(b'"')[0].decode() for c in route.calls]
    assert all(f["final"] == "true" for f in forms)
    assert sorted(n.rsplit(".", 1)[1] for n in names) == ["db", "json"]


async def test_unreachable_hypervisor_stages_the_upload(cfg: HeadlessConfig, batch: Batch) -> None:
    job = batch.job_names()[0]
    set_jobs(batch, {job: {"state": "completed", "worker": 0, "started": iso_ago(10), "endTurn": 20}})
    finish_job(batch, job)
    with respx.mock() as mock:
        mock.post("http://hv.test/submit-stats").mock(side_effect=httpx.ConnectError("down"))
        assert await _hand_over_all(cfg, batch, harvest.Ledger(cfg.work_dir)) == ["staged"]
    assert pending_count(cfg.pending_dir) == 1
    meta = json.loads(next(Path(cfg.pending_dir).glob("*.meta.json")).read_text(encoding="utf-8"))
    assert meta["endpoint"] == "/submit-stats" and meta["extraFields"]["turn"] == "20"


async def test_rejected_upload_is_recorded_not_retried(cfg: HeadlessConfig, batch: Batch) -> None:
    job = batch.job_names()[0]
    set_jobs(batch, {job: {"state": "completed", "worker": 0, "started": iso_ago(10)}})
    finish_job(batch, job)
    ledger = harvest.Ledger(cfg.work_dir)
    with respx.mock() as mock:
        mock.post("http://hv.test/submit-stats").mock(
            return_value=httpx.Response(400, json={"detail": "bad"})
        )
        assert await _hand_over_all(cfg, batch, ledger) == ["rejected"]
    assert harvest.finished_games(batch, ledger, cfg.work_dir) == []
    assert pending_count(cfg.pending_dir) == 0


async def test_unfinished_and_retried_games(cfg: HeadlessConfig, batch: Batch) -> None:
    job = batch.job_names()[0]
    set_jobs(batch, {job: {"state": "running", "worker": 0, "started": iso_ago(10)}})
    ledger = harvest.Ledger(cfg.work_dir)
    assert harvest.finished_games(batch, ledger, cfg.work_dir) == []
    first = iso_ago(100)
    ledger.add(harvest.ledger_key(batch, job, first))
    # A new attempt of the same job (c5h --retry-failed) is a new game.
    set_jobs(batch, {job: {"state": "completed", "worker": 0, "started": iso_ago(5)}})
    assert len(harvest.finished_games(batch, ledger, cfg.work_dir)) == 1


async def test_prune_deletes_handed_over_completed_runs_only(cfg: HeadlessConfig, batch: Batch) -> None:
    uploaded, staged, failed, rejected = batch.job_names()
    set_jobs(
        batch,
        {
            uploaded: {"state": "completed", "worker": 0, "started": iso_ago(10)},
            staged: {"state": "completed", "worker": 1, "started": iso_ago(10)},
            failed: {"state": "failed", "worker": 2, "started": iso_ago(10)},
        },
    )
    runs = {job: finish_job(batch, job) for job in (uploaded, staged, failed)}
    calls = iter([httpx.Response(204), httpx.ConnectError("down")])
    with respx.mock() as mock:
        mock.post("http://hv.test/submit-stats").mock(side_effect=lambda _req: _next(calls))
        mock.post("http://hv.test/submit-crash").mock(return_value=httpx.Response(204))
        await _hand_over_all(cfg, batch, harvest.Ledger(cfg.work_dir), prune=True)
    assert not runs[uploaded].exists()
    assert not runs[staged].exists() and pending_count(cfg.pending_dir) == 1
    assert runs[failed].is_dir()  # kept for debugging

    set_jobs(batch, {rejected: {"state": "completed", "worker": 0, "started": iso_ago(5)}})
    runs[rejected] = finish_job(batch, rejected)
    with respx.mock() as mock:
        mock.post("http://hv.test/submit-stats").mock(return_value=httpx.Response(400))
        assert await _hand_over_all(cfg, batch, harvest.Ledger(cfg.work_dir), prune=True) == ["rejected"]
    assert runs[rejected].is_dir()


async def test_no_prune_keeps_run_folders(cfg: HeadlessConfig, batch: Batch) -> None:
    job = batch.job_names()[0]
    set_jobs(batch, {job: {"state": "completed", "worker": 0, "started": iso_ago(10)}})
    run = finish_job(batch, job)
    with respx.mock() as mock:
        mock.post("http://hv.test/submit-stats").mock(return_value=httpx.Response(204))
        assert await _hand_over_all(cfg, batch, harvest.Ledger(cfg.work_dir)) == ["uploaded"]
    assert (run / "cache" / "stats.db").is_file()


def _next(responses):
    r = next(responses)
    if isinstance(r, Exception):
        raise r
    return r

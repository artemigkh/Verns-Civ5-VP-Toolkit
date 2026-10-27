"""The bridge: keeps a c5h queue playing and reports it to the hypervisor.

Scheduling follows the runner's: a start request (any slot's ``/start-game``, or ``autostart``) turns
it on, and the bridge then keeps a batch playing; when a batch is done it writes the next one
(``continuous``). A stop request turns it off and lets the queue drain: running games finish and are
uploaded, no new game starts. c5h itself fills the worker slots as games end.

The scheduling intent (on or off, and the turn cap) is kept in ``<work_dir>/schedule.json``, so a
bridge that restarts carries on as before: it adopts a queue that kept playing, or starts the next one.

Every ``poll_interval_sec`` the bridge hands finished games to the hypervisor (``harvest``) and
restarts the queue if it ended while scheduling is on. A queue that keeps ending within a minute of
its start without finishing a game (a broken spec, a missing database) turns scheduling off and shows
the slots as failed, instead of restarting it in a loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time

import httpx

from autoplay.common import HeartbeatPayload, RunnerKind, RunnerState
from autoplay.headless import harvest
from autoplay.headless.batches import Batch, all_batches, latest_batch, write_batch
from autoplay.headless.config import HeadlessConfig
from autoplay.headless.queue_process import QueueProcess
from autoplay.headless.slots import SlotSnapshot, slot_uuid, snapshot_slots

logger = logging.getLogger(__name__)

QUICK_EXIT_SEC = 60.0
"""A queue that ends sooner than this after its start, having finished no game, failed to start."""

MAX_QUICK_EXITS = 3

SCHEDULE_FILENAME = "schedule.json"


class Bridge:
    def __init__(self, cfg: HeadlessConfig, base_url: str, queue: QueueProcess | None = None) -> None:
        self.cfg = cfg
        self.base_url = base_url.rstrip("/")
        self.queue = queue or QueueProcess(cfg)
        self.ledger = harvest.Ledger(cfg.work_dir)
        self.scheduling = False
        self.stopping = False
        self.failed: str | None = None
        self.max_turn: int | None = None
        self._quick_exits = 0
        self._finished_at_start = 0
        self._lock = asyncio.Lock()

    # --- identity --------------------------------------------------------

    def slot_url(self, slot: int) -> str:
        return f"{self.base_url}/slots/{slot}"

    def slot_uuid(self, slot: int) -> str:
        return slot_uuid(self.cfg.work_dir, slot)

    # --- control ---------------------------------------------------------

    async def start(self, max_turn: int | None = None) -> str:
        """Turn scheduling on (idempotent). ``max_turn`` caps the games of batches written from now on."""
        async with self._lock:
            self.max_turn = max_turn
            self.scheduling, self.failed, self._quick_exits = True, None, 0
            self._save_schedule()
            if self.queue.running():
                if self.stopping:
                    self.queue.cancel_stop()
                    self.stopping = False
                    logger.info("Start request: cancelled the drain of %s", self.queue.batch.name)
                    return "resumed"
                return "running"
            self._launch()
            return "started"

    async def stop(self) -> str:
        """Turn scheduling off and let the running games finish (idempotent)."""
        async with self._lock:
            self.scheduling = False
            self._save_schedule()
            if self.stopping:
                return "stopping"  # Stop All reaches every slot: one drain is enough
            if self.queue.running():
                self.queue.request_stop()
                self.stopping = True
                logger.info("Stop request: draining %s (running games finish)", self.queue.batch.name)
                return "stopping"
            return "stopped"

    async def restore(self) -> None:
        """At startup: adopt a queue that kept playing, else resume scheduling if it was on."""
        try:
            saved = json.loads((self.cfg.work_dir / SCHEDULE_FILENAME).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        if self.queue.adopt():
            self.scheduling, self.max_turn = True, saved.get("maxTurn")
        elif saved.get("scheduling"):
            logger.info("Scheduling was on when the bridge last ran; resuming")
            await self.start(saved.get("maxTurn"))
        elif self.cfg.autostart:
            await self.start()

    def _save_schedule(self) -> None:
        path = self.cfg.work_dir / SCHEDULE_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        intent = {"scheduling": self.scheduling, "maxTurn": self.max_turn}
        path.write_text(json.dumps(intent), encoding="utf-8")

    def _launch(self) -> None:
        """Start the latest batch if it has games left, else a new one."""
        batch = latest_batch(self.cfg.work_dir)
        if batch is None or not batch.unfinished():
            batch = write_batch(self.cfg, self.max_turn or self.cfg.turns)
            logger.info(
                "Wrote %s: %d games to turn %d",
                batch.name,
                self.cfg.games_per_batch,
                self.max_turn or self.cfg.turns,
            )
        self._finished_at_start = len(batch.job_names()) - len(batch.unfinished())
        self.queue.start(batch)

    # --- supervision ------------------------------------------------------

    async def supervise_once(self, client: httpx.AsyncClient) -> None:
        """Hand over finished games, then restart the queue if it ended while scheduling is on."""
        await self.harvest(client, [self.queue.batch] if self.queue.batch else [])
        async with self._lock:
            if self.queue.running():
                return
            batch = self.queue.batch
            if self.stopping:
                self.stopping = False
                logger.info("Queue drained; scheduling is off")
            if not self.scheduling or batch is None:
                return
            finished = len(batch.job_names()) - len(batch.unfinished())
            quick = (time.time() - (self.queue.started_at or 0)) < QUICK_EXIT_SEC
            if quick and finished == self._finished_at_start:
                self._quick_exits += 1
                logger.error(
                    "c5h queue %s ended %.0f s after its start without finishing a game (exit %s); see %s",
                    batch.name,
                    time.time() - (self.queue.started_at or 0),
                    self.queue.returncode(),
                    self.cfg.work_dir / "logs" / f"{batch.name}.out",
                )
                if self._quick_exits >= MAX_QUICK_EXITS:
                    self.scheduling = False
                    self._save_schedule()
                    self.failed = f"c5h queue failed to start {MAX_QUICK_EXITS} times; see {batch.name}.out"
                    logger.error("Scheduling turned off: %s", self.failed)
                    return
            else:
                self._quick_exits = 0
            if batch.unfinished() or self.cfg.continuous:
                self._launch()
            else:
                self.scheduling = False
                self._save_schedule()
                logger.info("Batch %s done; scheduling is off (continuous is off)", batch.name)

    async def harvest(self, client: httpx.AsyncClient, batches: list[Batch]) -> int:
        """Hand over the finished, not yet handed over games of ``batches``. Returns how many."""
        done = 0
        for batch in batches:
            for h in harvest.finished_games(batch, self.ledger, self.cfg.work_dir):
                await harvest.hand_over(
                    client,
                    h,
                    hypervisor_url=self.cfg.hypervisor_url,
                    modpack=self.cfg.modpack,
                    runner_url=self.slot_url(h.slot),
                    pending_dir=self.cfg.pending_dir,
                    ledger=self.ledger,
                )
                done += 1
        return done

    async def harvest_all(self, client: httpx.AsyncClient) -> int:
        """Hand over anything any batch left (a bridge that stopped before it could)."""
        return await self.harvest(client, all_batches(self.cfg.work_dir))

    # --- reporting --------------------------------------------------------

    def snapshots(self) -> list[SlotSnapshot]:
        snaps = snapshot_slots(
            self.queue.batch,
            self.cfg.workers,
            queue_running=self.queue.running(),
            stopping=self.stopping,
            now=time.time(),
        )
        if self.failed:
            for s in snaps:
                if s.state == RunnerState.idle:
                    s.state = RunnerState.failed
        return snaps

    def heartbeats(self) -> list[HeartbeatPayload]:
        return [
            HeartbeatPayload(
                uuid=self.slot_uuid(s.slot),
                state=s.state,
                game_id=s.game_id,
                turn=s.turn,
                time_elapsed_sec=s.time_elapsed_sec,
                last_turn_sec=s.last_turn_sec,
                url=self.slot_url(s.slot),
                modpack=self.cfg.modpack,
                kind=RunnerKind.headless,
            )
            for s in self.snapshots()
        ]

    def status(self) -> dict:
        batch = self.queue.batch
        return {
            "scheduling": self.scheduling,
            "stopping": self.stopping,
            "failed": self.failed,
            "maxTurn": self.max_turn,
            "queueRunning": self.queue.running(),
            "batch": batch.name if batch else None,
            "batchUnfinished": len(batch.unfinished()) if batch else None,
            "gamesHandedOver": len(self.ledger),
            "slots": [
                {
                    "slot": s.slot,
                    "uuid": self.slot_uuid(s.slot),
                    "state": s.state.value,
                    "job": s.job,
                    "gameId": s.game_id,
                    "turn": s.turn,
                    "timeElapsedSec": s.time_elapsed_sec,
                    "lastTurnSec": s.last_turn_sec,
                }
                for s in self.snapshots()
            ],
        }


async def heartbeat_loop(bridge: Bridge, stop_event: asyncio.Event) -> None:
    """Send every slot's heartbeat until ``stop_event`` is set; the hypervisor auto-registers new slots."""
    url = f"{bridge.cfg.hypervisor_url.rstrip('/')}/runner-heartbeat"
    async with httpx.AsyncClient(timeout=10.0) as client:
        while not stop_event.is_set():
            payloads = bridge.heartbeats()
            results = await asyncio.gather(
                *(client.post(url, json=p.model_dump(by_alias=True, mode="json")) for p in payloads),
                return_exceptions=True,
            )
            for p, r in zip(payloads, results, strict=True):
                if isinstance(r, Exception):
                    logger.debug("Heartbeat for slot %s failed: %s", p.url, r)
                elif r.status_code >= 400:
                    logger.warning("Heartbeat for slot %s rejected: %s %s", p.url, r.status_code, r.text)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=bridge.cfg.heartbeat_interval_sec)


async def supervise_loop(bridge: Bridge, stop_event: asyncio.Event) -> None:
    async with httpx.AsyncClient(timeout=300.0) as client:
        await bridge.harvest_all(client)
        while not stop_event.is_set():
            try:
                await bridge.supervise_once(client)
            except Exception:  # noqa: BLE001 - one bad pass must not end supervision
                logger.exception("Supervision pass failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=bridge.cfg.poll_interval_sec)


async def deregister_slots(bridge: Bridge) -> None:
    url = f"{bridge.cfg.hypervisor_url.rstrip('/')}/deregister-runner"
    async with httpx.AsyncClient(timeout=5.0) as client:
        await asyncio.gather(
            *(client.post(url, json={"uuid": bridge.slot_uuid(k)}) for k in range(bridge.cfg.workers)),
            return_exceptions=True,
        )

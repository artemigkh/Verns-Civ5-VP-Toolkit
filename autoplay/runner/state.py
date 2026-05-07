"""In-process runner state shared by the heartbeat loop and HTTP endpoints."""

from __future__ import annotations

import threading
import uuid as uuid_module
from dataclasses import dataclass, field

from autoplay.common import RunnerState


@dataclass
class RunnerGlobalState:
    """Single-process global state for the runner.

    Per the design doc the runner is explicitly single-process; all handlers and
    the heartbeat loop share this object guarded by a single lock.
    """

    uuid: str = field(default_factory=lambda: str(uuid_module.uuid4()))
    url: str | None = None
    modpack: str | None = None
    state: RunnerState = RunnerState.idle
    current_game_id: str | None = None
    current_game_start_time: float | None = None
    current_game_turn: int | None = None
    # When True, the runner automatically starts another game after the current
    # one finishes (success or crash) and all artifacts have been uploaded.
    # /start-game sets this True; /stop-game sets it False.
    is_scheduling_games: bool = False
    # Unix timestamp of the last successful heartbeat round-trip, or None if
    # no heartbeat has succeeded yet. Used to detect "hypervisor down".
    last_successful_heartbeat_ts: float | None = None
    # If True, a finished game wanted to auto-reschedule but the hypervisor
    # was unreachable, so the runner stayed idle. The heartbeat loop will
    # trigger a deferred relaunch the next time it sees a successful POST.
    pending_reschedule: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> "RunnerGlobalState":
        with self.lock:
            return RunnerGlobalState(
                uuid=self.uuid,
                url=self.url,
                modpack=self.modpack,
                state=self.state,
                current_game_id=self.current_game_id,
                current_game_start_time=self.current_game_start_time,
                current_game_turn=self.current_game_turn,
                is_scheduling_games=self.is_scheduling_games,
                last_successful_heartbeat_ts=self.last_successful_heartbeat_ts,
                pending_reschedule=self.pending_reschedule,
            )


_STATE: RunnerGlobalState | None = None


def get_state() -> RunnerGlobalState:
    global _STATE
    if _STATE is None:
        _STATE = RunnerGlobalState()
    return _STATE

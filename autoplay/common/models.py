"""Pydantic models shared across the REST API surface."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RunnerState(str, Enum):
    """Lifecycle states of a runner as reported in heartbeats."""

    idle = "idle"
    starting = "starting"
    running = "running"
    stopping = "stopping"
    failed = "failed"
    harvesting_logs = "harvesting_logs"
    uploading_logs = "uploading_logs"
    updating_modpack = "updating_modpack"
    attempting_recovery = "attempting_recovery"
    # Pulse-only state: emitted in a single heartbeat after a recovery succeeds,
    # immediately before transitioning back to ``running``. Used by the
    # hypervisor to bump a per-runner ``recovery_count``.
    recovered = "recovered"


class RunnerKind(str, Enum):
    """What sits behind a runner row.

    ``client`` is the classic runner driving a full Civ 5 game client.
    ``headless`` is one worker slot of a headless bridge (``autoplay.headless``)
    that plays games in civ5-headless; it has no modpack install or autosave
    resume, and control actions on any of its slots act on the whole bridge.
    """

    client = "client"
    headless = "headless"


class _CamelModel(BaseModel):
    """Base model that accepts and emits camelCase JSON keys."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=lambda s: _to_camel(s))


def _to_camel(snake: str) -> str:
    parts = snake.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


class RunnerRegistration(_CamelModel):
    """Payload sent by a runner when it first registers with the hypervisor."""

    uuid: str
    url: str
    modpack: str | None = None
    kind: RunnerKind = RunnerKind.client


class StartGameRequest(_CamelModel):
    """Optional body of the runner's ``/start-game`` and ``/resume-game`` endpoints.

    ``max_turn`` caps game length: once the game reaches this turn the runner
    ends it and harvests/uploads its stats exactly as for a normal completion.
    ``None`` means no cap (play to a natural game end).
    """

    max_turn: int | None = Field(default=None, ge=1)


class HeartbeatPayload(_CamelModel):
    """Periodic heartbeat payload from a runner.

    ``url`` and ``modpack`` are included so the hypervisor can transparently
    re-register a runner whose entry was lost (e.g. hypervisor restart) without
    requiring the runner to detect the loss and re-POST /runner-registration.
    """

    uuid: str
    state: RunnerState
    game_id: str | None = None
    turn: int | None = None
    time_elapsed_sec: int | None = None
    url: str | None = None
    modpack: str | None = None
    kind: RunnerKind | None = Field(
        default=None,
        description="Runner kind, for auto-registration from a heartbeat. None keeps the stored kind.",
    )
    last_turn_sec: float | None = Field(
        default=None,
        description="Seconds the most recently completed turn took. None when unknown.",
    )


class RunnerStatusRow(_CamelModel):
    """Row returned by GET /runner-status describing a live runner."""

    uuid: str
    url: str
    modpack: str | None = None
    state: RunnerState
    game_id: str | None = None
    turn: int | None = None
    time_elapsed_sec: int | None = None
    kind: RunnerKind = RunnerKind.client
    last_turn_sec: float | None = Field(
        default=None,
        description="Seconds the most recently completed turn took, as last reported.",
    )
    last_heartbeat_ts: float = Field(
        description="Unix timestamp (seconds) of the most recent heartbeat received."
    )
    success_count: int = Field(default=0, description="Completed games for this runner.")
    failure_count: int = Field(default=0, description="Failed/crashed games for this runner.")
    recovery_count: int = Field(
        default=0,
        description="Times this runner successfully recovered a crashed game by reloading the autosave.",
    )


class FileStatus(BaseModel):
    """Aggregate counts of completed and failed games per modpack version."""

    complete: dict[str, int] = Field(default_factory=dict)
    failed: dict[str, int] = Field(default_factory=dict)

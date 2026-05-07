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


class RunnerStatusRow(_CamelModel):
    """Row returned by GET /runner-status describing a live runner."""

    uuid: str
    url: str
    modpack: str | None = None
    state: RunnerState
    game_id: str | None = None
    turn: int | None = None
    time_elapsed_sec: int | None = None
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

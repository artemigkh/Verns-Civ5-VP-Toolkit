"""Tests for autoplay.common.models (camelCase aliasing + schema round-trips)."""

from __future__ import annotations

import pytest

from autoplay.common.models import (
    FileStatus,
    HeartbeatPayload,
    RunnerRegistration,
    RunnerState,
    RunnerStatusRow,
    _to_camel,
)


class TestToCamel:
    @pytest.mark.parametrize(
        "snake,expected",
        [
            ("", ""),
            ("foo", "foo"),
            ("foo_bar", "fooBar"),
            ("foo_bar_baz", "fooBarBaz"),
            ("game_id", "gameId"),
            ("time_elapsed_sec", "timeElapsedSec"),
            ("last_heartbeat_ts", "lastHeartbeatTs"),
        ],
    )
    def test_basic_conversion(self, snake: str, expected: str) -> None:
        assert _to_camel(snake) == expected


class TestRunnerRegistration:
    def test_dump_uses_camel_aliases(self) -> None:
        reg = RunnerRegistration(uuid="u1", url="http://h", modpack="MP_AUTOPLAY_VP_1")
        d = reg.model_dump(by_alias=True)
        assert d == {"uuid": "u1", "url": "http://h", "modpack": "MP_AUTOPLAY_VP_1"}

    def test_accepts_snake_and_camel(self) -> None:
        # No underscored fields here, but at least ensure construction works.
        r1 = RunnerRegistration.model_validate(
            {"uuid": "u1", "url": "http://h", "modpack": None}
        )
        assert r1.modpack is None


class TestHeartbeatPayload:
    def test_camel_aliases_on_dump(self) -> None:
        hb = HeartbeatPayload(
            uuid="u1",
            state=RunnerState.running,
            game_id="g1",
            turn=42,
            time_elapsed_sec=120,
            url="http://r",
            modpack="MP_AUTOPLAY_VP_1",
        )
        d = hb.model_dump(by_alias=True)
        assert d["gameId"] == "g1"
        assert d["timeElapsedSec"] == 120
        assert "game_id" not in d
        assert "time_elapsed_sec" not in d

    def test_validate_accepts_camel_input(self) -> None:
        hb = HeartbeatPayload.model_validate(
            {
                "uuid": "u1",
                "state": "running",
                "gameId": "g1",
                "turn": 5,
                "timeElapsedSec": 17,
                "url": "http://r",
                "modpack": "MP_AUTOPLAY_VP_1",
            }
        )
        assert hb.game_id == "g1"
        assert hb.time_elapsed_sec == 17
        assert hb.state == RunnerState.running

    def test_validate_accepts_snake_input(self) -> None:
        hb = HeartbeatPayload.model_validate(
            {
                "uuid": "u1",
                "state": "idle",
                "game_id": "g1",
                "turn": 5,
                "time_elapsed_sec": 17,
            }
        )
        assert hb.game_id == "g1"
        assert hb.time_elapsed_sec == 17

    def test_optional_fields_default_to_none(self) -> None:
        hb = HeartbeatPayload(uuid="u1", state=RunnerState.idle)
        assert hb.game_id is None
        assert hb.turn is None
        assert hb.time_elapsed_sec is None
        assert hb.url is None
        assert hb.modpack is None


class TestRunnerStatusRow:
    def test_camel_aliases_present(self) -> None:
        row = RunnerStatusRow(
            uuid="u1",
            url="http://r",
            modpack=None,
            state=RunnerState.idle,
            last_heartbeat_ts=1700000000.0,
        )
        d = row.model_dump(by_alias=True)
        assert d["lastHeartbeatTs"] == 1700000000.0
        assert d["successCount"] == 0
        assert d["failureCount"] == 0
        assert d["recoveryCount"] == 0


class TestFileStatus:
    def test_default_empty_dicts(self) -> None:
        fs = FileStatus()
        assert fs.complete == {}
        assert fs.failed == {}

    def test_round_trip(self) -> None:
        fs = FileStatus(complete={"MP_AUTOPLAY_VP_1": 3}, failed={"MP_AUTOPLAY_VP_1": 1})
        d = fs.model_dump()
        again = FileStatus.model_validate(d)
        assert again == fs


class TestRunnerStateEnum:
    def test_recovered_is_pulse_state(self) -> None:
        assert RunnerState.recovered.value == "recovered"

    def test_all_states_string_values(self) -> None:
        for s in RunnerState:
            assert isinstance(s.value, str) and s.value

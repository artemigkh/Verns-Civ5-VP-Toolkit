"""End-to-end integration tests for the CSV snapshot+consolidation pipeline.

Drives ``_snapshot_csv_segment`` and ``_consolidate_csv_segments`` together
to verify that a multi-recovery game produces a coherent splice of:
* the original Logs/ contents (treated as the final segment), plus
* every intermediate seg_NNN/ snapshot,

with proper header de-duplication for headered CSVs and raw concatenation
for non-headered CSVs.
"""

from __future__ import annotations

from pathlib import Path

from autoplay.runner.game_controller import (
    _consolidate_csv_segments,
    _snapshot_csv_segment,
)


def test_three_recovery_cycles_produce_coherent_csvs(tmp_path: Path) -> None:
    user_dir = tmp_path
    logs = user_dir / "Logs"
    logs.mkdir()
    game_id = "g_cycle"

    # --- Cycle 1: turns 1-3 then "crash" ---
    (logs / "WorldState_Log.csv").write_bytes(
        b"Turn,Player,Score\n1,A,10\n2,A,20\n3,A,30\n"
    )
    (logs / "Score_Log.csv").write_bytes(
        b"Turn,Player\n1,A\n2,A\n3,A\n"
    )
    (logs / "RawLog.csv").write_bytes(b"raw1\nraw2\nraw3\n")
    seg0 = _snapshot_csv_segment(logs, game_id, user_dir, label="cycle1")
    assert seg0 is not None and seg0.name == "seg_000"

    # --- Cycle 2: after recovery, turns 4-5 then crash ---
    (logs / "WorldState_Log.csv").write_bytes(
        b"Turn,Player,Score\n4,A,40\n5,A,50\n"
    )
    (logs / "Score_Log.csv").write_bytes(b"Turn,Player\n4,A\n5,A\n")
    (logs / "RawLog.csv").write_bytes(b"raw4\nraw5\n")
    seg1 = _snapshot_csv_segment(logs, game_id, user_dir, label="cycle2")
    assert seg1 is not None and seg1.name == "seg_001"

    # --- Cycle 3 (final): turns 6-7, no crash; current Logs is final segment ---
    (logs / "WorldState_Log.csv").write_bytes(
        b"Turn,Player,Score\n6,A,60\n7,A,70\n"
    )
    (logs / "Score_Log.csv").write_bytes(b"Turn,Player\n6,A\n7,A\n")
    (logs / "RawLog.csv").write_bytes(b"raw6\nraw7\n")

    rewritten = _consolidate_csv_segments(logs, game_id, user_dir)
    assert rewritten == 3

    # Headered CSVs: header from seg_000 only.
    assert (logs / "WorldState_Log.csv").read_bytes() == (
        b"Turn,Player,Score\n"
        b"1,A,10\n2,A,20\n3,A,30\n"
        b"4,A,40\n5,A,50\n"
        b"6,A,60\n7,A,70\n"
    )
    assert (logs / "Score_Log.csv").read_bytes() == (
        b"Turn,Player\n"
        b"1,A\n2,A\n3,A\n"
        b"4,A\n5,A\n"
        b"6,A\n7,A\n"
    )
    # Non-headered CSV: raw concatenation.
    assert (logs / "RawLog.csv").read_bytes() == (
        b"raw1\nraw2\nraw3\nraw4\nraw5\nraw6\nraw7\n"
    )


def test_consolidation_when_only_some_csvs_present_in_each_segment(
    tmp_path: Path,
) -> None:
    """A CSV that only appears in a later cycle still gets consolidated correctly."""
    user_dir = tmp_path
    logs = user_dir / "Logs"
    logs.mkdir()
    gid = "gid"

    # Cycle 1: only WorldState_Log
    (logs / "WorldState_Log.csv").write_bytes(b"Turn,X\n1,a\n")
    _snapshot_csv_segment(logs, gid, user_dir, label="c1")

    # Cycle 2: WorldState_Log + LateLog appears for first time
    (logs / "WorldState_Log.csv").write_bytes(b"Turn,X\n2,b\n")
    (logs / "LateLog.csv").write_bytes(b"late1\nlate2\n")
    _snapshot_csv_segment(logs, gid, user_dir, label="c2")

    # Final
    (logs / "WorldState_Log.csv").write_bytes(b"Turn,X\n3,c\n")
    (logs / "LateLog.csv").write_bytes(b"late3\n")
    _consolidate_csv_segments(logs, gid, user_dir)

    assert (logs / "WorldState_Log.csv").read_bytes() == b"Turn,X\n1,a\n2,b\n3,c\n"
    assert (logs / "LateLog.csv").read_bytes() == b"late1\nlate2\nlate3\n"


def test_consolidation_idempotent_with_no_segments(tmp_path: Path) -> None:
    logs = tmp_path / "Logs"
    logs.mkdir()
    (logs / "WorldState_Log.csv").write_bytes(b"Turn\n1\n")
    n = _consolidate_csv_segments(logs, "no_such_game", tmp_path)
    assert n == 0
    assert (logs / "WorldState_Log.csv").read_bytes() == b"Turn\n1\n"

"""Tests for autoplay.hypervisor.bundles_db."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from autoplay.hypervisor import bundles_db


def test_record_creates_db_and_inserts(tmp_path: Path) -> None:
    bundles_db.record_bundle(
        tmp_path,
        modpack="MP_AUTOPLAY_VP_1",
        bundle_name="g1.tar",
        game_id="g1",
        runner_uuid="u1",
        file_size_bytes=42,
        metadata={"finalTurn": 100, "timeElapsedSec": 600},
    )
    db_path = tmp_path / "MP_AUTOPLAY_VP_1_bundles.sqlite"
    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT bundle_name, game_id, runner_uuid, file_size_bytes, metadata_json "
            "FROM bundles"
        ).fetchall()
    assert len(rows) == 1
    name, gid, uuid, size, meta = rows[0]
    assert name == "g1.tar"
    assert gid == "g1"
    assert uuid == "u1"
    assert size == 42
    assert json.loads(meta) == {"finalTurn": 100, "timeElapsedSec": 600}


def test_record_appends_multiple(tmp_path: Path) -> None:
    for i in range(3):
        bundles_db.record_bundle(
            tmp_path,
            modpack="MP",
            bundle_name=f"b{i}.tar",
            game_id=f"g{i}",
            runner_uuid="u",
            file_size_bytes=i,
            metadata=None,
        )
    db_path = tmp_path / "MP_bundles.sqlite"
    with sqlite3.connect(db_path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM bundles").fetchone()[0]
    assert n == 3


def test_record_with_none_metadata_writes_empty_dict(tmp_path: Path) -> None:
    bundles_db.record_bundle(
        tmp_path, modpack="M", bundle_name="b", game_id="g",
        runner_uuid=None, file_size_bytes=0, metadata=None,
    )
    with sqlite3.connect(tmp_path / "M_bundles.sqlite") as conn:
        meta = conn.execute("SELECT metadata_json FROM bundles").fetchone()[0]
    assert json.loads(meta) == {}


def test_per_modpack_dbs_separated(tmp_path: Path) -> None:
    bundles_db.record_bundle(
        tmp_path, modpack="A", bundle_name="x", game_id="g", runner_uuid="u",
        file_size_bytes=1,
    )
    bundles_db.record_bundle(
        tmp_path, modpack="B", bundle_name="y", game_id="g", runner_uuid="u",
        file_size_bytes=1,
    )
    assert (tmp_path / "A_bundles.sqlite").exists()
    assert (tmp_path / "B_bundles.sqlite").exists()

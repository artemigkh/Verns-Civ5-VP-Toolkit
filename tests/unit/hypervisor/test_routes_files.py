"""Tests for hypervisor /submit-logs, /submit-crash, /file-status routes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autoplay.hypervisor.app import create_app
from autoplay.hypervisor.config import HypervisorConfig


@pytest.fixture
def client_and_root(tmp_storage_root: Path):
    cfg = HypervisorConfig(
        storage_root=tmp_storage_root,
        port=5999,
        host="127.0.0.1",
        runner_timeout_sec=120,
    )
    app = create_app(cfg)
    with TestClient(app) as c:
        yield c, tmp_storage_root


def test_submit_logs_writes_tar_and_records_bundle(client_and_root) -> None:
    client, root = client_and_root
    # Pre-register the runner so success_count can increment.
    client.post(
        "/runner-registration",
        json={"uuid": "u1", "url": "http://r", "modpack": "MP_AUTOPLAY_VP_1"},
    )
    r = client.post(
        "/submit-logs",
        data={
            "modpack": "MP_AUTOPLAY_VP_1",
            "gameId": "g1",
            "runnerUuid": "u1",
            "turn": "100",
            "timeElapsedSec": "600",
        },
        files={"file": ("g1.tar", b"tar-bytes", "application/x-tar")},
    )
    assert r.status_code == 204
    dest = root / "MP_AUTOPLAY_VP_1" / "complete" / "g1.tar"
    assert dest.read_bytes() == b"tar-bytes"
    # bundles_db row
    bundles_db_path = root / "MP_AUTOPLAY_VP_1_bundles.sqlite"
    assert bundles_db_path.exists()
    with sqlite3.connect(bundles_db_path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM bundles").fetchone()[0]
    assert n == 1
    # success counter incremented
    rows = client.get("/runner-status").json()
    assert rows[0]["successCount"] == 1


def test_submit_logs_invalid_modpack_rejected(client_and_root) -> None:
    client, _ = client_and_root
    r = client.post(
        "/submit-logs",
        data={"modpack": "../etc", "gameId": "g1"},
        files={"file": ("g1.tar", b"x")},
    )
    assert r.status_code == 400


def test_submit_logs_invalid_game_id_rejected(client_and_root) -> None:
    client, _ = client_and_root
    r = client.post(
        "/submit-logs",
        data={"modpack": "MP_AUTOPLAY_VP_1", "gameId": "../bad"},
        files={"file": ("g.tar", b"x")},
    )
    assert r.status_code == 400


def test_submit_crash_tar_extension(client_and_root) -> None:
    client, root = client_and_root
    r = client.post(
        "/submit-crash",
        data={"modpack": "MP_AUTOPLAY_VP_1", "gameId": "g2", "final": "false"},
        files={"file": ("g2.tar", b"crash-data", "application/x-tar")},
    )
    assert r.status_code == 204
    assert (root / "MP_AUTOPLAY_VP_1" / "failed" / "g2.tar").read_bytes() == b"crash-data"


def test_submit_crash_civ5save_extension(client_and_root) -> None:
    client, root = client_and_root
    r = client.post(
        "/submit-crash",
        data={"modpack": "MP_AUTOPLAY_VP_1", "gameId": "g3", "final": "true"},
        files={"file": ("g3.Civ5Save", b"save-data")},
    )
    assert r.status_code == 204
    assert (root / "MP_AUTOPLAY_VP_1" / "failed" / "g3.Civ5Save").exists()


def test_submit_crash_final_increments_failure(client_and_root) -> None:
    client, _ = client_and_root
    client.post(
        "/runner-registration",
        json={"uuid": "u1", "url": "http://r", "modpack": "MP_AUTOPLAY_VP_1"},
    )
    client.post(
        "/submit-crash",
        data={
            "modpack": "MP_AUTOPLAY_VP_1",
            "gameId": "g4",
            "final": "true",
            "runnerUuid": "u1",
        },
        files={"file": ("g4.tar", b"x")},
    )
    rows = client.get("/runner-status").json()
    assert rows[0]["failureCount"] == 1


def test_file_status_counts_complete_and_failed(client_and_root) -> None:
    client, root = client_and_root
    # Submit two completes and one failed.
    for gid in ("a", "b"):
        client.post(
            "/submit-logs",
            data={"modpack": "MP_AUTOPLAY_VP_1", "gameId": gid},
            files={"file": (f"{gid}.tar", b"x")},
        )
    client.post(
        "/submit-crash",
        data={"modpack": "MP_AUTOPLAY_VP_1", "gameId": "c", "final": "false"},
        files={"file": ("c.tar", b"x")},
    )
    r = client.get("/file-status")
    assert r.status_code == 200
    body = r.json()
    assert body["complete"]["MP_AUTOPLAY_VP_1"] == 2
    assert body["failed"]["MP_AUTOPLAY_VP_1"] == 1


def test_file_status_unique_failed_stems(client_and_root) -> None:
    """One crashed game depositing both .tar and .Civ5Save counts as 1 failed."""
    client, _ = client_and_root
    client.post(
        "/submit-crash",
        data={"modpack": "MP_AUTOPLAY_VP_1", "gameId": "x", "final": "false"},
        files={"file": ("x.tar", b"a")},
    )
    client.post(
        "/submit-crash",
        data={"modpack": "MP_AUTOPLAY_VP_1", "gameId": "x", "final": "true"},
        files={"file": ("x.Civ5Save", b"b")},
    )
    r = client.get("/file-status")
    assert r.json()["failed"]["MP_AUTOPLAY_VP_1"] == 1


def test_submit_logs_collision_renames_game_id(client_and_root) -> None:
    """Two bundles arriving with the same game_id must not clobber each other.

    The second submission should be stored as ``<gameId>-1.tar``, the third as
    ``<gameId>-2.tar``, and so on. Each bundle must be recorded in bundles_db
    under its disambiguated game_id.
    """
    client, root = client_and_root
    complete_dir = root / "MP_AUTOPLAY_VP_1" / "complete"

    # First submission: stored as "dup.tar" with game_id "dup".
    r1 = client.post(
        "/submit-logs",
        data={"modpack": "MP_AUTOPLAY_VP_1", "gameId": "dup"},
        files={"file": ("dup.tar", b"first")},
    )
    assert r1.status_code == 204

    # Second submission with the same game_id -> "dup-1.tar".
    r2 = client.post(
        "/submit-logs",
        data={"modpack": "MP_AUTOPLAY_VP_1", "gameId": "dup"},
        files={"file": ("dup.tar", b"second")},
    )
    assert r2.status_code == 204

    # Third submission with the same game_id -> "dup-2.tar".
    r3 = client.post(
        "/submit-logs",
        data={"modpack": "MP_AUTOPLAY_VP_1", "gameId": "dup"},
        files={"file": ("dup.tar", b"third")},
    )
    assert r3.status_code == 204

    # All three bundles preserved on disk with distinct names + contents.
    assert (complete_dir / "dup.tar").read_bytes() == b"first"
    assert (complete_dir / "dup-1.tar").read_bytes() == b"second"
    assert (complete_dir / "dup-2.tar").read_bytes() == b"third"

    # bundles_db records each bundle under its unique game_id.
    bundles_db_path = root / "MP_AUTOPLAY_VP_1_bundles.sqlite"
    with sqlite3.connect(bundles_db_path) as conn:
        rows = conn.execute(
            "SELECT game_id, bundle_name, metadata_json "
            "FROM bundles ORDER BY id"
        ).fetchall()
    assert [r[0] for r in rows] == ["dup", "dup-1", "dup-2"]
    assert [r[1] for r in rows] == ["dup.tar", "dup-1.tar", "dup-2.tar"]
    # Renamed entries record the original gameId in their metadata.
    import json as _json

    assert "originalGameId" not in _json.loads(rows[0][2])
    assert _json.loads(rows[1][2])["originalGameId"] == "dup"
    assert _json.loads(rows[2][2])["originalGameId"] == "dup"

    # file-status reflects the three completed bundles.
    body = client.get("/file-status").json()
    assert body["complete"]["MP_AUTOPLAY_VP_1"] == 3


def test_submit_logs_collision_skips_used_suffixes(client_and_root) -> None:
    """``-1`` already on disk should cause the next collision to use ``-2``."""
    client, root = client_and_root
    complete_dir = root / "MP_AUTOPLAY_VP_1" / "complete"
    complete_dir.mkdir(parents=True, exist_ok=True)
    # Pre-seed both the original and ``-1`` variants on disk.
    (complete_dir / "g.tar").write_bytes(b"old")
    (complete_dir / "g-1.tar").write_bytes(b"older")

    r = client.post(
        "/submit-logs",
        data={"modpack": "MP_AUTOPLAY_VP_1", "gameId": "g"},
        files={"file": ("g.tar", b"new")},
    )
    assert r.status_code == 204
    assert (complete_dir / "g-2.tar").read_bytes() == b"new"
    # Existing files on disk are not modified.
    assert (complete_dir / "g.tar").read_bytes() == b"old"
    assert (complete_dir / "g-1.tar").read_bytes() == b"older"


def test_submit_logs_no_collision_keeps_original_game_id(client_and_root) -> None:
    """When no collision exists the bundle is stored under its original id."""
    client, root = client_and_root
    r = client.post(
        "/submit-logs",
        data={"modpack": "MP_AUTOPLAY_VP_1", "gameId": "fresh"},
        files={"file": ("fresh.tar", b"x")},
    )
    assert r.status_code == 204
    assert (root / "MP_AUTOPLAY_VP_1" / "complete" / "fresh.tar").exists()
    bundles_db_path = root / "MP_AUTOPLAY_VP_1_bundles.sqlite"
    with sqlite3.connect(bundles_db_path) as conn:
        row = conn.execute(
            "SELECT game_id, metadata_json FROM bundles"
        ).fetchone()
    assert row[0] == "fresh"
    import json as _json

    assert "originalGameId" not in _json.loads(row[1])

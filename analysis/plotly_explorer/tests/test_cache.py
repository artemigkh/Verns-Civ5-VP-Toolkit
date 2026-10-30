"""aggregate/cache.py: mtime freshness, per-CSV rebuilds, column self-healing, fingerprints."""

from __future__ import annotations

import os

import pandas as pd
import pytest

from plotly_explorer.aggregate.cache import ensure_csv, ensure_group, is_fresh


@pytest.fixture
def db_cfg(cfg):
    cfg.db_path.write_bytes(b"db")
    cfg.intermediate_data_dir.mkdir()
    return cfg


def _touch(path, mtime: float) -> None:
    os.utime(path, (mtime, mtime))


def test_is_fresh_compares_against_the_source_db(db_cfg):
    csv = db_cfg.intermediate_data_dir / "x.csv"
    assert not is_fresh(csv, db_cfg)  # missing
    csv.write_text("a\n1\n")
    db_mtime = os.path.getmtime(db_cfg.db_path)
    _touch(csv, db_mtime - 10)
    assert not is_fresh(csv, db_cfg)  # older than the DB
    _touch(csv, db_mtime)
    assert is_fresh(csv, db_cfg)  # same age counts as fresh


def test_ensure_csv_builds_once_then_reuses(db_cfg):
    csv = db_cfg.intermediate_data_dir / "sub" / "x.csv"  # parent is created
    calls = []

    def builder():
        calls.append(1)
        return pd.DataFrame({"a": [1, 2]})

    first = ensure_csv(db_cfg, csv, builder)
    second = ensure_csv(db_cfg, csv, builder)
    assert len(calls) == 1
    pd.testing.assert_frame_equal(first, second)
    assert csv.exists()


def test_ensure_csv_force_and_stale_rebuild(db_cfg):
    csv = db_cfg.intermediate_data_dir / "x.csv"
    calls = []

    def builder():
        calls.append(1)
        return pd.DataFrame({"a": [len(calls)]})

    ensure_csv(db_cfg, csv, builder)
    assert ensure_csv(db_cfg, csv, builder, force=True)["a"].iloc[0] == 2
    _touch(csv, os.path.getmtime(db_cfg.db_path) - 100)  # now older than the DB
    assert ensure_csv(db_cfg, csv, builder)["a"].iloc[0] == 3


def test_ensure_csv_rebuilds_when_required_column_is_missing(db_cfg):
    csv = db_cfg.intermediate_data_dir / "x.csv"
    pd.DataFrame({"a": [1]}).to_csv(csv, index=False)
    _touch(csv, os.path.getmtime(db_cfg.db_path) + 10)  # fresh by mtime
    out = ensure_csv(db_cfg, csv, lambda: pd.DataFrame({"a": [1], "b": [2]}), required_columns=("b",))
    assert list(out.columns) == ["a", "b"]
    assert list(pd.read_csv(csv).columns) == ["a", "b"]


def test_ensure_group_rebuilds_all_when_one_is_stale(db_cfg):
    p1 = db_cfg.intermediate_data_dir / "one.csv"
    p2 = db_cfg.intermediate_data_dir / "two.csv"
    calls = []

    def builder():
        calls.append(1)
        return pd.DataFrame({"a": [1]}), pd.DataFrame({"b": [2]})

    ensure_group(db_cfg, [p1, p2], builder)
    assert len(calls) == 1
    p2.unlink()
    ensure_group(db_cfg, [p1, p2], builder)
    assert len(calls) == 2
    assert p1.exists() and p2.exists()


def test_ensure_group_fingerprint_invalidates_fresh_csvs(db_cfg):
    p1 = db_cfg.intermediate_data_dir / "one.csv"
    calls = []

    def builder():
        calls.append(1)
        return (pd.DataFrame({"a": [1]}),)

    ensure_group(db_cfg, [p1], builder, fingerprint="v1")
    ensure_group(db_cfg, [p1], builder, fingerprint="v1")
    assert len(calls) == 1
    assert p1.with_suffix(".fingerprint").read_text(encoding="utf-8") == "v1"
    ensure_group(db_cfg, [p1], builder, fingerprint="v2")
    assert len(calls) == 2
    assert p1.with_suffix(".fingerprint").read_text(encoding="utf-8") == "v2"

"""Tests for autoplay.hypervisor.runner_names_db."""

from __future__ import annotations

from pathlib import Path

from autoplay.hypervisor import runner_names_db as rdb


def test_init_creates_db(tmp_path: Path) -> None:
    rdb.init(tmp_path)
    assert (tmp_path / "runner_names.sqlite").exists()


def test_set_get_delete(tmp_path: Path) -> None:
    rdb.init(tmp_path)
    assert rdb.all_names(tmp_path) == {}
    rdb.set_name(tmp_path, "192.168.2.5", "alpha")
    rdb.set_name(tmp_path, "192.168.2.6", "beta")
    assert rdb.all_names(tmp_path) == {
        "192.168.2.5": "alpha",
        "192.168.2.6": "beta",
    }
    assert rdb.delete_name(tmp_path, "192.168.2.5") is True
    assert rdb.delete_name(tmp_path, "192.168.2.5") is False
    assert rdb.all_names(tmp_path) == {"192.168.2.6": "beta"}


def test_set_name_overwrites(tmp_path: Path) -> None:
    rdb.init(tmp_path)
    rdb.set_name(tmp_path, "h1", "first")
    rdb.set_name(tmp_path, "h1", "second")
    assert rdb.all_names(tmp_path) == {"h1": "second"}

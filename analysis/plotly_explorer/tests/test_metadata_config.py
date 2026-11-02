"""config.py env loading and the metadata helpers the payload builders lean on."""

from __future__ import annotations

import pytest

from plotly_explorer import config as C
from plotly_explorer import metadata as M


def test_load_config_requires_the_three_paths(monkeypatch):
    for name in ("DB_TYPE", "DB_PATH", "INTERMEDIATE_DATA_DIR", "PUBLISH_DIR", "DB_MEMORY_LIMIT"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match="DB_PATH"):
        C.load_config()


def test_load_config_resolves_relative_paths_against_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_TYPE", " DuckDB ")
    monkeypatch.setenv("DB_PATH", "data/run/stats.duckdb")
    monkeypatch.setenv("INTERMEDIATE_DATA_DIR", "data/run/cache")
    monkeypatch.setenv("PUBLISH_DIR", str(tmp_path / "abs_public"))
    monkeypatch.delenv("DB_MEMORY_LIMIT", raising=False)
    cfg = C.load_config()
    assert cfg.db_type == "duckdb"
    assert cfg.db_path == tmp_path / "data" / "run" / "stats.duckdb"
    assert cfg.publish_dir == tmp_path / "abs_public"
    assert cfg.db_memory_limit == C.DEFAULT_DB_MEMORY_LIMIT
    assert cfg.index_html_path == tmp_path / "abs_public" / "index.html"
    assert cfg.game_result_path == cfg.intermediate_data_dir / "game_result.csv"


def test_load_config_rejects_unknown_db_type(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_TYPE", "postgres")
    monkeypatch.setenv("DB_PATH", "x")
    monkeypatch.setenv("INTERMEDIATE_DATA_DIR", "y")
    monkeypatch.setenv("PUBLISH_DIR", "z")
    with pytest.raises(SystemExit, match="DB_TYPE"):
        C.load_config()


def test_turn_buckets():
    starts = M.turn_bucket_starts()
    assert starts[0] == 0 and starts[-1] == 290 and len(starts) == 30
    assert M.turn_bucket_label(60) == "60-69"
    assert M.turn_bucket_label(starts[-1]) == "290-299"


def test_db_era_to_name():
    assert M.db_era_to_name(0) == "Ancient"
    assert M.db_era_to_name(1) == "Classical"
    assert M.db_era_to_name(99) is None


def test_civ_list_is_the_43_majors():
    civs = M.load_civ_list()
    assert len(civs) == 43
    assert civs == sorted(civs)
    assert not {"City State", "Barbarians"} & set(civs)
    assert {"Rome", "The Inca", "Venice"} <= set(civs)


def test_static_metadata_loads():
    meta = M.load_metadata()
    assert meta.buildings and meta.unique_to_base
    # Every unique maps to a base that heads a group containing it.
    for unique, base in meta.unique_to_base.items():
        assert unique in meta.unique_groups[base]
    assert M.load_wonder_eras()
    units = M.load_unit_metadata()
    assert units and all({"combat_class", "domain", "is_combat"} <= set(v) for v in units.values())
    leaders = M.load_leader_attributes()
    assert len(leaders.civs) == 43 and leaders.groups

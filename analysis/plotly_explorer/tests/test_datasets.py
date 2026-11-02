"""datasets.py: which datasets a build renders, and which reports each can show."""

from __future__ import annotations

import dataclasses

import pytest

from plotly_explorer import datasets as D
from plotly_explorer.config import CIV_TURN_ERA_TABLE, INSTANT_YIELDS_TABLE, RELIGION_TABLE, Config

ALL_TABLES = D._GAME_TABLES | {
    "BuildingsOverview",
    "BuildingYields",
    "BuildingInstantYields",
    RELIGION_TABLE,
    CIV_TURN_ERA_TABLE,
    "MapUnitsState",
    INSTANT_YIELDS_TABLE,
}

DESC = dict(patch="5.4.8", difficulty="Emperor", mapscript="Communitu 3.2.0", size="Standard")


@pytest.fixture
def default_cfg(tmp_path) -> Config:
    run_dir = tmp_path / "MP_AUTOPLAY_VP_5_4_8_headless"
    run_dir.mkdir()
    (run_dir / "stats.duckdb").write_bytes(b"")
    return Config(
        db_type="duckdb",
        db_path=run_dir / "stats.duckdb",
        intermediate_data_dir=run_dir / "plotly_explorer_cache",
        publish_dir=run_dir / "plotly_explorer_public",
    )


@pytest.fixture
def toml(tmp_path, monkeypatch):
    """Point datasets.py at a datasets.toml in tmp_path; returns a writer for it."""
    path = tmp_path / "datasets.toml"
    monkeypatch.setattr(D, "DATASETS_TOML", path)

    def write(text: str) -> None:
        path.write_text(text, encoding="utf-8")

    return write


def test_load_datasets_matches_default_by_db_path_and_drops_missing_dbs(tmp_path, default_cfg, toml):
    other = tmp_path / "MP_AUTOPLAY_VP_WARLORD" / "stats.db"
    other.parent.mkdir()
    other.write_bytes(b"")
    cache = tmp_path / "custom_cache"
    toml(
        f"""
[[dataset]]
id = "main"
label = "Main run"
db_path = "{default_cfg.db_path.as_posix()}"
patch = "ignored"
difficulty = "ignored"

[[dataset]]
id = "warlord"
label = "Warlord"
db_path = "{other.as_posix()}"
cache_dir = "{cache.as_posix()}"
patch = "5.3.3"
difficulty = "Warlord"

[[dataset]]
id = "gone"
label = "Deleted run"
db_path = "{(tmp_path / "nope" / "stats.duckdb").as_posix()}"
"""
    )
    out = D.load_datasets(default_cfg, **DESC)
    assert [d.id for d in out] == ["main", "warlord"]

    main = out[0]
    assert main.is_default and main.label == "Main run"
    assert main.cfg is default_cfg
    assert (main.patch, main.difficulty) == ("5.4.8", "Emperor")  # CLI descriptors win

    warlord = out[1]
    assert not warlord.is_default
    assert warlord.cfg.db_type == "sqlite"  # from the .db suffix
    assert warlord.cfg.db_path == other
    assert warlord.cfg.intermediate_data_dir == cache
    assert warlord.cfg.publish_dir == default_cfg.publish_dir
    assert (warlord.patch, warlord.difficulty, warlord.mapscript) == ("5.3.3", "Warlord", "")


def test_load_datasets_default_cache_dir_sits_beside_the_db(tmp_path, default_cfg, toml):
    other = tmp_path / "run2" / "stats.duckdb"
    other.parent.mkdir()
    other.write_bytes(b"")
    toml(f'[[dataset]]\nid = "a"\ndb_path = "{default_cfg.db_path.as_posix()}"\n'
         f'[[dataset]]\nid = "b"\ndb_path = "{other.as_posix()}"\n')
    b = D.load_datasets(default_cfg, **DESC)[1]
    assert b.cfg.db_type == "duckdb"
    assert b.cfg.intermediate_data_dir == other.parent / "plotly_explorer_cache"
    assert b.label == "b"  # label defaults to the id


def test_load_datasets_inserts_an_unlisted_default_first(default_cfg, toml, tmp_path):
    other = tmp_path / "run2" / "stats.duckdb"
    other.parent.mkdir()
    other.write_bytes(b"")
    toml(f'[[dataset]]\nid = "x"\ndb_path = "{other.as_posix()}"\n')
    out = D.load_datasets(default_cfg, **DESC)
    assert [d.id for d in out] == ["5_4_8_headless", "x"]  # run dir minus the MP_AUTOPLAY_VP_ prefix
    assert out[0].is_default and out[0].label == "VP 5.4.8 Emperor"


def test_load_datasets_without_a_toml_is_just_the_default(default_cfg, toml, tmp_path):
    (tmp_path / "datasets.toml").unlink(missing_ok=True)
    out = D.load_datasets(default_cfg, **DESC)
    assert len(out) == 1 and out[0].is_default


def test_load_datasets_derived_default_id_avoids_a_collision(default_cfg, toml, tmp_path):
    other = tmp_path / "run2" / "stats.duckdb"
    other.parent.mkdir()
    other.write_bytes(b"")
    toml(f'[[dataset]]\nid = "5_4_8_headless"\ndb_path = "{other.as_posix()}"\n')
    out = D.load_datasets(default_cfg, **DESC)
    assert [d.id for d in out] == ["5_4_8_headless_default", "5_4_8_headless"]


@pytest.mark.parametrize(
    "body, message",
    [
        ('[[dataset]]\nid = "bad id!"\ndb_path = "x"\n', "must match"),
        (
            '[[dataset]]\nid = "dup"\ndb_path = "{db}"\n[[dataset]]\nid = "dup"\ndb_path = "{db}"\n',
            "duplicate",
        ),
    ],
)
def test_load_datasets_rejects_bad_and_duplicate_ids(default_cfg, toml, body, message):
    toml(body.replace("{db}", default_cfg.db_path.as_posix()))
    with pytest.raises(SystemExit, match=message):
        D.load_datasets(default_cfg, **DESC)


# ---------------------------------------------------------------------------
# Which reports a dataset can show
# ---------------------------------------------------------------------------


def _dataset(cfg: Config) -> D.Dataset:
    return D.Dataset(id="t", label="t", cfg=cfg, is_default=True, **DESC)


def test_unavailable_reports_names_the_missing_table(default_cfg, monkeypatch):
    monkeypatch.setattr(D, "list_tables", lambda cfg: ALL_TABLES - {INSTANT_YIELDS_TABLE})
    out = _dataset(default_cfg).unavailable_reports()
    assert INSTANT_YIELDS_TABLE in out["instant_yields"]
    assert "predates" in out["instant_yields"]
    # Every other report has its tables but no CSVs were built.
    assert out["civs"] == "This report's summaries were not built for this dataset."
    assert set(out) >= {"civs", "building", "religion", "units", "wonders"}


def test_unavailable_reports_is_empty_once_every_csv_exists(default_cfg, monkeypatch):
    monkeypatch.setattr(D, "list_tables", lambda cfg: ALL_TABLES)
    for _key, (_tables, csvs) in D._report_sources(default_cfg).items():
        for p in csvs:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("")
    assert _dataset(default_cfg).unavailable_reports() == {}


def test_ensure_summaries_skips_steps_whose_tables_are_missing(default_cfg, monkeypatch):
    ran = []

    def step_a(cfg, *, force):
        ran.append(("a", force))

    def step_b(cfg, *, force):
        ran.append(("b", force))

    monkeypatch.setattr(D, "STEPS", [(step_a, {"GameResult"}), (step_b, {"GameResult", "Missing"})])
    monkeypatch.setattr(D, "list_tables", lambda cfg: {"GameResult"})
    _dataset(default_cfg).ensure_summaries(force=True)
    assert ran == [("a", True)]


def test_dataset_is_frozen(default_cfg):
    ds = _dataset(default_cfg)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ds.id = "other"  # type: ignore[misc]

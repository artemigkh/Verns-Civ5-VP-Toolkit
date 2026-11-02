"""Shared fixtures for the Plotly Explorer test suite.

Running the tests (uv is often not on PATH here; it lives at
``%APPDATA%\\Python\\Python311\\Scripts\\uv.exe``)::

    uv run --project analysis/plotly_explorer pytest analysis/plotly_explorer/tests

Everything runs against tiny inputs built in ``tmp_path``; nothing reads the
real ``data/`` directory, and the whole suite takes a few seconds.

Adding a report. The pattern every report follows is: an aggregation step in
``aggregate/`` that writes CSVs under ``Config.intermediate_data_dir`` (test the
pure DataFrame functions directly, and the SQL through ``sqlite_db``), and a
``build_<report>_payload`` in ``render.py`` that reads those CSVs (write the CSVs
with ``write_csv`` against the ``cfg`` fixture and assert on the dict).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from pathlib import Path

import pandas as pd
import pytest

from plotly_explorer.config import Config

# ---------------------------------------------------------------------------
# A Config whose every path lives under tmp_path.
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(
        db_type="sqlite",
        db_path=tmp_path / "stats.db",
        intermediate_data_dir=tmp_path / "cache",
        publish_dir=tmp_path / "public",
    )


@pytest.fixture
def write_csv() -> Callable[[Path, Iterable[dict]], pd.DataFrame]:
    """Write ``rows`` (list of dicts) to ``path`` as CSV, creating parents."""

    def _write(path: Path, rows: Iterable[dict]) -> pd.DataFrame:
        df = pd.DataFrame(list(rows))
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        return df

    return _write


# ---------------------------------------------------------------------------
# Small game-stats intermediates, shaped like the aggregator's CSVs.
# ---------------------------------------------------------------------------

VICTORY_STEMS = [
    ("culture", "Cultural"),
    ("diplomatic", "Diplomatic"),
    ("domination", "Domination"),
    ("science", "Science"),
    ("time", "Time"),
]


def game_result_rows() -> list[dict]:
    """Three decided games (two Cultural, one Science) and one undecided."""
    rows = [
        {"game_id": 1, "turn": 300, "num_civs": 4, "victory_type": "Cultural", "victory_civ": "Rome"},
        {"game_id": 2, "turn": 350, "num_civs": 4, "victory_type": "Science", "victory_civ": "Egypt"},
        {"game_id": 3, "turn": 280, "num_civs": 4, "victory_type": "Cultural", "victory_civ": "Rome"},
        {"game_id": 4, "turn": 500, "num_civs": 4, "victory_type": "", "victory_civ": ""},
    ]
    for r in rows:
        for stem, label in VICTORY_STEMS:
            r[f"{stem}_victory"] = int(r["victory_type"] == label)
    return rows


def power_ranking_rows() -> list[dict]:
    """Per-civ rows for the four civs of :func:`game_result_rows`."""

    def row(civ, games, winrate, culture, science, tiles, cities, score, rank):
        wins = culture + science
        nan = float("nan")
        return {
            "civ": civ,
            "count_games": games,
            "winrate": winrate,
            "culture_victories": culture,
            "diplomatic_victories": 0,
            "domination_victories": 0,
            "science_victories": science,
            "time_victories": 0,
            "pct_culture_victories": culture / wins if wins else nan,
            "pct_diplomatic_victories": 0.0 if wins else nan,
            "pct_domination_victories": 0.0 if wins else nan,
            "pct_science_victories": science / wins if wins else nan,
            "pct_time_victories": 0.0 if wins else nan,
            "avg_tiles_owned_percentage": tiles,
            "avg_cities_owned_percentage": cities,
            "avg_score": score,
            "avg_rank_at_game_end": rank,
        }

    return [
        row("Egypt", 4, 0.25, 0, 1, 0.30, 0.28, 2100.0, 2.0),
        row("Rome", 4, 0.50, 2, 0, 0.40, 0.35, 2500.0, 1.5),
        row("Siam", 4, 0.00, 0, 0, 0.15, 0.20, 1200.0, 3.25),
        row("Zulu", 4, 0.00, 0, 0, 0.15, 0.17, 900.0, 3.25),
    ]


@pytest.fixture
def game_stats_csvs(cfg: Config, write_csv) -> Config:
    """``cfg`` with ``game_result.csv`` and ``power_ranking.csv`` written."""
    write_csv(cfg.game_result_path, game_result_rows())
    write_csv(cfg.power_ranking_path, power_ranking_rows())
    return cfg


# ---------------------------------------------------------------------------
# A SQLite stats DB with the raw tables the game-stats aggregation reads.
# ---------------------------------------------------------------------------

# Game 1: three civs, ends turn 150, Rome wins Cultural; Siam is conquered
#         (score 0, stops logging at turn 120).
# Game 2: ends turn 50 -> a dev test completion, dropped everywhere.
# Game 3: ends turn 200, undecided; everyone alive.
SQLITE_FIXTURE_SQL = """
CREATE TABLE GameResult (GameId INTEGER, Turn INTEGER, Civ TEXT, Score INTEGER, VictoryType TEXT);
INSERT INTO GameResult VALUES
  (1, 150, 'Rome',  500, 'Cultural'),
  (1, 150, 'Egypt', 300, ''),
  (1, 150, 'Siam',    0, ''),
  (2,  50, 'Rome',  100, 'Domination'),
  (2,  50, 'Egypt',  50, ''),
  (3, 200, 'Rome',  100, NULL),
  (3, 200, 'Egypt', 400, NULL),
  (3, 200, 'Siam',  350, NULL);

CREATE TABLE civ_turn_era (GameId INTEGER, civ TEXT, Turn INTEGER, Era INTEGER);
WITH RECURSIVE turns(t) AS (SELECT 1 UNION ALL SELECT t + 1 FROM turns WHERE t < 200)
INSERT INTO civ_turn_era
  SELECT 1, 'Rome',  t, 0 FROM turns WHERE t <= 150 UNION ALL
  SELECT 1, 'Egypt', t, 0 FROM turns WHERE t <= 150 UNION ALL
  SELECT 1, 'Siam',  t, 0 FROM turns WHERE t <= 120 UNION ALL
  SELECT 3, 'Rome',  t, 0 FROM turns UNION ALL
  SELECT 3, 'Egypt', t, 0 FROM turns UNION ALL
  SELECT 3, 'Siam',  t, 0 FROM turns;

-- Only each game's end turn matters to the ownership query; an earlier turn is
-- included to prove it is ignored.
CREATE TABLE MapPlotsState (GameId INTEGER, Turn INTEGER, owner TEXT, cityName TEXT);
INSERT INTO MapPlotsState VALUES
  (1, 100, 'Siam', 'Sukhothai'), (1, 100, 'Siam', ''),
  (1, 150, 'Rome', 'Rome'), (1, 150, 'Rome', 'Antium'), (1, 150, 'Rome', ''), (1, 150, 'Rome', ''),
  (1, 150, 'Rome', ''), (1, 150, 'Rome', ''),
  (1, 150, 'Egypt', 'Thebes'), (1, 150, 'Egypt', ''), (1, 150, 'Egypt', ''), (1, 150, 'Egypt', ''),
  (1, 150, '', ''), (1, 150, '', ''),
  (3, 200, 'Rome', 'Rome'), (3, 200, 'Rome', ''),
  (3, 200, 'Egypt', 'Thebes'), (3, 200, 'Egypt', 'Memphis'), (3, 200, 'Egypt', ''), (3, 200, 'Egypt', ''),
  (3, 200, 'Egypt', ''),
  (3, 200, 'Siam', 'Sukhothai'), (3, 200, 'Siam', ''), (3, 200, 'Siam', '');

CREATE TABLE ReligionChoices (
  GameId INTEGER, Turn INTEGER, Civ TEXT, Action TEXT, Belief TEXT, BeliefType TEXT);
INSERT INTO ReligionChoices VALUES
  (1, 20, 'Rome',  'PANTHEON_FOUNDED',  'Goddess of Beauty', 'pantheon'),
  (1, 60, 'Rome',  'RELIGION_FOUNDED',  'Council of Elders', 'FOUNDER'),
  (1, 60, 'Rome',  'RELIGION_FOUNDED',  'Scripture',         'FOLLOWER'),
  (1, 25, 'Egypt', 'PANTHEON_FOUNDED',  'God of the Sun',    'PANTHEON'),
  (1, 90, 'Egypt', 'RELIGION_CONQUERED', '',                 ''),
  (2, 20, 'Rome',  'PANTHEON_FOUNDED',  'Goddess of Beauty', 'PANTHEON'),
  (3, 30, 'Siam',  'PANTHEON_FOUNDED',  'God of the Sun',    'PANTHEON');

CREATE TABLE PolicyChoices (GameId INTEGER, Turn INTEGER, Civ TEXT, Era INTEGER, Branch TEXT, Policy TEXT);
INSERT INTO PolicyChoices VALUES
  (1, 10, 'Rome',  0, 'Tradition', ''),
  (1, 10, 'Rome',  0, 'Tradition', 'Justice'),
  (1, 30, 'Rome',  0, 'Tradition', 'Sovereignty'),
  (1, 12, 'Egypt', 0, 'Progress',  ''),
  (3, 15, 'Siam',  0, 'Authority', '');
"""


@pytest.fixture
def sqlite_db(cfg: Config) -> Config:
    """``cfg`` pointing at a populated SQLite stats DB (see ``SQLITE_FIXTURE_SQL``)."""
    with sqlite3.connect(cfg.db_path) as cnx:
        cnx.executescript(SQLITE_FIXTURE_SQL)
    return cfg

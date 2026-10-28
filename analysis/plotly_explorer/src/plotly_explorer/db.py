"""Database access abstraction.

Hides whether the source is SQLite or DuckDB so the rest of the code is
DB-agnostic, and — more importantly — keeps the aggregations inside bounded
memory.

**The raw tables do not fit in RAM.** ``BuildingYields`` alone is ~250M rows in
the Warlord 5.3.3 dataset; materializing it as a DataFrame needs tens of GiB and
dies with ``numpy._core._exceptions._ArrayMemoryError``. Every aggregation in
this package therefore pushes its ``GROUP BY`` down to the DB via
:func:`read_query` and only pulls the (few-thousand-row) result back, which is
what makes peak memory independent of dataset size.

Two guard rails keep it that way:

* DuckDB connections are opened with an explicit ``memory_limit`` and a
  ``temp_directory``. Its hash aggregates, joins and sorts spill to that
  directory once the limit is hit, so a 250M-row ``GROUP BY`` runs in a bounded
  working set instead of being capped by physical RAM. Both are configurable
  (``DB_MEMORY_LIMIT``, default :data:`DEFAULT_MEMORY_LIMIT`).
* :func:`read_table` — the whole-table read — refuses tables above
  :data:`MAX_WHOLE_TABLE_ROWS` rows, so a new aggregation that reaches for a
  huge table fails immediately with an actionable message rather than after
  minutes of swapping.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pandas as pd

from .config import Config

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection

# Ceiling on DuckDB's working set. Anything above it spills to the temp
# directory rather than being allocated, so this doubles as the peak-memory
# guarantee for the aggregation phase. Deliberately well under a typical 16 GB
# machine: the aggregates stream, so a bigger limit buys nothing.
DEFAULT_MEMORY_LIMIT = "4GB"

# Where DuckDB spills. Kept beside the intermediate CSVs (a known-writable
# directory the pipeline already owns) instead of DuckDB's default
# ``<db file>.tmp``, which sits next to a possibly read-only source DB.
TEMP_DIR_NAME = "duckdb_spill"

# Whole-table reads above this many rows are rejected by :func:`read_table`.
# Every table the pipeline reads whole is orders of magnitude smaller (the
# largest, ``civ_turn_era``, is <1M rows); anything bigger belongs in a
# pushed-down query. Override with ``DB_MAX_TABLE_ROWS``.
MAX_WHOLE_TABLE_ROWS = 5_000_000

# Values the reports show under another name, swapped in on every result
# :func:`read_table` and :func:`read_query` return. Doing it here, the one
# exit from the DB, means every summary CSV -- and every pandas join between
# them -- agrees on the new name, while the SQL inside a query still joins on
# the raw one. Exact cell matches in text columns only.
#
# The CSV cache does not know about this map: after changing it, rebuild with
# --force (a DB that keeps growing rebuilds on its own).
VALUE_RENAMES = {
    "Niten Ichi Ryu": "Baseline",
}


def _rename_values(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            df[col] = df[col].replace(VALUE_RENAMES)
    return df


def _max_whole_table_rows() -> int:
    return int(os.environ.get("DB_MAX_TABLE_ROWS", MAX_WHOLE_TABLE_ROWS))


def _require_db(cfg: Config) -> None:
    if not cfg.db_path.exists():
        raise SystemExit(f"Source database not found: {cfg.db_path}")


@contextmanager
def _duckdb(cfg: Config) -> Iterator[DuckDBPyConnection]:
    """Read-only DuckDB connection with a hard memory limit and disk spilling."""
    import duckdb

    temp_dir = cfg.intermediate_data_dir / TEMP_DIR_NAME
    temp_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(cfg.db_path), read_only=True)
    try:
        con.execute(f"SET memory_limit='{cfg.db_memory_limit}'")
        con.execute(f"SET temp_directory='{temp_dir.as_posix()}'")
        yield con
    finally:
        con.close()


def _row_count(cfg: Config, table: str) -> int:
    sql = f'SELECT COUNT(*) FROM "{table}"'
    if cfg.db_type == "sqlite":
        with sqlite3.connect(cfg.db_path) as cnx:
            return int(cnx.execute(sql).fetchone()[0])
    with _duckdb(cfg) as con:
        return int(con.execute(sql).fetchone()[0])


def list_tables(cfg: Config) -> set[str]:
    """Names of the tables in the source DB.

    Older datasets predate some of the logging tables, so the pipeline checks
    this before running an aggregation rather than letting its query fail.
    """
    _require_db(cfg)

    if cfg.db_type == "sqlite":
        with sqlite3.connect(cfg.db_path) as cnx:
            rows = cnx.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    else:
        with _duckdb(cfg) as con:
            rows = con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    return {r[0] for r in rows}


def read_table(cfg: Config, table: str) -> pd.DataFrame:
    """Return the full contents of ``table`` as a DataFrame.

    Only for tables small enough to hold in memory; raises above
    :data:`MAX_WHOLE_TABLE_ROWS` rows. Use :func:`read_query` with the
    aggregation pushed into SQL for anything larger.
    """
    _require_db(cfg)

    if cfg.db_type not in {"sqlite", "duckdb"}:
        raise SystemExit(f"Unsupported DB_TYPE: {cfg.db_type}")

    limit = _max_whole_table_rows()
    rows = _row_count(cfg, table)
    if rows > limit:
        raise SystemExit(
            f'Refusing to read all {rows:,} rows of "{table}" into memory '
            f"(limit {limit:,}). Push the aggregation into SQL with "
            f"read_query() so only the summary comes back, or raise "
            f"DB_MAX_TABLE_ROWS if the table really does fit."
        )

    if cfg.db_type == "sqlite":
        with sqlite3.connect(cfg.db_path) as cnx:
            return _rename_values(pd.read_sql_query(f'SELECT * FROM "{table}"', cnx))

    with _duckdb(cfg) as con:
        return _rename_values(con.execute(f'SELECT * FROM "{table}"').df())


def read_query(cfg: Config, sql: str) -> pd.DataFrame:
    """Run a read-only ``sql`` query and return the result.

    The workhorse of every aggregation: the heavy scans/joins/group-bys run in
    the DB (bounded by ``memory_limit``, spilling to disk as needed) and only
    the small result is materialized as a DataFrame. ``sql`` is kept portable
    across SQLite and DuckDB.
    """
    _require_db(cfg)

    if cfg.db_type == "sqlite":
        with sqlite3.connect(cfg.db_path) as cnx:
            return _rename_values(pd.read_sql_query(sql, cnx))

    if cfg.db_type == "duckdb":
        with _duckdb(cfg) as con:
            return _rename_values(con.execute(sql).df())

    raise SystemExit(f"Unsupported DB_TYPE: {cfg.db_type}")

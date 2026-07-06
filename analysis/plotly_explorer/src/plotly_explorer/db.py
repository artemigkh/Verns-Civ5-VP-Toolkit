"""Database access abstraction.

The aggregation pipeline only needs whole tables as DataFrames; this module
hides whether the source is SQLite or DuckDB so the rest of the code is
DB-agnostic.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from .config import Config


def read_table(cfg: Config, table: str) -> pd.DataFrame:
    """Return the full contents of ``table`` as a DataFrame."""
    if not cfg.db_path.exists():
        raise SystemExit(f"Source database not found: {cfg.db_path}")

    if cfg.db_type == "sqlite":
        with sqlite3.connect(cfg.db_path) as cnx:
            return pd.read_sql_query(f'SELECT * FROM "{table}"', cnx)

    if cfg.db_type == "duckdb":
        import duckdb

        con = duckdb.connect(str(cfg.db_path), read_only=True)
        try:
            return con.execute(f'SELECT * FROM "{table}"').df()
        finally:
            con.close()

    raise SystemExit(f"Unsupported DB_TYPE: {cfg.db_type}")


def read_query(cfg: Config, sql: str) -> pd.DataFrame:
    """Run an arbitrary read-only ``sql`` query and return the result.

    Used when a whole-table read would be wasteful (e.g. ``MapPlotsState`` has
    tens of millions of rows but we only need a filtered aggregate).
    """
    if not cfg.db_path.exists():
        raise SystemExit(f"Source database not found: {cfg.db_path}")

    if cfg.db_type == "sqlite":
        with sqlite3.connect(cfg.db_path) as cnx:
            return pd.read_sql_query(sql, cnx)

    if cfg.db_type == "duckdb":
        import duckdb

        con = duckdb.connect(str(cfg.db_path), read_only=True)
        try:
            return con.execute(sql).df()
        finally:
            con.close()

    raise SystemExit(f"Unsupported DB_TYPE: {cfg.db_type}")

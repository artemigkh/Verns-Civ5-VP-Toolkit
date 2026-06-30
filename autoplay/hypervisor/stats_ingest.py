"""DuckDB long-term stats store and SQLite-stats ingestion.

In SQLite-stats mode the Civ5 process writes game statistics into a local
SQLite database (``stats.db``). Runners upload that file to the hypervisor,
which ingests it into a per-modpack DuckDB store at
``<storage_root>/<modpack>/stats.duckdb`` using DuckDB's native ``sqlite``
extension (``ATTACH ... (TYPE SQLITE)`` + ``INSERT ... SELECT``).

Identity translation
--------------------
Each uploaded SQLite database normalises its game UUIDs into a local
``uuid_dictionary(id, uuid_hex)`` table; every stats table references that
local id via a ``GameId`` column. During ingestion the UUID hex strings are
upserted into the DuckDB ``uuid_dictionary`` (which mints fresh global ids via
a sequence) and each stats table's ``GameId`` is rewritten from the local id to
the global id by joining through both dictionaries.

Atomicity
---------
A file is validated in full before any rows are written: if *any* table's
schema (column names *and* types) disagrees with the existing DuckDB table, the
whole file is rejected and quarantined to ``<modpack>/incomplete_processing/``
without ingesting anything. This avoids partial / double ingestion when a file
is later re-examined.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import duckdb

from autoplay.common.constants import (
    STATS_DUCKDB_FILENAME,
    STATS_GAME_FK_COLUMN,
    STATS_IGNORED_TABLES,
    UUID_DICTIONARY_TABLE,
)

logger = logging.getLogger(__name__)

_UUID_SEQ = "uuid_dictionary_id_seq"


@dataclass
class IngestResult:
    """Outcome of ingesting one uploaded SQLite stats database."""

    ok: bool
    game_id: str
    archived_path: Path | None = None
    bundle_name: str | None = None
    file_size_bytes: int = 0
    quarantine_path: Path | None = None
    error: str | None = None
    tables_ingested: tuple[str, ...] = ()
    rows_ingested: int = 0


# --- type mapping -----------------------------------------------------------


def duckdb_type(sqlite_decl_type: str) -> str:
    """Map a SQLite declared column type to a canonical DuckDB type name.

    Uses SQLite's type-affinity rules so the mapping is robust to the exact
    declared spelling (e.g. ``INTEGER``/``INT`` -> ``BIGINT``).
    """
    t = (sqlite_decl_type or "").upper()
    if "INT" in t:
        return "BIGINT"
    if "CHAR" in t or "CLOB" in t or "TEXT" in t:
        return "VARCHAR"
    if "BLOB" in t or t == "":
        return "BLOB"
    if "REAL" in t or "FLOA" in t or "DOUB" in t:
        return "DOUBLE"
    if "NUM" in t or "DEC" in t or "BOOL" in t or "DATE" in t or "TIME" in t:
        return "DOUBLE"
    return "VARCHAR"


# --- SQLite schema introspection -------------------------------------------


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def read_sqlite_schema(sqlite_path: Path) -> dict[str, list[tuple[str, str]]]:
    """Return ``{table: [(col_name, duckdb_type), ...]}`` for each stats table.

    Excludes bookkeeping tables (``sqlite_sequence``, ``uuid_dictionary``).
    Column order matches the table's declared order.
    """
    schema: dict[str, list[tuple[str, str]]] = {}
    uri = sqlite_path.resolve().as_uri()
    conn = sqlite3.connect(f"{uri}?mode=ro", uri=True, timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        names = [r[0] for r in cur.fetchall()]
        for name in names:
            if name in STATS_IGNORED_TABLES:
                continue
            cur.execute(f"PRAGMA table_info({_quote(name)})")
            cols = [(c[1], duckdb_type(c[2])) for c in cur.fetchall()]
            schema[name] = cols
    finally:
        conn.close()
    return schema


# --- DuckDB store -----------------------------------------------------------


def duckdb_path(storage_root: Path, modpack: str) -> Path:
    return storage_root / modpack / STATS_DUCKDB_FILENAME


def _connect_duckdb(ddb_path: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(ddb_path))
    # The sqlite extension is autoloadable in modern DuckDB; attempt an explicit
    # install/load but tolerate failure so an offline host still works via
    # autoloading.
    for stmt in ("INSTALL sqlite", "LOAD sqlite"):
        try:
            con.execute(stmt)
        except Exception as exc:  # noqa: BLE001
            logger.debug("DuckDB %s failed (continuing): %s", stmt, exc)
    return con


def _ensure_uuid_dictionary(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"CREATE SEQUENCE IF NOT EXISTS {_UUID_SEQ} START 1")
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {UUID_DICTIONARY_TABLE} (
            id       BIGINT PRIMARY KEY DEFAULT nextval('{_UUID_SEQ}'),
            uuid_hex VARCHAR UNIQUE NOT NULL
        )
        """
    )


def ensure_duckdb(storage_root: Path, modpack: str) -> Path:
    """Eagerly create (if absent) the per-modpack DuckDB store + uuid_dictionary."""
    ddb_path = duckdb_path(storage_root, modpack)
    ddb_path.parent.mkdir(parents=True, exist_ok=True)
    con = _connect_duckdb(ddb_path)
    try:
        _ensure_uuid_dictionary(con)
    finally:
        con.close()
    return ddb_path


def _existing_table_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[tuple[str, str]] | None:
    """Return ``[(col_name, data_type), ...]`` for ``table`` or None if absent."""
    rows = con.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = ?
        ORDER BY ordinal_position
        """,
        [table],
    ).fetchall()
    if not rows:
        return None
    return [(r[0], str(r[1]).upper()) for r in rows]


def _create_table(con: duckdb.DuckDBPyConnection, table: str, columns: list[tuple[str, str]]) -> None:
    col_defs = ", ".join(f"{_quote(name)} {dtype}" for name, dtype in columns)
    con.execute(f"CREATE TABLE {_quote(table)} ({col_defs})")


def _schema_matches(incoming: list[tuple[str, str]], existing: list[tuple[str, str]]) -> bool:
    """Compare column names AND types (order-sensitive)."""
    if len(incoming) != len(existing):
        return False
    for (in_name, in_type), (ex_name, ex_type) in zip(incoming, existing, strict=True):
        if in_name != ex_name or in_type.upper() != ex_type.upper():
            return False
    return True


# --- ingestion --------------------------------------------------------------


def _unique_archive_path(complete_dir: Path, game_id: str) -> Path:
    candidate = complete_dir / f"{game_id}.db"
    suffix = 1
    while candidate.exists():
        candidate = complete_dir / f"{game_id}-{suffix}.db"
        suffix += 1
    return candidate


def _quarantine(modpack_dir: Path, sqlite_path: Path, game_id: str) -> Path:
    quarantine_dir = modpack_dir / "incomplete_processing"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    dest = quarantine_dir / f"{game_id}.db"
    suffix = 1
    while dest.exists():
        dest = quarantine_dir / f"{game_id}-{suffix}.db"
        suffix += 1
    sqlite_path.replace(dest)
    return dest


def ingest_stats_db(
    storage_root: Path,
    modpack: str,
    game_id: str,
    sqlite_path: Path,
) -> IngestResult:
    """Validate and ingest one uploaded SQLite stats database into DuckDB.

    On success the raw ``.db`` is moved to ``<modpack>/complete/<gameId>.db``.
    On any table schema mismatch the file is quarantined to
    ``<modpack>/incomplete_processing/`` and nothing is ingested.
    """
    modpack_dir = storage_root / modpack
    try:
        size = sqlite_path.stat().st_size
    except OSError:
        size = 0

    try:
        schema = read_sqlite_schema(sqlite_path)
    except sqlite3.Error as exc:
        logger.error("Cannot read SQLite schema from %s: %s", sqlite_path.name, exc)
        qpath = _quarantine(modpack_dir, sqlite_path, game_id)
        return IngestResult(ok=False, game_id=game_id, quarantine_path=qpath, error=f"unreadable: {exc}")

    ddb_path = ensure_duckdb(storage_root, modpack)
    con = _connect_duckdb(ddb_path)
    src_alias = "src_sqlite"
    try:
        # 1. Validate every table's schema BEFORE writing anything (atomic).
        to_create: list[str] = []
        for table, cols in schema.items():
            existing = _existing_table_columns(con, table)
            if existing is None:
                to_create.append(table)
                continue
            if not _schema_matches(cols, existing):
                logger.error(
                    "Schema mismatch for table %r in %s: incoming=%s existing=%s",
                    table,
                    sqlite_path.name,
                    cols,
                    existing,
                )
                con.close()
                qpath = _quarantine(modpack_dir, sqlite_path, game_id)
                return IngestResult(
                    ok=False,
                    game_id=game_id,
                    quarantine_path=qpath,
                    error=f"schema mismatch on table {table!r}",
                )

        # 2. Create any new tables mirroring the SQLite schema.
        for table in to_create:
            _create_table(con, table, schema[table])

        # 3. Attach the SQLite file and transfer rows inside a transaction.
        con.execute(f"ATTACH '{str(sqlite_path)}' AS {src_alias} (TYPE SQLITE, READ_ONLY)")
        rows_ingested = 0
        try:
            con.execute("BEGIN TRANSACTION")
            # Upsert UUIDs -> global ids via the sequence default.
            con.execute(
                f"""
                INSERT INTO {UUID_DICTIONARY_TABLE} (uuid_hex)
                SELECT DISTINCT uuid_hex
                FROM {src_alias}.{UUID_DICTIONARY_TABLE}
                WHERE uuid_hex NOT IN (SELECT uuid_hex FROM {UUID_DICTIONARY_TABLE})
                """
            )
            for table, cols in schema.items():
                select_cols = []
                for name, _dtype in cols:
                    if name == STATS_GAME_FK_COLUMN:
                        select_cols.append(f"g.id AS {_quote(name)}")
                    else:
                        select_cols.append(f"s.{_quote(name)}")
                sql = (
                    f"INSERT INTO {_quote(table)} "
                    f"SELECT {', '.join(select_cols)} "
                    f"FROM {src_alias}.{_quote(table)} s "
                    f"JOIN {src_alias}.{UUID_DICTIONARY_TABLE} su "
                    f"  ON s.{_quote(STATS_GAME_FK_COLUMN)} = su.id "
                    f"JOIN {UUID_DICTIONARY_TABLE} g ON g.uuid_hex = su.uuid_hex"
                )
                cur = con.execute(sql)
                affected = cur.fetchone()
                if affected and affected[0] is not None:
                    rows_ingested += int(affected[0])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.execute(f"DETACH {src_alias}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ingest failed for %s: %s", sqlite_path.name, exc)
        with contextlib.suppress(Exception):
            con.close()
        qpath = _quarantine(modpack_dir, sqlite_path, game_id)
        return IngestResult(ok=False, game_id=game_id, quarantine_path=qpath, error=str(exc))
    finally:
        with contextlib.suppress(Exception):
            con.close()

    # 4. Archive the raw SQLite db into complete/.
    complete_dir = modpack_dir / "complete"
    complete_dir.mkdir(parents=True, exist_ok=True)
    archived = _unique_archive_path(complete_dir, game_id)
    sqlite_path.replace(archived)
    logger.info(
        "Ingested %s: modpack=%s game=%s tables=%d rows=%d -> %s",
        archived.name,
        modpack,
        game_id,
        len(schema),
        rows_ingested,
        archived,
    )
    return IngestResult(
        ok=True,
        game_id=game_id,
        archived_path=archived,
        bundle_name=archived.name,
        file_size_bytes=size,
        tables_ingested=tuple(schema.keys()),
        rows_ingested=rows_ingested,
    )

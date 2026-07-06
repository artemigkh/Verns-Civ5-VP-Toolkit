---
name: duckdb-inspect
description: >-
  Examine and query DuckDB database files safely in read-only mode using the
  `duckdb` CLI. Use this whenever the user wants to inspect, explore, browse,
  query, profile, or understand the contents or schema of a DuckDB database —
  any `.duckdb`, `.ddb`, or `.db` file created by DuckDB — including questions
  like "what tables are in this duckdb file", "show me the schema", "describe
  table X", "how many rows", or "run this analytical query against the db".
  Always prefer this over ad-hoc commands so the database is opened read-only
  and can never be modified.
compatibility: Requires the `duckdb` command on PATH.
---

# Inspecting DuckDB databases (read-only)

The goal of this skill is to look inside a DuckDB database **without any risk of
modifying it**. The `duckdb` CLI can write, so we always attach the database
with the `-readonly` flag. In read-only mode any statement that would modify the
database (INSERT/UPDATE/DELETE/CREATE/DROP, etc.) fails with
`Cannot execute statement ... attached in read-only mode` — that failure is the
safety guarantee we want.

## The one rule

Always invoke `duckdb` with `-readonly` as the **first argument**, immediately
after the command, in this exact shape:

```
duckdb -readonly <database-file> "<SQL>"
```

Keeping `-readonly` first and consistent is what lets these calls run without a
permission prompt. Do not use a bare `duckdb <db> ...` invocation for
inspection, even if you "only" intend to read.

Note: `-readonly` requires a real database file — DuckDB refuses to launch an
**in-memory** database in read-only mode. So this skill is for examining
existing `.duckdb` files. (Querying a standalone Parquet/CSV/JSON file directly
via an in-memory session is a different, un-sandboxed operation and is out of
scope here.)

## Common tasks

**List all tables/views across schemas** (cleaner than the noisy `.tables`):
```
duckdb -readonly mydata.duckdb "SHOW ALL TABLES;"
```

**Describe a table's columns and types:**
```
duckdb -readonly mydata.duckdb "DESCRIBE my_table;"
```

**Show the full DDL / schema:**
```
duckdb -readonly mydata.duckdb "SELECT sql FROM duckdb_tables();"
duckdb -readonly mydata.duckdb "FROM duckdb_columns() SELECT table_name, column_name, data_type;"
```

**Run a query.** DuckDB's default box output is already human-friendly; add
`LIMIT` on big tables:
```
duckdb -readonly mydata.duckdb "SELECT * FROM sales LIMIT 20;"
duckdb -readonly mydata.duckdb "SELECT region, SUM(amount) FROM sales GROUP BY region ORDER BY 2 DESC;"
```

**Machine-readable output** — pass the output-mode flag after `-readonly`
(`-json`, `-csv`, `-markdown`, `-line`, …):
```
duckdb -readonly -json mydata.duckdb "SELECT id, name FROM users LIMIT 20;"
duckdb -readonly -csv  mydata.duckdb "SELECT * FROM sales;"
```

**Quick reconnaissance of an unfamiliar database:**
```
duckdb -readonly mydata.duckdb "SHOW ALL TABLES;"
duckdb -readonly mydata.duckdb "SUMMARIZE my_table;"
```
`SUMMARIZE` is a DuckDB convenience that returns per-column stats (min, max,
approx unique, null %, etc.) — great for profiling.

## Tips

- On large tables, add `LIMIT` before dumping rows so you don't flood the output.
- If a path contains spaces, quote it: `duckdb -readonly "C:/My Data/app.duckdb" ...`.
- The trailing SQL argument and the `-c "<SQL>"` form are equivalent; either is
  fine, but keep `-readonly` first so the invocation stays consistent.
- If you genuinely need to modify a database, that is out of scope for this
  skill: tell the user, and only proceed with an explicit non-read-only command
  after they confirm.

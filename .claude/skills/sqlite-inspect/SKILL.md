---
name: sqlite-inspect
description: >-
  Examine and query SQLite database files safely in read-only mode using the
  `sqlite3` CLI. Use this whenever the user wants to inspect, explore, browse,
  query, dump, or understand the contents or schema of a SQLite database — any
  `.db`, `.sqlite`, `.sqlite3`, or similar file — including questions like
  "what tables are in this database", "show me the schema", "count the rows in
  X", or "run this SELECT against the db". Always prefer this over ad-hoc
  commands so the database is opened read-only and can never be modified.
compatibility: Requires the `sqlite3` command on PATH.
---

# Inspecting SQLite databases (read-only)

The goal of this skill is to let you look inside a SQLite database **without any
risk of modifying it**. The `sqlite3` CLI can write to a database, so we always
open it with the `-readonly` flag. When a database is opened read-only, any
statement that would modify it (INSERT/UPDATE/DELETE/DROP/CREATE, `VACUUM`,
`PRAGMA` writes, etc.) fails with `attempt to write a readonly database` — this
is exactly the safety guarantee we want.

## The one rule

Always invoke `sqlite3` with `-readonly` as the **first argument**, immediately
after the command, in this exact shape:

```
sqlite3 -readonly <database-file> [output-flags] "<SQL or dot-command>"
```

Keeping `-readonly` first and consistent is what lets these calls run without a
permission prompt. Do not use a bare `sqlite3 <db> ...` invocation for
inspection, even if you "only" intend to read — the read-only flag is the
guarantee, not your intent.

## Common tasks

**List the tables (and views):**
```
sqlite3 -readonly mydata.db ".tables"
```

**Show the schema** (whole DB, or one object):
```
sqlite3 -readonly mydata.db ".schema"
sqlite3 -readonly mydata.db ".schema users"
```

**Run a query with readable output** — `-header -column` gives aligned columns;
`-box` and `-markdown` are also nice for humans:
```
sqlite3 -readonly mydata.db -header -column "SELECT * FROM users LIMIT 20;"
sqlite3 -readonly mydata.db -box "SELECT status, COUNT(*) FROM orders GROUP BY status;"
```

**Machine-readable output** — for parsing, prefer JSON or CSV:
```
sqlite3 -readonly mydata.db -json "SELECT id, name FROM users LIMIT 20;"
sqlite3 -readonly mydata.db -csv -header "SELECT * FROM orders;"
```

**Quick reconnaissance of an unfamiliar database:**
```
sqlite3 -readonly mydata.db ".tables"
sqlite3 -readonly mydata.db ".schema"
sqlite3 -readonly mydata.db "SELECT name, type FROM sqlite_master WHERE type IN ('table','view','index');"
```

**Row counts / spot checks:**
```
sqlite3 -readonly mydata.db "SELECT COUNT(*) FROM events;"
sqlite3 -readonly mydata.db -header -column "SELECT * FROM events ORDER BY ts DESC LIMIT 5;"
```

## Tips

- On large tables, always add `LIMIT` before dumping rows so you don't flood the
  output.
- If a path contains spaces, quote it: `sqlite3 -readonly "C:/My Data/app.db" ...`.
- Multiple dot-commands or statements can be separated by `;` inside one quoted
  string, or you can make several small calls — small calls are easier to read.
- If you genuinely need to modify a database, that is out of scope for this
  skill: tell the user, and only proceed with an explicit non-read-only command
  after they confirm.

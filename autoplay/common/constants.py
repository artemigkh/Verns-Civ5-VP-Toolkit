"""Constants shared by the hypervisor and runner."""

from __future__ import annotations

import re

MODPACK_FOLDER_PREFIX = "MP_AUTOPLAY_VP_"
"""Folder name prefix used for autoplay modpack folders in the DLC directory."""

MODPACK_FOLDER_REGEX = re.compile(rf"^{re.escape(MODPACK_FOLDER_PREFIX)}(?P<version>.+)$")
"""Regex that matches a modpack folder name and captures its version string."""

# --- SQLite-stats mode ------------------------------------------------------

STATS_DB_FILENAME = "stats.db"
"""Name of the SQLite database the Civ5 process writes game stats into."""

STATS_DUCKDB_FILENAME = "stats.duckdb"
"""Name of the per-modpack DuckDB long-term store at ``data/<modpack>/``."""

UUID_DICTIONARY_TABLE = "uuid_dictionary"
"""Table that maps an auto-incremented integer id to a game's uuid hex string."""

STATS_GAME_FK_COLUMN = "GameId"
"""Column present on every stats table that references ``uuid_dictionary.id``."""

GAME_RESULT_TABLE = "GameResult"
"""Stats table whose presence of rows for the latest game id signals completion."""

WORLD_STATE_LOG_TABLE = "WorldStateLog"
"""Stats table with one row per turn; used by the runner to track turn progress."""

MILITARY_SUMMARY_TABLE = "MilitarySummary"
"""Stats table used as a fallback turn-progress source when WorldStateLog is empty."""

# Tables that are part of the bookkeeping schema rather than game stats and must
# not be mirrored/ingested as stats tables.
STATS_IGNORED_TABLES = frozenset({"sqlite_sequence", UUID_DICTIONARY_TABLE})

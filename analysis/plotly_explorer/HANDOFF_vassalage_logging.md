# Handoff: log vassalage to `stats.db`

**For:** an agent session working in the Vox Populi DLL repo,
`C:\Users\Art\Documents\GitHub\Community-Patch-DLL`.
**Written from:** the `verns_civ5_vp_toolkit` session that built the Plotly Explorer's
synthetic "Authority Victory" aggregation (`analysis/plotly_explorer/src/plotly_explorer/aggregate/authority.py`).

## Why

The Plotly Explorer is getting a synthetic **Authority Victory**: the first turn a civ
controls more than 2/3 of the map's cities *and* of its owned tiles, it wins on that turn.
That rule is ported from the old Spark pipeline (`logs_processing/src/main/scala/civ5/GameResult.scala`,
`AggregateAuthorityVictories`, and `MapState.scala`, `AggregateMapStateRecords`), which counts a
**vassal's tiles and cities as its master's** (`effective_owner`).

The Spark pipeline got vassalage from the CSV log `DiplomacyAI_TradeAgreements_Log_.csv`
(`***** Vassalage Trade *****` lines). The SQLite stats pipeline that replaced the CSV logs
records no vassalage at all, so the explorer cannot apply the rule faithfully. Without
it the rule fires in only 2 of ~240 Emperor games and 25 of 339 Warlord games.

**Your job:** make the DLL log vassalage into `stats.db` so that, for any game and turn, a
consumer can tell which civs were vassals and who their masters were.

## Decide with the user before writing code

1. **Base branch.** The checkout is on `memory-diagnostics`. That branch's `SqliteLogger` stamps
   every row with a `RunId` column. The DuckDB the current datasets live in
   (`data/MP_AUTOPLAY_VP_5_4_8_headless/stats.duckdb` in the toolkit repo) has **no** `RunId`
   column on any table. The hypervisor rejects a whole `stats.db` if any existing table's
   columns differ (see "Ingest" below). So a DLL built from `memory-diagnostics` can only feed
   a **new** dataset directory, not the existing 5.4.8 headless one. The release-based
   checkouts `Community-Patch-DLL-5.4.7-pragmas` / `-5.4.8-pragmas` (branches
   `sqlite-pragmas-5.4.x`) have no `RunId`. Each also has an uncommitted 6-line change to
   `SqliteLogger.cpp`. Ask which branch builds the DLL for the next dataset and branch
   from it. Don't touch the uncommitted changes.
2. Whether the event table (Deliverable 2) is wanted now or later. The snapshot (Deliverable 1)
   is the one the explorer needs.

## Background you need

### How a table gets into `stats.db`

Read the header comment of `CvGameCoreDLL_Expansion2/SqliteLogger.h`. It is the API doc.
In short:

- Every table has a registration helper in `CvGameCoreDLL_Expansion2/SqliteLoggerRegistrations.h`
  using the run-once pattern (`RegisterTechChoicesTable()` is the smallest example). You declare
  only your own columns.
- The logger adds `GameId` and `Turn` (`GC.getGame().getElapsedGameTurns()`), plus `RunId` on
  branches that have it. Don't declare or bind those.
- Single rows: `GET_SQLITE_LOGGER().BeginLogRow("Table").bind(...)...execute();`
  Many rows: `SqliteLogger::BatchWriter kBatch = GET_SQLITE_LOGGER().BeginLogBatch("Table");`
  then `kBatch.BeginLogRow().bind(...).addRowToBatch();` and `kBatch.flush();`.
  `CvGame::LogMapPlotsState()` (`CvGame.cpp`) is the model for the batch form.
- Everything is gated on `MOD_SQLITE_LOGGING`. The code is C++03 (no `auto`, lambdas, `nullptr`).

### Naming civs

Every civ-valued column in `stats.db` uses `GET_PLAYER(e).getCivilizationShortDescription()`.
`MapPlotsState.owner`, `GameResult.Civ` and `PolicyChoices.Civ` all do. Use the same, so the new
table joins directly to `MapPlotsState.owner` and `GameResult.Civ`.

### Where vassalage lives in the DLL

Vassalage is **team**-level (`CvTeam`). In autoplay every team has exactly one player, but
don't assume that in code.

- `CvTeam::setVassal(TeamTypes eIndex, bool bNewValue, bool bVoluntary)` (`CvTeam.cpp`) is the only
  writer of `m_eMaster`. It has two callers:
  - `CvTeam::DoBecomeVassal(eTeam, bVoluntary, eOriginatingMaster)` calls `setVassal(eTeam, true, bVoluntary)`
    after its `canBecomeVassal` guard. Callers: trade deals (`CvDealClasses.cpp`, `TRADE_ITEM_VASSALAGE`,
    `bVoluntary = !bIsPeaceDeal`, so a capitulation in a peace deal is involuntary) and liberation
    (`CvPlayer.cpp`, the liberated civ voluntarily becomes the liberator's vassal).
  - `CvTeam::DoEndVassal(eTeam, bPeaceful, bSuppressNotification)` calls `setVassal(eTeam, false)`.
    Callers include independence through diplomacy (`CvDiplomacyAI.cpp`), the master liberating
    (`DoLiberateVassal` → net message → `DoEndVassal`), the master declaring war on its vassal
    (`CvTeam.cpp`), a new vassal's own vassals being freed (`CvTeam::DoBecomeVassal`),
    `TRADE_ITEM_VASSALAGE_REVOKE`, World Congress (`CvVotingClasses.cpp`) and `CvPlayer.cpp`.
- Readers: `GetMaster()`, `IsVassal(eTeam)`, `IsVoluntaryVassal(eTeam)`, `GetNumTurnsIsVassal()`.
- **Unverified:** what happens to a vassal when its master is eliminated. Check whether anything
  calls `DoEndVassal` then, or whether `m_eMaster` is left pointing at a dead team. The snapshot
  must not report a dead master either way.

### Ingest (toolkit repo, no change needed)

The runner uploads `stats.db`, and the hypervisor ingests it into
`data/<MODPACK>/stats.duckdb` (`autoplay/hypervisor/stats_ingest.py`). A table it hasn't seen
is **created automatically** from the SQLite schema. A table whose column names or types differ
from the existing DuckDB table gets the **whole file quarantined**. So add new tables freely, but
don't change the columns of any existing table.

## Deliverable 1 (required): `VassalageState` per-turn snapshot

One row per living major-civ **player** whose team is a vassal of a living team, written every
turn in the same place and at the same moment as `MapPlotsState`, so a game's
`(GameId, Turn)` lines up with the map snapshot exactly.

| Column | Type | Value |
|---|---|---|
| `Vassal` | TEXT | vassal player's `getCivilizationShortDescription()` |
| `Master` | TEXT | master team's leader (`GET_TEAM(eMaster).getLeaderID()`), short description |
| `Voluntary` | BOOL | `IsVoluntaryVassal(eMaster)` |
| `TurnsAsVassal` | INT | `GetNumTurnsIsVassal()` |

(+ implicit `GameId`, `Turn` [, `RunId`].)

- Register it with a `RegisterVassalageStateTable()` helper in `SqliteLoggerRegistrations.h`.
  Write it from a `CvGame::LogVassalageState()` called right after `LogMapPlotsState()` in the
  `MOD_SQLITE_LOGGING` block of `CvGame.cpp` (next to `LogMapUnitsState()` / `LogCivTurnEra()`).
- Turns with no vassals write no rows. Absence means "nobody is a vassal".
- Why a snapshot and not only events: the consumer needs "who is whose vassal on turn T", which a
  snapshot answers with a join. It also stays correct across save/reload and the headless
  save-retry path. A game resumed in a new process (hence `RunId`) would never re-log a vassalage
  that began before the save, but the snapshot re-states it every turn.

## Deliverable 2 (recommended): `VassalageEvents`

One row per vassalage start or end, for analysis (how often civs capitulate vs. vassalize
voluntarily, how long vassalage lasts, how it ends).

| Column | Type | Value |
|---|---|---|
| `Vassal` | TEXT | vassal player's short description (one row per player on the vassal team) |
| `Master` | TEXT | master team leader's short description |
| `Action` | TEXT | `BEGIN` or `END` |
| `Voluntary` | BOOL | `BEGIN`: `bVoluntary`. `END`: whether the vassalage being ended was voluntary (read it **before** `setVassal(.., false)`) |
| `Peaceful` | BOOL | `END`: `bPeaceful`. `BEGIN`: `true` |

- Log `BEGIN` in `DoBecomeVassal` right after `setVassal(eTeam, true, bVoluntary)`, and `END` in
  `DoEndVassal` after its early-return guard, before state is torn down. Don't log from `setVassal`
  itself: it doesn't know `bPeaceful`.

## Verification

Use the DLL repo's `vp-dll-dev` skill (`.claude/skills/vp-dll-dev/SKILL.md`): `vp_build.py` to build
and install, `vp_game.py start|load --turns N` to play, `vp_stats.py` to inspect `stats.db`. Read its
paradigm/save-tree warnings before running anything.

1. The build succeeds with `MOD_SQLITE_LOGGING` on, and the game runs N turns with no new crash.
2. Vassalage is rare before the mid-game. Load a late save (Medieval or later, several wars)
   and play enough turns that at least one vassalage begins. If none happens, say so instead of
   claiming success.
3. In `stats.db`:
   - The `VassalageState` and `VassalageEvents` tables exist with exactly the columns above.
   - Every `BEGIN` event is followed, from the next snapshot on, by `VassalageState` rows for that
     pair until a matching `END`.
   - No `VassalageState` row names a dead master or a city-state.
   - `Vassal` and `Master` values appear verbatim in `GameResult.Civ` for the same `GameId`.
4. Cross-check against the game itself: compare with the CSV `DiplomacyAI_TradeAgreements_Log_.csv`
   `Vassalage Trade` lines if CSV AI logging is on, or with `Teams[i]:GetMaster()` in Lua.
5. Existing tables are byte-for-byte unchanged in schema. Diff `PRAGMA table_info` for every
   pre-existing table against a `stats.db` from before your change.

## Out of scope

- Any change to the toolkit repo (hypervisor, explorer). The explorer change comes after a dataset
  with this table exists. For context, it will build `effective_owner` per (game, turn) by
  left-joining `MapPlotsState.owner` to `VassalageState.Vassal` on `(GameId, Turn)`, and use
  `COALESCE(Master, owner)`.
- Deploying the DLL to the headless runners or the remote worker boxes (the toolkit's
  `headless-remote-setup` skill does that once the user is ready).
- Changing existing tables, or the `RunId` question beyond flagging it (see "Decide with the user").

## Done means

- A branch on the agreed base with the registration helper(s), the snapshot logger and (if wanted)
  the event logging, committed with a message saying what each table holds.
- A short report: the branch name, the save and turns used to verify, sample rows from both tables,
  and anything left unverified (e.g. the master-elimination case).

# Civ 5 VP Autoplay Architecture

Design for running autoplay Civ 5 games using the Vox Populi mod distributed over an aribtrary number of compute nodes in order to collect full game history datasets.

## High Level Overview

There are two major components:

1. The autoplay hypervisor. A Python Flask REST API server and simple webapp that manages multiple runners via REST API. Collects logfile bundle tar archives (each log gzip'd individually inside) to a central location via REST API endpoint and controls runners.
2. Autoplay runner. A Python Flask REST API server intended to be deployed to VMs, Sandboxes, or remote machines. Handles starting the Civ 5 executable, patching its modpack files, and collecting, compressing, and sending logs to the hypervisor.

## Terminology and Concepts
* Civ 5 VP: Sid Meier's Civilization 5 running the Community Patch Vox Populi Overhaul Mod
* Autoplay Game: a game played out by 8 computer controlled players that has been configured to start when the executable is launched. Completion is detected differently per stats mode (see **Stats Collection Modes**): in SQLite-stats mode (default) when rows for the latest game id appear in the `GameResult` table of the local `stats.db`; in legacy-logs mode when a `GameResult_Log.csv` has been written to the logs directory.
* Modpack: A folder loaded by the game containing a specific Vox Populi version. In this project, modpacks are identified by the folder name, which generally looks like `MP_AUTOPLAY_VP_<version>`. Modpacks are distributed as zip files that are unpacked into the `DLC` folder by the runner.

### Civ 5 VP Install
Civ 5 installs consist of two locations:
1. `USER_DIR`, generally `C:\Users\<USER>\Documents\My Games\Sid Meier's Civilization 5`. Notably, this directory contains the `Logs` directory, where game logs will be written, and the `Saves` directory, from where saves that cause crashes will be harvested.
2. `INSTALL_DIR`, generally `C:\Users\<USER>\Desktop\pure_vp\Sid Meier's Civilization V`. This directory contains the game executable, `CivilizationV_DX11.exe`. If that file is missing or unreadable when a game launch is requested, the runner waits up to 30 seconds for it to become accessible (covering transient Steam/antivirus locks) and otherwise enters a failed state. The location the game checks for modpacks is `<INSTALL_DIR>\Assets\DLC`.

## Technical Design

### Stats Collection Modes

The system supports two mutually exclusive stats-collection modes, selected independently on the hypervisor (`AUTOPLAY_HV_STATS_MODE`) and runner (`AUTOPLAY_RUNNER_STATS_MODE`). Both services default to `sqlite`; pass `--legacy-logs` on either's command line to force `legacy_logs` (the flag sets the corresponding env var before config load).

* **`sqlite` (default)** — The Civ 5 process writes game statistics into a local SQLite database at `<USER_DIR>/cache/stats.db`. On completion the runner uploads that single file to the hypervisor, which ingests it into a per-modpack DuckDB long-term store.
* **`legacy_logs`** — The historical behaviour: the game writes per-system CSV logs into `<USER_DIR>/Logs`, which the runner gzips into a `.tar` bundle and uploads to `/submit-logs`.

Game correlation metadata (`gameId`, `runnerUuid`, `turn`, `timeElapsedSec`, `runnerUrl`) is sent as form fields in **both** modes, so the bundles audit log, `game_stats.sqlite`, and `file-status.json` behave identically regardless of mode.

#### SQLite stats schema

Each `stats.db` contains a `uuid_dictionary(id INTEGER PRIMARY KEY AUTOINCREMENT, uuid_hex TEXT UNIQUE NOT NULL)` table mapping a per-game local integer id to that game's UUID hex string. Every stats table (`GameResult`, `MilitarySummary`, `PolicyChoices`, `ReligionChoices`, `TechChoices`, `WorldStateLog`, …) has a leading `GameId INTEGER` column referencing `uuid_dictionary.id`. `sqlite_sequence` and `uuid_dictionary` are bookkeeping tables and are never ingested as stats tables.

#### DuckDB ingestion (hypervisor)

The hypervisor eagerly creates a `stats.duckdb` file under `data/<MP_VERSION>/` for every existing modpack directory at startup (and on first upload for a new modpack), each pre-seeded with a global `uuid_dictionary(id BIGINT PRIMARY KEY DEFAULT nextval(seq), uuid_hex VARCHAR UNIQUE NOT NULL)`.

Uploaded files are streamed to a staging directory `data/incoming/<stem>.db` with a sidecar `<stem>.json` of submission metadata, then handed to a **single background ingest worker** (one `asyncio.Queue` consumer — effectively a mutex so only one file ingests at a time). Leftover `data/incoming/*.db` files from a prior run are re-enqueued on startup.

For each staged file the worker, via DuckDB's native `sqlite` extension (`ATTACH ... (TYPE SQLITE, READ_ONLY)` + `INSERT ... SELECT`):
1. **Validates every table's schema first (atomic).** A table's column **names and types** must match the existing DuckDB table. If *any* table disagrees, the whole file is rejected, **nothing** is ingested, and the file is moved to `data/<MP_VERSION>/incomplete_processing/` with the mismatch logged. Atomic per-file granularity avoids partial/double ingestion when a file is later re-examined.
2. **Translates ids local → global.** Distinct `uuid_hex` values are upserted into the global `uuid_dictionary` (minting fresh global ids via a sequence; existing hexes dedupe to their existing id). Each stats table's `GameId` is rewritten from the local id to the global id by joining through both dictionaries, inside a single transaction.
3. On success the raw `.db` is archived to `data/<MP_VERSION>/complete/<gameId>.db`, a row is appended to `<modpack>_bundles.sqlite`, the runner's success counter and `game_stats.sqlite` are updated, and `file-status.json` is refreshed.

`file-status.json` completed-game counts include both `.tar` (legacy) and `.db` (sqlite) files in `complete/`.

### Autoplay Hypersivor

The autoplay hypervisor server code will live in `autoplay/hypervisor/`. In order to support multiple worker processes in parallel, internal state about active runners and games will be stored in a SQLite database at the `STORAGE_ROOT` location. Additionally, it must be deployed in such a way that endpoints are non-blocking, as some operations may involve lengthy file IO. The hypervisor will store logs sent by the runners to the `STORAGE_ROOT` location with the following structure (there will be one set of logs for each `<version>` of the Vox Populi modpack):
```
STORAGE_ROOT/
  file-status.json
  runners.db
  incoming/                          # SQLite-stats staging (uploaded stats.db + sidecar .json)
  MP_AUTOPLAY_VP_<version>_bundles.sqlite
  MP_AUTOPLAY_VP_<version>/
    stats.duckdb                     # per-modpack DuckDB long-term store (SQLite-stats mode)
    complete/
        2024-10-11T23.09.45.167468.tar   # legacy-logs mode
        2024-10-12T03.11.24.296620.db    # SQLite-stats mode (archived raw upload)
        ...
        2024-10-12T13.30.48.399117.tar
    failed/
        2024-10-04T17.43.48.196137-turn350.Civ5Save
    incomplete_processing/           # quarantined stats.db files that failed schema validation
```

For each modpack version, an **append-only** `<MODPACK_VERSION>_bundles.sqlite` is maintained at the storage root. Every successful `/submit-logs` ingest inserts a single row recording the bundle filename, gameId, runner UUID, file size, ingest timestamp, and a JSON blob of all extra metadata the runner submitted (e.g. final turn, elapsed seconds, runner URL). Rows are never updated or deleted; this is a permanent audit log of bundle provenance.

A second SQLite database, `game_stats.sqlite`, lives at the storage root and maintains **one row per `(runner_uuid, game_id)`** with columns `(modpack, turns, total_time_sec, finished, finished_status, first_seen_at, last_updated_at)`. On every heartbeat the row is upserted to keep the maximum `turn` and the maximum `time_elapsed_sec` ever observed for that game. When the game ends — `success` via `/submit-logs` or `failure` via `/submit-crash` with `final=true` — the row is marked `finished` with a final-turn snapshot and is **kept in history forever** (success or fail). The endpoint `GET /turn-times/by-runner` aggregates these rows into a per-runner summary `{games, finished, totalTurns, totalTimeSec, avgSec}`, where `avgSec` is the mean across that runner's games (active + finished) of `total_time_sec / turns`. In-progress games contribute their current snapshot, so the displayed average updates live as turns advance.

#### Configuration
All configuration is supplied via environment variables (prefix `AUTOPLAY_HV_`). The provided `run_hypervisor.bat` launcher sets them explicitly so operators can tune each knob in one place.

* `STORAGE_ROOT`: The root storage directory where logs are stored long term.
* `PORT` [default: 5000]: The port on which the hypervisor server listens for HTTP requests.
* `HOST` [default: `0.0.0.0`]: Bind host.
* `RUNNER_TIMEOUT_SEC` [default: 120]: The amount of time after missing a heartbeat that a runner is considered dead and removed from the pool of available runners.
* `STATS_MODE` [default: `sqlite`]: Either `sqlite` (DuckDB ingestion of uploaded `stats.db` files via `/submit-stats`) or `legacy_logs` (CSV `.tar` bundles via `/submit-logs`). Launch with `--legacy-logs` to force the latter. In `sqlite` mode the ingest worker and `/submit-stats` are active; in `legacy_logs` mode the worker is not started and `/submit-stats` returns 503.


#### HTTP Endpoints

* `POST /runner-registration` with input JSON schema:
```
uuid: str - The unique identifier generated by the runner to identify itself to the hypervisor
url: str - HTTP URL from which this runner can be controlled
modpack: str | null - The modpack this runner currently has installed, or null if it has no modpack installed
```
Used by runner servers to register themselves to the list of runners managed by this hypervisor.

* `POST /runner-heartbeat` with input JSON schema:
```
uuid: str - The unique identifier of the runner sending the heartbeat
gameId: str | null - The unique identifier of the game. Null when no active game
turn: int | null - The current turn number. Null when no active game
timeElapsedSec: int | null - The amount of time elapsed in seconds since the start of the game. Null when no active game
state: "idle" | "starting" | "running" | "failed" | "harvesting_logs" | "uploading_logs" | "updating_modpack" | "attempting_recovery" | "recovered" - The current state of the runner. ``recovered`` is a one-shot pulse: the hypervisor increments the runner's ``recovery_count`` and persists it as ``running``.
url: str | null - HTTP URL from which this runner can be controlled (used for hypervisor-side auto-registration)
modpack: str | null - Currently installed modpack (used for hypervisor-side auto-registration)
```
If the heartbeat arrives for an unknown runner UUID and carries `url`, the hypervisor **auto-registers** the runner from the heartbeat (as if it had POSTed `/runner-registration`). This makes the system robust to hypervisor restarts: runners that survived the outage are silently re-adopted on their next heartbeat. If `url` is missing, the hypervisor instead returns `410 Gone` so the runner falls back to an explicit re-registration.

* `POST /deregister-runner` with input JSON schema:
```
uuid: str - The unique identifier of the runner being removed
```
Called by a runner during graceful shutdown so the hypervisor immediately removes it from the live list rather than waiting for the heartbeat-timeout grace window. Idempotent (returns 204 even when the runner was already absent).

* `POST /submit-logs`: **(legacy-logs mode)** Endpoint for runners to submit logs after completing a game. A simple file upload endpoint for submitting the tar log bundles (each individual log file is gzip-compressed with a `.gz` suffix inside an uncompressed `.tar`). The request should include the following form data:
```
modpack: str - The modpack version of the logs being submitted
gameId: str - The unique identifier of the game these logs correspond to
runnerUuid: str (optional) - The submitting runner
turn: int (optional) - Final turn reached
timeElapsedSec: int (optional) - Game wall-clock duration
runnerUrl: str (optional) - Submitting runner's URL
```
and write the uploaded file to the `STORAGE_ROOT/<modpack>/<gameId>.tar` location on disk, then append a row to `<modpack>_bundles.sqlite` recording the metadata above plus the file size and ingest timestamp.

* `POST /submit-stats`: **(SQLite-stats mode)** Endpoint for runners to upload the local `stats.db` after completing a game. Accepts the same form fields as `/submit-logs` (`modpack`, `gameId`, `runnerUuid`, `turn`, `timeElapsedSec`, `runnerUrl`) plus the file. The upload is streamed to `STORAGE_ROOT/incoming/<stem>.db` with a sidecar metadata `.json`, then enqueued to the single background ingest worker (see **DuckDB ingestion** above); the endpoint returns immediately (204) without blocking on ingestion. Returns 503 if the hypervisor is running in legacy-logs mode.

* `POST /submit-crash`: Endpoint for runners to submit crash artifacts after a game fails. A simple file upload endpoint that stores the uploaded file under `STORAGE_ROOT/<modpack>/failed/<gameId><ext>` (extension chosen from the uploaded filename: `.tar` partial log bundle, `.db` partial stats database in SQLite-stats mode, or `.Civ5Save` autosave). Crash artifacts are **never ingested** into DuckDB. The request should include the following form data:
```
modpack: str - The modpack version of the crash save being submitted
gameId: str - The unique identifier of the game these logs correspond to
```

* `GET /runner-status`: Returns a JSON array with the status of all registered runners, including their current state, active game (if any), and last heartbeat time.

* `GET /file-status`: Returns a JSON object that is simply a dict of `<modpack>: <count  of games in that modpack>`.
This can be cached in `STORAGE_ROOT/file-status.json` and updated by the hypervisor when new logs are submitted.

* `POST /control/start-all`: Fan-out helper that POSTs `/start-game` to every registered runner that is currently idle. Returns a JSON summary `{ uuid: {status, detail} }`.

* `POST /control/stop-all`: Fan-out helper that POSTs `/stop-game` to every registered runner. Returns the same summary shape.

* `POST /control/install-modpack`: Accepts a modpack zip upload (same layout as the runner's `/update-modpack`). The hypervisor inspects the zip's top-level `MP_AUTOPLAY_VP_<version>/` folder to determine the target version, then streams the zip to `/update-modpack` on every registered runner whose currently-installed modpack differs from that version. Returns a per-runner summary.

* `POST /control/start/{uuid}`, `POST /control/stop/{uuid}`, `POST /control/install-modpack/{uuid}`: Per-runner versions of the above fan-out helpers; proxy to just the one runner matching `uuid`.

* `GET /runner-names`: Returns a JSON dict `{host: name}` of operator-supplied display tags keyed by host (IP/hostname without port). Backed by `STORAGE_ROOT/runner_names.sqlite` (durable across hypervisor restarts and machine moves) with schema `runner_names(host TEXT PRIMARY KEY, name TEXT NOT NULL, updated_ts REAL NOT NULL)`.

* `PUT /runner-names/{host}` (body `{"name": "..."}`, 1–64 chars): UPSERT a display tag for the given host. Returns 204.

* `DELETE /runner-names/{host}`: Clear the tag. Returns 204.

#### Webapp
The hypervisor serves a single self-contained `webapp/index.html` (CSS and JS embedded) at `GET /` and `GET /index.html`. Both routes return the file with `Cache-Control: no-store, no-cache, must-revalidate, max-age=0`, `Pragma: no-cache`, and `Expires: 0` so reloads always pick up the latest build. The page polls `/runner-status` (configurable: 1/5/10/30s), `/file-status` (60s), `/turn-times/by-runner` (15s), and `/runner-names` (60s).

All user-configurable UI state is bookmarkable in the URL via `URLSearchParams` and mirrored to one-year cookies (`hv_<key>`, `SameSite=Lax`) as a fallback for direct visits. URL writes use `history.replaceState` (no back-button pollution) and only emit non-default values. State keys: `group` (group-by-runner toggle), `sort`/`dir` (flat-table sort), `groupSort`/`groupSortDir` (per-IP grouped-table sort), `layout` (`comfortable`/`compact` — `compact` shrinks padding/font sizes via `body[data-layout=...]`), `pollSec` (runner-status poll interval). On boot, each key resolves URL → cookie → default.

The webapp includes a control row above the runners table with three fan-out buttons:
* **Start All** — calls `POST /control/start-all`
* **Stop All** — calls `POST /control/stop-all`
* **Mass Install Modpack** — opens a file picker for a `.zip`, then uploads it via `POST /control/install-modpack`

Each row in the runners table also includes per-runner **Start** / **Stop** / **Install Modpack** buttons that target only that runner via the `/control/{action}/{uuid}` endpoints. Column headers are clickable to sort the table by any column (Runner UUID, Address, Modpack, State, Turn, Game Time, Game ID, Successes, Failures); clicking the same header again toggles ascending/descending. Default sort: Runner UUID ascending.

A **Group By Runner** toggle is rendered right-justified next to the "Runners" section header. When off, the flat sortable table is shown. When on, runners are grouped by the IP portion of their `url` (port stripped) and rendered as one mini-table per IP, each with its own **Start All** / **Stop All** / **Mass Install Modpack** buttons that fan out client-side over only the UUIDs in that IP group, hitting the existing `/control/{action}/{uuid}` endpoints. No new backend endpoints are required for the group fan-outs. Each group header also shows an aggregate average turn time (with per-100-turns buckets in a tooltip) sourced from `GET /turn-times/by-runner`, polled separately every 15s. Each grouped mini-table has its own sortable column headers (sort state shared across all groups, persisted via the `groupSort`/`groupSortDir` URL keys).

Each group header renders the host's display tag (or the IP if no tag is set). **Double-clicking the host name** turns it into a `contentEditable` field; pressing Enter commits via `PUT /runner-names/{host}`, Escape reverts. When a tag is set, the IP is shown as a parenthesized suffix and a small `clear` link issues `DELETE /runner-names/{host}`.

The webapp will display the following information in the primary table:
* Runner UUID
* Runner Address (host:port of the runner's HTTP server)
* Modpack Version
* Runner State - same schema as state field in the heartbeat endpoint. Should have a color code (green for running, yellow for starting, red for failed, blue for idle, purple for harvesting/uploading logs, orange for updating modpack, dark-orange for attempting_recovery, teal for recovered).
* Active Game Turn or a dash if no active game
* Active Game Time in HH:MM or a dash if no active game
* Active Game ID (ISO timestamp) or a dash if no active game
* Per-runner counters: Successes, Failures, **Recoveries** (number of crashed games this runner successfully resumed via autosave reload).

And in a secondary table below, the count of completed games for each modpack version:
* Modpack Version
* Completed Game Count
* Failed Game Count


---



### Autoplay Runner

The autoplay runner server code will live in `autoplay/runner/`. While the hypervisor is necessarily multi-process, the runner should be a very simple one file Flask server where all the endpoints and heartbeat loop share a single global state.

#### Startup Sequence
1. Generate a UUID to identify itself to the hypervisor for the duration of its lifetime
2. Start the Flask server, binding to port 0 to get a port allocated by the OS
3. **Install patched files.** The runner ships a `runner/patched_files/` directory; on startup it overwrites (or creates if missing) the following destinations from those sources:
   * `<USER_DIR>/config.ini` ← `patched_files/config.ini`
   * `<USER_DIR>/UserSettings.ini` ← `patched_files/UserSettings.ini`
   * `<USER_DIR>/GraphicsSettingsDX11.ini` ← `patched_files/GraphicsSettingsDX11.ini`
   * `<INSTALL_DIR>/lua51_Win32.dll` ← `patched_files/lua51_Win32.dll`
   * `<INSTALL_DIR>/d3d9.dll` ← `patched_files/d3d9.dll` (only when `USE_BLANK_D3D9_PROXY` is True; otherwise any existing copy at this destination is deleted)
   * `<INSTALL_DIR>/Assets/Maps/Communitu_79a.lua` ← `patched_files/Communitu_79a.lua`
   * `<INSTALL_DIR>/Assets/UI/FrontEnd/FrontEnd.lua` ← `patched_files/FrontEnd.lua`
   * `<INSTALL_DIR>/Assets/UI/FrontEnd/MainMenu.lua` ← `patched_files/MainMenu.lua`
   * `<INSTALL_DIR>/Assets/Automation/RunAutoplayGame.lua` ← `patched_files/RunAutoplayGame.lua`

   Failures here are logged but non-fatal. The patched FrontEnd/MainMenu pair causes the game to auto-load the most recent autosave when launched with no command-line arguments — this is what enables crash recovery (see below). The first line of the installed `MainMenu.lua` is a `local loadOnStart = <bool>;` flag that the runner rewrites immediately before each launch: `false` for a fresh `-Automation` start, `true` when relaunching to recover a crashed game.
4. Determine the modpack version currently installed by checking the `DLC` folder in the `INSTALL_DIR` for folders matching the `MP_AUTOPLAY_VP_<version>` pattern
5. Send a registration request to the hypervisor to register itself
6. Start a heartbeat thread that sends heartbeats to the hypervisor every `HEARTBEAT_INTERVAL_SEC` seconds with updates on the current state of the runner and active game (if any). The source of game progress and completion is **mode-dependent**: in SQLite-stats mode (default) the runner reads the local `<USER_DIR>/cache/stats.db` (latest game = `MAX(id)` in `uuid_dictionary`; current turn = `MAX(Turn)` in `WorldStateLog` for that id, falling back to `MilitarySummary`; complete when `GameResult` has rows for that id); in legacy-logs mode it watches the CSV files in `<USER_DIR>/Logs` (current turn from `WorldState_Log.csv`, complete when `GameResult_Log.csv` exists). On completion the runner submits an asynchronous harvest task (SQLite-stats: checkpoint + upload `stats.db` to `/submit-stats`; legacy-logs: gzip each log, pack into an uncompressed tar, upload to `/submit-logs`) and then returns to an idle state.

#### Global State
The runner will maintain the following global state in memory:
* `uuid`: The unique identifier generated at startup to identify itself to the hypervisor
* `modpack`: The modpack version currently installed on this runner
* `current_game_id`: The unique identifier of the currently active game, or null if no active game
* `current_game_start_time`: The timestamp of when the current game started, or null if no active game
* `current_game_turn`: The current turn number of the active game, or null if no active game


#### Configuration
All configuration is supplied via environment variables (prefix `AUTOPLAY_RUNNER_`). The provided `run_runner.bat` launcher sets them explicitly so operators can tune each knob in one place.

For convenience, `autoplay/scripts/run_both.bat` spawns the hypervisor and runner in two separate titled console windows (via `start "<title>" cmd /K ...`), providing a tmux-like side-by-side view where each service's logs stream to its own window.

* `HYPERVISOR_URL` [default: `http://localhost:5000`]: The HTTP URL of the hypervisor server to which this runner will send heartbeats and submit logs.
* `USER_DIR` [default: `C:\Users\<USER>\Documents\My Games\Sid Meier's Civilization 5`]: The user directory where Civ 5 VP is installed on the runner machines.
* `INSTALL_DIR` [default: `C:\Users\<USER>\Desktop\pure_vp\Sid Meier's Civilization V`]: The install directory where Civ 5 VP is installed on the runner machines.
* `STARTUP_TIMEOUT_SEC` [default: 600]: The amount of time to wait for the Civ 5 VP executable to begin writing logs before entering a failed state.
* `TURN_TIMEOUT_SEC` [default: 600]: The amount of time to wait for a turn to complete (as determined in `WorldState_Log.csv`) before considering the game frozen. A turn timeout triggers the same load-most-recent-autosave recovery flow as a hard process crash.
* `REGISTRATION_TIMEOUT_SEC` [default: 180]: The amount of time to retry registration to the hypervisor before exiting.
* `HEARTBEAT_INTERVAL_SEC` [default: 2]: The amount of time between heartbeats sent to the hypervisor to indicate aliveness and provide updates on the current game state.
* `LOG_IGNORE_PATTERNS` [default: `["CitySites_*", "TradePlayerRouteLog_*"]`]: A list of glob patterns for log files that should be ignored when harvesting logs at the end of a game.
* `USE_BLANK_D3D9_PROXY` [default: False]: When True, copy `patched_files/d3d9.dll` over `<INSTALL_DIR>/d3d9.dll` on startup (the historical behaviour). When False, any existing `<INSTALL_DIR>/d3d9.dll` is removed so the game uses the system DirectX runtime.
* `RECOVERY_MAX_ATTEMPTS` [default: 3]: How many times to attempt to recover a crashed game by relaunching the executable without `-Automation` (which loads the most recent autosave thanks to the patched FrontEnd/MainMenu) before finally marking the game as failed.
* `RECOVERY_ATTEMPT_TIMEOUT_SEC` [default: 600]: Per-recovery-attempt deadline. If no turn progresses past the crashed turn within this many seconds (or the process dies again), the attempt is counted as a failure and the next one is tried.
* `CRASH_HANDLER_POLL_MS` [default: 1000]: How often (milliseconds) the runner enumerates top-level windows looking for one whose title contains `Game Crash`. If found, the game's process tree is killed and the runner enters the same recovery flow as a normal process-died event. Set to `0` to disable.
* `PENDING_UPLOADS_DIR` [default: `~/.civ5_autoplay_pending`]: Local directory used to stage log/crash bundles that could not be uploaded immediately (e.g. while the hypervisor is unreachable). A background drain loop retries until each pending bundle is accepted.
* `STATS_MODE` [default: `sqlite`]: Either `sqlite` (poll `<USER_DIR>/cache/stats.db` for completion/turns and upload it to `/submit-stats`) or `legacy_logs` (watch `<USER_DIR>/Logs` CSVs and upload a `.tar` to `/submit-logs`). Launch with `--legacy-logs` to force the latter.

#### Process Death Detection & Crash Recovery

The game monitor polls `proc.poll()` every 1 second. If the process exits unexpectedly while a turn has already been observed, the runner attempts **autosave recovery** before declaring the game failed:

The same monitor loop also enumerates top-level windows on the configurable `CRASH_HANDLER_POLL_MS` cadence (default 1000ms). If any visible window's title contains `Game Crash`, the runner force-kills the Civ 5 process tree and enters the recovery flow exactly as if the process had died on its own — this catches in-process crash dialogs that don't actually exit the parent process.

1. State transitions to `attempting_recovery` (heartbeat reflects this).
2. The runner relaunches the Civ 5 executable with **no command-line arguments**. The patched `FrontEnd.lua` / `MainMenu.lua` files cause the game to auto-load the most recent autosave.
3. The runner watches for turn progression past the crashed turn, with a per-attempt deadline of `RECOVERY_ATTEMPT_TIMEOUT_SEC`. If the process dies again or no progress occurs in time, the attempt is counted as failed.
4. On the first successful attempt that progresses past the crashed turn, the runner emits a single out-of-band `recovered` heartbeat (which the hypervisor uses to bump that runner's `recovery_count`), transitions back to `running`, and continues monitoring the same `gameId` as if no crash had occurred.
5. After `RECOVERY_MAX_ATTEMPTS` failed attempts the game is marked as failed and the standard crash-report flow runs (partial log bundle + autosave uploaded to `/submit-crash`, logs cleaned, runner returns to idle / reschedules).

##### Preserving CSV logs across recoveries

Civ 5 *overwrites* its log files (rather than appending) when it restarts from an autosave, so a naive harvest after a recovered game would only contain the logs from the most recent run. To keep a complete record across any number of crash/recovery cycles within a single game, the runner snapshots every `*.csv` file in the `Logs` directory into `<USER_DIR>/AutoplayLogSegments/<gameId>/seg_NNN/` immediately before each recovery launch. At harvest time (both the success path and the final-failure crash path) those segments are spliced back together in order, with the live `Logs` content treated as the last segment.

For `WorldState_Log.csv`, `Score_Log.csv`, and `GameResult_Log.csv` (the three CSVs that have a header row) only the first segment's header is kept; every other CSV is concatenated raw. Non-CSV log files (`*.log`, `*.txt`, etc.) are not snapshotted — only the most recent run's copy is harvested. After a successful upload (or terminal crash report) the segment dir for that game is deleted.

> This CSV segment preservation applies to **legacy-logs mode only**. In SQLite-stats mode the persistent `<USER_DIR>/cache/stats.db` survives a recovery relaunch unchanged (the game reopens and continues appending to the same file), so no per-recovery snapshotting is needed and CSV segments are not used.

##### SQLite-stats harvest & lifecycle

In SQLite-stats mode the `stats.db` lifecycle is:
* **On `start-game`**: ensure `<USER_DIR>/cache/` exists and delete any stale `stats.db` (plus its `-wal`/`-shm` sidecars) so a previous game's `GameResult` rows cannot be mistaken for this run's completion.
* **On completion** (`GameResult` has rows for the latest id): the runner first **stops the Civ 5 process** (so the file is unlocked and WAL is flushed), runs `PRAGMA wal_checkpoint(TRUNCATE)` to fold the WAL back into a single self-contained file, uploads it to `/submit-stats` with filename `<gameId>.db`, and on return deletes the local copy. (If the hypervisor was unreachable the bytes are staged in `PENDING_UPLOADS_DIR` first, so deleting the local copy is still safe.)
* **On terminal crash/timeout**: the runner stops Civ 5, checkpoints the partial `stats.db`, and uploads it (plus the most recent autosave) to `/submit-crash` — these are stored under `failed/` and **not** ingested. The local `stats.db` is then cleared.
* **On `stop-game`**: in addition to clearing `Logs`, the local `stats.db` and its sidecars are deleted.

The hypervisor exposes a per-runner `recoveryCount` alongside `successCount` / `failureCount` in `/runner-status`, and the webapp shows it as a sortable **Recoveries** column.

#### Hypervisor-Outage Behavior

The runner is designed to survive a hypervisor that goes down, restarts, or is briefly unreachable:

* **Heartbeats include `url` and `modpack`**, so when the hypervisor returns it auto-registers the runner from the next heartbeat — no explicit re-registration round-trip is needed.
* **If a heartbeat fails while a game is running**, the runner keeps playing the game and keeps trying heartbeats. When the game finishes (or crashes), if the hypervisor is still unreachable the runner harvests the bundle and stages it in `PENDING_UPLOADS_DIR`. A background drain loop retries staged uploads on a fixed interval and removes them once accepted.
* **If a finished game would have auto-rescheduled** but pending uploads exist (i.e. the hypervisor appears to be down), the runner stays idle and sets a "deferred reschedule" flag instead of starting a new game. The next successful heartbeat triggers the deferred relaunch, so scheduling automatically resumes once the hypervisor is back.
* **If the runner was idle when the hypervisor went away**, it stays idle and keeps heart-beating; on hypervisor recovery it is auto-registered and remains idle (no reschedule).
* **Initial registration at startup is best-effort**: a transient hypervisor outage at runner startup no longer crashes the runner — it logs a warning and relies on the heartbeat loop to register once the hypervisor is reachable.

#### HTTP Endpoints

* `POST /start-game`. If a game is currently running, returns a 400 with an error message. Otherwise, starts a new autoplay game by launching the Civ 5 executable. `gameId` is the ISO-timestamp string of the launch time (e.g. `2024-10-11T23.09.45.167468`). Also sets the runner's `is_scheduling_games` flag to True so the runner automatically starts a new game after each completion or crash (once all artifacts are uploaded).

* `POST /stop-game`. Clears `is_scheduling_games`, then terminates any running Civ 5 process tree (recursively via `psutil`) and clears the `USER_DIR/Logs` directory (and, in SQLite-stats mode, deletes the local `stats.db`). Returns 200 even if no game is active (idempotent). No log, stats, or crash bundle is uploaded.

* `POST /update-modpack` which accepts a zip file upload of a modpack and unpacks it to the `DLC` folder in the `INSTALL_DIR`, then deleting any old modpacks that may be present (starts with the same `MP_AUTOPLAY_VP_` prefix). The zip must contain a single top-level `MP_AUTOPLAY_VP_<version>/` folder. Rejected with 409 if a game is currently running.
```
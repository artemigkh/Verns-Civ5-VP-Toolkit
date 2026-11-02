---
name: headless-remote-setup
description: Set up another Windows machine on the LAN as a civ5-headless autoplay worker: copy the game DLLs/Assets, the c5h host kit, the pinned VP modpack database and this toolkit to it over SSH, install uv/Python/deps, point the headless bridge at the desktop's hypervisor and run a validation batch. Use when the user wants to add, rebuild or re-provision a remote headless runner (e.g. "set up the headless runner on <machine>", "add another worker box", "reinstall the laptop runner"), or to push an updated toolkit / modpack pin to one.
---

# Remote headless worker setup

Turns a fresh Windows box into a headless bridge (`autoplay.headless`) that plays c5h games and reports to
the desktop hypervisor. First done 2026-10-27 for the old laptop (`ssh laptop`, 192.168.2.54).

Nothing is installed from Steam on the remote. It never needs the real game client, only:

| Piece | Where it comes from | Remote path |
|---|---|---|
| Firaxis DLLs (`lua51_Win32`, `CvGameDatabaseWin32Final Release`, `CvLocalizationWin32Final Release`), `Locale/` (ICU data, doctor checks it), `Assets/` (Lua, XML, SQL, maps, all DLC incl. `VP_MODPACK_*` and its patched CP DLL) **without art, audio or video** | desktop Steam install | `C:\civ5\game\Sid Meier's Civilization V\` (~210 MB) |
| VC++ 2008 x86 runtime | `Steamworks Shared\_CommonRedist\vcredist\2008\vcredist_x86.exe` | installed (`/q`), skipped if present |
| c5h release kit (host exe with the `modpack-vfs-tiebreak` fix, python pkg, profiles, probes) | `tools/make_kit.py --worktree --python none` in `~/Documents/civ5-headless` | `C:\civ5\civ5-headless\` |
| Pinned game DB + localization + specs | `civ5-headless/pinned/vp-modpack-<ver>/`, `pinned/specs/` | `C:\civ5\civ5-headless\pinned\` |
| `civ5headless.toml` (game_dir, dll, db, loc_db) | generated | `C:\civ5\civ5-headless\civ5headless.toml` |
| Toolkit working tree (tracked + untracked-not-ignored) | `git ls-files -co --exclude-standard` | `C:\civ5\toolkit\` with `.venv` |
| uv | desktop's `uv.exe` | `C:\civ5\bin\uv.exe` (uv downloads Python 3.12 itself; needs internet) |

The remote doesn't need My Games, a mods DB or `config.ini`. `c5h doctor` warns about them, and that is
expected. The c5h queue runs on the toolkit's `.venv` Python, because the kit is built `--python none`: the
bundled embeddable Python failed make_kit's signature check on non-binary files.

## Prerequisites (one-time per machine, needs the user at the keyboard)

1. SSH access as an elevated admin user via an alias in `~/.ssh/config`. The laptop's setup is in
   `misc/remote_laptop/` (gitignored): `laptop-setup.ps1` installs Win32-OpenSSH, pins a key and adds a
   firewall rule. Copy and adapt it for a new machine. Never disable host-key checking.
2. Auto-mode permissions so remote commands don't prompt. Add these:
   - `Bash(ssh <alias> *)`, `Bash(scp * <alias>:*)` and their PowerShell equivalents to `.claude/settings.local.json`.
   - An `autoMode.environment` and an `autoMode.allow` entry naming the alias in `~/.claude/settings.json`. Keep
     `"$defaults"` in both. The laptop entries there are the template.
3. The desktop hypervisor listening on `0.0.0.0:5000` (it does by default) and reachable from the remote.
   Check from the remote: `Invoke-WebRequest -UseBasicParsing http://192.168.2.57:5000/runner-status`.

## Steps

1. **Inspect the remote**: `ssh <alias> 'hostname; (Get-CimInstance Win32_Processor).Name; ...'`. Note the
   cores and RAM. Each game is one thread at ~240–310 MB peak, so `workers` ≈ logical CPUs is reasonable.
2. **Pack and copy** (desktop, Git Bash, from the repo root):
   ```bash
   bash .claude/skills/headless-remote-setup/scripts/pack.sh <alias> <scratch-dir>
   ```
   Env overrides: `PINNED_VERSION` (default 5.4.8-neutrals), `C5H_DIR`, `UV_EXE`. Takes ~20 s over the LAN.
   If the modpack changes, also edit `-ModpackFolder`/`-Modpack` below and re-pin on the desktop first
   (see memory `civ5-headless-layout`).
3. **Install** (runs on the remote, idempotent, ~1 min; uv's first Python + deps download takes most of it):
   ```bash
   ssh <alias> 'powershell -ExecutionPolicy Bypass -File C:\civ5\incoming\remote-install.ps1 -HypervisorUrl http://192.168.2.57:5000 -Workers 8 -GamesPerBatch 1000 -Continuous true'
   ```
   It also does the following:
   - opens inbound TCP 5100 (the bridge's fixed port) to `192.168.2.0/24`;
   - sets AC sleep/hibernate to never;
   - writes `C:\civ5\run_headless_remote.bat` with every `AUTOPLAY_HEADLESS_*` setting baked in, `BIND_HOST`
     included;
   - writes `C:\civ5\start_headless_detached.ps1`;
   - ends with `c5h doctor`. It must say `ready for host games`.

   Other params: `-Turns` (500), `-ModpackFolder` (`VP_MODPACK_5_4_8_NEUTRALS`), `-PinnedVersion`, `-Modpack`
   (the hypervisor name, `MP_AUTOPLAY_VP_5_4_8_NEUTRALS_headless`, the same as the desktop bridge so games pool together),
   `-BridgePort`, `-LanPrefix`.
4. **Smoke game** (~30 s): one 5-turn game, then check that `runs\*\cache\stats.db` exists, then delete
   `C:\civ5\civ5-headless\runs`:
   ```bash
   ssh <alias> 'cd C:\civ5\civ5-headless; $env:PYTHONPATH="C:\civ5\civ5-headless\python"; $ErrorActionPreference="Continue"; & C:\civ5\toolkit\.venv\Scripts\python.exe -m civ5headless run pinned\specs\communitu-standard.json --turns 5 --no-mods --detail summary 2>&1 | Select-Object -Last 3 | % { "$_" }'
   ```
5. **Start the bridge detached.** An SSH session's children die with it. `start_headless_detached.ps1` uses
   `Win32_Process.Create`, which escapes the session's job object:
   ```bash
   ssh <alias> 'powershell -ExecutionPolicy Bypass -File C:\civ5\start_headless_detached.ps1 -BridgeArgs "--autostart"'
   ```
   Leave out `--autostart` to wait for Start in the hypervisor webapp, which then passes its `--max-turn`.
   Logs go to `C:\civ5\logs\bridge-*.log`, with c5h queue output in `C:\civ5\toolkit\headless_data\logs\`.
6. **Verify**:
   - `http://localhost:5000/runner-status` lists `<workers>` rows with `url` `http://<remote-ip>:5100/slots/<k>`
     and `kind: headless`.
   - `http://<remote-ip>:5100/status` answers from the desktop, which proves the firewall rule works.
   - For a bounded validation run, install with `-GamesPerBatch 20 -Continuous false`. Done means `/status`
     shows `batchUnfinished: 0` and `queueRunning: false`, and `gamesHandedOver` equals the batch size.
7. **Switch to production**: re-run step 3 with `-GamesPerBatch 1000 -Continuous true`. It keeps
   `headless_data`. Then stop the old bridge (`Stop-Process` the `python -m autoplay.headless` and its
   `civ5headless queue` child, or press Stop in the webapp and wait for the drain) and repeat step 5.

## Gotchas

- **GNU tar and `C:/` paths**: `tar -cf C:/...` from Git Bash reads `C:` as a remote host. Use `/c/...`.
- **PowerShell 5.1 + native stderr**: under `$ErrorActionPreference='Stop'`, uv's progress output on stderr
  becomes a terminating error. The install script wraps native calls in `Native { ... }`.
- **The `Locale\icudt44l.dat` ICU file is required** by the host. Excluding `Locale/` makes doctor FAIL.
- **Transient `PermissionError` from `os.replace(... .state.json)`** in c5h's `queue.save()` on a fresh
  laptop with Defender real-time scanning. The queue exits; the bridge restarts it and it resumes. Three quick
  exits in a row turn scheduling off. Check `headless_data\logs\batch-*.out`.
- **Disk use**: each finished game's run folder is ~80 MB (mostly `cache/stats.db`). Since 2026-10-28 the
  bridge empties a completed game's folder once it is uploaded or staged (`AUTOPLAY_HEADLESS_KEEP_RUN_FOLDERS=true`
  keeps them); failed and rejected games keep theirs. It must keep `status.json`: c5h re-queues any job whose
  folder lacks one whenever it (re)starts a batch. An early version deleted whole folders, and a resumed desktop
  batch replayed and re-uploaded 183 games (ids in `misc/duplicate_headless_games.txt`). Since 2026-11-01 it also
  keeps the game's `report.html` (~1 MB); c5h can only rebuild that from the files pruning deletes.
  `scripts/prune_uploaded_runs.py <work_dir> [--delete]` empties old folders the same way from the upload ledger. Before that, folders piled up at ~1 GB/hour per 8-worker
  box. The hypervisor still archives every raw upload under `data/<modpack>/complete/` (~80 MB/game) by design.
- **Reboots**: Windows Update restarts a fresh install on its own (the laptop did at 23:50 on 2026-10-27), and
  nothing restarted the bridge. `scripts/register_boot_task.ps1` (run on the remote, elevated) adds the task
  `civ5-headless-bridge`, which runs `C:\civ5\boot_bridge.ps1` at startup: it waits for the LAN address, skips
  if 5100 is already listening, and logs to `C:\civ5\logs\boot.log`. Installed on the laptop only so far.
- **Deploying new bridge code** to a running runner: copy the changed files into `C:\civ5\toolkit\`, then
  run `scripts/restart_bridge.ps1` there (copied to `C:\civ5\restart_bridge.ps1`). It hard-kills only the bridge,
  and the new one adopts the still-running c5h queue, so no game is lost. `-All` kills the queue and games too.
  `scripts/stop_bridge.ps1` (copied to `C:\civ5\stop_bridge.ps1`) stops the bridge, queue and games outright;
  also `Disable-ScheduledTask civ5-headless-bridge` where the boot task exists, or a reboot brings it back.
  Don't start a second bridge while one runs: it adopts the queue, fails to bind 5100, and kills the queue on exit.
- **Changing the desktop's WORKERS**: an adopted queue keeps its old worker count, so the queue and its games have
  to go too. Kill the `cmd` running `run_headless.bat` first, or edit the .bat only after it has exited. cmd re-reads a
  running .bat from disk, and on 2026-11-01 an in-place edit made it re-run `uv run` with the old WORKERS when
  the bridge was killed. Then deregister the dropped slots' UUIDs on the hypervisor and relaunch detached.
- **The desktop bridge plays on its own game folder copy** (since 2026-10-28). With
  `AUTOPLAY_HEADLESS_MODPACK_FOLDER` set, it copies the Steam install's root DLLs, `Locale\` and `Assets\`
  (no media; the configured modpack is the only modpack among the DLC) once, to
  `headless_data\game\<folder>\Sid Meier's Civilization V\` (~190 MB, ~11 s), and writes `gameDir` and `dll`
  into each batch's defaults (resumed batches too). Its games then hold no Steam file, so the user can play the
  real game without the modpack. A copy counts only once its `headless-game-copy.json` marker exists. Remotes
  don't set the variable: their `C:\civ5\game` is already private and `civ5headless.toml` points at it.
- The desktop's `pinned/` and `civ5headless.toml` are gitignored, so they never arrive via the toolkit. They
  arrive via `pinned.tar` and the generated toml.
- Throughput reference: the i7-7700HQ laptop (4C/8T) with 8 workers ran early turns at ~0.4 s/turn per game.
  The 20-game validation batch (to turn 500) took 2 h 10 min wall clock: 7253 game turns, ~3300 game turns/hour.
  Every game ended by victory between turns 280 and 423, with none failed or restarted.
- **Switching modpacks** (done 2026-10-28 for `VP_MODPACK_5_4_8_NEUTRALS`, which replaced `VP_MODPACK_5_4_8`):
  1. On the desktop, after the user has started the real game once with the new modpack, copy
     `My Games\...\cache\Civ5DebugDatabase.db` and `Localization-Merged.db` to `civ5-headless/pinned/vp-modpack-<ver>/`.
  2. Swap in the pragma-patched `CvGameCore_Expansion2.dll`, keeping the original as `.dll.orig` (see memory
     `civ5-headless-layout`). A generated modpack ships the official DLL.
  3. Point `civ5headless.toml` at the new paths, smoke one game, and set a new `AUTOPLAY_HEADLESS_MODPACK` and
     `AUTOPLAY_HEADLESS_MODPACK_FOLDER` in `autoplay/scripts/run_headless.bat`. The desktop bridge then makes
     its own copy of the game folder with that modpack on its next start (below), so the new modpack must be in
     Steam's `Assets\DLC` at that moment; it can be removed from Steam afterwards.
  4. Move each runner's old `headless_data` aside (`headless_data_<old>`; remotes: `C:\civ5\headless_data_<old>`,
     outside the toolkit tree that remote-install clears). Otherwise the new bridge resumes the old batch's
     unfinished games on the new database.
  5. Then run pack.sh and remote-install with `-ModpackFolder`, `-PinnedVersion` and `-Modpack` set.
- **Map scripts the modpack doesn't register** (done 2026-10-29 for Continental Drift / Huge,
  `MP_AUTOPLAY_VP_5_4_8_CDRIFT_HUGE_headless`). A pinned database lists only Assets\Maps, the user's Maps folder and
  DLC MapDirectory scripts. The modpack's `Mods\(2) Vox Populi\Mapscripts\` aren't among them, so a spec naming one fails
  with "map script ... matches 0 entries". The fix is to copy the pinned dir and run a `civ5headless.exe builddb` plan
  on it: `snapshot <pinned db>`, `attach <copy of Localization-Merged.db> Localization`, `phase mapscripts`,
  `mapscript <file> <FileName as recorded>`, `detach Localization`, plus `vfs` lines from `dbbuild.build_vfs(game, [], set())`.
  The plan adds only MapScripts/MapScriptOptions/MapScriptOptionPossibleValues rows.
  - Record the script under a game-relative path (`Assets\DLC\<folder>\Mods\(2) Vox Populi\Mapscripts\X.lua`), which
    every runner's game copy has.
  - The result is `pinned/vp-modpack-5.4.8-cdrift` (5.4.8 original flavors), played on the NEUTRALS DLC folder's
    DLL and Lua. The two pinned databases differ only in leader flavor rows, so those files match.
  - remote-install/pack.sh defaults still describe the NEUTRALS Communitu setup. The remotes were switched by hand:
    `civ5headless.toml` db/loc_db, plus `run_headless_remote.bat` SPEC/MODPACK/maxSeconds 43200. The `.5_4_8_neutrals.bak`
    copies sit beside them.
  - Workers: desktop 16 (Huge games use more memory; the desktop has 32 GB).

# Installs the civ5-headless bridge on a remote Windows machine from the bundles pack.sh copied to
# <Root>\incoming. Idempotent: re-running replaces the game subset, kit, pinned database and toolkit, and keeps
# <Root>\toolkit\headless_data (queue state, upload ledger) and the uv-managed Python.
#
#   powershell -ExecutionPolicy Bypass -File C:\civ5\incoming\remote-install.ps1 -HypervisorUrl http://192.168.2.57:5000
#
# Layout it leaves behind:
#   <Root>\game\Sid Meier's Civilization V\   the Firaxis DLLs and Assets (Lua, XML, SQL, maps, DLC) the host loads
#   <Root>\civ5-headless\                      c5h release kit + civ5headless.toml + pinned\ (game DB, specs)
#   <Root>\toolkit\                            this repository's tracked files, .venv from `uv sync --no-dev`
#   <Root>\bin\uv.exe                          uv
#   <Root>\run_headless_remote.bat             bridge launcher (all settings baked in; extra args pass through)
#   <Root>\start_headless_detached.ps1         starts the launcher outside the SSH session, logging to <Root>\logs
param(
    [string]$Root = 'C:\civ5',
    [Parameter(Mandatory = $true)][string]$HypervisorUrl,
    [string]$ModpackFolder = 'VP_MODPACK_5_4_8',
    [string]$PinnedVersion = '5.4.8',
    [string]$Modpack = 'MP_AUTOPLAY_VP_5_4_8_headless',
    [int]$Workers = 8,
    [int]$GamesPerBatch = 512,
    [string]$Continuous = 'true',
    [int]$Turns = 500,
    [int]$BridgePort = 5100,
    [string]$LanPrefix = '192.168.2.'
)
$ErrorActionPreference = 'Stop'
$in = Join-Path $Root 'incoming'
$game = Join-Path $Root "game\Sid Meier's Civilization V"
$c5h = Join-Path $Root 'civ5-headless'
$toolkit = Join-Path $Root 'toolkit'
$bin = Join-Path $Root 'bin'
function Step($msg) { Write-Output "== $msg" }
# PowerShell 5.1 turns a native program's stderr into a terminating error under 'Stop'; uv logs to stderr.
function Native([scriptblock]$Block) {
    $ErrorActionPreference = 'Continue'
    & $Block 2>&1 | ForEach-Object { "$_" }
}

Step 'Game subset (DLLs + Assets without media)'
if (Test-Path $game) { Remove-Item -Recurse -Force $game }
New-Item -ItemType Directory -Force (Join-Path $Root 'game') | Out-Null
tar -xf (Join-Path $in 'civ5-game-subset.tar') -C (Join-Path $Root 'game')
if ($LASTEXITCODE) { throw 'game tar failed' }
$dll = Join-Path $game "Assets\DLC\$ModpackFolder\Mods\(1) Community Patch\CvGameCore_Expansion2.dll"
if (-not (Test-Path $dll)) { throw "modpack DLL missing: $dll" }

Step 'VC++ 2008 x86 runtime'
$vc = Get-ChildItem 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall' |
    Get-ItemProperty | Where-Object { $_.DisplayName -like 'Microsoft Visual C++ 2008*x86*' }
if ($vc) { Write-Output "already installed: $($vc[0].DisplayName)" }
else {
    $p = Start-Process (Join-Path $in 'vcredist_x86.exe') -ArgumentList '/q' -Wait -PassThru
    Write-Output "vcredist_x86 exit code $($p.ExitCode)"
}

Step 'c5h release kit + pinned database'
if (Test-Path $c5h) { Remove-Item -Recurse -Force $c5h }
$tmp = Join-Path $Root 'kit-unzip'
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
$zip = Get-ChildItem $in -Filter 'civ5-headless-*.zip' | Sort-Object LastWriteTime | Select-Object -Last 1
Expand-Archive $zip.FullName $tmp
Move-Item (Get-ChildItem $tmp -Directory | Select-Object -First 1).FullName $c5h
Remove-Item -Recurse -Force $tmp
tar -xf (Join-Path $in 'pinned.tar') -C $c5h
if ($LASTEXITCODE) { throw 'pinned tar failed' }
$fwd = { param($p) $p -replace '\\', '/' }
@"
# Written by remote-install.ps1: play the $ModpackFolder modpack on a pinned copy of the desktop game's database.
game_dir = "$(& $fwd $game)"
dll = "$(& $fwd $dll)"
db = "pinned/vp-modpack-$PinnedVersion/Civ5DebugDatabase.db"
loc_db = "pinned/vp-modpack-$PinnedVersion/Localization-Merged.db"
"@ | Set-Content -Encoding ascii (Join-Path $c5h 'civ5headless.toml')

Step 'uv + toolkit'
New-Item -ItemType Directory -Force $bin | Out-Null
Copy-Item -Force (Join-Path $in 'uv.exe') $bin
New-Item -ItemType Directory -Force $toolkit | Out-Null
Get-ChildItem $toolkit -Force | Where-Object { $_.Name -notin @('headless_data', '.venv') } | Remove-Item -Recurse -Force
tar -xf (Join-Path $in 'toolkit.tar') -C $toolkit
if ($LASTEXITCODE) { throw 'toolkit tar failed' }
Push-Location $toolkit
Native { & (Join-Path $bin 'uv.exe') sync --no-dev }
if ($LASTEXITCODE) { Pop-Location; throw 'uv sync failed' }
Pop-Location

Step 'LAN address, firewall, power'
$lan = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress.StartsWith($LanPrefix) } |
    Select-Object -First 1).IPAddress
if (-not $lan) { throw "no IPv4 address starting with $LanPrefix" }
Write-Output "bridge binds $lan`:$BridgePort"
$rule = 'civ5-headless-bridge'
Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $rule -Direction Inbound -Protocol TCP -LocalPort $BridgePort `
    -RemoteAddress "$($LanPrefix)0/24" -Action Allow -Profile Any | Out-Null
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

Step 'Launchers'
New-Item -ItemType Directory -Force (Join-Path $Root 'logs') | Out-Null
@"
@echo off
REM Written by remote-install.ps1. Extra arguments (e.g. --autostart) pass through to autoplay.headless.
setlocal
cd /d "$toolkit"
set "PATH=$bin;%PATH%"
set "AUTOPLAY_HEADLESS_HYPERVISOR_URL=$HypervisorUrl"
set "AUTOPLAY_HEADLESS_C5H_DIR=$c5h"
set "AUTOPLAY_HEADLESS_SPEC=$c5h\pinned\specs\communitu-standard.json"
set "AUTOPLAY_HEADLESS_MODPACK=$Modpack"
set "AUTOPLAY_HEADLESS_WORK_DIR=$toolkit\headless_data"
set "AUTOPLAY_HEADLESS_WORKERS=$Workers"
set "AUTOPLAY_HEADLESS_AFFINITY=none"
set "AUTOPLAY_HEADLESS_GAMES_PER_BATCH=$GamesPerBatch"
set "AUTOPLAY_HEADLESS_TURNS=$Turns"
set "AUTOPLAY_HEADLESS_CONTINUOUS=$Continuous"
set AUTOPLAY_HEADLESS_JOB_DEFAULTS={"noMods": true, "detail": "summary", "maxSeconds": 28800, "stallSeconds": 1800}
set "AUTOPLAY_HEADLESS_BIND_HOST=$lan"
set "PYTHONUNBUFFERED=1"
uv run --no-sync python -u -m autoplay.headless --port $BridgePort %*
endlocal
"@ | Set-Content -Encoding ascii (Join-Path $Root 'run_headless_remote.bat')

# Win32_Process.Create puts the process outside the SSH session's job object, so it survives the disconnect.
@"
param([string]`$BridgeArgs = '')
`$log = Join-Path '$Root\logs' ("bridge-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
`$cmd = 'cmd.exe /c ""$Root\run_headless_remote.bat" ' + `$BridgeArgs + ' > "' + `$log + '" 2>&1"'
`$r = Invoke-CimMethod Win32_Process -MethodName Create -Arguments @{ CommandLine = `$cmd; CurrentDirectory = '$Root' }
"pid `$(`$r.ProcessId) (return `$(`$r.ReturnValue)), log `$log"
"@ | Set-Content -Encoding ascii (Join-Path $Root 'start_headless_detached.ps1')

Step 'c5h doctor'
Push-Location $c5h
$env:PYTHONPATH = Join-Path $c5h 'python'
Native { & (Join-Path $toolkit '.venv\Scripts\python.exe') -m civ5headless doctor }
Write-Output "doctor exit code $LASTEXITCODE"
Pop-Location
Step 'done'

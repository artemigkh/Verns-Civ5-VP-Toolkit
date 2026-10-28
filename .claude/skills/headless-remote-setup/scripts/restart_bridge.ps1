# Restart the headless bridge on a remote runner so it loads new toolkit code.
# Hard-kills only the bridge (python -m autoplay.headless): its c5h queue is a separate process group,
# survives, and the new bridge adopts it from queue.pid.json. -All also kills the queue and its games.
# Never matches powershell.exe, so the SSH session running this survives.
param([switch]$All)
$procs = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' }
$bridge = $procs | Where-Object { $_.CommandLine -match '-m autoplay\.headless' }
$bridge | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; "killed bridge $($_.ProcessId)" }
if ($All) {
    Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'civ5headless.exe' -or ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'civ5headless queue run') } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; "killed $($_.Name) $($_.ProcessId)" }
}
for ($i = 0; $i -lt 20 -and (Get-NetTCPConnection -LocalPort 5100 -State Listen -ErrorAction SilentlyContinue); $i++) { Start-Sleep 1 }
'queue processes alive: ' + @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'civ5headless queue run' -and $_.Name -eq 'python.exe' }).Count
& powershell -ExecutionPolicy Bypass -File C:\civ5\start_headless_detached.ps1 -BridgeArgs '--autostart'

# Stop the headless bridge, its c5h queue and every game it is playing, now. Never matches
# powershell.exe, so the SSH session running this survives. Restart with start_headless_detached.ps1.
Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq 'python.exe' -and $_.CommandLine -match '-m autoplay\.headless|civ5headless queue run') -or
    $_.Name -eq 'civ5headless.exe' -or ($_.Name -eq 'cmd.exe' -and $_.CommandLine -match 'run_headless_remote\.bat')
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; "killed $($_.Name) $($_.ProcessId)" }
Start-Sleep 2
'left: ' + @(Get-CimInstance Win32_Process | Where-Object { $_.Name -in 'python.exe', 'civ5headless.exe' }).Count

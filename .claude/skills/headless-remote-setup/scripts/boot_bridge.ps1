# Started at boot by the scheduled task "civ5-headless-bridge" (see register_boot_task.ps1).
# Restarts the headless bridge after Windows Update reboots. Logs to C:\civ5\logs\boot.log.
param([string]$BridgeArgs = '--autostart', [int]$Port = 5100)
$log = 'C:\civ5\logs\boot.log'
function Log($m) { Add-Content $log "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" }

# The bridge binds to the LAN address, so wait for DHCP/static config to come up (up to 5 min).
$bind = (Select-String -Path 'C:\civ5\run_headless_remote.bat' -Pattern 'BIND_HOST=([\d.]+)').Matches.Groups[1].Value
for ($i = 0; $i -lt 60 -and $bind -and -not (Get-NetIPAddress -IPAddress $bind -ErrorAction SilentlyContinue); $i++) { Start-Sleep 5 }

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { Log "port $Port already listening; not starting"; return }
Log ("starting bridge: " + (& powershell -ExecutionPolicy Bypass -File C:\civ5\start_headless_detached.ps1 -BridgeArgs $BridgeArgs))

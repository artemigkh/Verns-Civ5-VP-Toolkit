# Registers "civ5-headless-bridge": runs C:\civ5\boot_bridge.ps1 at startup as the SSH user,
# elevated, without needing a logon (S4U stores no password). Remove with:
#   Unregister-ScheduledTask civ5-headless-bridge -Confirm:$false
$action    = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\civ5\boot_bridge.ps1' -WorkingDirectory 'C:\civ5'
$trigger   = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = 'PT1M'
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName 'civ5-headless-bridge' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Select-Object TaskName, State

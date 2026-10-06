# Registers scripts\ollama_watchdog.ps1 as a per-user scheduled task that starts at logon (H1).
#
# Run ONCE, from an ordinary (non-admin) PowerShell, when you want the watchdog to survive a
# reboot without a window open:
#     powershell -ExecutionPolicy Bypass -File scripts\register_ollama_watchdog_task.ps1
# Remove it again with:
#     powershell -ExecutionPolicy Bypass -File scripts\register_ollama_watchdog_task.ps1 -Unregister
#
# Nothing here runs the watchdog now; registration only schedules it for the next logon.
# The task has NO execution time limit (Task Scheduler's default would stop it after 3 days,
# mid-trial), and it restarts itself up to 3 times if the process exits with an error.

param(
    [string]$TaskName = "OntoSage-OllamaWatchdog",
    [switch]$Unregister
)

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName' (if it existed)."
    exit 0
}

$script = Join-Path $PSScriptRoot "ollama_watchdog.ps1"
if (-not (Test-Path $script)) {
    Write-Host "Cannot find $script"
    exit 2
}

$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "Registered '$TaskName' to start at logon, running $script."
Write-Host "Check it with: Get-ScheduledTask -TaskName $TaskName"

<#
.SYNOPSIS
Register, or remove, the nightly encrypted backup as a Windows Scheduled Task.

.DESCRIPTION
Creates the task OntoSage-nightly-backup. It runs every day at -Time (default 02:30) as the
current user, and only while that user is logged on. The passphrase is in the Windows
Credential Manager, which is per user, so the task must run as that user. A scheduled run
cannot prompt: with no stored passphrase it exits with code 2, and the failure shows up in the
task's Last Run Result.

The action is:
    <repo>\.venv\Scripts\python.exe scripts\backup_encrypted.py --out-dir <OutDir> --keep <Keep>

Retention is done by backup_encrypted.py itself, not by this script. After a successful write
it deletes the oldest ontosage-*.enc files beyond the newest -Keep, and it touches no other file
in the output directory.

Before the first scheduled run, store the passphrase once:
    .venv\Scripts\python.exe scripts\_backup_secret.py --set

.PARAMETER Time
Daily start time, HH:mm (default 02:30).

.PARAMETER Keep
Newest archives to retain (default 14).

.PARAMETER OutDir
Archive directory (default: %USERPROFILE%\OntoSage-backups, outside the repository).

.PARAMETER Remove
Unregister the task instead of registering it.

.PARAMETER WhatIf
Print what would be registered or removed. Nothing is changed.

.EXAMPLE
.\scripts\register_backup_task.ps1 -WhatIf

.EXAMPLE
.\scripts\register_backup_task.ps1
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Time = '02:30',
    [ValidateRange(1, 365)][int]$Keep = 14,
    [string]$OutDir = (Join-Path $env:USERPROFILE 'OntoSage-backups'),
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$taskName = 'OntoSage-nightly-backup'
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv\Scripts\python.exe'
$script = Join-Path $repo 'scripts\backup_encrypted.py'

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "No task named $taskName is registered; nothing to remove."
        exit 0
    }
    if ($PSCmdlet.ShouldProcess($taskName, 'Unregister scheduled task')) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Removed $taskName."
    }
    exit 0
}

$argument = '"{0}" --out-dir "{1}" --keep {2}' -f $script, $OutDir, $Keep
$action = New-ScheduledTaskAction -Execute $python -Argument $argument -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12)
$user = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$description = "Encrypted local backup of the active OntoSage building. Keeps the newest $Keep archives."

Write-Host "Task       : $taskName"
Write-Host "Runs       : daily at $Time as $user (only when logged on)"
Write-Host "Command    : $python $argument"
Write-Host "Archives   : $OutDir (keeps the newest $Keep ontosage-*.enc)"
if (-not (Test-Path $python)) {
    Write-Host "warning: venv python not found at $python; registration would fail" -ForegroundColor Yellow
}

if ($PSCmdlet.ShouldProcess($taskName, 'Register scheduled task')) {
    if (-not (Test-Path $python)) {
        Write-Host "error: create the venv first (.venv\Scripts\python.exe)" -ForegroundColor Red
        exit 1
    }
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Description $description -Force | Out-Null
    Write-Host "Registered $taskName."
} else {
    Write-Host 'WhatIf: nothing was registered.'
}

<#
.SYNOPSIS
Deploy the orchestrator: a cheap restart by default, an expensive rebuild only on request.

.DESCRIPTION
Two operations, kept apart on purpose. The script always prints which one it will run.

  RESTART (default, seconds):
      docker compose restart orchestrator
      Reuses the existing image and recreates nothing. In this deployment orchestrator/ is
      bind-mounted, so Python source edits reach the running process on restart. It does NOT
      pick up anything baked into the image: new pip dependencies, Dockerfile changes, or files
      outside the mounts (BUG-343). Restart also keeps the old environment (CAVEAT-178): an
      .env change needs `up -d`, not restart.

  REBUILD (-Rebuild, minutes; requires -Confirm):
      docker compose build orchestrator, then docker compose up -d --no-deps orchestrator
      Builds a new image from the current checkout, with GIT_SHA and BUILD_TIME set so that
      /health reports code_sha for the commit being deployed. Use it after a Dockerfile or
      dependency change, or whenever /health code_sha does not match mounted_sha.

-WhatIf prints the plan and runs nothing. A -Rebuild without -Confirm is refused (exit 2).
The script never runs `docker compose down` and never removes volumes.

.PARAMETER Rebuild
Select the rebuild operation instead of the restart.

.PARAMETER Confirm
Required together with -Rebuild. Without it the rebuild does not run.

.PARAMETER WhatIf
Print the plan and exit without touching Docker.

.PARAMETER ComposeFile
Compose file to use (default: docker-compose.yml, the active building's file).

.EXAMPLE
.\scripts\deploy.ps1
Restart the orchestrator (cheap).

.EXAMPLE
.\scripts\deploy.ps1 -WhatIf
Show which operation would run.

.EXAMPLE
.\scripts\deploy.ps1 -Rebuild -Confirm
Rebuild the orchestrator image from the current checkout and recreate the container.
#>
[CmdletBinding()]
param(
    [switch]$Rebuild,
    [switch]$Confirm,
    [switch]$WhatIf,
    [string]$ComposeFile = 'docker-compose.yml',
    [string]$Service = 'orchestrator',
    [string]$HealthUrl = 'http://127.0.0.1:8000/health'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

if (-not (Test-Path $ComposeFile)) {
    Write-Host "error: compose file not found: $ComposeFile (is a building active?)" -ForegroundColor Red
    exit 1
}

if ($Rebuild) {
    if (-not $Confirm) {
        Write-Host 'REFUSED: -Rebuild rebuilds the image (minutes). Re-run with -Rebuild -Confirm.' -ForegroundColor Yellow
        exit 2
    }
    $operation = "REBUILD: docker compose build $Service, then up -d --no-deps $Service (minutes)"
} else {
    $operation = "RESTART: docker compose restart $Service (seconds, no rebuild)"
}

Write-Host "Compose file : $ComposeFile"
Write-Host "Operation    : $operation"

if ($WhatIf) {
    Write-Host 'WhatIf: nothing was run.'
    exit 0
}

if ($Rebuild) {
    $sha = (git rev-parse HEAD).Trim()
    $env:GIT_SHA = $sha
    $env:BUILD_TIME = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    Write-Host "Building from commit $sha ..."
    docker compose -f $ComposeFile build $Service
    if ($LASTEXITCODE -ne 0) { Write-Host 'build failed; nothing was recreated.' -ForegroundColor Red; exit $LASTEXITCODE }
    docker compose -f $ComposeFile up -d --no-deps $Service
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    docker compose -f $ComposeFile restart $Service
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# Read back what is running. Non-fatal: the stack may still be warming (GraphDB, ontology).
$health = $null
for ($i = 0; $i -lt 12 -and -not $health; $i++) {
    try {
        $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 5
    } catch {
        Start-Sleep -Seconds 5
    }
}
if ($health -and $health.data) {
    Write-Host ("running code_sha={0} mounted_sha={1} status={2}" -f `
        $health.data.code_sha, $health.data.mounted_sha, $health.data.status)
} else {
    Write-Host 'health not answering yet; check again with: curl http://127.0.0.1:8000/health'
}

param(
  [string]$ProjectRoot = "$PSScriptRoot/..",
  [int]$TimeoutSec = 3600
)
$ErrorActionPreference = 'Stop'
Write-Host "[train-rasa] ProjectRoot = $ProjectRoot"
# Prefer Docker Compose if available
try {
  if (Get-Command docker -ErrorAction SilentlyContinue) {
    $composeOk = $true
    try {
      docker compose version | Out-Null
    } catch {
      $composeOk = $false
    }
    if ($composeOk) {
      Write-Host "[train-rasa] Running docker compose run --rm rasa-train"
      docker compose --project-directory $ProjectRoot run --rm rasa-train
      exit 0
    }
  }
} catch {}

# Fallback: trigger remote train via http_server API
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
try {
  Invoke-RestMethod -Uri http://localhost:8080/api/register -Method Post -Body (@{username='dev';password='devpass'} | ConvertTo-Json) -ContentType 'application/json' -WebSession $session -TimeoutSec 10 | Out-Null
} catch {}
try {
  Invoke-RestMethod -Uri http://localhost:8080/api/login -Method Post -Body (@{username='dev';password='devpass'} | ConvertTo-Json) -ContentType 'application/json' -WebSession $session -TimeoutSec 10 | Out-Null
} catch {}
Write-Host "[train-rasa] Triggering remote training via http_server"
$resp = Invoke-RestMethod -Uri http://localhost:8080/api/rasa/train -Method Post -WebSession $session -TimeoutSec $TimeoutSec -ErrorAction Stop
$resp | ConvertTo-Json -Depth 6

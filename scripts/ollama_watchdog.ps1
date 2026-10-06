# Ollama watchdog for the QA trial (H1 of tasks/TRIAL_TRACKER.csv, 2026-10-06).
#
# On 2026-10-01 the host killed `ollama serve` mid-measurement and did not bring it back; the
# orchestrator's breaker opened 134 times and 14 of 60 answers were honest non-answers that read,
# to a tester, like the building could not answer (CAVEAT-1409).
#
# The first version of this loop probed /api/tags, which answers even when the model runner is
# hung. This version asks the MODEL to produce one token, because a hung runner is exactly the
# failure a trial hits. Each probe is a POST to /api/generate with a 60 s timeout. After
# TWO consecutive failed probes the watchdog stops any running `ollama` server process and starts
# `ollama serve` again, then waits at least 120 s before it will judge the server again.
#
# Run it in its own PowerShell window on the host (not in a container -- Ollama is host-side):
#     powershell -ExecutionPolicy Bypass -File scripts\ollama_watchdog.ps1
# or register it as a logon task once: scripts\register_ollama_watchdog_task.ps1
#
# The model name is read from OLLAMA_MODEL in .env1 (then .env) unless -Model is given.
#
# Known limit: a probe is queued behind any real answer (OLLAMA_NUM_PARALLEL=1). A 60 s timeout
# during a slow real answer counts as a failure, and two of those in a row restart the server
# under it. The probe cannot tell "hung" from "busy" without asking the runner; that is the
# trade the owner accepted in exchange for catching a real hang.

param(
    [string]$Url = "http://127.0.0.1:11434/api/generate",
    [string]$Model = "",
    [int]$IntervalSeconds = 30,
    [int]$ProbeTimeoutSeconds = 60,
    [int]$FailuresBeforeRestart = 2,
    [int]$RestartFloorSeconds = 120,
    [string]$Log = "$PSScriptRoot\outputs\ollama_watchdog.log"
)

$ErrorActionPreference = "Continue"

function Write-Log($msg) {
    $dir = Split-Path -Parent $Log
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $Log -Value $line
    Write-Host $line
}

function Get-ConfiguredModel {
    foreach ($f in @("$PSScriptRoot\..\.env1", "$PSScriptRoot\..\.env")) {
        if (Test-Path $f) {
            $hit = Select-String -Path $f -Pattern '^OLLAMA_MODEL=' | Select-Object -First 1
            if ($hit) {
                return ($hit.Line -replace '^OLLAMA_MODEL=', '').Trim().Trim('"').Trim("'")
            }
        }
    }
    return ""
}

if (-not $Model) { $Model = Get-ConfiguredModel }
if (-not $Model) {
    Write-Host "OLLAMA_MODEL not found in .env1 or .env; pass -Model <name>"
    exit 2
}

# One real generation of one token. Returns $true only for an HTTP 200 whose body is JSON
# with a "response" field, so a 404 (model not pulled) counts as a failure, not a pass.
function Test-OllamaGenerates {
    $payload = [ordered]@{
        model   = $Model
        prompt  = "hi"
        stream  = $false
        options = [ordered]@{ num_predict = 1 }
    } | ConvertTo-Json -Compress -Depth 5
    try {
        $r = Invoke-WebRequest -Uri $Url -Method Post -Body $payload `
            -ContentType "application/json" -UseBasicParsing -TimeoutSec $ProbeTimeoutSeconds
        if ($r.StatusCode -eq 200 -and ($r.Content | ConvertFrom-Json).response -ne $null) {
            return @{ ok = $true; detail = "200" }
        }
        return @{ ok = $false; detail = "status $($r.StatusCode) without a response field" }
    } catch {
        return @{ ok = $false; detail = $_.Exception.Message }
    }
}

function Restart-Ollama {
    $procs = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
    if ($procs) {
        Write-Log "stopping ollama process(es) $($procs.Id -join ',') -- two consecutive probes failed"
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 5
    }
    Write-Log "starting 'ollama serve'"
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
}

$failures = 0
Write-Log ("watchdog started: POST {0} model={1} every {2}s, timeout {3}s, restart after {4} failures, floor {5}s" -f `
    $Url, $Model, $IntervalSeconds, $ProbeTimeoutSeconds, $FailuresBeforeRestart, $RestartFloorSeconds)

while ($true) {
    $probe = Test-OllamaGenerates
    if ($probe.ok) {
        if ($failures -gt 0) { Write-Log "ollama generates again" }
        $failures = 0
    } else {
        $failures++
        Write-Log "probe failed: $($probe.detail) (failure $failures of $FailuresBeforeRestart)"
    }

    if ($failures -ge $FailuresBeforeRestart) {
        Restart-Ollama
        $failures = 0
        # 120 s floor after any restart: the model needs time to load before it is judged.
        Start-Sleep -Seconds ([Math]::Max($RestartFloorSeconds, $IntervalSeconds))
        continue
    }
    Start-Sleep -Seconds $IntervalSeconds
}

# Ollama watchdog for the QA trial (Phase 0.5 of tasks/QA_TRIAL_PLAN_2026-10-02.md).
#
# On 2026-10-01 the host killed `ollama serve` mid-measurement and did not bring it back; the
# orchestrator's breaker opened 134 times and 14 of 60 answers were honest non-answers that read,
# to a tester, like the building could not answer (CAVEAT-1409). Nothing restarts the model
# runner today. This loop asks `/api/tags` every 30 s and, after two consecutive failures,
# starts `ollama serve` again and writes a line to the log. It never stops a running server.
#
# Run it in its own PowerShell window on the host (not in a container -- Ollama is host-side):
#     powershell -ExecutionPolicy Bypass -File scripts\ollama_watchdog.ps1
#
# The orchestrator's own breaker and `model_is_unavailable()` still tell the reader when the
# model is down; this only shortens how long that is true.

param(
    [string]$Url = "http://127.0.0.1:11434/api/tags",
    [int]$IntervalSeconds = 30,
    [int]$FailuresBeforeRestart = 2,
    [string]$Log = "$PSScriptRoot\outputs\ollama_watchdog.log"
)

$failures = 0
function Write-Log($msg) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $Log -Value $line
    Write-Host $line
}

Write-Log "watchdog started: $Url every ${IntervalSeconds}s, restart after $FailuresBeforeRestart failures"
while ($true) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
        if ($r.StatusCode -eq 200) {
            if ($failures -gt 0) { Write-Log "ollama reachable again" }
            $failures = 0
        } else {
            $failures++
            Write-Log "unexpected status $($r.StatusCode) (failure $failures)"
        }
    } catch {
        $failures++
        Write-Log "unreachable: $($_.Exception.Message) (failure $failures)"
    }
    if ($failures -ge $FailuresBeforeRestart) {
        $running = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
        if (-not $running) {
            Write-Log "starting 'ollama serve'"
            Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
        } else {
            Write-Log "ollama process exists but is not answering; leaving it (will not kill a running server)"
        }
        $failures = 0
        Start-Sleep -Seconds 20
    }
    Start-Sleep -Seconds $IntervalSeconds
}

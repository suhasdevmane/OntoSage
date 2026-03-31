<#
.SYNOPSIS
    Switches the Model Provider in the .env file.

.DESCRIPTION
    This script updates the MODEL_PROVIDER variable in the .env file to the specified provider.
    It supports 'local', 'cloud', and 'openai'.

.PARAMETER Provider
    The name of the provider to switch to. Defaults to 'local'.

.EXAMPLE
    .\scripts\switch-provider.ps1 -Provider "openai"
    Switches to OpenAI.

.EXAMPLE
    .\scripts\switch-provider.ps1
    Switches to local (default).
#>

param (
    [string]$Provider = "local"
)

$EnvFile = Join-Path $PSScriptRoot "..\.env"

if (-not (Test-Path $EnvFile)) {
    Write-Error ".env file not found at $EnvFile"
    exit 1
}

$Content = Get-Content $EnvFile
$NewContent = @()
$Updated = $false

foreach ($Line in $Content) {
    if ($Line -match "^MODEL_PROVIDER=") {
        $NewContent += "MODEL_PROVIDER=$Provider"
        $Updated = $true
    } else {
        $NewContent += $Line
    }
}

if (-not $Updated) {
    # If variable didn't exist, append it
    $NewContent += "MODEL_PROVIDER=$Provider"
}

$NewContent | Set-Content $EnvFile -Encoding UTF8
Write-Host "✅ Successfully switched Model Provider to: $Provider"
Write-Host "♻️  Applying changes to containers..."
docker-compose -f docker-compose.agentic.yml up -d orchestrator
Write-Host "🎉 Done! The system is now using $Provider provider."

# .\scripts\switch-provider.ps1 -Provider "local"
# .\scripts\switch-provider.ps1 -Provider "openai"
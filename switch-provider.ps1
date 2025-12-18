#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Quick provider switcher for OntoSage 2.0

.DESCRIPTION
    Switch between local/cloud/openai without full restart
    Only restarts the orchestrator service

.PARAMETER Provider
    Target provider: local, cloud, or openai

.EXAMPLE
    .\switch-provider.ps1 cloud
    # Switch to cloud Ollama (fast)

.EXAMPLE
    .\switch-provider.ps1 local
    # Switch to local Ollama (free)
#>

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('local', 'cloud', 'openai')]
    [string]$Provider
)

$ErrorActionPreference = 'Stop'

Write-Host @"

╔═══════════════════════════════════════════════════╗
║       🔄 OntoSage Provider Switcher 🔄           ║
╚═══════════════════════════════════════════════════╝

"@ -ForegroundColor Cyan

# Show what we're switching to
$providerInfo = @{
    'local' = @{
        Icon = '🖥️'
        Name = 'Local Ollama'
        Model = 'deepseek-r1:32b'
        Speed = '2-3 min'
        Cost = 'FREE'
    }
    'cloud' = @{
        Icon = '☁️'
        Name = 'Cloud Ollama'
        Model = 'gpt-oss:120b-cloud'
        Speed = '5-10 sec'
        Cost = 'Pay per token'
    }
    'openai' = @{
        Icon = '🌐'
        Name = 'OpenAI'
        Model = 'gpt-4-turbo'
        Speed = '5-10 sec'
        Cost = '$0.01/1K tokens'
    }
}

$info = $providerInfo[$Provider]
Write-Host "Switching to: $($info.Icon) $($info.Name)" -ForegroundColor Green
Write-Host "   Model:  $($info.Model)" -ForegroundColor White
Write-Host "   Speed:  $($info.Speed)" -ForegroundColor White
Write-Host "   Cost:   $($info.Cost)" -ForegroundColor White
Write-Host ""

# Validate API key for cloud providers
if ($Provider -eq 'cloud') {
    Write-Host "🔑 Checking Ollama Cloud API key..." -ForegroundColor Cyan
    $envContent = Get-Content '.env' -Raw
    if ($envContent -match 'OLLAMA_CLOUD_API_KEY=(.+)') {
        $apiKey = $matches[1].Trim()
        if ($apiKey -and $apiKey -ne '' -and $apiKey.Length -gt 20) {
            Write-Host "   ✅ API key found" -ForegroundColor Green
        }
        else {
            Write-Host "   ❌ ERROR: Invalid Ollama Cloud API key in .env" -ForegroundColor Red
            exit 1
        }
    }
    else {
        Write-Host "   ❌ ERROR: OLLAMA_CLOUD_API_KEY not found in .env" -ForegroundColor Red
        exit 1
    }
}
elseif ($Provider -eq 'openai') {
    Write-Host "🔑 Checking OpenAI API key..." -ForegroundColor Cyan
    $envContent = Get-Content '.env' -Raw
    if ($envContent -match 'OPENAI_API_KEY=(.+)') {
        $apiKey = $matches[1].Trim()
        if ($apiKey -and $apiKey -ne '' -and $apiKey -ne 'your_openai_api_key_here' -and $apiKey.StartsWith('sk-')) {
            Write-Host "   ✅ API key found" -ForegroundColor Green
        }
        else {
            Write-Host "   ❌ ERROR: Invalid OpenAI API key in .env" -ForegroundColor Red
            Write-Host "   Get your key from: https://platform.openai.com/api-keys" -ForegroundColor Yellow
            exit 1
        }
    }
    else {
        Write-Host "   ❌ ERROR: OPENAI_API_KEY not found in .env" -ForegroundColor Red
        exit 1
    }
}

# Update .env file
Write-Host "📝 Updating .env file..." -ForegroundColor Cyan
$envPath = '.env'
if (-not (Test-Path $envPath)) {
    Write-Host "   ❌ ERROR: .env file not found" -ForegroundColor Red
    exit 1
}

$envContent = Get-Content $envPath -Raw
if ($envContent -match 'MODEL_PROVIDER=\w+') {
    $oldProvider = $matches[0] -replace 'MODEL_PROVIDER=', ''
    $envContent = $envContent -replace 'MODEL_PROVIDER=\w+', "MODEL_PROVIDER=$Provider"
    Set-Content -Path $envPath -Value $envContent -NoNewline
    Write-Host "   ✅ Changed MODEL_PROVIDER: $oldProvider → $Provider" -ForegroundColor Green
}
else {
    Write-Host "   ❌ ERROR: MODEL_PROVIDER not found in .env" -ForegroundColor Red
    exit 1
}

# Restart orchestrator only (fast switch)
Write-Host "`n🔄 Restarting orchestrator service..." -ForegroundColor Cyan
docker-compose -f docker-compose.agentic.yml restart orchestrator

# Wait for health check
Write-Host "`n⏳ Waiting for orchestrator to be ready (15 seconds)..." -ForegroundColor Cyan
Start-Sleep -Seconds 15

# Health check
Write-Host "🏥 Checking service health..." -ForegroundColor Cyan
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -Method GET -TimeoutSec 5 -ErrorAction Stop
    Write-Host "   ✅ Orchestrator is HEALTHY" -ForegroundColor Green
}
catch {
    Write-Host "   ⚠️  Orchestrator not ready yet (check logs if issue persists)" -ForegroundColor Yellow
}

# Verify provider in logs
Write-Host "`n📋 Verifying provider in logs..." -ForegroundColor Cyan
Start-Sleep -Seconds 2
$logs = docker logs ontosage-orchestrator --tail 20 2>&1

if ($Provider -eq 'local') {
    if ($logs -match 'Initialized Ollama LLM.*deepseek-r1') {
        Write-Host "   ✅ Local Ollama (deepseek-r1:32b) confirmed" -ForegroundColor Green
    }
    else {
        Write-Host "   ⚠️  Could not confirm model initialization. Check logs:" -ForegroundColor Yellow
        Write-Host "      docker logs ontosage-orchestrator --tail 50" -ForegroundColor Gray
    }
}
elseif ($Provider -eq 'cloud') {
    if ($logs -match 'Initialized Ollama Cloud LLM.*gpt-oss') {
        Write-Host "   ✅ Cloud Ollama (gpt-oss:120b-cloud) confirmed" -ForegroundColor Green
    }
    else {
        Write-Host "   ⚠️  Could not confirm cloud initialization. Check logs:" -ForegroundColor Yellow
        Write-Host "      docker logs ontosage-orchestrator --tail 50" -ForegroundColor Gray
    }
}
elseif ($Provider -eq 'openai') {
    if ($logs -match 'Initialized.*OpenAI') {
        Write-Host "   ✅ OpenAI (gpt-4-turbo) confirmed" -ForegroundColor Green
    }
    else {
        Write-Host "   ⚠️  Could not confirm OpenAI initialization. Check logs:" -ForegroundColor Yellow
        Write-Host "      docker logs ontosage-orchestrator --tail 50" -ForegroundColor Gray
    }
}

Write-Host @"

╔═══════════════════════════════════════════════════╗
║              ✅ SWITCH COMPLETE!                 ║
╚═══════════════════════════════════════════════════╝

🌐 Test your new provider:
   http://localhost:3000

📊 Current Configuration:
   Provider: $($info.Icon) $($info.Name)
   Model:    $($info.Model)
   Speed:    $($info.Speed)

💡 To switch again:
   .\switch-provider.ps1 <local|cloud|openai>

"@ -ForegroundColor Green

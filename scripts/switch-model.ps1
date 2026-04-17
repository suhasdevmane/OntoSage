<#
.SYNOPSIS
    Switches the OpenAI model in the .env file and other configuration files.

.DESCRIPTION
    Updates the OPENAI_MODEL variable in the .env file and related service configs,
    then restarts the orchestrator for a quick switch.

.PARAMETER Model
    The exact OpenAI model id to switch to (e.g., gpt-5.4-long-context).

.PARAMETER Pick
    Picks a model by index from the preferred list (use -List to see).

.PARAMETER List
    Prints the preferred model list in order and exits.

.PARAMETER NoRestart
    Skip docker restart (only update config files).

.EXAMPLE
    .\scripts\switch-model.ps1 -List
    Shows the preferred model list.

.EXAMPLE
    .\scripts\switch-model.ps1 -Pick 1
    Switches to the top recommended model.

.EXAMPLE
    .\scripts\switch-model.ps1 -Model "gpt-4.1-mini-long-context"
    Switches to GPT-4.1 mini long-context.
#>

param (
    [string]$Model,
    [int]$Pick = 0,
    [switch]$List,
    [switch]$NoRestart
)

$PreferredModels = @(
    "gpt-5.4-long-context",
    "gpt-5-mini-2025-08-07",
    "o4-mini-2025-04-16",
    "o3-mini-2025-01-31",
    "gpt-4.1-mini-long-context",
    "gpt-4.1-nano-long-context",
    "gpt-5.1-codex-mini",
    "chatgpt-o-mini-latest",
    "o4-mini-2025-04-16-shared",
    "o3-mini-2025-01-31-shared"
)

if ($List) {
    Write-Host "Preferred OpenAI models (highest to lowest for general quality):" -ForegroundColor Cyan
    for ($i = 0; $i -lt $PreferredModels.Count; $i++) {
        $idx = $i + 1
        Write-Host ("  {0}. {1}" -f $idx, $PreferredModels[$i])
    }
    Write-Host ""
    Write-Host "Usage examples:" -ForegroundColor Cyan
    Write-Host "  .\scripts\switch-model.ps1 -Pick 1"
    Write-Host "  .\scripts\switch-model.ps1 -Model gpt-4.1-mini-long-context"
    return
}

if (-not $Model -and $Pick -gt 0) {
    if ($Pick -le $PreferredModels.Count) {
        $Model = $PreferredModels[$Pick - 1]
    } else {
        Write-Error "Pick index out of range. Use -List to see valid indexes."
        exit 1
    }
}

if (-not $Model) {
    Write-Host "No model specified." -ForegroundColor Yellow
    Write-Host "Run: .\\scripts\\switch-model.ps1 -List" -ForegroundColor Yellow
    exit 1
}

# List of files to update
$FilesToUpdate = @(
    "..\.env",
    "..\rag-service\graphdbRAG\.env",
    "..\rag-service\RAG system\.env",
    "..\rag-service\RAG system advance\.env",
    "..\orchestrator\agents\.env"
)

# Function to update a single file
function Update-File {
    param (
        [string]$FilePath,
        [string]$ModelName
    )

    $FullPath = Join-Path $PSScriptRoot $FilePath
    if (-not (Test-Path $FullPath)) {
        Write-Warning "File not found: $FullPath"
        return
    }

    $Content = Get-Content $FullPath
    $NewContent = @()
    $Updated = $false

    foreach ($Line in $Content) {
        if ($Line -match "^OPENAI_MODEL=") {
            $NewContent += "OPENAI_MODEL=$ModelName"
            $Updated = $true
        } else {
            $NewContent += $Line
        }
    }

    if (-not $Updated) {
        # If variable didn't exist, append it
        $NewContent += "OPENAI_MODEL=$ModelName"
    }

    $NewContent | Set-Content $FullPath -Encoding UTF8
    Write-Host "✅ Updated $FilePath"
}

# Update .env files
foreach ($File in $FilesToUpdate) {
    Update-File -FilePath $File -ModelName $Model
}

# Update Python files (regex replacement)
$PythonFiles = @(
    "..\rag-service\RAG system advance\advanced_rag_builder.py",
    "..\rag-service\RAG system advance\advanced_rag_test.py",
    "..\rag-service\graphdbRAG\Get llm response.py",
    "..\rag-service\GraphRAG\gpt-4o-mini.py",
    "..\rag-service\RAG system\rag_builder.py",
    "..\rag-service\RAG system\rag_builder_test.py"
)

foreach ($File in $PythonFiles) {
    $FullPath = Join-Path $PSScriptRoot $File
    if (Test-Path $FullPath) {
        $Content = Get-Content $FullPath -Raw
        # Replace OPENAI_MODEL = "..." with OPENAI_MODEL = "$Model"
        $NewContent = $Content -replace 'OPENAI_MODEL\s*=\s*"[^"]+"', "OPENAI_MODEL = `"$Model`""
        if ($NewContent -ne $Content) {
            $NewContent | Set-Content $FullPath -Encoding UTF8
            Write-Host "✅ Updated $File"
        }
    }
}

if (-not $NoRestart) {
    Write-Host "♻️  Applying changes to containers..."
    docker compose up -d orchestrator graphdb-rag-service
    Write-Host "🎉 Done! The system is now using $Model."
} else {
    Write-Host "✅ Config updated. Restart skipped (NoRestart)." -ForegroundColor Yellow
}


# .\scripts\switch-model.ps1 -List
# .\scripts\switch-model.ps1 -Pick 1
# .\scripts\switch-model.ps1 -Model "gpt-5.4"

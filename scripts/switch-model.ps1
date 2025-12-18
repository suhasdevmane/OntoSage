<#
.SYNOPSIS
    Switches the OpenAI model in the .env file and other configuration files.

.DESCRIPTION
    This script updates the OPENAI_MODEL variable in the .env file and other service configuration files to the specified model.
    It supports common models like o3-mini, gpt-4o, gpt-4o-mini, etc.

.PARAMETER Model
    The name of the model to switch to. Defaults to 'o3-mini'.

.EXAMPLE
    .\scripts\switch-model.ps1 -Model "gpt-4o"
    Switches to GPT-4o.

.EXAMPLE
    .\scripts\switch-model.ps1
    Switches to o3-mini (default).
#>

param (
    [string]$Model = "o3-mini"
)

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

Write-Host "♻️  Applying changes to containers..."
docker-compose -f docker-compose.agentic.yml up -d orchestrator graphdb-rag-service
Write-Host "🎉 Done! The system is now using $Model."


# .\scripts\switch-model.ps1 -Model "o3-mini"
# .\scripts\switch-model.ps1 -Model "gpt-4o"
# .\scripts\switch-model.ps1 -Model "gpt-4o-mini"
# .\scripts\switch-model.ps1 -Model "gpt-4.1-mini"
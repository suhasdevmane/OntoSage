param(
    [string]$SharedDataRoot = "rasa-ui/shared_data",
    [switch]$WhatIf
)

# Moves any files in the root of shared_data into the artifacts folder for consistency.
$rootPath = Join-Path -Path (Get-Location) -ChildPath $SharedDataRoot
$artifacts = Join-Path $rootPath 'artifacts'

if (-not (Test-Path $rootPath)) {
    Write-Error "Shared data root not found: $rootPath"
    exit 1
}
if (-not (Test-Path $artifacts)) {
    New-Item -ItemType Directory -Path $artifacts | Out-Null
}

# Only move files at the root (not directories)
Get-ChildItem -Path $rootPath -File | ForEach-Object {
    $dest = Join-Path $artifacts $_.Name
    if ($WhatIf) {
        Write-Host "Would move: $($_.FullName) -> $dest"
    } else {
        Move-Item -Path $_.FullName -Destination $dest -Force
        Write-Host "Moved: $($_.FullName) -> $dest"
    }
}

Write-Host "Done. Artifacts are under: $artifacts"

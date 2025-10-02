param(
  [string]$Root = (Join-Path $PSScriptRoot '..' | Resolve-Path)
)

$ErrorActionPreference = 'Stop'
$shared = Join-Path $Root 'shared_data'
$artifacts = Join-Path $shared 'artifacts'

if (!(Test-Path $shared)) { Write-Output "Shared dir not found: $shared"; exit 0 }
if (!(Test-Path $artifacts)) { New-Item -ItemType Directory -Path $artifacts | Out-Null }

Get-ChildItem -LiteralPath $shared -File | ForEach-Object {
  try {
    Move-Item -LiteralPath $_.FullName -Destination $artifacts -Force
    Write-Output "Moved $($_.Name) -> artifacts"
  } catch {
    Write-Warning "Failed to move $($_.Name): $_"
  }
}

Write-Output "Done. Current shared_data contents:"
Get-ChildItem -LiteralPath $shared -Force | Select-Object Name, Mode, Length | Format-Table -AutoSize

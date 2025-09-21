$ErrorActionPreference = 'Stop'

# Ensure models directory exists so artifacts can be written
New-Item -ItemType Directory -Force -Path "rasa-ui/models" | Out-Null

Write-Host "Starting one-off Rasa training (container will be auto-removed on exit)..." -ForegroundColor Cyan

# Use docker-compose 'run --rm' so the container is deleted after it exits
docker-compose -f docker-compose.rasatrain.yml run --rm rasa-train

$code = $LASTEXITCODE
if ($code -eq 0) {
  $latest = Get-ChildItem -Path "rasa-ui/models" -Filter '*.tar.gz' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($latest) {
    Write-Host "Training complete. Latest model: $($latest.FullName)" -ForegroundColor Green
  } else {
    Write-Host "Training finished but no model file found in rasa-ui/models" -ForegroundColor Yellow
  }
} else {
  Write-Error "Rasa training failed with exit code $code"
}

exit $code

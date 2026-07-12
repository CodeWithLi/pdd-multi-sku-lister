# Start local prod API (8010). Uses myTest/.env
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start-api-prod.ps1

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Host "Missing .env. Run: copy .env.example .env" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "=== PDD Agent PROD (8010) ===" -ForegroundColor Green
Write-Host "  API:    http://127.0.0.1:8010" -ForegroundColor Green
Write-Host "  Health: http://127.0.0.1:8010/api/health" -ForegroundColor DarkGray
Write-Host "  Config: .env (PDD_RUNTIME_PROFILE=prod)" -ForegroundColor DarkGray
Write-Host "  Stop:   Ctrl+C in this window" -ForegroundColor DarkGray
Write-Host ""

python -m pdd_agent.main api --host 0.0.0.0 --port 8010

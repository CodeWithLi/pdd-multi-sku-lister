# Start local test API (8011). Can run alongside prod on 8010.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start-api-test.ps1

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$EnvFile = Join-Path $Root ".env.test"
if (-not (Test-Path $EnvFile)) {
    Write-Host ""
    Write-Host "Missing .env.test. Run:" -ForegroundColor Yellow
    Write-Host "  copy .env.test.example .env.test" -ForegroundColor Yellow
    Write-Host "  Then set DATABASE_URL to pdd_agent_platform_test" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

$env:PDD_ENV_FILE = $EnvFile
$env:PDD_RUNTIME_PROFILE = "test"
$env:PDD_BACKGROUND_JOBS = "false"

Write-Host ""
Write-Host "=== PDD Agent TEST (8011) ===" -ForegroundColor Cyan
Write-Host "  API:    http://127.0.0.1:8011" -ForegroundColor Cyan
Write-Host "  Health: http://127.0.0.1:8011/api/health" -ForegroundColor DarkGray
Write-Host "  Config: .env.test (background_jobs=false)" -ForegroundColor DarkGray
Write-Host "  Stop:   Ctrl+C in this window" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Do not browser-test stores that prod 8010 is using." -ForegroundColor Yellow
Write-Host ""

python -m pdd_agent.main api --host 0.0.0.0 --port 8011

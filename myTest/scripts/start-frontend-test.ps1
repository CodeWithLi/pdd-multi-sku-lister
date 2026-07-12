# Start frontend dev server for test API 8011 (port 5174)
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start-frontend-test.ps1

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Frontend = Join-Path $Root "frontend"
Set-Location $Frontend

Write-Host ""
Write-Host "=== PDD Agent TEST frontend (5174) ===" -ForegroundColor Cyan
Write-Host "  UI:  http://127.0.0.1:5174" -ForegroundColor Cyan
Write-Host "  API: http://127.0.0.1:8011/api" -ForegroundColor DarkGray
Write-Host "  Stop: Ctrl+C in this window" -ForegroundColor DarkGray
Write-Host ""

npm run dev:test

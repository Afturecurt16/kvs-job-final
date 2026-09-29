$ErrorActionPreference = "Stop"

$projectDir = $PSScriptRoot
$python = Join-Path (Split-Path $projectDir -Parent) ".venv\Scripts\python.exe"
$url = "http://127.0.0.1:8000/miniapp"

Set-Location $projectDir

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python was not found: $python"
}

try {
    $health = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/healthz" -TimeoutSec 2
    if ($health.StatusCode -eq 200) {
        Write-Host "Miniapp is already running: $url" -ForegroundColor Green
        exit 0
    }
} catch {
    # Nothing healthy is listening yet; continue with a normal startup.
}

Write-Host "Starting PostgreSQL..." -ForegroundColor Cyan
docker compose up -d postgres
if ($LASTEXITCODE -ne 0) {
    throw "Failed to start PostgreSQL with Docker Compose"
}

Write-Host "Checking database..." -ForegroundColor Cyan
& $python -c "import asyncio; from database.db import init_db; asyncio.run(init_db())"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to initialize database"
}
$env:KVS_DB_INITIALIZED = "1"

Write-Host "Miniapp: $url" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop" -ForegroundColor DarkGray
& $python -m uvicorn miniapp.app:app --host 127.0.0.1 --port 8000 --log-level info

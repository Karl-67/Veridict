# Verdict — start all services
# Usage: .\start.ps1 [-NoFrontend]
param(
    [switch]$NoFrontend
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PgCtl = "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe"
$PgData = "C:\Program Files\PostgreSQL\17\data"
$LogDir = "$ProjectRoot\logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Green  { param($msg) Write-Host $msg -ForegroundColor Green }
function Write-Yellow { param($msg) Write-Host $msg -ForegroundColor Yellow }
function Write-Red    { param($msg) Write-Host $msg -ForegroundColor Red }

function Wait-ForPort {
    param([int]$Port, [string]$Label, [int]$Retries = 20)
    while ($Retries -gt 0) {
        $tc = Test-NetConnection -ComputerName "localhost" -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue 2>$null
        if ($tc) {
            Write-Green "✓ $Label is up on :$Port"
            return
        }
        $Retries--
        Start-Sleep -Seconds 1
    }
    Write-Red "✗ $Label did not come up on :$Port"
}

# ── 1. PostgreSQL ─────────────────────────────────────────────────────────────

Write-Host ""
Write-Yellow "── PostgreSQL ──────────────────────────────────────────────────"
$pgStatus = & $PgCtl status -D $PgData 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Green "✓ PostgreSQL already running"
} else {
    Write-Yellow "  Starting PostgreSQL..."
    & $PgCtl start -D $PgData -l "$LogDir\postgres.log"
    Start-Sleep -Seconds 2
    Write-Green "✓ PostgreSQL started"
}

# ── 2. Backend ───────────────────────────────────────────────────────────────
# --no-access-log suppresses the 200 OK line per poll — only errors surface

Write-Host ""
Write-Yellow "── Backend (uvicorn :8000) ─────────────────────────────────────"
try {
    $null = Invoke-WebRequest -Uri "http://localhost:8000/api/health" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
    Write-Green "✓ Backend already running"
} catch {
    $backendLog = "$LogDir\backend.log"
    $backendProc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "python -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000 --env-file app/backend/.env --no-access-log >> `"$backendLog`" 2>&1" `
        -WorkingDirectory $ProjectRoot `
        -PassThru -NoNewWindow
    $backendProc.Id | Set-Content "$LogDir\backend.pid"
    Wait-ForPort -Port 8000 -Label "Backend"
}

# ── 3. Worker ────────────────────────────────────────────────────────────────

Write-Host ""
Write-Yellow "── Worker ──────────────────────────────────────────────────────"
$workerLog = "$LogDir\worker.log"
$workerProc = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "python -m app.backend.worker >> `"$workerLog`" 2>&1" `
    -WorkingDirectory $ProjectRoot `
    -PassThru -NoNewWindow
$workerProc.Id | Set-Content "$LogDir\worker.pid"
Write-Green "✓ Worker started (PID $($workerProc.Id))"

# ── 4. Frontend ──────────────────────────────────────────────────────────────

if (-not $NoFrontend) {
    Write-Host ""
    Write-Yellow "── Frontend (Vite :5173) ───────────────────────────────────────"
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:5173" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
        Write-Green "✓ Frontend already running"
    } catch {
        $frontendLog = "$LogDir\frontend.log"
        $frontendProc = Start-Process -FilePath "cmd.exe" `
            -ArgumentList "/c", "cd /d `"$ProjectRoot\app\frontend`" && npm run dev >> `"$frontendLog`" 2>&1" `
            -WorkingDirectory "$ProjectRoot\app\frontend" `
            -PassThru -NoNewWindow
        $frontendProc.Id | Set-Content "$LogDir\frontend.pid"
        Wait-ForPort -Port 5173 -Label "Frontend"
    }
}

# ── summary ──────────────────────────────────────────────────────────────────

Write-Host ""
Write-Green "══════════════════════════════════════════════════════════════"
Write-Green "  Verdict is running"
Write-Green "  Frontend : http://localhost:5173"
Write-Green "  Backend  : http://localhost:8000"
Write-Green "  Logs     : backend.log  worker.log  frontend.log"
Write-Green "  Failures : logs\failures.jsonl"
Write-Green "  Stop all : .\stop.ps1"
Write-Green "══════════════════════════════════════════════════════════════"

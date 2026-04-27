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

function Wait-ForHttp {
    param([string]$Url, [string]$Label, [int]$Retries = 20)
    while ($Retries -gt 0) {
        try {
            $null = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            Write-Green "✓ $Label is reachable at $Url"
            return $true
        } catch {
            $Retries--
            Start-Sleep -Seconds 1
        }
    }
    Write-Red "✗ $Label did not become reachable at $Url"
    return $false
}

$backendReady = $false
$frontendReady = $NoFrontend

# Kill any leftover process on a port so we can bind cleanly
function Clear-Port {
    param([int]$Port)
    $hits = netstat -ano 2>$null | Select-String ":$Port\s.*LISTENING"
    foreach ($line in $hits) {
        $pid = ($line.Line.Trim() -split '\s+')[-1]
        if ($pid -match '^\d+$' -and [int]$pid -gt 0) {
            Stop-Process -Id ([int]$pid) -Force -ErrorAction SilentlyContinue
        }
    }
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
Clear-Port -Port 8000
$backendLog = "$LogDir\backend.log"
$backendProc = Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "python -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000 --env-file app/backend/.env --no-access-log >> `"$backendLog`" 2>&1" `
    -WorkingDirectory $ProjectRoot `
    -PassThru -NoNewWindow
$backendProc.Id | Set-Content "$LogDir\backend.pid"
$backendReady = Wait-ForHttp -Url "http://127.0.0.1:8000/api/health" -Label "Backend"
if (-not $backendReady) {
    Write-Yellow "  Last backend log lines:"
    Get-Content -Path $backendLog -Tail 25 -ErrorAction SilentlyContinue
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
    Clear-Port -Port 5173
    $frontendLog = "$LogDir\frontend.log"
    "" | Set-Content $frontendLog
    $frontendProc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "cd /d `"$ProjectRoot\app\frontend`" && .\node_modules\.bin\vite.cmd --host 127.0.0.1 --port 5173 >> `"$frontendLog`" 2>&1" `
        -WorkingDirectory "$ProjectRoot\app\frontend" `
        -PassThru -NoNewWindow
    $frontendProc.Id | Set-Content "$LogDir\frontend.pid"
    $frontendReady = Wait-ForHttp -Url "http://127.0.0.1:5173" -Label "Frontend"
    if (-not $frontendReady) {
        Write-Yellow "  Last frontend log lines:"
        Get-Content -Path $frontendLog -Tail 25 -ErrorAction SilentlyContinue
    }
}

# ── summary ──────────────────────────────────────────────────────────────────

Write-Host ""
if ($backendReady -and $frontendReady) {
    Write-Green "══════════════════════════════════════════════════════════════"
    Write-Green "  Verdict is running"
    if (-not $NoFrontend) {
        Write-Green "  Frontend : http://127.0.0.1:5173"
    }
    Write-Green "  Backend  : http://127.0.0.1:8000"
    Write-Green "  Logs     : backend.log  worker.log  frontend.log"
    Write-Green "  Failures : logs\failures.jsonl"
    Write-Green "  Stop all : .\stop.ps1"
    Write-Green "══════════════════════════════════════════════════════════════"
} else {
    Write-Red "══════════════════════════════════════════════════════════════"
    Write-Red "  Verdict did not fully start"
    Write-Red "  Backend ready : $backendReady"
    if (-not $NoFrontend) {
        Write-Red "  Frontend ready: $frontendReady"
    }
    Write-Red "  Check logs in : $LogDir"
    Write-Red "══════════════════════════════════════════════════════════════"
    exit 1
}

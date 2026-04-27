# Verdict — stop all services

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = "$ProjectRoot\logs"

function Write-Green  { param($msg) Write-Host $msg -ForegroundColor Green }
function Write-Yellow { param($msg) Write-Host $msg -ForegroundColor Yellow }

function Stop-PidFile {
    param([string]$Label, [string]$File)
    if (Test-Path $File) {
        $procId = (Get-Content $File).Trim()
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            Write-Green "✓ $Label stopped (PID $procId)"
        }
        Remove-Item $File -Force -ErrorAction SilentlyContinue
    }
}

# Kill any process listening on a given TCP port
function Stop-Port {
    param([int]$Port, [string]$Label)
    $hits = netstat -ano 2>$null | Select-String ":$Port\s.*LISTENING"
    foreach ($line in $hits) {
        $pid = ($line.Line.Trim() -split '\s+')[-1]
        if ($pid -match '^\d+$' -and [int]$pid -gt 0) {
            Stop-Process -Id ([int]$pid) -Force -ErrorAction SilentlyContinue
            Write-Green "✓ $Label on port $Port stopped (PID $pid)"
        }
    }
}

Write-Host ""
Write-Yellow "── Stopping Verdict services ───────────────────────────────────"

Stop-PidFile "Frontend" "$LogDir\frontend.pid"
Stop-PidFile "Worker"   "$LogDir\worker.pid"
Stop-PidFile "Backend"  "$LogDir\backend.pid"

# Kill by port in case child processes survived the PID-file kill
Stop-Port -Port 5173 -Label "Frontend"
Stop-Port -Port 8000 -Label "Backend"

# Kill named python/node processes that match our commands
Get-Process python, python3, node -ErrorAction SilentlyContinue | Where-Object {
    try {
        $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine
        $cmd -like "*uvicorn*app.backend.main*" -or $cmd -like "*app.backend.worker*"
    } catch { $false }
} | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    Write-Green "✓ Cleaned up stray process (PID $($_.Id))"
}

Write-Host ""
Write-Green "All services stopped."

# Verdict — stop all services

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = "$ProjectRoot\logs"

function Write-Green  { param($msg) Write-Host $msg -ForegroundColor Green }
function Write-Yellow { param($msg) Write-Host $msg -ForegroundColor Yellow }

function Stop-PidFile {
    param([string]$Label, [string]$File)
    if (Test-Path $File) {
        $pid = Get-Content $File
        $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-Process -Id $pid -Force
            Write-Green "✓ $Label stopped (PID $pid)"
        } else {
            Write-Yellow "  $Label was not running"
        }
        Remove-Item $File -Force
    } else {
        Write-Yellow "  No PID file for $Label"
    }
}

Write-Host ""
Write-Yellow "── Stopping Verdict services ───────────────────────────────────"
Stop-PidFile "Frontend" "$LogDir\frontend.pid"
Stop-PidFile "Worker"   "$LogDir\worker.pid"
Stop-PidFile "Backend"  "$LogDir\backend.pid"

# Clean up any stray processes
Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.MainWindowTitle -eq "" -and (
        ($_.CommandLine -like "*uvicorn*app.backend.main*") -or
        ($_.CommandLine -like "*app.backend.worker*")
    )
} | ForEach-Object {
    Stop-Process -Id $_.Id -Force
    Write-Green "✓ Cleaned up stray process (PID $($_.Id))"
}

Write-Host ""
Write-Green "All services stopped."

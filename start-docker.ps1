# Verdict - start all Docker services
# Usage:
#   .\start-docker.ps1
#   .\start-docker.ps1 -Build
#   .\start-docker.ps1 -WithOllama

param(
    [switch]$Build,
    [switch]$WithOllama,
    [switch]$Logs
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Green  { param($msg) Write-Host $msg -ForegroundColor Green }
function Write-Yellow { param($msg) Write-Host $msg -ForegroundColor Yellow }
function Write-Red    { param($msg) Write-Host $msg -ForegroundColor Red }

function Wait-ForHttp {
    param([string]$Url, [string]$Label, [int]$Retries = 60)
    while ($Retries -gt 0) {
        try {
            $null = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            Write-Green "[OK] $Label is reachable at $Url"
            return $true
        } catch {
            $Retries--
            Start-Sleep -Seconds 2
        }
    }
    Write-Red "[FAIL] $Label did not become reachable at $Url"
    return $false
}

Set-Location $ProjectRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Red "Docker was not found on PATH. Start Docker Desktop or install Docker, then rerun this script."
    exit 1
}

try {
    $null = docker compose version
} catch {
    Write-Red "'docker compose' is not available. Update Docker Desktop to a version with Compose v2."
    exit 1
}

if (-not (Test-Path "$ProjectRoot\.env")) {
    if (Test-Path "$ProjectRoot\app\backend\.env") {
        Copy-Item -LiteralPath "$ProjectRoot\app\backend\.env" -Destination "$ProjectRoot\.env"
        Write-Yellow "Created root .env from app\backend\.env for Docker Compose."
    } else {
        Write-Red "Missing .env. Create one at the project root or app\backend\.env before starting Docker."
        exit 1
    }
}

if ($WithOllama) {
    $env:DOCKER_OLLAMA_BASE_URL = "http://ollama:11434/v1"
    $composeArgs = @("compose", "--profile", "local-inference", "up", "-d")
} else {
    Remove-Item Env:\DOCKER_OLLAMA_BASE_URL -ErrorAction SilentlyContinue
    $composeArgs = @("compose", "up", "-d")
}

if ($Build) {
    $composeArgs += "--build"
}

Write-Host ""
Write-Yellow "-- Docker Compose ------------------------------------------------"
docker @composeArgs

Write-Host ""
Write-Yellow "-- Readiness -----------------------------------------------------"
$apiReady = Wait-ForHttp -Url "http://127.0.0.1:8000/api/health" -Label "API"
$frontendReady = Wait-ForHttp -Url "http://127.0.0.1:8080" -Label "Frontend"

if ($apiReady -and $frontendReady) {
    Write-Host ""
    Write-Green "=============================================================="
    Write-Green "  Verdict Docker stack is running"
    Write-Green "  Frontend : http://127.0.0.1:8080"
    Write-Green "  Backend  : http://127.0.0.1:8000"
    if ($WithOllama) {
        Write-Green "  Ollama   : http://127.0.0.1:11434"
    } else {
        Write-Green "  Ollama   : host.docker.internal:11434"
    }
    Write-Green "  Stop all : docker compose down"
    Write-Green "=============================================================="

    if ($Logs) {
        docker compose logs -f
    }
} else {
    Write-Host ""
    Write-Red "=============================================================="
    Write-Red "  Verdict Docker stack did not fully start"
    Write-Red "  API ready     : $apiReady"
    Write-Red "  Frontend ready: $frontendReady"
    Write-Red "=============================================================="
    docker compose ps
    docker compose logs --tail 80 api frontend worker postgres
    exit 1
}

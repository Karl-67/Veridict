#!/usr/bin/env bash
# Verdict — start all services
# Usage: bash start.sh [--no-frontend]
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"

mkdir -p "$LOG_DIR"

# ── helpers ──────────────────────────────────────────────────────────────────

green()  { echo -e "\033[32m$*\033[0m"; }
yellow() { echo -e "\033[33m$*\033[0m"; }
red()    { echo -e "\033[31m$*\033[0m"; }

wait_for_http() {
  local url=$1 label=$2 retries=30
  while ! curl -sf "$url" >/dev/null 2>&1; do
    retries=$((retries - 1))
    [[ $retries -le 0 ]] && { red "✗ $label did not come up at $url"; return 1; }
    sleep 1
  done
  green "✓ $label is up"
}

pick_python() {
  local candidates=(
    "$PROJECT_ROOT/app/backend/venv/bin/python3"
    "$PROJECT_ROOT/app/backend/venv/bin/python"
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
    "python3"
    "python"
  )

  for candidate in "${candidates[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if env -u VIRTUAL_ENV -u PYTHONHOME -u PYTHONPATH "$candidate" -c "import sqlalchemy, uvicorn" >/dev/null 2>&1; then
        echo "$candidate"
        return 0
      fi
    fi
  done

  red "✗ No Python with backend dependencies found. Install app/backend/requirements.txt first."
  return 1
}

resolve_pgdata() {
  if [[ -n "${PGDATA:-}" && -d "$PGDATA" ]]; then
    echo "$PGDATA"
    return 0
  fi

  local candidates=(
    "/opt/homebrew/var/postgresql@16"
    "/usr/local/var/postgresql@16"
    "/opt/homebrew/var/postgresql@17"
    "/usr/local/var/postgresql@17"
    "/opt/homebrew/var/postgres"
    "/usr/local/var/postgres"
  )

  for dir in "${candidates[@]}"; do
    [[ -d "$dir" ]] && { echo "$dir"; return 0; }
  done

  return 1
}

# ── 1. PostgreSQL ─────────────────────────────────────────────────────────────

echo ""
yellow "── PostgreSQL ──────────────────────────────────────────────────"
if pg_isready >/dev/null 2>&1; then
  green "✓ PostgreSQL already running"
else
  PGDATA_DIR="$(resolve_pgdata || true)"
  if [[ -z "${PGDATA_DIR:-}" ]]; then
    red "✗ Could not find a PostgreSQL data directory. Set PGDATA and rerun."
    exit 1
  fi

  if [[ -f "$PGDATA_DIR/postmaster.pid" ]] && ! lsof -iTCP:5432 -sTCP:LISTEN -n -P >/dev/null 2>&1; then
    yellow "  Removing stale PostgreSQL lock file..."
    rm -f "$PGDATA_DIR/postmaster.pid"
  fi

  yellow "  Starting PostgreSQL from $PGDATA_DIR..."
  pg_ctl -D "$PGDATA_DIR" start -l "$LOG_DIR/postgres.log" >/dev/null
  sleep 1
  if pg_isready >/dev/null 2>&1; then
    green "✓ PostgreSQL started"
  else
    red "✗ PostgreSQL did not start. See $LOG_DIR/postgres.log"
    exit 1
  fi
fi

createdb veridict >/dev/null 2>&1 || true

PYTHON_BIN="$(pick_python)"

# ── 2. Backend ───────────────────────────────────────────────────────────────

echo ""
yellow "── Backend (uvicorn :8000) ─────────────────────────────────────"
if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
  green "✓ Backend already running"
else
  env -u VIRTUAL_ENV -u PYTHONHOME -u PYTHONPATH "$PYTHON_BIN" -m uvicorn app.backend.main:app \
    --host 127.0.0.1 --port 8000 \
    --env-file app/backend/.env \
    >> "$LOG_DIR/backend.log" 2>&1 &
  BACKEND_PID=$!
  echo "$BACKEND_PID" > "$LOG_DIR/backend.pid"
  wait_for_http "http://localhost:8000/api/health" "Backend"
fi

# ── 3. Worker ────────────────────────────────────────────────────────────────

echo ""
yellow "── Worker ──────────────────────────────────────────────────────"
env -u VIRTUAL_ENV -u PYTHONHOME -u PYTHONPATH "$PYTHON_BIN" -m app.backend.worker >> "$LOG_DIR/worker.log" 2>&1 &
WORKER_PID=$!
echo "$WORKER_PID" > "$LOG_DIR/worker.pid"
green "✓ Worker started (PID $WORKER_PID)"

# ── 4. Frontend ──────────────────────────────────────────────────────────────

if [[ "${1:-}" != "--no-frontend" ]]; then
  echo ""
  yellow "── Frontend (Vite :5173) ───────────────────────────────────────"
  if curl -sf http://localhost:5173 >/dev/null 2>&1; then
    green "✓ Frontend already running"
  else
    (cd "$PROJECT_ROOT/app/frontend" && npm run dev >> "$LOG_DIR/frontend.log" 2>&1) &
    FRONTEND_PID=$!
    echo "$FRONTEND_PID" > "$LOG_DIR/frontend.pid"
    wait_for_http "http://localhost:5173" "Frontend"
  fi
fi

# ── summary ──────────────────────────────────────────────────────────────────

echo ""
green "══════════════════════════════════════════════════════════════"
green "  Verdict is running"
green "  Frontend : http://localhost:5173"
green "  Backend  : http://localhost:8000"
green "  Logs     : $LOG_DIR/"
green "  Stop all : bash stop.sh"
green "══════════════════════════════════════════════════════════════"

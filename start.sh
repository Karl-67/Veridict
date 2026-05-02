#!/usr/bin/env bash
# Verdict — start all services
# Usage: bash start.sh [--no-frontend]
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PGCTL="C:/Program Files/PostgreSQL/17/bin/pg_ctl"
PGDATA="C:/Program Files/PostgreSQL/17/data"
LOG_DIR="$PROJECT_ROOT/logs"

mkdir -p "$LOG_DIR"

# ── helpers ──────────────────────────────────────────────────────────────────

green()  { echo -e "\033[32m$*\033[0m"; }
yellow() { echo -e "\033[33m$*\033[0m"; }
red()    { echo -e "\033[31m$*\033[0m"; }

wait_for_port() {
  local port=$1 label=$2 retries=20
  while ! curl -sf "http://localhost:$port" >/dev/null 2>&1; do
    retries=$((retries - 1))
    [[ $retries -le 0 ]] && { red "✗ $label did not come up on :$port"; return 1; }
    sleep 1
  done
  green "✓ $label is up on :$port"
}

# ── 1. PostgreSQL ─────────────────────────────────────────────────────────────

echo ""
yellow "── PostgreSQL ──────────────────────────────────────────────────"
if "$PGCTL" status -D "$PGDATA" >/dev/null 2>&1; then
  green "✓ PostgreSQL already running"
else
  yellow "  Starting PostgreSQL..."
  "$PGCTL" start -D "$PGDATA" -l "$LOG_DIR/postgres.log"
  sleep 2
  green "✓ PostgreSQL started"
fi

# ── 2. Backend ───────────────────────────────────────────────────────────────

echo ""
yellow "── Backend (uvicorn :8000) ─────────────────────────────────────"
if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
  green "✓ Backend already running"
else
  uvicorn app.backend.main:app \
    --host 127.0.0.1 --port 8000 \
    --env-file app/backend/.env \
    >> "$LOG_DIR/backend.log" 2>&1 &
  BACKEND_PID=$!
  echo "$BACKEND_PID" > "$LOG_DIR/backend.pid"
  wait_for_port 8000 "Backend"
fi

# ── 3. Worker ────────────────────────────────────────────────────────────────

echo ""
yellow "── Worker ──────────────────────────────────────────────────────"
python -m app.backend.worker >> "$LOG_DIR/worker.log" 2>&1 &
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
    wait_for_port 5173 "Frontend"
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

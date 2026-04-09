#!/usr/bin/env bash
# Verdict — stop all services
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"

green()  { echo -e "\033[32m$*\033[0m"; }
yellow() { echo -e "\033[33m$*\033[0m"; }

kill_pid_file() {
  local label=$1 file=$2
  if [[ -f "$file" ]]; then
    local pid
    pid=$(cat "$file")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null && green "✓ $label stopped (PID $pid)"
    else
      yellow "  $label was not running"
    fi
    rm -f "$file"
  else
    yellow "  No PID file for $label"
  fi
}

echo ""
yellow "── Stopping Verdict services ───────────────────────────────────"
kill_pid_file "Frontend" "$LOG_DIR/frontend.pid"
kill_pid_file "Worker"   "$LOG_DIR/worker.pid"
kill_pid_file "Backend"  "$LOG_DIR/backend.pid"

# Also kill any stray uvicorn / worker processes on known ports
pkill -f "uvicorn app.backend.main" 2>/dev/null && green "✓ Cleaned up stray uvicorn" || true
pkill -f "app.backend.worker"       2>/dev/null && green "✓ Cleaned up stray worker"  || true

echo ""
green "All services stopped."

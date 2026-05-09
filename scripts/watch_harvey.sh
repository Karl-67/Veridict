#!/bin/bash
# Harvey llama-server watchdog.
# Polls :8000 (primary) and :8080 (secondary) every 30s.
# Dumps diagnostics and restarts the dead instance.
# Hard-stops after MAX_RESTARTS consecutive failures for each port.
# Log: /workspace/harvey_watchdog.log

LLAMA=/workspace/llama.cpp/build/bin/llama-server
HARVEY=/workspace/harvey_q4km.gguf
NO_THINK=/workspace/no_think.jinja
MAX_RESTARTS=5

TS() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[harvey-watchdog $(TS)] $*"; }

RESTART_COUNT_8000=0
RESTART_COUNT_8080=0

restart_harvey() {
  local port=$1 logfile=$2 restart_var=$3
  local count=${!restart_var}

  log "Harvey :$port unhealthy (restart #$((count + 1)) of $MAX_RESTARTS)."

  if (( count >= MAX_RESTARTS )); then
    log "FATAL: Harvey :$port has crashed $MAX_RESTARTS times in a row — NOT restarting."
    log "FATAL: Manual intervention required. Check $logfile and nvidia-smi."
    log "--- nvidia-smi ---"
    nvidia-smi || true
    log "------------------"
    return
  fi

  log "--- last 80 lines of $logfile ---"
  tail -n 80 "$logfile" || true
  log "--- nvidia-smi ---"
  nvidia-smi || true
  log "------------------"

  pkill -f "llama-server.*$port" 2>/dev/null || true
  sleep 3

  nohup "$LLAMA" \
    --model "$HARVEY" \
    --port "$port" \
    --host 0.0.0.0 \
    --ctx-size 32768 \
    --n-predict -1 \
    --chat-template-file "$NO_THINK" \
    >> "$logfile" 2>&1 &
  NEW_PID=$!
  log "Harvey :$port restarted (pid $NEW_PID). Waiting 90s for model load..."

  printf -v "$restart_var" '%d' $(( count + 1 ))
  sleep 90

  if ! kill -0 "$NEW_PID" 2>/dev/null; then
    log "ERROR: Harvey :$port pid $NEW_PID exited during 90s load window."
    tail -n 30 "$logfile" || true
  fi
}

while true; do
  sleep 30

  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    RESTART_COUNT_8000=0
  else
    restart_harvey 8000 /workspace/harvey_server.log RESTART_COUNT_8000
  fi

  if curl -sf http://localhost:8080/health >/dev/null 2>&1; then
    RESTART_COUNT_8080=0
  else
    restart_harvey 8080 /workspace/harvey_secondary_server.log RESTART_COUNT_8080
  fi
done

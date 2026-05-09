#!/bin/bash
# Kira llama-server watchdog.
# Polls :8002 every 30s. If Kira is down, dumps diagnostics then restarts it.
# Hard-stops after MAX_RESTARTS consecutive failures to prevent a perpetual loop.
# Log: /workspace/kira_watchdog.log

LLAMA=/workspace/llama.cpp/build/bin/llama-server
KIRA=/workspace/kira_q4km.gguf
NO_THINK=/workspace/no_think.jinja
MAX_RESTARTS=5

TS() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[kira-watchdog $(TS)] $*"; }

RESTART_COUNT=0

while true; do
  sleep 30

  if curl -sf http://localhost:8002/health >/dev/null 2>&1; then
    # Healthy — reset restart counter on sustained health
    RESTART_COUNT=0
    continue
  fi

  log "Kira unhealthy on :8002 (restart #$((RESTART_COUNT + 1)) of $MAX_RESTARTS)."

  if (( RESTART_COUNT >= MAX_RESTARTS )); then
    log "FATAL: Kira has crashed $MAX_RESTARTS times in a row — NOT restarting."
    log "FATAL: Manual intervention required. Check /workspace/kira_server.log and nvidia-smi."
    log "--- nvidia-smi ---"
    nvidia-smi || true
    log "------------------"
    exit 1
  fi

  log "--- last 80 lines of kira_server.log ---"
  tail -n 80 /workspace/kira_server.log || true
  log "--- nvidia-smi ---"
  nvidia-smi || true
  log "------------------"

  pkill -f "llama-server.*8002" 2>/dev/null || true
  sleep 3

  nohup "$LLAMA" \
    --model "$KIRA" \
    --port 8002 \
    --host 0.0.0.0 \
    --ctx-size 32768 \
    --n-predict -1 \
    --parallel 1 \
    --chat-template-file "$NO_THINK" \
    >> /workspace/kira_server.log 2>&1 &
  NEW_PID=$!
  log "Kira restarted (pid $NEW_PID). Waiting 90s for model load..."

  RESTART_COUNT=$(( RESTART_COUNT + 1 ))
  sleep 90

  if ! kill -0 "$NEW_PID" 2>/dev/null; then
    log "ERROR: Kira pid $NEW_PID exited during 90s load window."
    log "--- last 30 lines of kira_server.log ---"
    tail -n 30 /workspace/kira_server.log || true
  fi
done

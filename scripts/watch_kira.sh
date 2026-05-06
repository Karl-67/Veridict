#!/bin/bash
# Kira llama-server watchdog.
# Polls port 8002 every 30s. If Kira is down, kills any stale process and restarts it.
# Run via start_models.sh after initial startup; log goes to /workspace/kira_watchdog.log.

LLAMA=/workspace/llama.cpp/build/bin/llama-server
KIRA=/workspace/kira_q4km.gguf
NO_THINK=/workspace/no_think.jinja

while true; do
  if ! curl -sf http://localhost:8002/health >/dev/null 2>&1; then
    echo "[watchdog $(date '+%Y-%m-%d %H:%M:%S')] Kira unhealthy on :8002 — restarting"
    pkill -f "llama-server.*8002" 2>/dev/null || true
    sleep 3
    nohup "$LLAMA" \
      --model "$KIRA" \
      --port 8002 \
      --host 0.0.0.0 \
      --ctx-size 32768 \
      --n-predict -1 \
      --parallel 2 \
      --chat-template-file "$NO_THINK" \
      >> /workspace/kira_server.log 2>&1 &
    echo "[watchdog $(date '+%Y-%m-%d %H:%M:%S')] Kira restarted (pid $!), waiting 60s for load"
    sleep 60
  fi
  sleep 30
done

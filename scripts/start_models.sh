#!/bin/bash
# Start Harvey (primary :8000), Kira (:8002, proxied via nginx to :8001),
# and Harvey secondary (:8080) on RunPod using llama.cpp llama-server.
#
# Thinking is disabled at the server level via --chat-template-kwargs so it
# cannot be overridden per-request. This is the only reliable way to stop
# Gemma-4 from emitting reasoning tokens with llama.cpp.
#
# Usage (from /workspace after SSH'ing in):
#   nohup bash scripts/start_models.sh > /workspace/startup.log 2>&1 &
#   tail -f /workspace/startup.log

set -euo pipefail

LLAMA=/workspace/llama.cpp/build/bin/llama-server
HARVEY=/workspace/harvey_q4km.gguf
KIRA=/workspace/kira_q4km.gguf
NO_THINK='{"enable_thinking": false}'

wait_ready() {
  local port=$1 label=$2
  echo "[start_models] waiting for $label on :$port ..."
  for i in $(seq 1 120); do
    if curl -sf "http://localhost:$port/health" >/dev/null 2>&1; then
      echo "[start_models] $label is ready"
      return 0
    fi
    sleep 5
  done
  echo "[start_models] ERROR: $label did not become healthy on :$port after 10 min" >&2
  return 1
}

echo "[start_models] starting Harvey primary on :8000"
nohup "$LLAMA" \
  --model "$HARVEY" \
  --port 8000 \
  --host 0.0.0.0 \
  --ctx-size 8192 \
  --n-predict -1 \
  --chat-template-kwargs "$NO_THINK" \
  > /workspace/harvey_server.log 2>&1 &

wait_ready 8000 "Harvey primary"

echo "[start_models] starting Kira on :8002 (nginx proxies :8001 -> :8002)"
nohup "$LLAMA" \
  --model "$KIRA" \
  --port 8002 \
  --host 0.0.0.0 \
  --ctx-size 8192 \
  --n-predict -1 \
  --chat-template-kwargs "$NO_THINK" \
  > /workspace/kira_server.log 2>&1 &

wait_ready 8002 "Kira"

echo "[start_models] starting Harvey secondary on :8080"
nohup "$LLAMA" \
  --model "$HARVEY" \
  --port 8080 \
  --host 0.0.0.0 \
  --ctx-size 8192 \
  --n-predict -1 \
  --chat-template-kwargs "$NO_THINK" \
  > /workspace/harvey_secondary_server.log 2>&1 &

wait_ready 8080 "Harvey secondary"

echo "[start_models] all three servers are up and thinking is disabled"

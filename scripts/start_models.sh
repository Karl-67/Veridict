#!/bin/bash
# Start Harvey (primary :8000), Kira (:8002, proxied via nginx to :8001),
# and Harvey secondary (:8080) on RunPod using llama.cpp llama-server.
#
# Thinking is disabled by passing a custom jinja template (no_think.jinja)
# that never emits <think> tokens.
#
# Usage:
#   nohup bash /workspace/start_models.sh > /workspace/startup.log 2>&1 &
#   tail -f /workspace/startup.log

set -euo pipefail

LLAMA=/workspace/llama.cpp/build/bin/llama-server
HARVEY=/workspace/harvey_q4km.gguf
KIRA=/workspace/kira_q4km.gguf
NO_THINK=/workspace/no_think.jinja

TS() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[start_models $(TS)] $*"; }
die() { echo "[start_models $(TS)] FATAL: $*" >&2; pkill -f llama-server 2>/dev/null || true; exit 1; }

# ---------------------------------------------------------------------------
# Log rotation — truncate old logs so failures are easy to find
# ---------------------------------------------------------------------------
for f in /workspace/harvey_server.log /workspace/kira_server.log \
          /workspace/harvey_secondary_server.log \
          /workspace/kira_watchdog.log /workspace/harvey_watchdog.log; do
  > "$f" 2>/dev/null || true
done
log "Old logs truncated."

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
log "=== PRE-FLIGHT ==="

for path in "$LLAMA" "$HARVEY" "$KIRA" "$NO_THINK"; do
  if [[ ! -f "$path" ]]; then
    die "Required file not found: $path"
  fi
  log "  OK  $path"
done

log "--- nvidia-smi ---"
if ! nvidia-smi; then
  die "nvidia-smi failed — GPU driver not available on this pod."
fi
log "------------------"

# Check for stale llama-server processes holding target ports
for port in 8000 8001 8002 8080; do
  pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    log "WARNING: port $port already in use by PID(s) $pids — killing."
    kill -9 $pids 2>/dev/null || true
    sleep 1
  fi
done

# ---------------------------------------------------------------------------
# Nginx — route port 8001 → Kira on 8002
# ---------------------------------------------------------------------------
log "=== NGINX SETUP ==="
rm -f /etc/nginx/conf.d/kira_proxy.conf
sed -i "/listen 8001/,/proxy_pass/ s|proxy_pass http://localhost:[0-9]*;|proxy_pass http://localhost:8002;|" \
  /etc/nginx/nginx.conf
grep -q "proxy_read_timeout" /etc/nginx/nginx.conf || \
  sed -i "s|proxy_pass http://localhost:8002;|proxy_pass http://localhost:8002;\n        proxy_read_timeout 600s;\n        proxy_send_timeout 600s;\n        proxy_ignore_client_abort on;|" \
  /etc/nginx/nginx.conf

if ! nginx -t 2>&1; then
  die "nginx config test failed."
fi
nginx -s reload 2>/dev/null || nginx
log "nginx OK."

# ---------------------------------------------------------------------------
# PID-aware wait_ready
# Polls /health every 5s. If the process has exited, dumps its log immediately
# instead of waiting the full timeout. Exits 1 on any failure.
# ---------------------------------------------------------------------------
wait_ready() {
  local port=$1 label=$2 pid=$3 logfile=$4
  log "Waiting for $label on :$port (pid $pid)..."

  local i
  for i in $(seq 1 120); do
    # Fast-fail: process died
    if ! kill -0 "$pid" 2>/dev/null; then
      log "ERROR: $label (pid $pid) exited before becoming healthy!"
      log "--- last 80 lines of $logfile ---"
      tail -n 80 "$logfile" || true
      log "--- nvidia-smi at time of crash ---"
      nvidia-smi || true
      log "---------------------------------"
      return 1
    fi

    if curl -sf "http://localhost:$port/health" >/dev/null 2>&1; then
      log "$label ready after $((i * 5))s."
      return 0
    fi

    # Log GPU stats every 60s (every 12 iterations) while waiting
    if (( i % 12 == 0 )); then
      log "  [GPU @ ${i}x5s] $(nvidia-smi --query-gpu=memory.used,memory.free,temperature.gpu --format=csv,noheader,nounits 2>/dev/null || echo 'nvidia-smi unavailable')"
    fi

    sleep 5
  done

  log "ERROR: $label timed out after 600s."
  log "--- last 80 lines of $logfile ---"
  tail -n 80 "$logfile" || true
  log "--- nvidia-smi at timeout ---"
  nvidia-smi || true
  log "-----------------------------"
  return 1
}

# ---------------------------------------------------------------------------
# Launch servers sequentially — wait for each before starting the next.
# This makes it obvious which server failed and avoids GPU contention during load.
# ---------------------------------------------------------------------------
log "=== LAUNCHING SERVERS ==="

log "Starting Harvey primary on :8000..."
nohup "$LLAMA" \
  --model "$HARVEY" \
  --port 8000 --host 0.0.0.0 \
  --ctx-size 32768 --n-predict -1 \
  --chat-template-file "$NO_THINK" \
  > /workspace/harvey_server.log 2>&1 &
HARVEY_PID=$!
log "Harvey primary pid: $HARVEY_PID"

if ! wait_ready 8000 "Harvey primary" "$HARVEY_PID" /workspace/harvey_server.log; then
  die "Harvey primary failed to start. See log above."
fi

log "Starting Kira on :8002..."
nohup "$LLAMA" \
  --model "$KIRA" \
  --port 8002 --host 0.0.0.0 \
  --ctx-size 32768 --n-predict -1 \
  --parallel 1 \
  --chat-template-file "$NO_THINK" \
  > /workspace/kira_server.log 2>&1 &
KIRA_PID=$!
log "Kira pid: $KIRA_PID"

if ! wait_ready 8002 "Kira" "$KIRA_PID" /workspace/kira_server.log; then
  die "Kira failed to start. See log above."
fi

log "Starting Harvey secondary on :8080..."
nohup "$LLAMA" \
  --model "$HARVEY" \
  --port 8080 --host 0.0.0.0 \
  --ctx-size 32768 --n-predict -1 \
  --chat-template-file "$NO_THINK" \
  > /workspace/harvey_secondary_server.log 2>&1 &
HARVEY_SEC_PID=$!
log "Harvey secondary pid: $HARVEY_SEC_PID"

if ! wait_ready 8080 "Harvey secondary" "$HARVEY_SEC_PID" /workspace/harvey_secondary_server.log; then
  die "Harvey secondary failed to start. See log above."
fi

log "=== ALL SERVERS UP ==="
nvidia-smi --query-gpu=memory.used,memory.free,temperature.gpu --format=csv,noheader,nounits 2>/dev/null \
  | while read line; do log "  [GPU] $line"; done

# ---------------------------------------------------------------------------
# Start watchdogs
# ---------------------------------------------------------------------------
nohup bash /workspace/watch_kira.sh   > /workspace/kira_watchdog.log   2>&1 &
log "Kira watchdog started (pid $!)."

nohup bash /workspace/watch_harvey.sh > /workspace/harvey_watchdog.log 2>&1 &
log "Harvey watchdog started (pid $!)."

log "Startup complete."

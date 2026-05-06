#!/bin/bash
# Start Harvey (primary :8000), Kira (:8002, proxied via nginx to :8001),
# and Harvey secondary (:8080) on RunPod using llama.cpp llama-server.
#
# Thinking is disabled by passing a custom jinja template (no_think.jinja)
# that never emits <think> tokens. This overrides the GGUF-embedded template
# and works on all llama.cpp versions.
#
# Usage (from /workspace after SSH'ing in):
#   nohup bash /workspace/start_models.sh > /workspace/startup.log 2>&1 &
#   tail -f /workspace/startup.log

LLAMA=/workspace/llama.cpp/build/bin/llama-server
HARVEY=/workspace/harvey_q4km.gguf
KIRA=/workspace/kira_q4km.gguf
NO_THINK=/workspace/no_think.jinja

wait_ready() {
  local port=$1 label=$2
  echo "[start_models] waiting for $label on :$port ..."
  local i
  for i in {1..120}; do
    if curl -sf "http://localhost:$port/health" >/dev/null 2>&1; then
      echo "[start_models] $label ready"; return 0
    fi
    sleep 5
  done
  echo "ERROR: $label not healthy on :$port" >&2; return 1
}

# Route port 8001 → Kira on 8002 (RunPod nginx.conf defaults 8001 → 8000)
rm -f /etc/nginx/conf.d/kira_proxy.conf
sed -i "/listen 8001/,/proxy_pass/ s|proxy_pass http://localhost:[0-9]*;|proxy_pass http://localhost:8002;|" /etc/nginx/nginx.conf
# Extend nginx timeouts for port 8001 so Kira isn't killed by the 60s RunPod proxy timeout.
# proxy_ignore_client_abort keeps the backend connection alive even when the upstream proxy
# drops the frontend connection after its own 60s timeout.
grep -q "proxy_read_timeout" /etc/nginx/nginx.conf || \
  sed -i "s|proxy_pass http://localhost:8002;|proxy_pass http://localhost:8002;\n        proxy_read_timeout 600s;\n        proxy_send_timeout 600s;\n        proxy_ignore_client_abort on;|" /etc/nginx/nginx.conf
nginx -t && (nginx -s reload 2>/dev/null || nginx)

pkill -f llama-server 2>/dev/null || true
sleep 2

echo "[start_models] launching all three servers in parallel"
# All servers use 32768 ctx — prompts can exceed 9k tokens and output needs the remaining headroom.
nohup "$LLAMA" --model "$HARVEY" --port 8000 --host 0.0.0.0 --ctx-size 32768 --n-predict -1 --chat-template-file "$NO_THINK" > /workspace/harvey_server.log 2>&1 &
nohup "$LLAMA" --model "$KIRA"   --port 8002 --host 0.0.0.0 --ctx-size 32768 --n-predict -1 --parallel 1 --chat-template-file "$NO_THINK" > /workspace/kira_server.log 2>&1 &
nohup "$LLAMA" --model "$HARVEY" --port 8080 --host 0.0.0.0 --ctx-size 32768 --n-predict -1 --chat-template-file "$NO_THINK" > /workspace/harvey_secondary_server.log 2>&1 &

echo "[start_models] waiting for all three in parallel..."
wait_ready 8000 "Harvey primary" &
wait_ready 8002 "Kira"           &
wait_ready 8080 "Harvey secondary" &
wait

echo "[start_models] all servers up"

# Start Kira watchdog — auto-restarts Kira if health check fails (e.g. after OOM crash)
nohup bash /workspace/watch_kira.sh > /workspace/kira_watchdog.log 2>&1 &
echo "[start_models] Kira watchdog started (pid $!)"

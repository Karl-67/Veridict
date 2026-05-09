#!/bin/bash
set -e

# Auto-discover volume mount point
VOLUME=""
for candidate in "${VOLUME_PATH:-}" "/runpod-volume" "/workspace"; do
    if [ -n "$candidate" ] && [ -x "$candidate/llama.cpp/build/bin/llama-server" ]; then
        VOLUME="$candidate"
        break
    fi
done

if [ -z "$VOLUME" ]; then
    echo "ERROR: llama-server binary not found in /runpod-volume or /workspace"
    echo "Contents of /runpod-volume: $(ls /runpod-volume 2>/dev/null || echo 'not found')"
    echo "Contents of /workspace: $(ls /workspace 2>/dev/null || echo 'not found')"
    exit 1
fi

LLAMA="$VOLUME/llama.cpp/build/bin/llama-server"
NO_THINK="$VOLUME/no_think.jinja"

# Resolve model path — fix prefix if env var uses a different volume path
MODEL="${MODEL_PATH:-$VOLUME/harvey_q4km.gguf}"
if [ ! -f "$MODEL" ]; then
    FIXED=$(echo "$MODEL" | sed "s|/runpod-volume|$VOLUME|g; s|/workspace|$VOLUME|g")
    if [ -f "$FIXED" ]; then
        echo "MODEL_PATH=$MODEL not found; using $FIXED"
        MODEL="$FIXED"
    fi
fi

PORT="${PORT:-8000}"
PARALLEL="${PARALLEL:-4}"
CTX="${CTX_SIZE:-32768}"
GPU_LAYERS="${N_GPU_LAYERS:--1}"

echo "llama-server: volume=$VOLUME model=$MODEL port=$PORT parallel=$PARALLEL ctx=$CTX gpu_layers=$GPU_LAYERS"

if [ ! -f "$MODEL" ]; then
    echo "ERROR: model file not found: $MODEL"
    echo "Volume contents: $(ls $VOLUME 2>/dev/null)"
    exit 1
fi

ARGS=(
    --model "$MODEL"
    --port "$PORT"
    --host 0.0.0.0
    --ctx-size "$CTX"
    --n-predict -1
    --parallel "$PARALLEL"
    --n-gpu-layers "$GPU_LAYERS"
)

[ -f "$NO_THINK" ] && ARGS+=(--chat-template-file "$NO_THINK")

exec "$LLAMA" "${ARGS[@]}"

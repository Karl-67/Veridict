#!/bin/bash
# Build and push the RunPod serverless worker image.
# Run from the repo root:
#   bash scripts/serverless/build_push.sh <dockerhub-username>
#
# Creates one image — Harvey and Kira differ only in env vars set in RunPod UI.

set -euo pipefail

DOCKER_USER=${1:?"Usage: $0 <dockerhub-username>"}
IMAGE="$DOCKER_USER/verdict-llm-worker:latest"

echo "[build] Building $IMAGE ..."
docker build -t "$IMAGE" -f scripts/serverless/Dockerfile scripts/serverless/

echo "[build] Pushing $IMAGE ..."
docker push "$IMAGE"

echo ""
echo "Done. Image: $IMAGE"
echo ""
echo "Create two RunPod Serverless endpoints pointing to this image:"
echo ""
echo "  Harvey endpoint:"
echo "    GPU:        A100 SXM4 80GB (or similar)"
echo "    Min workers: 0  Max workers: 3"
echo "    Idle timeout: 20 min"
echo "    Network volume: mount your /workspace volume at /runpod-volume"
echo "    Env vars:"
echo "      MODEL_PATH=/runpod-volume/harvey_q4km.gguf"
echo "      PARALLEL=4"
echo ""
echo "  Kira endpoint:"
echo "    GPU:        A100 SXM4 80GB (or similar)"
echo "    Min workers: 0  Max workers: 2"
echo "    Idle timeout: 20 min"
echo "    Network volume: mount your /workspace volume at /runpod-volume"
echo "    Env vars:"
echo "      MODEL_PATH=/runpod-volume/kira_q4km.gguf"
echo "      PARALLEL=1"
echo ""
echo "After creating the endpoints, copy each endpoint ID and update k8s/configmap.yaml:"
echo "  VLLM_BASE_URL:  https://api.runpod.ai/v2/<harvey-endpoint-id>/openai/v1"
echo "  VLLM_BASE_URL_2: (leave blank — Harvey scales to 3 workers automatically)"
echo "  KIRA_MODEL_URL: https://api.runpod.ai/v2/<kira-endpoint-id>/openai/v1"
echo "  VLLM_API_KEY:   <your RunPod API key>"

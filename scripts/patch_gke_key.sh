#!/usr/bin/env bash
# Patch the live GKE cluster with the correct RunPod API key and restart pods.
# Run from Google Cloud Shell or any machine with gcloud + kubectl configured.
#
# Usage:
#   bash scripts/patch_gke_key.sh
#
# If kubectl is not yet pointed at the cluster, run first:
#   gcloud container clusters get-credentials verdict-gke \
#     --zone us-central1-a --project verdict-ai-prod

set -euo pipefail

NAMESPACE="verdict"
# Pass the key via environment: NEW_KEY=rpa_... bash scripts/patch_gke_key.sh
NEW_KEY="${NEW_KEY:?ERROR: set NEW_KEY environment variable to the RunPod API key}"

echo "==> Patching verdict-config configmap..."
kubectl patch configmap verdict-config -n "$NAMESPACE" \
  --type merge \
  -p "{\"data\":{\"VLLM_API_KEY\":\"${NEW_KEY}\"}}"

echo "==> Restarting API and worker deployments..."
kubectl rollout restart deployment/verdict-api deployment/verdict-worker -n "$NAMESPACE"

echo "==> Waiting for rollout..."
kubectl rollout status deployment/verdict-api -n "$NAMESPACE" --timeout=120s
kubectl rollout status deployment/verdict-worker -n "$NAMESPACE" --timeout=120s

echo "==> Done. New key is live."
echo "    Verify with: kubectl get configmap verdict-config -n verdict -o jsonpath='{.data.VLLM_API_KEY}'"

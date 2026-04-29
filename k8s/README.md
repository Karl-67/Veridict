# Verdict — AKS Deployment Guide

## Architecture

Two vLLM inference servers (Gemma 4 26B Q4/A4B quantized) back 8 logical agents:

| vLLM pod | Agents | Model |
|---|---|---|
| `verdict-vllm-base` | Harvey×3 + AdminMergeAgent | Base Gemma 4 26B |
| `verdict-vllm-kira` | KiraWorker×1 + KiraPanelReviewer×3 | Fine-tuned Kira (LoRA) |

## Prerequisites

- Azure CLI (`az`) installed and logged in
- `kubectl` installed
- Docker installed (for local builds)

---

## Step 1 — Create AKS Cluster and ACR

```bash
# Resource group and container registry
az group create --name verdict-rg --location eastus
az acr create --name verdictacr --resource-group verdict-rg --sku Basic

# AKS cluster with CPU system node pool (2 nodes)
az aks create \
  --resource-group verdict-rg \
  --name verdict-aks \
  --node-count 2 \
  --node-vm-size Standard_D4s_v3 \
  --attach-acr verdictacr \
  --generate-ssh-keys

# GPU node pool — 2 nodes, one per vLLM server (~$3.67/hr each)
az aks nodepool add \
  --resource-group verdict-rg \
  --cluster-name verdict-aks \
  --name gpupool \
  --node-count 2 \
  --node-vm-size Standard_NC24ads_A100_v4 \
  --node-taints sku=gpu:NoSchedule \
  --labels sku=gpu

# NVIDIA device plugin (required for GPU scheduling)
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.1/nvidia-device-plugin.yml

# Enable AGIC ingress addon (creates an Azure Application Gateway)
az aks enable-addons \
  --addons ingress-appgw \
  --resource-group verdict-rg \
  --name verdict-aks \
  --appgw-name verdict-appgw \
  --appgw-subnet-cidr "10.225.0.0/16"

# Get kubeconfig
az aks get-credentials --resource-group verdict-rg --name verdict-aks
```

---

## Step 2 — Create Secrets

Never commit real values. Create secrets directly via kubectl:

```bash
POSTGRES_PASS=$(openssl rand -hex 16)
SECRET_KEY=$(openssl rand -hex 32)
HF_TOKEN="hf_your_token_here"   # HuggingFace token with access to google/gemma-4-26B-A4B-it

kubectl create namespace verdict

kubectl create secret generic verdict-secrets -n verdict \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASS" \
  --from-literal=POSTGRES_DSN="postgresql://verdict:${POSTGRES_PASS}@verdict-postgres:5432/verdict" \
  --from-literal=SECRET_KEY="$SECRET_KEY" \
  --from-literal=HF_TOKEN="$HF_TOKEN" \
  --dry-run=client -o yaml | kubectl apply -f -
```

---

## Step 3 — Build and Push Images

```bash
# Log in to ACR
az acr login --name verdictacr

# Build and push all three images
docker build -f Dockerfile.api -t verdictacr.azurecr.io/verdict-api:latest .
docker push verdictacr.azurecr.io/verdict-api:latest

docker build -f Dockerfile.worker -t verdictacr.azurecr.io/verdict-worker:latest .
docker push verdictacr.azurecr.io/verdict-worker:latest

docker build -f Dockerfile.frontend -t verdictacr.azurecr.io/verdict-frontend:latest .
docker push verdictacr.azurecr.io/verdict-frontend:latest
```

After this step, CI/CD (`.github/workflows/build-push.yml`) handles future builds automatically on push to `main`.

---

## Step 4 — Deploy

```bash
# Apply all manifests (namespace, storage, postgres, vllm pods, api, worker, frontend, ingress)
kubectl apply -k k8s/

# Wait for postgres
kubectl rollout status statefulset/verdict-postgres -n verdict --timeout=3m

# Run database migrations
kubectl apply -f k8s/migration-job.yaml -n verdict
kubectl wait --for=condition=complete job/verdict-migrate -n verdict --timeout=2m

# vLLM pods take 5–10 minutes to download and load the model on first start
kubectl rollout status deployment/verdict-vllm-base -n verdict --timeout=15m
kubectl rollout status deployment/verdict-vllm-kira -n verdict --timeout=15m

# Application pods
kubectl rollout status deployment/verdict-api -n verdict --timeout=5m
kubectl rollout status deployment/verdict-worker -n verdict --timeout=3m
kubectl rollout status deployment/verdict-frontend -n verdict --timeout=3m
```

---

## Step 5 — Verify

```bash
# All pods should be Running
kubectl get pods -n verdict

# Check vLLM model loaded successfully
kubectl logs deployment/verdict-vllm-base -n verdict | grep -E "model loaded|INFO.*Starting"
kubectl logs deployment/verdict-vllm-kira -n verdict | grep -E "model loaded|INFO.*Starting"

# Health check via AGIC public IP
AGIC_IP=$(kubectl get ingress verdict -n verdict -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
curl http://$AGIC_IP/api/health
```

---

## Step 6 — Fine-Tune Kira (after baseline deployment is healthy)

```bash
# Set required env vars
export RUNPOD_HOST=your-runpod-ssh-host
export RUNPOD_SSH_KEY_PATH=~/.ssh/runpod_key
export HF_TOKEN=hf_your_token_here
export GDRIVE_FOLDER_ID=1FWhdw0eM2a3iyc_c3hpCCiWnFmBHvfgL

# Run the full pipeline: download data → export → train on RunPod → upload adapter → restart vllm-kira
python -m scripts.fine_tune.launch
```

After training completes, the script automatically:
1. Copies the LoRA adapter to the `verdict-vllm-kira` pod's `/mnt/kira-adapter/` PVC
2. Triggers a rolling restart: `kubectl rollout restart deployment/verdict-vllm-kira -n verdict`

Then uncomment `--enable-lora` and `--lora-modules kira=/mnt/kira-adapter` in `k8s/vllm-kira.yaml` and re-apply.

---

## Useful Commands

```bash
# Watch all pod status
kubectl get pods -n verdict -w

# Stream worker logs (pipeline execution)
kubectl logs -f deployment/verdict-worker -n verdict

# Stream vLLM logs
kubectl logs -f deployment/verdict-vllm-base -n verdict
kubectl logs -f deployment/verdict-vllm-kira -n verdict

# Restart a deployment
kubectl rollout restart deployment/verdict-api -n verdict

# Scale worker replicas
kubectl scale deployment/verdict-worker --replicas=2 -n verdict
```

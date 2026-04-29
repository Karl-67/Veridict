# Verdict — Azure Deployment Plan

## Overview

The deployment happens in two phases separated by the Kira fine-tuning run.

| Phase | When | What gets deployed |
|---|---|---|
| **Phase 1** | Now | AKS cluster, ACR, all app infrastructure, vLLM pods dormant (0 replicas) |
| **Phase 2** | After fine-tuning completes | GPU node pool, vLLM pods scaled up, LoRA adapter loaded |

---

## Phase 1 — Deploy Now (No GPU Required)

### 1.1 Create the Azure infrastructure

Run once from any terminal with `az` installed and logged in.

```bash
# Resource group and container registry
az group create --name verdict-rg --location eastus
az acr create --name verdictacr --resource-group verdict-rg --sku Basic

# AKS cluster — CPU nodes only (no GPU yet)
az aks create \
  --resource-group verdict-rg \
  --name verdict-aks \
  --node-count 2 \
  --node-vm-size Standard_D4s_v3 \
  --attach-acr verdictacr \
  --generate-ssh-keys

# Pull kubeconfig into your local kubectl
az aks get-credentials --resource-group verdict-rg --name verdict-aks
```

### 1.2 Create the namespace and secrets

```bash
kubectl create namespace verdict

POSTGRES_PASS=$(openssl rand -hex 16)
SECRET_KEY=$(openssl rand -hex 32)

kubectl create secret generic verdict-secrets -n verdict \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASS" \
  --from-literal=POSTGRES_DSN="postgresql://verdict:${POSTGRES_PASS}@verdict-postgres:5432/verdict" \
  --from-literal=SECRET_KEY="$SECRET_KEY" \
  --from-literal=HF_TOKEN="placeholder-set-after-fine-tuning"
```

> Save `$POSTGRES_PASS` somewhere safe — you'll need it if you ever recreate the secret.

### 1.3 Build and push Docker images to ACR

```bash
az acr login --name verdictacr

docker build -f Dockerfile.api     -t verdictacr.azurecr.io/verdict-api:latest .
docker build -f Dockerfile.worker  -t verdictacr.azurecr.io/verdict-worker:latest .
docker build -f Dockerfile.frontend -t verdictacr.azurecr.io/verdict-frontend:latest .

docker push verdictacr.azurecr.io/verdict-api:latest
docker push verdictacr.azurecr.io/verdict-worker:latest
docker push verdictacr.azurecr.io/verdict-frontend:latest
```

### 1.4 Deploy all manifests

```bash
# Apply the full kustomization (postgres, api, worker, frontend, ingress, vLLM manifests)
kubectl apply -k k8s/

# Immediately scale vLLM pods to 0 — no GPU nodes exist yet, nothing to schedule on
kubectl scale deployment/verdict-vllm-base --replicas=0 -n verdict
kubectl scale deployment/verdict-vllm-kira --replicas=0 -n verdict
```

### 1.5 Run database migrations

```bash
kubectl apply -f k8s/migration-job.yaml -n verdict
kubectl wait --for=condition=complete job/verdict-migrate -n verdict --timeout=3m
```

### 1.6 Verify Phase 1

```bash
kubectl get pods -n verdict
```

Expected output — all Running except vLLM (0 replicas):

```
verdict-postgres-0        1/1   Running
verdict-api-xxx           1/1   Running   (×2)
verdict-worker-xxx        1/1   Running
verdict-frontend-xxx      1/1   Running   (×2)
```

The vLLM deployments exist in the cluster (`kubectl get deployments -n verdict`) but have no pods. This is correct — they are maintained and ready to scale up, just dormant.

---

## Between Phase 1 and Phase 2 — What Is Running

| Component | Status | Notes |
|---|---|---|
| PostgreSQL | Running | Stores runs, findings, users |
| Backend API | Running | All routes available, health endpoint live |
| Worker | Running | Pipeline executes but LLM calls will fail until vLLM is up |
| Frontend | Running | UI accessible via ingress IP |
| `verdict-vllm-base` | **Dormant (0 replicas)** | Harvey + Admin agents — no GPU node yet |
| `verdict-vllm-kira` | **Dormant (0 replicas)** | Kira agents — waiting for fine-tuned weights |

> The worker will error on LLM stages while vLLM is dormant. This is expected. Set `MAX_STAGE_RETRIES` high enough (default is 3) so runs don't permanently fail before Phase 2.

---

## Running Fine-Tuning (Prerequisite for Phase 2)

Fine-tuning runs on RunPod via the existing pipeline. Do this before Phase 2.

```bash
# Set environment variables
export RUNPOD_HOST=your-runpod-ssh-host
export RUNPOD_SSH_KEY_PATH=~/.ssh/runpod_key
export HF_TOKEN=hf_your_real_token_here
export GDRIVE_FOLDER_ID=1FWhdw0eM2a3iyc_c3hpCCiWnFmBHvfgL

# Run full pipeline:
# 1. Download labeled data from Google Drive
# 2. Export to fine-tuning format
# 3. Baseline evaluation
# 4–6. SSH to RunPod, upload data, train, download LoRA adapter
# 7. After-training evaluation
# 8. Upload adapter to K8s PVC + restart vllm-kira
python -m scripts.fine_tune.launch
```

The script ends by automatically copying the LoRA adapter into the Kira vLLM pod's PVC. You still need to uncomment the `--enable-lora` flags in `k8s/vllm-kira.yaml` (see Phase 2 Step 2.3) before the pod will actually load the adapter.

---

## Phase 2 — Activate vLLM After Fine-Tuning

### 2.1 Add the GPU node pool

```bash
az aks nodepool add \
  --resource-group verdict-rg \
  --cluster-name verdict-aks \
  --name gpupool \
  --node-count 2 \
  --node-vm-size Standard_NC24ads_A100_v4 \
  --node-taints sku=gpu:NoSchedule \
  --labels sku=gpu

# Install NVIDIA device plugin
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.1/nvidia-device-plugin.yml

# Confirm GPU nodes are Ready
kubectl get nodes -l sku=gpu
```

### 2.2 Update the HF token in the secret

```bash
kubectl create secret generic verdict-secrets -n verdict \
  --from-literal=HF_TOKEN="hf_your_real_token_here" \
  --dry-run=client -o yaml | kubectl apply -f -
```

> The HuggingFace token needs access to `google/gemma-4-26B-A4B-it` (gated model). Request access at huggingface.co/google/gemma-4-26B-A4B-it if not already granted.

### 2.3 Enable the LoRA adapter in the Kira manifest

Edit `k8s/vllm-kira.yaml` and uncomment the three lines under the args section:

```yaml
# Before (lines are commented out):
            # - --enable-lora
            # - --lora-modules
            # - kira=/mnt/kira-adapter

# After (uncommented):
            - --enable-lora
            - --lora-modules
            - kira=/mnt/kira-adapter
```

Then re-apply:

```bash
kubectl apply -f k8s/vllm-kira.yaml
```

### 2.4 Scale up vLLM pods

```bash
kubectl scale deployment/verdict-vllm-base --replicas=1 -n verdict
kubectl scale deployment/verdict-vllm-kira --replicas=1 -n verdict
```

### 2.5 Wait for model loading (5–10 minutes on first start)

The pods download the model from HuggingFace on first boot (~30–50 GB). Subsequent restarts use the PVC cache and are faster (~2–3 minutes).

```bash
# Watch pod status
kubectl get pods -n verdict -w

# Stream logs to confirm model loaded
kubectl logs -f deployment/verdict-vllm-base -n verdict
kubectl logs -f deployment/verdict-vllm-kira -n verdict
```

Look for a line containing `Application startup complete` or `model loaded` in the vLLM logs.

### 2.6 Verify the full stack

```bash
# All pods Running
kubectl get pods -n verdict

# Health check
AGIC_IP=$(kubectl get ingress verdict -n verdict -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
curl http://$AGIC_IP/api/health

# Confirm vLLM endpoints respond
kubectl exec -it deployment/verdict-api -n verdict -- \
  curl http://verdict-vllm-base:8000/health

kubectl exec -it deployment/verdict-api -n verdict -- \
  curl http://verdict-vllm-kira:8000/health
```

### 2.7 Enable AGIC ingress (if not already done in Phase 1)

```bash
az aks enable-addons \
  --addons ingress-appgw \
  --resource-group verdict-rg \
  --name verdict-aks \
  --appgw-name verdict-appgw \
  --appgw-subnet-cidr "10.225.0.0/16"
```

---

## Ongoing Maintenance

### Push a code update

```bash
# Rebuild and push changed image(s)
docker build -f Dockerfile.api -t verdictacr.azurecr.io/verdict-api:latest .
docker push verdictacr.azurecr.io/verdict-api:latest

# Roll out the update
kubectl rollout restart deployment/verdict-api -n verdict
kubectl rollout status deployment/verdict-api -n verdict
```

Or just push to `main` — the GitHub Actions workflow (`.github/workflows/build-push.yml`) handles build, push, and deploy automatically.

### Re-train Kira and reload the adapter

```bash
python -m scripts.fine_tune.launch --skip-gdrive   # if data is already local

# The script automatically:
# 1. Trains on RunPod
# 2. Downloads the new adapter
# 3. Copies it to the vllm-kira pod PVC
# 4. Triggers: kubectl rollout restart deployment/verdict-vllm-kira -n verdict
```

### Stop the GPU nodes to save cost (when not testing)

```bash
# Scale GPU node pool to 0 (deallocates VMs, stops billing)
az aks nodepool scale \
  --resource-group verdict-rg \
  --cluster-name verdict-aks \
  --name gpupool \
  --node-count 0

# vLLM pods will go Pending (no nodes) — scale them down to avoid noise
kubectl scale deployment/verdict-vllm-base --replicas=0 -n verdict
kubectl scale deployment/verdict-vllm-kira --replicas=0 -n verdict
```

### Resume GPU nodes

```bash
az aks nodepool scale \
  --resource-group verdict-rg --cluster-name verdict-aks \
  --name gpupool --node-count 2

kubectl scale deployment/verdict-vllm-base --replicas=1 -n verdict
kubectl scale deployment/verdict-vllm-kira --replicas=1 -n verdict
```

---

## Quick Reference

| Command | Purpose |
|---|---|
| `kubectl get pods -n verdict` | Check all pod status |
| `kubectl logs -f deployment/verdict-worker -n verdict` | Stream pipeline execution logs |
| `kubectl logs -f deployment/verdict-vllm-base -n verdict` | Stream Harvey model server logs |
| `kubectl logs -f deployment/verdict-vllm-kira -n verdict` | Stream Kira model server logs |
| `kubectl rollout restart deployment/verdict-api -n verdict` | Restart API after config change |
| `kubectl get ingress verdict -n verdict` | Get public IP |
| `az aks nodepool scale ... --node-count 0` | Stop GPU billing |

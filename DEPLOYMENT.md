# Veridict — GCP Deployment Guide

## Overview

Veridict runs on **Google Kubernetes Engine (GKE)** in region `europe-west1` (Belgium).
Infrastructure is managed with **Terraform** (`infra/gcp/`).
Container images are stored in **Google Artifact Registry** (GAR).

Phase 1 provisions the cluster and deploys all services except GPU workloads.
Phase 2 (deferred) scales up the GPU node pool for vLLM fine-tuning and serving.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| `gcloud` CLI | latest | https://cloud.google.com/sdk/docs/install |
| `terraform` | >= 1.6 | https://developer.hashicorp.com/terraform/install |
| `docker` | latest | https://docs.docker.com/get-docker/ |
| `kubectl` | latest | `gcloud components install kubectl` |

Authenticate gcloud before running the scripts:

```powershell
gcloud auth login
gcloud auth application-default login
```

---

## Phase 1 — First-time Deployment

### Step 1 — Provision infrastructure

```powershell
.\deploy_gcp_phase1.ps1
```

This script:
1. Creates GCP project `veridict-dev` (skips if it already exists).
2. Pauses for you to enable billing in the GCP console.
3. Runs `terraform init && terraform apply -var-file=dev.tfvars` in `infra/gcp/`.
4. Saves Terraform outputs to `%TEMP%\veridict_gcp_outputs.json`.

Terraform provisions:
- GKE Standard cluster `veridict-dev-gke` (2× e2-standard-4 system nodes)
- GPU node pool (0 nodes initially, autoscales 0–4 when needed)
- Artifact Registry repository `veridict`
- GCS buckets: `veridict-dev-datasets`, `veridict-dev-artifacts`, `veridict-dev-rag`
- Workload Identity SA with roles: `artifactregistry.reader`, `storage.objectAdmin`, `secretmanager.secretAccessor`

### Step 2 — Build images and deploy

```powershell
.\deploy_gcp_phase1_images.ps1
```

This script:
1. Reads Terraform outputs from `%TEMP%\veridict_gcp_outputs.json`.
2. Configures Docker for GAR authentication.
3. Builds and pushes `verdict-api`, `verdict-worker`, `verdict-frontend`.
4. Patches k8s manifests with the real project ID.
5. Gets GKE credentials and applies all manifests.
6. Installs nginx-ingress controller.
7. Prompts for secret values (POSTGRES_PASSWORD, SECRET_KEY, HF_TOKEN).
8. Scales vLLM deployments to 0 replicas (no GPU cost in dev).
9. Runs the database migration job.
10. Prints the Ingress external IP.

### Verify deployment

```bash
kubectl get pods -n verdict
curl http://INGRESS_IP/api/health   # expected: {"status":"ok"}
```

---

## Continuous Deployment (GitHub Actions)

`.github/workflows/build-push.yml` runs on every push to `main`:
1. Builds and pushes images to GAR.
2. Runs the eval gate (`scripts/eval_gate.py`).
3. Applies updated manifests to GKE.
4. Runs migrations, waits for rollouts, smoke-tests `/api/health`.
5. Auto-rolls back if the smoke test fails.

### Required GitHub Secrets / Variables

| Key | Type | Value |
|-----|------|-------|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Secret | OIDC provider resource name — see `docs/GCP_GITHUB_OIDC.md` |
| `GCP_SERVICE_ACCOUNT` | Secret | `github-actions@veridict-dev.iam.gserviceaccount.com` |
| `MLFLOW_TRACKING_URI` | Secret | MLflow server URL |
| `EVAL_ENDPOINT` | Secret | Staging vLLM endpoint for eval gate |
| `EVAL_MODEL` | Secret | Model name for eval gate |
| `GCP_PROJECT_ID` | Variable | `veridict-dev` |
| `GAR_REGISTRY` | Variable | `europe-west1-docker.pkg.dev/veridict-dev/veridict` |
| `GKE_CLUSTER_NAME` | Variable | `veridict-dev-gke` |
| `GKE_REGION` | Variable | `europe-west1` |
| `DEPLOY_VLLM` | Variable | `false` (set `true` to enable GPU blue-green) |

See `docs/GCP_GITHUB_OIDC.md` for instructions on setting up Workload Identity Federation.

---

## Emergency Rollback

Trigger the **Emergency Rollback** workflow from GitHub Actions → `rollback.yml`.

Select `scope`:
- `api` — rolls back only the API deployment
- `worker` — rolls back only the worker
- `all` — rolls back api, worker, frontend, and vllm

Or run locally:
```bash
python scripts/rollback.py --scope all
```

---

## Phase 2 — GPU / Fine-tuning (deferred)

When ready to run vLLM inference or fine-tuning:

1. Scale the GPU node pool:
   ```bash
   gcloud container clusters resize veridict-dev-gke \
     --node-pool gpu \
     --num-nodes 1 \
     --region europe-west1
   ```

2. Set `DEPLOY_VLLM=true` in GitHub repository variables.

3. Scale vLLM deployments:
   ```bash
   kubectl scale deployment verdict-vllm-base -n verdict --replicas=1
   kubectl scale deployment verdict-vllm-kira -n verdict --replicas=1
   ```

GPU node pool uses `g2-standard-4` (NVIDIA L4, 24 GB VRAM) with taint `sku=gpu:NoSchedule`.

---

## Terraform Operations

```bash
cd infra/gcp

# Preview changes
terraform plan -var-file=dev.tfvars

# Apply changes
terraform apply -var-file=dev.tfvars

# Destroy (careful — deletes all GCP resources)
terraform destroy -var-file=dev.tfvars
```

> **Azure files** are archived in `infra/azure/` for reference.

---

## Architecture

```
Internet
    │
    ▼
nginx-ingress LoadBalancer (GKE)
    │
    ├── /api  ──► verdict-api (FastAPI, 2 replicas)
    │                │
    │                ├── PostgreSQL (StatefulSet)
    │                ├── verdict-worker (pipeline stages 1–12)
    │                └── PVC: documents, rag, fine-tune-output
    │
    └── /     ──► verdict-frontend (React/Nginx, 2 replicas)

GCS Buckets:
  veridict-dev-datasets   — training data
  veridict-dev-artifacts  — MLflow artifacts
  veridict-dev-rag        — vector store snapshots

GAR: europe-west1-docker.pkg.dev/veridict-dev/veridict/
```

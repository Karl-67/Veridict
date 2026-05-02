# Veridict — Step-by-Step Deployment Guide

## Priority: Get the pipeline running end-to-end

This guide focuses on deploying the **main pipeline** (API + Worker + Frontend + Postgres)
so you can test all 12 stages. vLLM / GPU nodes are kept at 0 replicas until fine-tuned
weights are ready.

---

## Prerequisites checklist

- [ ] `gcloud` CLI installed and authenticated (`gcloud auth login`)
- [ ] `docker` installed and running
- [ ] `kubectl` installed (`gcloud components install kubectl gke-gcloud-auth-plugin`)
- [ ] GCP project `veridict` exists with billing linked
- [ ] You have a HuggingFace token (https://huggingface.co/settings/tokens) — needed for model downloads later

---

## Phase 1 — Provision infrastructure (~15 min, run once)

```powershell
.\deploy_gcp_phase1.ps1
```

When prompted for billing, press **Enter** (already linked).

**What gets created:**
- GKE cluster `veridict-dev-gke` (2× e2-standard-4 nodes, europe-west1)
- Artifact Registry repo `veridict`
- GCS buckets: `veridict-dev-datasets`, `veridict-dev-artifacts`, `veridict-dev-rag`
- IAM service account with correct roles

**Verify:**
```powershell
gcloud container clusters list --project=veridict
# Should show veridict-dev-gke with STATUS=RUNNING
```

---

## Phase 2 — Build images and deploy (~10 min)

```powershell
.\deploy_gcp_phase1_images.ps1
```

**You will be prompted for 3 secrets:**

| Secret | What to enter |
|--------|---------------|
| `POSTGRES_PASSWORD` | Any strong password, e.g. `veridict-pg-2026` |
| `SECRET_KEY` | Random string — generate one with the command below |
| `HF_TOKEN` | Your HuggingFace token (or press Enter to skip for now) |

Generate a SECRET_KEY:
```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

**What gets deployed:**
- Builds `verdict-api`, `verdict-worker`, `verdict-frontend` Docker images
- Pushes them to GAR
- Deploys everything to GKE via `kubectl apply -k k8s/`
- Installs nginx-ingress controller
- Runs Alembic database migrations
- Prints the public Ingress IP

---

## Phase 3 — Verify the pipeline is running

### Check all pods are healthy
```powershell
kubectl get pods -n verdict
```

Expected output:
```
NAME                                READY   STATUS    RESTARTS
verdict-api-xxx                     1/1     Running   0
verdict-api-xxx                     1/1     Running   0
verdict-worker-xxx                  1/1     Running   0
verdict-frontend-xxx                1/1     Running   0
verdict-frontend-xxx                1/1     Running   0
verdict-postgres-0                  1/1     Running   0
```

vLLM pods will show `0/1` or not exist — that's expected (GPU nodes are off).

### Check API health
```powershell
# Get the ingress IP
kubectl get ingress verdict -n verdict

# Hit the health endpoint
curl http://INGRESS_IP/api/health
# Expected: {"status":"ok"}
```

### Open the frontend
Navigate to `http://INGRESS_IP/` in your browser.

---

## Testing the pipeline (all 12 stages)

1. Log in to the frontend and create an organisation + workspace
2. Upload a PDF contract
3. Watch the pipeline progress in the UI:
   - `create_run` → `ingest_pdf` → `parse_ocr_normalize` → `clause_index`
   - → `harvey_context_load` → `kira_context_load`
   - → `harvey_review_block` → `kira_review_block` → `admin_merge`
   - → `final_review_block` → `awaiting_human_review` → `finalized`

> **Note:** Stages `harvey_review_block` and `kira_review_block` call the vLLM endpoint.
> With vLLM at 0 replicas these stages will stall. To test the full pipeline
> you need to either point the worker at a remote LLM (see section below)
> or scale up a GPU node.

### Quick test with a remote LLM (no GPU cost)

Update `k8s/configmap.yaml` to point to OpenRouter or any OpenAI-compatible endpoint:

```yaml
LLM_PROVIDER: "openai"
VLLM_BASE_URL: "https://openrouter.ai/api/v1"
VLLM_BASE_MODEL: "google/gemma-2-9b-it:free"
KIRA_MODEL_URL: "https://openrouter.ai/api/v1"
KIRA_MODEL_NAME: "google/gemma-2-9b-it:free"
```

Then add your API key to the secrets:
```powershell
kubectl create secret generic verdict-secrets -n verdict \
  --from-literal=OPENAI_API_KEY=your_openrouter_key \
  --dry-run=client -o yaml | kubectl apply -f -
```

Then restart the worker:
```powershell
kubectl rollout restart deployment/verdict-worker -n verdict
```

---

## Loading the Kira fine-tuned weights (nothingsometimes/kira-gemma4-adapter)

The Kira model is a **LoRA adapter** on top of `google/gemma-4-26B-A4B-it`.
The `k8s/vllm-kira.yaml` manifest is already configured to load it directly
from HuggingFace at pod startup — no manual download needed.

### What's already configured in vllm-kira.yaml

```yaml
args:
  - --model
  - google/gemma-4-26B-A4B-it        # base model (downloaded from HF)
  - --enable-lora
  - --lora-modules
  - kira=nothingsometimes/kira-gemma4-adapter   # your adapter (downloaded from HF)
```

vLLM fetches both the base model and the adapter from HuggingFace on first boot,
caches them on the PVC (`verdict-vllm-kira-cache`, 60 Gi SSD), and serves them
merged at the `kira` route.

### To activate Kira (requires GPU node)

**Step 1 — Make sure HF_TOKEN secret is set**
```powershell
kubectl create secret generic verdict-secrets -n verdict `
  --from-literal=HF_TOKEN=hf_YOUR_TOKEN_HERE `
  --dry-run=client -o yaml | kubectl apply -f -
```

Get your token at: https://huggingface.co/settings/tokens
The repo `nothingsometimes/kira-gemma4-adapter` must be accessible with that token
(if it's private) or no token is needed (if public).

**Step 2 — Scale up a GPU node**
```powershell
gcloud container node-pools create gpu `
    --cluster=veridict-dev-gke `
    --region=europe-west1 `
    --machine-type=g2-standard-4 `
    --disk-size=200 `
    --num-nodes=1 `
    --project=veridict
```

This takes ~5 min. The node has an NVIDIA L4 GPU (24 GB VRAM).

**Step 3 — Scale up the Kira vLLM pod**
```powershell
kubectl scale deployment verdict-vllm-kira-blue -n verdict --replicas=1
```

**Step 4 — Watch it start (first boot downloads ~50 GB, takes 10-20 min)**
```powershell
kubectl logs -f deployment/verdict-vllm-kira-blue -n verdict
# Wait for: "Uvicorn running on http://0.0.0.0:8000"
```

**Step 5 — Verify the adapter is loaded**
```powershell
# Port-forward and check models endpoint
kubectl port-forward service/verdict-vllm-kira 8888:8000 -n verdict &
curl http://localhost:8888/v1/models
# Should list "kira" as an available model
```

### To stop Kira and save GPU credits
```powershell
kubectl scale deployment verdict-vllm-kira-blue -n verdict --replicas=0

# Delete the GPU node pool entirely if done for the day
gcloud container node-pools delete gpu `
    --cluster=veridict-dev-gke `
    --region=europe-west1 `
    --project=veridict --quiet
```

---

## Stopping everything (save credits)

```powershell
# Delete the cluster (stops all VM charges)
gcloud container clusters delete veridict-dev-gke --region=europe-west1 --project=veridict --quiet

# Optionally delete buckets (frees storage cost)
gcloud storage rm -r gs://veridict-dev-datasets
gcloud storage rm -r gs://veridict-dev-artifacts
gcloud storage rm -r gs://veridict-dev-rag

# Optionally delete GAR (frees storage cost)
gcloud artifacts repositories delete veridict --location=europe-west1 --project=veridict --quiet
```

To restart: rerun `.\deploy_gcp_phase1.ps1` then `.\deploy_gcp_phase1_images.ps1`.

---

## Troubleshooting

| Problem | Command |
|---------|---------|
| Pod stuck in `Pending` | `kubectl describe pod POD_NAME -n verdict` |
| Pod in `CrashLoopBackOff` | `kubectl logs POD_NAME -n verdict --previous` |
| API not responding | `kubectl logs deployment/verdict-api -n verdict` |
| Worker stuck on a stage | `kubectl logs deployment/verdict-worker -n verdict` |
| Migration failed | `kubectl logs job/verdict-migrate -n verdict` |
| Ingress IP not assigned | `kubectl describe ingress verdict -n verdict` |

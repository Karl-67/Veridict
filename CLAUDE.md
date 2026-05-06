# Project Context (Claude Code)

Managed by the AI Orchestrator. Claude Code reads this file on startup.

## Project Architecture
See `orchestrator.md` in this directory for a full project summary, folder structure, architecture overview, and notes on what each component does.

## Memory

All persistent memory lives in `.orchestrator/`:
- `bugs.md` · `decisions.md` · `key_facts.md` · `issues.md` · `memory.yaml`

Check these before making architectural changes or debugging known issues.
Run `/init` to have Qwen populate them from the codebase if they are empty.

**Current State (updated 2026-05-03)**

Phase 1 pipeline fully implemented and verified end-to-end (all 12 stages). Full auth system, multi-tenant org/workspace model, contract reader with PDF highlights, collaborative comments, and admin panel are all live.

**Startup (local dev):**
```bash
python3 -m uvicorn app.backend.main:app --host 0.0.0.0 --port 8000 --reload
python3 -m app.backend.worker
cd app/frontend && npm run dev
```
Requires Ollama running locally.

**LLM Provider:** Local Ollama (`LLM_PROVIDER=ollama`). Change only `OLLAMA_MODEL` in `.env` to swap models — no code changes needed.

**What is running (local):**
- Backend: FastAPI on port 8000
- Worker: `python3 -m app.backend.worker` (processes all 12 stages)
- Frontend: React/Vite on port 5173
- PostgreSQL on localhost:5432, database `veridict`
- Ollama: local inference at `http://localhost:11434/v1`

**All 12 stages verified:** create_run → ingest_pdf → parse_ocr_normalize → clause_index → harvey_context_load → kira_context_load → harvey_review_block → kira_review_block → admin_merge → final_review_block → awaiting_human_review → finalized

**What remains open:**
- Export Report — not yet implemented (button is no-op)
- Email sending for invites — manual link copy only
- Schedule Partner Review — postponed
- Parser extraction confidence not yet propagated (RISK-001)
- Automated corpus ETL from parquet files (RISK-002) — corpus seeded manually
- Small-model quality ceiling (RISK-008) — llama3.2:3b works but larger models recommended for production

---

## GCP Production Deployment (updated 2026-05-06)

Infrastructure fully migrated from Azure (ACR + AKS) to GCP (GAR + GKE). LLM inference moved off-cluster to RunPod.

**Web app (production):** `http://136.110.220.144`
**Pipeline failures log:** `http://136.110.220.144/api/admin/pipeline-failures/unauthenticated` (requires `DEBUG_OPEN_LOGS=true` in configmap)

**GCP project:** `verdict-ai-prod`  
**Registry:** `us-central1-docker.pkg.dev/verdict-ai-prod/verdict/`  
**Cluster:** `verdict-gke` — GKE Standard, single node `e2-standard-2`, zone `us-central1-a`  
**Namespace:** `verdict`

**LLM inference:** RunPod via llama.cpp + GGUF models (NOT vLLM)
- Pod ID: `8lq123pws2o7do`
- SSH (direct TCP): `ssh root@213.173.105.5 -p 30196 -i ~/.ssh/id_ed25519` — key passphrase: `student1`
- SSH (RunPod gateway): `ssh 8lq123pws2o7do-64410ec3@ssh.runpod.io -i ~/.ssh/id_ed25519`
- Harvey endpoint: `https://8lq123pws2o7do-8000.proxy.runpod.net/v1`
- Kira endpoint: `https://8lq123pws2o7do-8001.proxy.runpod.net/v1` (nginx 8001→8002)
- Harvey secondary: `https://8lq123pws2o7do-8080.proxy.runpod.net/v1`
- Models: `/workspace/harvey_q4km.gguf` (Harvey), `/workspace/kira_q4km.gguf` (Kira) — Q4_K_M GGUF
- llama.cpp binary: `/workspace/llama.cpp/build/bin/llama-server`
- Kira training data still at: `/workspace/kira_gemma4_training/`

**To start all servers on RunPod:**
```bash
# SSH in via gateway (direct TCP may refuse banner exchange)
ssh 8lq123pws2o7do-64410ec3@ssh.runpod.io -i ~/.ssh/id_ed25519

# Run startup script (starts Harvey primary, waits, then Kira, then Harvey secondary)
nohup bash /workspace/start_models.sh > /workspace/startup.log 2>&1 &

# Monitor progress (~5-10 min per model)
tail -f /workspace/startup.log
tail -f /workspace/harvey_server.log
tail -f /workspace/kira_server.log

# Test
curl https://8lq123pws2o7do-8000.proxy.runpod.net/v1/models
```

**RunPod environment notes:**
- No tmux or screen — use `nohup ... &`
- `/workspace` is persistent across restarts; root fs is ephemeral
- Direct TCP SSH (port 26619) may fail with banner exchange error — use gateway instead

**CI/CD — `.github/workflows/build-push.yml`:**
- 3 parallel build jobs: `build-api`, `build-worker`, `build-frontend` (each with its own GHA cache scope)
- `deploy` job starts only when all 3 succeed
- Auth: `credentials_json: ${{ secrets.GCP_SA_KEY }}` (SA key, not WIF)
- Migration step polls every 5s for job success/failure and prints pod logs on failure
- Migration job: `backoffLimit: 0`, `restartPolicy: Never` — fails fast, no silent retries
- Rollout timeouts: API 10m, Worker 5m, Frontend 5m
- Smoke test: port-forward to `verdict-api:8000`, curl `/api/health`, expect HTTP 200
- Auto-rollback runs `scripts/rollback.py` on smoke test failure

**Required GitHub Secrets:**
```
GCP_SA_KEY          — full JSON of verdict-cicd service account key
GKE_CLUSTER         — verdict-gke
GKE_REGION          — us-central1-a
GCP_PROJECT         — verdict-ai-prod
MLFLOW_TRACKING_URI — (optional, for eval-gate)
```

**Key k8s files:**
- `k8s/configmap.yaml` — RunPod URLs, CORS `["*"]` (update to LB IP once known)
- `k8s/api.yaml` — GCP image, NodePort service, BackendConfig annotation, HPA min:1 max:3
- `k8s/ingress.yaml` — GCE ingress + BackendConfig (300s timeout) for `/api/*` and `/*`
- `k8s/storage.yaml` — `standard-rwo` StorageClass (GCE pd-standard)
- `k8s/migration-job.yaml` — runs `alembic upgrade head` before each deploy
- `k8s/kustomization.yaml` — vllm-base and vllm-kira removed (RunPod replaces them)

**First deploy checklist:**
1. `kubectl apply -f k8s/secret.yaml` (populate real values first, never commit)
2. `kubectl apply -k k8s/`
3. `kubectl get ingress verdict -n verdict` — wait ~3 min for LB IP
4. Update `CORS_ORIGINS` in configmap to `["http://<LB_IP>"]` and rollout restart api

**Known GHA cache behaviour:** First run after a new branch/commit builds cold (~15 min per image). Subsequent runs with cache hits take ~1 min per image. The 3 parallel jobs mean wall-clock build time equals the slowest single image.

## Kira fine-tuning (updated 2026-05-03)

QLoRA SFT for the Kira reviewer agent — training is **complete**. Adapter is saved and backed up on RunPod. Full step-by-step in `KIRA_QLORA_RUNBOOK.md`.

**Target model:** `unsloth/gemma-4-26B-A4B-it` (26B-param MoE, 4B active, 128 experts, multimodal).

**Training was done on:** RTX A5000, 24 GB VRAM. **Inference now runs on:** A100 SXM4 80 GB (same pod, upgraded).

**Adapter location (production):** `/workspace/kira_gemma4_training/kira_adapter/`  
**Backup:** `/workspace/backups/kira_gemma4_20260430/`  
**Training data:** `/workspace/kira_gemma4_training/data/` (22858 / 5327 / 5273 train/val/test examples)  
**Training log:** `/workspace/kira_gemma4_training/train.log`

**SSH from Windows (Claude Code automation):** use `SSH_ASKPASS_REQUIRE=force` with a helper script that echoes the password. See runbook §"SSH from Windows git-bash".

**Non-obvious gotchas (training — kept for reference if retraining):**
- `bnb_4bit_use_double_quant=True` triggers a meta-tensor crash in `QuantState.as_dict` during accelerate dispatch — must be `False`.
- transformers 5.5/5.7 passes `_is_hf_initialized` to `Params4bit.__new__`, which bnb 0.49 rejects — monkey-patch `Params4bit.__new__` to drop the kwarg.
- `device_map={"": 0}` OOMs at ~33% of weight load. Use `max_memory={0: "20GiB", "cpu": "300GiB"}` to stream through CPU.
- `llm_int8_enable_fp32_cpu_offload=True` is required in `BitsAndBytesConfig` once any module spills to CPU.
- Workspace quota is 90 GB. Keep venvs in `/workspace`, not `/home` (which is ephemeral on this pod config).

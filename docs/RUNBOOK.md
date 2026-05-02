# Runbook

## Local API

1. Create `app/backend/.env` with `POSTGRES_DSN`.
2. Install backend dependencies: `pip install -r app/backend/requirements.txt`.
3. Run migrations: `alembic upgrade head` from `app/backend`.
4. Start API: `uvicorn app.backend.main:app --reload`.
5. Start worker: `python -m app.backend.worker`.

## Frontend

```bash
cd app/frontend
npm ci
npm run dev
```

## Docker

```bash
docker compose up --build
```

## RAG Walkthrough

1. Sign in as org admin or workspace admin.
2. Open Admin → RAG.
3. Upload a policy, playbook, or reference contract PDF.
4. Watch ingestion status until terminal state.
5. Start a contract run scoped to the same policy family and jurisdiction.

## Metrics

Prometheus metrics are exposed at `/metrics`.

## Evaluation

Run `python scripts/eval_model_registry.py` to check model registry readiness. Run `python scripts/eval_finetune_vs_baseline.py` after endpoints and datasets are configured.

## MLflow

Set `MLFLOW_TRACKING_URI` before running training or evaluation to log new additive runs. The scripts intentionally create fresh runs and ignore an inherited `MLFLOW_RUN_ID`, so previously completed/manual MLflow runs are not modified.

Useful optional variables:

```bash
export MLFLOW_TRACKING_URI=https://your-mlflow-host
export MLFLOW_EXPERIMENT=veridict-training
export HF_ADAPTER_REPO=your-org/kira-adapter
```

The Hugging Face adapter repo is logged as metadata only; training scripts do not overwrite manually uploaded weights.

## DeepSeek Distillation

For Kira DeepSeek teacher-labeling, use `DEEPSEEK_MODEL=deepseek-v4-pro` and keep the API key in the repo-root `.env` file. See `docs/DEEPSEEK_DISTILLATION.md`.

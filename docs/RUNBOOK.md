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

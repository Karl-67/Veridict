# Current Limitations

## Impossible Now

- Fine-tuned Gemma 26B weights are not present in this repository.
- Superiority claims over baselines cannot be made until the evaluation workflow has real endpoints and datasets.

## Blocked by Missing Weights

- `gemma_26b_finetuned` is listed in `configs/models.yaml` as disabled with `N/A - weights pending`.

## Blocked by Missing Secrets/Cloud

- Hosted inference, Modal/Vercel, and production database URLs require secrets outside the repo.
- RAG ingestion works against uploaded customer PDFs only after a tenant corpus exists.

## Deferred by Scope

- bge-reranker integration is a no-op hook.
- pgvector ANN search is scaffolded; text search keeps citation grounding until tuning lands.

## Implemented but Not Benchmark-Proven

- Harvey RAG, Kira problem finding, Admin consensus, human review, and output generation are represented in code but need full integration tests against Postgres.

# Implementation Changelog

## Pipeline Topology

- Run topology removes `final_review_block`; legacy rows remain read-only. Extent: partial.

## RAG

- Added RAG ORM usage, ingestion service, retrieval service, admin API, and frontend panel. Extent: partial.
- pgvector vector search is scaffolded with grounded text retrieval fallback. Extent: partial.

## Evaluation

- Added model registry and evaluation metric scaffolding. Extent: partial.

## Deployment

- Added API, worker, frontend Dockerfiles and compose stack. Extent: partial.

## Observability

- Added Prometheus metric declarations and `/metrics` mount. Extent: partial.

## Tests

- Added contract tests as executable smoke coverage where external services are unavailable. Extent: partial.

## Docs

- Added architecture, API, RAG, deployment, evaluation, limitations, and runbook docs. Extent: full for current scaffold.

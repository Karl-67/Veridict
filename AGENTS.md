# Project Context (Codex)

Managed by the AI Orchestrator. Codex CLI reads this file on startup.

## Project Architecture
See `orchestrator.md` in this directory for a full project summary, folder structure, architecture overview, and notes on what each component does.

## Memory

All persistent memory lives in `.orchestrator/`:
- `bugs.md` · `decisions.md` · `key_facts.md` · `issues.md` · `memory.yaml`

Check these before making architectural changes or debugging known issues.
Run `/init` to have Qwen populate them from the codebase if they are empty.

**Current State**

The active implementation is now the run-based architecture scaffold:

- Product architecture is `input/upload → Harvey RAG → Kira finds problems → Admin consensus → output`.
- Active topology is `create_run → ingest_pdf → parse_ocr_normalize → clause_index → harvey_context_load → kira_review_block → admin_merge → awaiting_human_review → finalized`.
- `final_review_block`, `harvey_review_block`, and `kira_context_load` are legacy-only. New runs must never enqueue them, and workers skip them.
- Harvey is the RAG/evidence retrieval lane only.
- Kira is the problem-finding lane.
- Admin is merge-only. There are no admin/final reviewer agents in the active topology.
- Harvey-only RAG is enforced at the service layer: Harvey can query pgvector RAG, Kira must use structured compliance corpora only.
- Evidence schema is active: findings carry `contract_evidence[]` and `rag_citations[]`; Harvey citations must resolve to the run retrieval trace, and Kira findings must not contain RAG citations.
- Tenant/workspace identity for RAG and run APIs should be derived from JWT membership, never request body.
- Architecture docs live under `docs/`; update them after architecture changes.

**Known Follow-Up Work**

- The new RAG ingestion/retrieval modules are functional scaffolding; pgvector ANN search and reranking still need production tuning.
- Docker, CI, and evaluation workflows are present but need a real secrets/cloud setup before production use.
- Full database migration execution was not run in this session.
- Vite build can be blocked in the Codex sandbox by `esbuild` child process permissions; use `npx tsc -b` for type checking here.

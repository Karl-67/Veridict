# Key Facts

Automatically maintained by AI Orchestrator and the project-memory skill.

---

## Current Implementation State (updated 2026-04-09)

Phase 1 fully implemented and verified end-to-end. All 12 stages run clean. Full pipeline verified on 2026-04-09 with local Ollama (llama3.2:latest) — PDF upload flows through to `awaiting_human_review`, human review panel works, verdict card renders.

**LLM Provider:** Ollama (local). `LLM_PROVIDER=ollama` in `.env`. Change only `OLLAMA_MODEL` to swap models — no code changes needed. Provider class reuses `OpenRouterProvider` via OpenAI-compatible API at `http://localhost:11434/v1`.

---

## Startup

Use `.\start.ps1` from project root (PowerShell). Handles PostgreSQL, backend, worker, frontend in order.
`.\stop.ps1` to stop all. Logs: `logs/backend.log`, `logs/worker.log`, `logs/frontend.log`, `logs/failures.jsonl`.

Ollama must be running separately (`ollama serve` or Ollama Desktop).

---

## .env (app/backend/.env)

```
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3.2:latest          ← only this line changes per teammate

OPENROUTER_API_KEY=sk-or-v1-...      ← kept as cloud fallback (set LLM_PROVIDER=openrouter)
OPENROUTER_MODEL=openai/gpt-oss-120b:free
GEMINI_API_KEY=
GEMINI_MODEL_NAME=gemini-2.0-flash-lite
POSTGRES_DSN=postgresql://postgres:admin@localhost:5432/verdict
WORKER_LEASE_DURATION_SECONDS=60
MAX_STAGE_RETRIES=10
DOCUMENT_STORAGE_PATH=./storage/documents
ALLOWED_FRONTEND_ORIGINS=["http://localhost:5173"]
ENABLE_OCR_FALLBACK=True
PARSER_VERSION=docling-1
```

---

## Locked Stage Graph (state_machine.py)

| #  | Stage Name              | Agent / Service                                              |
|----|-------------------------|--------------------------------------------------------------|
| 1  | `create_run`            | inline                                                       |
| 2  | `ingest_pdf`            | validates PDF on disk                                        |
| 3  | `parse_ocr_normalize`   | `parse_pdf_to_canonical_document` (pdfplumber + OCR)        |
| 4  | `clause_index`          | `build_clause_index`                                         |
| 5  | `harvey_context_load`   | `resolve_policy_lineage` + `load_prior_policy_versions`      |
| 6  | `kira_context_load`     | `resolve_applicable_corpora`                                 |
| 7  | `harvey_review_block`   | 3× HarveyReviewerAgent + votes + HarveyValidatorAgent        |
| 8  | `kira_review_block`     | 3× KiraReviewerAgent + votes + KiraValidatorAgent            |
| 9  | `admin_merge`           | AdminMergeAgent                                              |
| 10 | `final_review_block`    | 3× FinalReviewerAgent + votes + AgreementCheckAgent          |
| 11 | `awaiting_human_review` | human gate — POST /api/runs/{id}/human-review required       |
| 12 | `finalized`             | `finalize_run_if_approved`                                   |

Multi-round stages (harvey/kira/final_review_block) create new `stage_executions` rows per round. `_stage_output()` orders by `round_number DESC` and prefers rows with `validated_output` key.

---

## Run States

`created → processing → awaiting_human_review → finalized`
`blocked` / `failed` are terminal error states. `human_rejected` closes run with no verdict.

---

## Backend API Contract

| Method | Path                             | Description                               |
|--------|----------------------------------|-------------------------------------------|
| GET    | `/api/health`                    | Health check                              |
| POST   | `/api/runs`                      | Create run, returns `run_id`              |
| GET    | `/api/runs/{run_id}`             | Full run detail with stage statuses       |
| GET    | `/api/runs/{run_id}/events`      | SSE stream of `RunEvent` objects          |
| GET    | `/api/runs/{run_id}/events/list` | Paginated persisted events                |
| POST   | `/api/runs/{run_id}/human-review`| Submit human review (edit/approve/reject) |
| GET    | `/api/failures`                  | Last 50 entries from logs/failures.jsonl  |

---

## DB Tables

`runs`, `stage_executions` (not `run_stages`), `parsed_clauses`, `findings`, `evidence`, `policy_versions`, `compliance_corpora`, `run_events`, `human_reviews`

---

## Key Lookup Keys

- Harvey lineage: `tenant_id + policy_family_id + version_number`
- Kira corpus: `tenant_id, corpus_type, jurisdiction, regime, effective_date`
- Seed in DB: demo-tenant/default/v1 (policy) and US/general (compliance corpus)

---

## Small-Model Coercion Layer

All LLM output that feeds Pydantic models passes through coercion helpers before validation:
- `_normalize_finding_item()` — coerces `issue_type`, `severity`, `exploitability`, `business_impact`, `recommendation`
- `_normalize_vote_raw()` — clamps `correctness_score` (handles 0-10 and 0-100 scales), filters `supported_reviewer_indexes` to 1-3, ensures `accepted_finding_keys` is a list
- `_parse_json_response()` — tries `json_repair.repair_json()` before raising on malformed JSON

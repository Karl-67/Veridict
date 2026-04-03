# Architectural Decisions

Automatically maintained by AI Orchestrator and the project-memory skill.
Tracks key design decisions using Architectural Decision Records (ADRs).

---

## ADR-001: Gemini as Phase-1 LLM Provider

**Status:** Accepted  
**Shared dependency:** `gemini-provider-boundary`, `phase-1-architecture-spec`

**Context:**  
The system requires a capable LLM for structured contract review, clause flagging, and compliance analysis. A production-grade provider is needed for phase 1 before local fine-tuned models are ready.

**Decision:**  
Use Google Gemini (via `google-genai`) as the sole LLM provider for phase 1. All LLM calls are routed through `GeminiProvider` in `app/backend/providers/google_provider.py`, which implements the `StructuredLLMProvider` interface.

**Consequences:**  
- Gemini owns transport, structured-output schema binding, retry/backoff, and raw response capture.  
- Role agents (reviewer, validator, admin) own prompts and result interpretation — they never call Gemini directly.  
- This boundary is the migration seam for swapping in local models later (see ADR-005).

---

## ADR-002: Docling as the Canonical PDF Parser

**Status:** Accepted  
**Shared dependency:** `docling-canonical-parser`, `phase-1-architecture-spec`

**Context:**  
Contract PDFs vary widely in layout and quality. A robust parser that can produce structured, normalized clause-level output with bounding boxes and confidence scores is required for reliable downstream analysis.

**Decision:**  
Use Docling as the primary PDF parser with OCR fallback. The canonical document format produced by `parse_pdf_to_canonical_document()` in `app/backend/services/parser.py` includes: document hash, parser version, clause UID, page number, bounding box, normalized text, and extraction confidence.

**Consequences:**  
- All downstream agents consume the canonical clause index, never raw PDF bytes.  
- OCR fallback ensures scanned contracts are handled.  
- `ParsedClauseRecord` in `app/backend/db/models.py` persists the canonical output for replayability.

---

## ADR-003: Postgres as System of Record

**Status:** Accepted  
**Shared dependency:** `postgres-stage-queue`, `phase-1-architecture-spec`

**Context:**  
The system executes multi-stage pipelines with retries, lease semantics, and human approval gates. An in-memory or file-based store is insufficient for durability, concurrency, and audit requirements.

**Decision:**  
Use Postgres (via SQLAlchemy) as the sole system of record for all runs, stage executions, findings, evidence anchors, events, and human review actions. Stage claiming uses row-level locking for idempotent worker semantics.

**Consequences:**  
- `app/backend/db/models.py` defines all ORM tables.  
- `app/backend/db/session.py` manages engine and session factory.  
- Alembic manages schema migrations.  
- The worker in `app/backend/worker.py` polls Postgres; no external queue is needed in phase 1.

---

## ADR-004: Mandatory Human Approval Before Run Finalization

**Status:** Accepted  
**Shared dependency:** `human-review-gate`, `phase-1-architecture-spec`

**Context:**  
Contract review has legal consequences. Fully automated verdicts without human oversight are unacceptable for the target use case.

**Decision:**  
Every run must pass through a mandatory human approval gate before `run_finalized` is emitted. The state machine blocks at `awaiting_human_review` and only advances via `submit_human_review()` + `finalize_run_if_approved()` in `app/backend/services/run_service.py`. Rejection resets the run to a disputable state.

**Consequences:**  
- `HumanReviewRecord` in `app/backend/db/models.py` captures edit provenance and approval decision.  
- `HumanReviewPanel` in the frontend exposes per-finding edit and approve/reject actions.  
- The SSE event stream emits `awaiting_human_review`, `human_edited`, `human_rejected`, and `human_approved` events (see `sse-run-events`).

---

## ADR-005: Provider Abstraction as Migration Seam for Local Fine-Tuned Agents

**Status:** Accepted  
**Shared dependency:** `gemini-provider-boundary`, `phase-1-architecture-spec`

**Context:**  
The long-term goal is to replace Gemini with locally hosted, domain-fine-tuned models (e.g., fine-tuned on CUAD/LEDGAR corpora in `data/`). This must not require rewriting role agents or orchestration logic.

**Decision:**  
All LLM calls are mediated by the `StructuredLLMProvider` abstract interface in `app/backend/providers/base.py`. `GeminiProvider` is the phase-1 implementation. Future local providers (e.g., a fine-tuned LLaMA or Mistral model) implement the same interface and are injected via `Settings` in `app/backend/core/config.py` without touching agent or orchestration code.

**Consequences:**  
- Agents receive a provider instance via dependency injection; they never import `google-genai` directly.  
- `generate_structured_output(prompt, response_schema)` is the sole contract between agents and providers.  
- Fine-tuning pipeline against CUAD/LEDGAR data (already in `data/`) is a future workstream — no code changes needed in phase 1 to prepare for it.

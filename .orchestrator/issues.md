# Issues / Work Log

Automatically maintained by AI Orchestrator and the project-memory skill.
Tracks completed tasks, their outcomes, and key notes.

---

## Open Implementation Risks

### RISK-001 — Parser confidence not propagated to downstream agents
**Dependency:** `docling-canonical-parser`
**Status:** Open
**Detail:** `app/backend/routes/contracts.py` currently uses `pdfplumber` with no confidence scoring. The target architecture requires Docling-first parsing that emits per-clause extraction confidence. Downstream reviewer and validator agents must gate on this confidence (e.g., skip or flag low-confidence clauses rather than hallucinating analysis). Until this is wired, the pipeline may silently produce findings on malformed extractions.
**Acceptance checkpoint:** `parse_pdf_to_canonical_document` returns `extraction_confidence` per clause; `build_clause_index` filters or marks clauses below threshold; state machine checks confidence before dispatching reviewer stage.

---

### RISK-002 — Corpus governance ingestion has no owner or ingestion pipeline
**Dependency:** `policy-lineage-and-corpora`
**Status:** Open
**Detail:** `load_internal_playbook_rules` and `load_external_compliance_rules` in `app/backend/services/compliance_repository.py` are sibling contracts not yet implemented. The `data/atticus/` and `data/legal_clauses/` parquet files exist from EDA but there is no ETL path from those files into the `ComplianceCorpusRecord` DB table. Corpus version, jurisdiction, regime, and effective-date metadata are undefined.
**Acceptance checkpoint:** At least one corpus type (internal playbook) is loadable via `resolve_applicable_corpora`; records exist in `ComplianceCorpusRecord` with version, jurisdiction, and effective-date populated; the parquet → DB ingestion script is documented and repeatable.

---

### RISK-003 — Schema version migration ownership is unassigned
**Dependency:** `postgres-stage-queue`
**Status:** Open
**Detail:** The initial Alembic migration (`0001_initial_architecture.py`) covering `RunRecord`, `StageExecutionRecord`, `FindingRecord`, `EvidenceRecord`, `ParsedClauseRecord`, `PolicyVersionRecord`, `ComplianceCorpusRecord`, `RunEventRecord`, and `HumanReviewRecord` does not yet exist. No one owns the migration authoring or the review process for future schema changes. Without this, `get_engine` and `get_session_factory` in `app/backend/db/session.py` cannot be wired to a real database.
**Acceptance checkpoint:** `alembic upgrade head` succeeds against a clean Postgres instance; all DB model tables are created; `alembic downgrade base` is reversible; ownership of future migrations is noted in `decisions.md`.

---

### RISK-004 — Human approval gate is not enforced; runs can finalize without it
**Dependency:** `human-review-gate`
**Status:** Critical / Blocking
**Detail:** The current `app/backend/routes/contracts.py` returns a `ReviewResult` directly with no approval workflow. The architecture mandates that no run transitions to `run_finalized` without a `human_approved` event. `finalize_run_if_approved` in `run_service.py` must check for this event before writing the final verdict. The frontend `HumanReviewPanel` component does not yet exist.
**Acceptance checkpoint:** `submit_human_review` with action `rejected` blocks finalization; `submit_human_review` with action `approved` allows `finalize_run_if_approved` to proceed; the `run_finalized` event is only emitted after approval; the `HumanReviewPanel` component surfaces approve/reject/edit actions.

---

### RISK-005 — Provider abstraction layer not yet wrapping the Gemini call
**Dependency:** `gemini-provider-boundary`
**Status:** Open
**Detail:** `app/backend/agents/reviewer.py` calls `google.genai` directly with no `StructuredLLMProvider` abstraction. The architecture requires that all LLM transport, structured-output schema binding, retry/backoff, and raw response capture live in `GeminiProvider`, not in the agent. Until this boundary exists, swapping Gemini for a local fine-tuned model later will require rewriting agent logic rather than swapping the provider.
**Acceptance checkpoint:** `reviewer.py` calls `generate_structured_output` on a `StructuredLLMProvider` instance; `GeminiProvider` handles retries and raw response logging; `InvalidSchemaOutputError`, `RateLimitError`, and `NonRetryableProviderError` are raised and handled at the orchestration layer.

---

### RISK-006 — SSE event stream is not persisted; pipeline state is ephemeral
**Dependency:** `sse-run-events`
**Status:** Open
**Detail:** There is no `RunEventRecord` table or `append_run_event` / `stream_run_events` implementation. The frontend `PipelineTracker` component currently receives a static `PipelineStatus` snapshot; it has no mechanism to subscribe to live stage updates. If the worker crashes mid-run, all progress is lost.
**Acceptance checkpoint:** `append_run_event` writes to `RunEventRecord`; `stream_run_events` yields events from `last_event_id`; the frontend connects via SSE and `PipelineTracker` animates transitions as events arrive.

---

### RISK-007 — Validator and admin agents are not implemented
**Dependency:** `run-state-contract`, `gemini-provider-boundary`
**Status:** Open
**Detail:** `HarveyValidatorAgent`, `KiraValidatorAgent`, `AdminMergeAgent`, `AgreementCheckAgent`, and `AdminDeltaInstructionBuilder` are sibling contracts with no implementation files yet. The current pipeline simulates all stages as immediately `done` in `contracts.py` without running them.
**Acceptance checkpoint:** Each agent class exists, accepts a `StructuredLLMProvider`, and returns typed output conforming to `run-state-contract`; the state machine dispatches each stage in order; findings from Harvey and Kira validators are merged by `AdminMergeAgent` before the human review gate.

---

## Acceptance Checkpoints — Phase 1 Exit Criteria

| # | Checkpoint | Blocking? |
|---|-----------|-----------|
| A | `parse_pdf_to_canonical_document` returns confidence-scored clauses (RISK-001) | Yes |
| B | At least one compliance corpus is loadable from DB (RISK-002) | Yes |
| C | Alembic migration 0001 runs clean on Postgres (RISK-003) | Yes |
| D | No run can reach `run_finalized` without a `human_approved` event (RISK-004) | Yes — Critical |
| E | All LLM calls routed through `StructuredLLMProvider` / `GeminiProvider` (RISK-005) | Yes |
| F | SSE event stream persists and replays from `last_event_id` (RISK-006) | No — Nice to have for Phase 1 |
| G | All five agent classes instantiable and wired to state machine (RISK-007) | Yes |

---

## Completed Tasks

_(none yet — populated as work is merged)_

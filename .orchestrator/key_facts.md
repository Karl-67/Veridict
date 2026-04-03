# Key Facts

Automatically maintained by AI Orchestrator and the project-memory skill.
Tracks project configuration, conventions, important URLs, and constants.

---

## Scaffolding Warning

**The current `app/backend/` and `app/frontend/` are scaffolding and NOT architecturally representative.**

- `app/backend/agents/reviewer.py` — single monolithic Gemini call; does not implement the multi-agent stage graph.
- `app/backend/routes/contracts.py` — single `/api/upload` endpoint; no run ID, no SSE, no human-review gate.
- `app/backend/models/schemas.py` — minimal Pydantic models; does not match the canonical run-state contract.
- `app/frontend/` — renders a fake static pipeline; not wired to real SSE events or run state.

None of these files should be used as a reference for the target architecture. Refer to the sibling contracts and shared dependency specs instead.

---

## Locked Stage Graph

Stages execute in this order. Names are canonical and must not be changed.

| # | Stage Name         | Agent / Service              |
|---|--------------------|------------------------------|
| 1 | `parse`            | `parse_pdf_to_canonical_document` (Docling + OCR fallback) |
| 2 | `harvey_review`    | `HarveyValidatorAgent`       |
| 3 | `kira_review`      | `KiraValidatorAgent`         |
| 4 | `reviewer_1`       | `GeminiProvider` (role: reviewer) |
| 5 | `reviewer_2`       | `GeminiProvider` (role: reviewer) |
| 6 | `reviewer_3`       | `GeminiProvider` (role: reviewer) |
| 7 | `admin_merge`      | `AdminMergeAgent`            |
| 8 | `agreement_check`  | `AgreementCheckAgent`        |
| 9 | `awaiting_human`   | human gate (blocks worker)   |
| 10| `finalize`         | `finalize_run_if_approved`   |

Consensus re-round: if `agreement_check` finds unresolved findings, `queue_disputed_findings_for_reround` re-queues `reviewer_*` stages for those findings only (max rounds defined in `Settings`).

---

## Run States

```
created → stage_running → stage_completed → ... → awaiting_human_review
                                                         ↓               ↓
                                                   human_approved   human_rejected
                                                         ↓
                                                    finalized
blocked (terminal error state, set by mark_run_blocked)
```

---

## Canonical SSE Event Names

All events persisted via `append_run_event` and streamed via `stream_run_events`.

| Event Type                | Trigger                                           |
|---------------------------|---------------------------------------------------|
| `run_created`             | `create_run` called                               |
| `stage_started`           | worker claims and begins a stage                  |
| `stage_completed`         | stage finishes successfully                       |
| `stage_failed`            | stage hits non-retryable error                    |
| `stage_retrying`          | stage scheduled for retry after transient error   |
| `consensus_unresolved`    | `agreement_check` finds disputed findings         |
| `awaiting_human_review`   | pipeline blocked pending human approval           |
| `human_edited`            | reviewer edits a finding                          |
| `human_rejected`          | reviewer rejects the run                          |
| `human_approved`          | reviewer approves the run                         |
| `run_finalized`           | `finalize_run_if_approved` completes successfully |

Frontend must subscribe to `GET /api/runs/{run_id}/events` (SSE) immediately after receiving a `run_id` from upload, and drive all UI state from the event stream.

---

## Harvey Lineage Key

Harvey policy lineage is keyed by the composite:

```
tenant_id + policy_family_id + version_number
```

Resolved via `resolve_policy_lineage(tenant_id, policy_family_id, version_number) -> dict`.
Prior versions loaded via `load_prior_policy_versions(...)`.

---

## Kira Corpus Metadata

Each Kira compliance corpus is versioned by:

```
tenant_id, corpus_type, jurisdiction, regime, effective_date
```

Resolution entry point: `resolve_applicable_corpora(tenant_id, jurisdiction, regime) -> dict`.
Rules loaded via:
- `load_internal_playbook_rules(tenant_id, jurisdiction, regime, effective_date)`
- `load_external_compliance_rules(tenant_id, jurisdiction, regime, effective_date)`

---

## Canonical Finding Fields

Every finding produced by any reviewer or validator agent must include:

| Field            | Type    | Description                                         |
|------------------|---------|-----------------------------------------------------|
| `finding_id`     | str     | UUID, stable across re-rounds                       |
| `clause_uid`     | str     | anchored to canonical clause index                  |
| `page`           | int     | page number from parsed document                    |
| `bbox`           | list    | bounding box `[x0, y0, x1, y1]` from Docling        |
| `normalized_text`| str     | normalized clause text from parser                  |
| `issue`          | str     | human-readable issue description                    |
| `severity`       | str     | `"low"` \| `"medium"` \| `"high"`                  |
| `confidence`     | float   | extraction confidence from parser (0.0–1.0)         |
| `agent_id`       | str     | which agent produced this finding                   |
| `round_number`   | int     | which consensus round (1-based)                     |
| `evidence`       | list    | list of evidence anchor dicts                       |

---

## Docling Canonical Parser

- Primary parser: Docling (`parse_pdf_to_canonical_document`)
- OCR fallback: enabled when Docling confidence is low
- Each parsed document carries: `document_hash`, `parser_version`
- Each clause carries: `clause_uid`, `page`, `bbox`, `normalized_text`, `extraction_confidence`
- Clause index built by `build_clause_index(parsed_document) -> list[dict]`
- All downstream agents anchor findings to `clause_uid`; never to raw character offsets

---

## Provider Abstraction (Gemini → Local)

- All LLM calls go through `StructuredLLMProvider` (base class in `providers/base.py`)
- `GeminiProvider` (in `providers/google_provider.py`) is the current concrete implementation
- Provider owns: transport, structured-output schema binding, retry/backoff, raw response capture
- Role agents (`HarveyValidatorAgent`, `KiraValidatorAgent`, `AdminMergeAgent`, etc.) own: prompts and result interpretation
- **This boundary is intentional**: swapping Gemini for a fine-tuned local model requires only replacing `GeminiProvider`, not touching agents
- Error hierarchy: `TransientProviderError` (retryable) → `RateLimitError` (retryable with backoff) → `NonRetryableProviderError` → `InvalidSchemaOutputError`

---

## Backend API Contract

| Method | Path                              | Description                            |
|--------|-----------------------------------|----------------------------------------|
| POST   | `/api/runs`                       | Create run, returns `run_id`           |
| GET    | `/api/runs/{run_id}`              | Full run detail with stage statuses    |
| GET    | `/api/runs/{run_id}/events`       | SSE stream of `RunEvent` objects       |
| GET    | `/api/runs/{run_id}/events/list`  | Paginated list of persisted events     |
| POST   | `/api/runs/{run_id}/review`       | Submit human review (edit/approve/reject) |

The old `/api/upload` endpoint in the scaffolding does not match this contract and will be replaced.

---

## Postgres Stage Queue Semantics

- Stage execution is idempotent: each `StageExecutionRecord` has a unique `(run_id, stage_name, round_number)` key
- Worker claims stages via `claim_next_stage()` which sets a lease timestamp
- Lease expiry triggers re-claim (not a new record)
- `retry_count` is incremented on `retry_stage()`; max retries defined in `Settings`
- `mark_run_blocked` is terminal — no further stage transitions

---

## Frontend SSE Subscription Behavior

1. On successful upload → receive `run_id`
2. Immediately open `EventSource` to `GET /api/runs/{run_id}/events`
3. Map event types to UI states:
   - `stage_started` / `stage_completed` / `stage_failed` → update `PipelineTracker`
   - `awaiting_human_review` → show `HumanReviewPanel`
   - `human_approved` / `run_finalized` → show final `VerdictCard`
   - `human_rejected` → show rejection state
   - `consensus_unresolved` → show re-round indicator in `PipelineTracker`
4. Close `EventSource` on `run_finalized` or `human_rejected`

---

## Current LLM Provider

- **Active**: Gemini via `google-genai` SDK (`gemini-2.5-flash`)
- **Configured by**: `GEMINI_API_KEY` env var
- **Future**: fine-tuned local model (provider swap only; no agent changes required)

### Architecture
- [2026-04-03] orchestrator.md is the authoritative phase-1 architecture reference, maintained by the AI Orchestrator

### Pipeline
- [2026-04-03] 15-stage pipeline: create_run → ingest_pdf → parse_ocr_normalize → clause_index → harvey_context_load + kira_context_load (parallel) → harvey_reviewers_1_2_3 → harvey_validator → kira_reviewers_1_2_3 → kira_validator → admin_merge → final_reviewers_1_2_3 → agreement_check → awaiting_human_review → finalized, with disagreement re-round branches

### Disagreement Policy
- [2026-04-03] Max 2 final-review rounds; round-1 disagreement triggers admin delta instructions + disputed-only re-review; round-2 disagreement triggers admin tie-break with unresolved_by_consensus flag; consensus requires all 3 reviewers agree on finding presence, clause reference, severity, and issue category

### Agent Scopes
- [2026-04-03] Harvey agents review policy lineage (tenant_id + policy_family_id + version_number); Kira agents review external compliance (tenant_id + jurisdiction + regime + effective_date)

### Code Conventions
- [2026-04-03] Provider boundary invariant: agents own prompts and schema interpretation; provider owns transport, structured-output schema binding, retry/backoff, and raw response capture — this boundary must not be crossed

### Human Gate
- [2026-04-03] Human review is mandatory — no verdict emitted without human action; actions are approved, edited (with HumanReviewRecord provenance), or rejected (run closed, no verdict)

### Issue Taxonomy
- [2026-04-03] Six issue types: liability exposure, open clauses, ambiguity, exploitability, weakened protections, compliance failures

### Phase-1 Gap
- [2026-04-03] 18 components are missing in phase-1: config, DB engine/session, ORM models, provider base, Gemini provider, validators, admin agents, parser service, policy/compliance repositories, event stream, run service, state machine, worker loop, human review UI, updated schemas/routes/types

### Architecture Decisions
- [2026-04-03] decisions.md now contains 5 accepted ADRs: ADR-001 (Gemini as phase-1 LLM provider), ADR-002 (Docling as canonical PDF parser), ADR-003 (Postgres as system of record), ADR-004 (mandatory human approval before finalization), ADR-005 (provider abstraction as migration seam for local fine-tuned agents)

### Architecture Decisions
- [2026-04-03] All ADRs share dependency on phase-1-architecture-spec; each ADR also references a domain-specific shared dependency (gemini-provider-boundary, docling-canonical-parser, postgres-stage-queue, human-review-gate)

### Provider Boundary
- [2026-04-03] StructuredLLMProvider in providers/base.py is the abstract interface; GeminiProvider in providers/google_provider.py is the phase-1 concrete implementation; error hierarchy: TransientProviderError → RateLimitError → NonRetryableProviderError → InvalidSchemaOutputError

### Pipeline Stages
- [2026-04-03] Locked 10-stage graph: parse → harvey_review → kira_review → reviewer_1 → reviewer_2 → reviewer_3 → admin_merge → agreement_check → awaiting_human → finalize

### Run States
- [2026-04-03] State machine: created → stage_running → stage_completed → ... → awaiting_human_review → (human_approved | human_rejected) → finalized; blocked is terminal

### SSE Events
- [2026-04-03] Canonical event types: run_created, stage_started, stage_completed, stage_failed, stage_retrying, consensus_unresolved, awaiting_human_review, human_edited, human_rejected, human_approved, run_finalized

### Harvey Lineage
- [2026-04-03] Harvey policy lineage keyed by composite: tenant_id + policy_family_id + version_number

### Kira Corpus
- [2026-04-03] Kira corpus metadata versioned by: tenant_id, corpus_type, jurisdiction, regime, effective_date

### Finding Schema
- [2026-04-03] Canonical finding fields: finding_id, clause_uid, page, bbox, normalized_text, issue, severity, confidence, agent_id, round_number, evidence

### Backend API Contract
- [2026-04-03] Required endpoints: POST /api/runs, GET /api/runs/{run_id}, GET /api/runs/{run_id}/events (SSE), GET /api/runs/{run_id}/events/list, POST /api/runs/{run_id}/review

### Frontend SSE Behavior
- [2026-04-03] Frontend must open EventSource to GET /api/runs/{run_id}/events immediately after upload; map events to UI states; close on run_finalized or human_rejected

### Scaffolding Warning
- [2026-04-03] Current backend/frontend are scaffolding only — single Gemini call in reviewer.py, fake static stages in contracts.py, minimal schemas, no real SSE or run IDs

### Parser
- [2026-04-03] Docling is canonical parser with OCR fallback; produces clause index with clause_uid, page, bbox, normalized_text, extraction_confidence

### Provider Abstraction
- [2026-04-03] StructuredLLMProvider base class; GeminiProvider is phase-1 impl; error hierarchy: TransientProviderError → RateLimitError → NonRetryableProviderError → InvalidSchemaOutputError

### Postgres Queue
- [2026-04-03] Stage execution idempotent via unique (run_id, stage_name, round_number); worker claims via claim_next_stage() with lease timestamps; retry_count tracked

### Issues Tracking
- [2026-04-03] issues.md tracks 7 open risks (RISK-001 through RISK-007) covering parser confidence, corpus ingestion, schema migrations, human approval gate, provider abstraction, SSE persistence, and unimplemented agents

### Issues Tracking
- [2026-04-03] Phase 1 exit criteria defined as 7 acceptance checkpoints (A–G), 6 blocking and 1 nice-to-have

### Dependencies
- [2026-04-03] requirements.txt is organized by architectural boundary: gemini-provider-boundary, docling-canonical-parser, postgres-stage-queue, sse-run-events

### Dependencies
- [2026-04-03] pdfplumber is demoted to a low-priority fallback; docling is the canonical PDF parser

### Dependencies
- [2026-04-03] Dual Postgres drivers: psycopg2-binary for sync (alembic migrations), asyncpg for async (SQLAlchemy engine)

### Dependencies
- [2026-04-03] pydantic-settings>=2.2.0 is required by core/config.py Settings class

### Dependencies
- [2026-04-03] sse-starlette>=2.1.0 provides Server-Sent Events streaming for real-time event delivery

### Configuration
- [2026-04-03] Settings class in core/config.py uses pydantic-settings with .env file, case_sensitive=False, extra=ignore

### Configuration
- [2026-04-03] get_settings() is lru_cache(maxsize=1) for singleton-like reuse across the app

### Configuration
- [2026-04-03] SettingsDep = Annotated[Settings, Depends(get_settings)] is the canonical FastAPI dependency for injecting config

### Configuration
- [2026-04-03] Config fields: gemini_api_key, gemini_model_name (default gemini-2.5-flash), postgres_dsn, worker_lease_duration_seconds (default 60), max_stage_retries (default 3), document_storage_path (default ./storage/documents), allowed_frontend_origins (default http://localhost:5173), enable_ocr_fallback (default True), parser_version (default docling-1)

### Dependencies
- [2026-04-03] pydantic-settings>=2.2.0 is required by core/config.py

### Architecture
- [2026-04-03] Database layer uses dual patterns: async (asyncpg) for API handlers/SSE, sync (psycopg2) for workers/Alembic

### Code Conventions
- [2026-04-03] Async sessions auto-commit on success and rollback on exception; sync sessions require explicit session.commit() after each atomic state transition

### Code Conventions
- [2026-04-03] POSTGRES_DSN is automatically rewritten by the session module (exact rewrite logic in app/backend/db/session.py)

### Architecture
- [2026-04-03] Engine and session factories are cached (get_engine, get_sync_engine, get_session_factory, get_sync_session_factory)

### Database
- [2026-04-03] PostgreSQL is the database backend, using SQLAlchemy ORM with PG_UUID dialect

### Code Conventions
- [2026-04-03] All models use string UUIDs (36-char) as primary keys via _uuid() helper, not native PG UUID type

### Code Conventions
- [2026-04-03] Base class is DeclarativeBase with _now() helper using datetime.utcnow()

### Architecture
- [2026-04-03] 9 ORM models: RunRecord, StageExecutionRecord, FindingRecord, EvidenceRecord, ParsedClauseRecord, PolicyVersionRecord, ComplianceCorpusRecord, RunEventRecord, HumanReviewRecord

### Architecture
- [2026-04-03] StageExecutionRecord implements a lease-based queue protocol with lease_expires_at, worker_id, retry_count, max_retries fields

### Architecture
- [2026-04-03] RunEventRecord uses BigInteger autoincrement PK for append-only SSE event stream with monotonic sequence_number per run

### Architecture
- [2026-04-03] ParsedClauseRecord uses deterministic clause_uid for stable clause referencing across re-parses

### Architecture
- [2026-04-03] PolicyVersionRecord and ComplianceCorpusRecord support multi-tenant policy lineage with UniqueConstraint on (tenant_id, policy_family_id, version_number)

### Architecture
- [2026-04-03] HumanReviewRecord captures before/after edit snapshots for full audit provenance

### Code Conventions
- [2026-04-03] All models use cascade='all, delete-orphan' on parent-child relationships

### Code Conventions
- [2026-04-03] Idempotency enforced via UniqueConstraint on (run_id, stage_name, round_number, attempt_number) for StageExecutionRecord

### Architecture
- [2026-04-03] Alembic env.py imports all 9 ORM models explicitly to ensure Base.metadata is fully populated for migration generation

### Architecture
- [2026-04-03] Alembic env.py uses sys.path manipulation to make the backend package importable when alembic is invoked from the project root

### Code Conventions
- [2026-04-03] Database URL resolution prefers alembic.ini sqlalchemy.url but fall back to Settings.postgres_dsn from .env

### Code Conventions
- [2026-04-03] Alembic configured with compare_type=True, compare_server_default=True, and render_as_batch=False for comprehensive schema diff detection

### Code Conventions
- [2026-04-03] NullPool used for online migrations to ensure single-use connection per migration run

### Database
- [2026-04-03] First Alembic migration (0001) creates 9 tables: runs, stage_executions, parsed_clauses, findings, evidence, policy_versions, compliance_corpora, run_events, human_reviews

### Database
- [2026-04-03] All tables use UUID-style string(36) primary keys, not native UUID or integer types

### Database
- [2026-04-03] All foreign keys use ondelete='CASCADE' except human_reviews.finding_id which uses ondelete='SET NULL'

### Database
- [2026-04-03] PostgreSQL-specific: uses postgresql.JSONB for payload columns and postgresql.dialects import

### Database
- [2026-04-03] Stage queue uses composite index (status, stage_order, lease_expires_at) for SELECT FOR UPDATE SKIP LOCKED worker claiming

### Database
- [2026-04-03] Run approval_state enum values: pending, awaiting_human_review, approved, edited, rejected, finalized

### Database
- [2026-04-03] Event types for SSE: run_created, stage_started, stage_completed, stage_failed, stage_retrying, consensus_unresolved, awaiting_human_review, human_edited, human_rejected, human_approved, run_finalized

### Database
- [2026-04-03] Composite unique index ix_policy_versions_lineage on (tenant_id, policy_family_id, version_number) for Harvey lineage

### Database
- [2026-04-03] Composite unique index ix_compliance_corpora_lookup on (tenant_id, corpus_type, jurisdiction, regime, effective_date) for Kira corpora

### Code Conventions
- [2026-04-03] Migration file includes shared dependency tags in docstring referencing canonical dependency names (postgres-stage-queue, run-state-contract, etc.)

### Schema Versioning
- [2026-04-03] schemas.py defines SCHEMA_VERSION = 1 as a module-level sentinel to be bumped when fields are added/removed, ensuring persisted records remain interpretable after model evolution

### Code Conventions
- [2026-04-03] All Pydantic models in schemas.py include schema_version: int = SCHEMA_VERSION as the first field for forward/backward compatibility

### Schema Contract
- [2026-04-03] schemas.py implements the run-state-contract shared dependency with 20+ models across 7 groups: Enums/Literals, Parser, Findings, Agent outputs, Verdict, Run/Stage state, API shapes, SSE events, Human review gate

### Finding Schema
- [2026-04-03] Finding model includes consensus tracking (consensus_status, unresolved_by_consensus) and human edit overlay (human_edited, human_edit_delta) fields

### Human Review Gate
- [2026-04-03] HumanReviewAction, HumanReviewPayload, and HumanReviewResult models define the human review request/response contract with per-finding edit deltas and run-level actions

### SSE Events
- [2026-04-03] RunEvent model carries event_id, run_id, event_type (EventType literal), payload dict, emitted_at, and monotonically increasing sequence number per run

### API Shapes
- [2026-04-03] RunCreateResponse, RunSummary, and RunDetail define three tiers of API response shapes — lightweight list view, creation response, and full detail with optional verdict

### Legacy Compatibility
- [2026-04-03] Legacy prototype models (ClauseFlag, ReviewResult, PipelineStage, PipelineStatus, UploadResponse) are retained at the bottom of schemas.py for backwards compat during route migration, marked for removal

### Architecture
- [2026-04-03] All role agents interact with LLMs exclusively through `StructuredLLMProvider.generate_structured_output(prompt, response_schema)` — a single abstract method that enforces structured output

### Error Handling
- [2026-04-03] Provider errors form a strict hierarchy: `ProviderError` (base) → `InvalidSchemaOutputError` (non-retryable), `TransientProviderError` (retryable, covers 5xx/timeouts), `RateLimitError` extends `TransientProviderError` with `retry_after_seconds`, `NonRetryableProviderError` (auth failure, bad API key, policy rejection)

### Observability
- [2026-04-03] Every provider call captures `RawProviderRequest` (model, prompt, schema, temperature, timestamp) and `RawProviderResponse` (raw text, parsed output, finish reason, usage, latency) for debugging and audit trails

### Code Conventions
- [2026-04-03] `StructuredLLMProvider` is an abstract base class — concrete provider implementations (OpenAI, Anthropic, etc.) must subclass it and implement the abstract method

### Provider Implementation
- [2026-04-03] GeminiProvider uses response_mime_type="application/json" + response_schema binding for structured output — no free-text JSON parsing

### Provider Implementation
- [2026-04-03] Default model is gemini-2.5-flash with temperature=0.3 and max_output_tokens=8192

### Error Handling
- [2026-04-03] Gemini SDK errors are classified via _classify_genai_error(): 429→RateLimitError, 5xx→TransientProviderError, other 4xx→NonRetryableProviderError, unknown→TransientProviderError

### Retry Strategy
- [2026-04-03] Exponential backoff with full jitter: random.uniform(0, min(max_backoff, base_backoff * 2^attempt)); RateLimitError respects retry_after_seconds hint

### Observability
- [2026-04-03] RawProviderRequest captured before each attempt via on_request_captured(); RawProviderResponse captured after success or terminal failure via on_response_captured()

### Code Conventions
- [2026-04-03] Provider factory function build_gemini_provider() is the preferred construction path for dependency injection — agents should not instantiate GeminiProvider directly

### Safety Net
- [2026-04-03] _parse_structured_response strips markdown code fences as a defensive measure against model regressions, even though structured-output mode should never produce them

### Architecture
- [2026-04-03] reviewer.py now contains three role-specific agent classes (HarveyReviewerAgent, KiraReviewerAgent, FinalReviewerAgent) instead of a single review_contract() function

### Architecture
- [2026-04-03] Each reviewer agent takes a reviewer_index (1-3) that maps to a distinct prompt role: 1=issue_discovery, 2=false_positive_challenge, 3=exploitability_impact

### Code Conventions
- [2026-04-03] All three reviewer agents use _ROLE_BY_INDEX mapping to assign ReviewerRole Literal types at construction time

### Code Conventions
- [2026-04-03] Reviewer agent_role property returns branch-specific strings: harvey_reviewer_N, kira_reviewer_N, final_reviewer_N

### Provider Boundary
- [2026-04-03] All reviewer agents call provider.generate_structured_output() with REVIEWER_OUTPUT_SCHEMA — no direct LLM calls

### Schema
- [2026-04-03] REVIEWER_OUTPUT_SCHEMA requires findings array with clause_uid, issue_type, severity, exploitability, business_impact, description, recommendation, recommendation_detail

### Prompt Design
- [2026-04-03] Three distinct system prompts: issue_discovery (exhaustive, err on inclusion), false_positive_challenge (material issues only, discard boilerplate), exploitability_impact (weaponization analysis, asymmetric risk)

### Architecture
- [2026-04-03] FinalReviewerAgent supports up to 2 disagreement rounds; round 2 uses delta_instructions for targeted re-review of disputed findings only

### Code Conventions
- [2026-04-03] _assemble_branch_output() validates clause_uid against the clause_index set and skips hallucinated references

### Architecture
- [2026-04-03] validator.py contains two validator agent classes (HarveyValidatorAgent, KiraValidatorAgent) and four internal helper functions (_normalize_reviewer_outputs, _score_evidence_quality, _deduplicate_overlapping_findings, _build_validator_prompt)

### Architecture
- [2026-04-03] Both validator agents depend on StructuredLLMProvider.generate_structured_output() with a shared _VALIDATOR_RESPONSE_SCHEMA that enforces hallucination detection, severity/issue_type normalization, and evidence quality scoring

### Code Conventions
- [2026-04-03] Evidence quality scoring (_score_evidence_quality) computes the mean of extraction_confidence across all EvidenceRef objects; returns 0.0 when no evidence exists

### Code Conventions
- [2026-04-03] Deduplication groups findings by (clause_uid, issue_type), selects the finding with highest evidence quality score as primary, and merges evidence refs across duplicates with clause_uid-level dedup

### Code Conventions
- [2026-04-03] KiraValidatorAgent.validate() accepts jurisdiction and regime parameters that are injected into the validator prompt and surfaced as inapplicable_regime_flags in the ValidatorOutput

### Code Conventions
- [2026-04-03] Hallucinated clause UIDs are filtered out before deduplication — any finding whose clause_uid appears in hallucinated_clause_uids is excluded from the validated output

### Schema
- [2026-04-03] _VALIDATOR_RESPONSE_SCHEMA defines finding_verdicts with normalised_severity enum (low/medium/high/critical) and normalised_issue_type enum matching the six-category issue taxonomy

### Code Conventions
- [2026-04-03] policy_repository.py uses sync sessions exclusively (get_sync_session_factory) despite the broader project having both async and sync patterns

### Code Conventions
- [2026-04-03] The _session() context manager uses @contextmanager decorator with explicit rollback on exception and close in finally block

### Code Conventions
- [2026-04-03] Record-to-dict conversion centralized in _record_to_dict() helper, including ISO-format serialization for datetime fields

### Architecture
- [2026-04-03] MissingLineageError carries a class-level blocked_reason attribute ('blocked_missing_lineage') that the state machine reads directly without instantiation

### Architecture
- [2026-04-03] resolve_policy_lineage() returns full rules_payload (dict) — not just metadata — enabling downstream agents to access complete policy rules

### Architecture
- [2026-04-03] load_prior_policy_versions() returns empty list (not error) for version 1 of a new policy family, treating it as valid

### Architecture
- [2026-04-03] Prior versions ordered ascending by version_number so callers can walk the lineage chain chronologically

### Scaffolding Warning
- [2026-04-03] app/backend/routes/contracts.py is scaffolding — single /api/upload endpoint with hardcoded fake pipeline stages, no run ID, no SSE, no human-review gate; will be replaced by the canonical /api/runs contract

### Dependencies
- [2026-04-03] contracts.py currently uses pdfplumber for PDF text extraction; this is demoted to a low-priority fallback — Docling is the canonical parser

### Code Conventions
- [2026-04-03] FastAPI app in main.py uses title='Veridict API' and version='0.1.0'

### Code Conventions
- [2026-04-03] CORS middleware configured with allow_origins=['http://localhost:5173'], allow_credentials=True

### Code Conventions
- [2026-04-03] Routes registered via include_router() — contracts router currently imported

### Architecture
- [2026-04-03] main.py loads .env via dotenv at module top before any other imports

### Architecture
- [2026-04-03] Current main.py does not yet wire settings module, DB lifecycle, startup checks, or run router — still using old contracts router with /api/upload endpoint

### Frontend State Machine
- [2026-04-03] App.tsx uses a local AppState union type: 'upload' | 'pipeline' | 'waiting' | 'verdict' — does not yet map to backend run states

### Frontend State Machine
- [2026-04-03] App.tsx uses dual-ref synchronization pattern (apiDoneRef + pipelineDoneRef) to coordinate fake pipeline animation with real API response

### Frontend API Integration
- [2026-04-03] Current upload flow calls uploadContract() directly and expects immediate ReviewResult — no run_id, no SSE subscription

### Frontend Polling
- [2026-04-03] A 300ms polling interval is used as a workaround in 'waiting' state to check if apiDoneRef is set — should be replaced by SSE

### Frontend Components
- [2026-04-03] App.tsx imports: Header, UploadForm, PipelineTracker, VerdictCard — no HumanReviewPanel component exists yet

### Scaffolding Warning
- [2026-04-03] PipelineTracker.tsx uses hardcoded STAGES array with timer-based animation (useEffect + setTimeout), not SSE-driven — does not reflect the canonical 10-stage backend graph (parse → harvey_review → kira_review → reviewer_1/2/3 → admin_merge → agreement_check → awaiting_human → finalize)

### Scaffolding Warning
- [2026-04-03] PipelineTracker.tsx defines only 7 stages (Harvey, Kira, Reviewer 1-3, Validators, Verdict) — missing parse, admin_merge, agreement_check, awaiting_human, and finalize stages from the locked stage graph

### Code Conventions
- [2026-04-03] PipelineTracker.tsx uses framer-motion for stage entry animations (opacity/x transitions) and pulsing indicator for running state (scale [1, 1.3, 1] infinite loop)

### Code Conventions
- [2026-04-03] PipelineTracker.tsx has three visual states per stage: done (CheckCircle2, green), running (pulsing Circle, primary color), pending (dim Circle) — but no retrying, blocked, or failed states

### Frontend SSE Behavior
- [2026-04-03] PipelineTracker.tsx accepts only an onComplete callback prop — no run_id, no SSE subscription, no backend integration; must be refactored to accept run_id and subscribe to GET /api/runs/{run_id}/events

### Frontend Types
- [2026-04-03] ReviewResult type is flat (clause_flags, risk_level, summary, recommendations) — lacks branch grouping, consensus state, evidence anchors, exploitability/business impact, unresolved_by_consensus markers, and human review outcome fields required by the VerdictCard spec

### Frontend Types
- [2026-04-03] ClauseFlag type is minimal (clause, issue, severity) — no finding_id, clause_uid, page, bbox, confidence, agent_id, round_number, or evidence fields from the canonical finding schema

### Code Conventions
- [2026-04-03] VerdictCard uses framer-motion for entrance animation (opacity + y translate) and AnimatePresence for expandable clause sections

### Code Conventions
- [2026-04-03] Risk levels map to tailwind color tokens via riskConfig: high→text-risk-high/bg-risk-high/15, medium→text-risk-medium/bg-risk-medium/15, low→text-risk-low/bg-risk-low/15

### Scaffolding Warning
- [2026-04-03] VerdictCard.tsx renders a flat risk-summary card using the legacy ReviewResult type — it does not implement the run-aware verdict view spec (no branch/consensus grouping, no evidence anchors, no human review outcomes, no edited findings display)

### Documentation
- [2026-04-03] app/README.md is outdated scaffolding documentation — references Anthropic, fake static frontend/backend, and lacks Gemini, Docling, Postgres, worker process, and SSE documentation

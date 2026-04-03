I need permission to write the file. Let me present the full content for your review first, then you can approve the write.

Here's the complete `orchestrator.md` I've prepared based on thorough analysis of every file in the codebase:

---

```markdown
# Verdict — Project Orchestrator

**Authoritative architecture reference for the Verdict multi-agent legal contract review system.**
Maintained by the AI Orchestrator. Read by humans and AI tools to understand the project.

---

## 1. Project Overview

Verdict is a multi-agent legal contract review system. It accepts a PDF contract, runs it through a structured pipeline of specialist reviewer agents (Harvey for internal policy lineage, Kira for external compliance), reconciles disagreements via an admin merge agent, requires mandatory human approval before finalizing, and produces a structured verdict with clause-level findings and evidence anchors.

**Phase 1 strategy (Google-Now / Local-Later):** All LLM calls go through the Gemini API (`gemini-2.5-flash`) via a `StructuredLLMProvider` abstraction. Each narrow-role agent (Harvey reviewer, Kira reviewer, validator, admin) can later be replaced by a locally fine-tuned model without touching orchestration logic. Fine-tuning targets individual roles using the CUAD and LEDGAR datasets — not one monolithic model.

---

## 2. Architecture

### Core Pattern: Provider Boundary + Role Agents

```
┌─────────────────────────────────────────────────────────────┐
│  Agents (own prompts + schema interpretation)               │
│  HarveyReviewer ×3  │  KiraReviewer ×3  │  FinalReviewer ×3 │
│  HarveyValidator    │  KiraValidator    │  AdminMerge       │
│  AgreementCheck     │  DeltaBuilder     │                   │
└──────────────────────┬──────────────────────────────────────┘
                       │ inject
┌──────────────────────▼──────────────────────────────────────┐
│  StructuredLLMProvider (abstract interface)                  │
│  - generate_structured_output(prompt, schema)                │
│  - on_request_captured() / on_response_captured()            │
└──────────────────────┬──────────────────────────────────────┘
                       │ implements
┌──────────────────────▼──────────────────────────────────────┐
│  GeminiProvider (concrete — Phase 1)                        │
│  - google-genai SDK, structured-output mode                  │
│  - retry/backoff, token budget, raw capture                  │
│  → Later: LocalModelProvider (vLLM/Ollama + fine-tuned)     │
└─────────────────────────────────────────────────────────────┘
```

**Boundary invariant:** Agents own prompts and schema interpretation. The provider owns transport, structured-output schema binding, retry/backoff, and raw response capture. This boundary must not be crossed.

### Execution Model: Postgres-Backed Stage Queue

Stages are persisted in Postgres. A dedicated worker process claims stages via `SELECT FOR UPDATE SKIP LOCKED`, executes them, and advances the state machine. Each stage is idempotent — retries and worker restarts do not duplicate findings or events.

### Event Stream: SSE for Frontend

All state transitions emit append-only events to `run_events`. The frontend subscribes via Server-Sent Events for real-time pipeline progress — no timer-based simulation.

### Human Review Gate

No verdict is emitted without a human action. The run enters `awaiting_human_review` state. The reviewer can approve, edit-and-approve, or reject. All actions are stored with full provenance.

---

## 3. Phase-1 Stage Graph

Stages execute in the order below. The worker claims one stage at a time from the Postgres queue.

```
create_run
  └─> ingest_pdf
        └─> parse_ocr_normalize          (Docling + OCR fallback)
              └─> clause_index           (build_clause_index → clause anchors)
                    └─> harvey_context_load   (parallel)
                    └─> kira_context_load     (parallel)
                          └─> harvey_reviewers_1_2_3   (3 independent calls)
                                └─> harvey_validator
                                      └─> kira_reviewers_1_2_3   (3 independent calls)
                                            └─> kira_validator
                                                  └─> admin_merge
                                                        └─> final_reviewers_1_2_3   (round 1)
                                                              └─> agreement_check
                                                                    ├─ [consensus] ──> awaiting_human_review
                                                                    └─ [disagreement, round < 2]
                                                                          └─> admin_delta_instructions
                                                                                └─> final_reviewers_1_2_3   (round 2, disputed only)
                                                                                      └─> agreement_check
                                                                                            ├─ [consensus] ──> awaiting_human_review
                                                                                            └─ [disagreement] ──> admin_tie_break
                                                                                                                    └─> awaiting_human_review

awaiting_human_review
  ├─ [approved]  ──> finalized
  ├─ [edited]    ──> finalized   (with human_edited provenance)
  └─ [rejected]  ──> (run closed; no verdict)
```

**Disagreement policy:** Max 2 final-review rounds. Round-1 disagreement triggers admin delta instructions for disputed findings only. Round-2 disagreement triggers admin tie-break with `unresolved_by_consensus` flag. Human reviewer must resolve all flags explicitly.

---

## 4. Folder Structure

```
Verdict/
├── orchestrator.md              # THIS FILE — authoritative architecture reference
├── AGENTS.md                    # AI agent entry point — points here
├── CLAUDE.md                    # Claude agent entry point — points here
├── requirements.txt             # Root-level: EDA deps (streamlit, plotly, datasets)
├── .gitignore
│
├── .orchestrator/               # Persistent AI memory
│   ├── bugs.md                  # Logged bugs and known issues
│   ├── decisions.md             # Architecture Decision Records (ADRs)
│   ├── key_facts.md             # Tracked facts: stage names, schemas, API contracts
│   ├── issues.md                # Open implementation risks + acceptance checkpoints
│   ├── memory.yaml              # Past mistakes, code conventions, patterns learned
│   └── plan.md                  # Implementation plan with file-level tasks
│
├── app/
│   ├── README.md                # Setup docs (needs update to match current architecture)
│   │
│   ├── backend/                 # FastAPI backend — Python
│   │   ├── main.py              # FastAPI app entrypoint (scaffolding — hardcoded CORS)
│   │   ├── requirements.txt     # Backend runtime dependencies
│   │   │
│   │   ├── core/
│   │   │   └── config.py        # ✅ Settings: Gemini key, Postgres DSN, worker settings
│   │   │
│   │   ├── db/
│   │   │   ├── session.py       # ✅ Dual engine: async (asyncpg) + sync (psycopg2)
│   │   │   └── models.py        # ✅ 9 ORM models: Run, Stage, Finding, Evidence, Clause,
│   │   │                        #    PolicyVersion, ComplianceCorpus, RunEvent, HumanReview
│   │   │
│   │   ├── providers/
│   │   │   ├── base.py          # ✅ StructuredLLMProvider abstract interface + error hierarchy
│   │   │   └── google_provider.py # ✅ GeminiProvider with structured output, retry, audit
│   │   │
│   │   ├── agents/
│   │   │   ├── reviewer.py      # ✅ HarveyReviewerAgent, KiraReviewerAgent, FinalReviewerAgent
│   │   │   │                    #    (3 distinct prompt roles per branch, provider injection)
│   │   │   └── validator.py     # ✅ HarveyValidatorAgent, KiraValidatorAgent
│   │   │                        #    (hallucination detection, dedup, evidence scoring)
│   │   │
│   │   ├── models/
│   │   │   └── schemas.py       # ✅ Full run-state-contract: 20+ Pydantic models
│   │   │                        #    + legacy prototype models (backwards compat)
│   │   │
│   │   ├── routes/
│   │   │   └── contracts.py     # ❌ OLD: single /api/upload endpoint, pdfplumber, hardcoded
│   │   │                        #    Needs replacement with async run API (POST /runs, SSE, etc.)
│   │   │
│   │   ├── services/
│   │   │   └── policy_repository.py # ✅ Harvey lineage service (resolve + load prior versions)
│   │   │   ├── parser.py            # ❌ MISSING: Docling PDF parsing + OCR fallback
│   │   │   ├── compliance_repository.py # ❌ MISSING: Kira corpora loaders
│   │   │   ├── event_stream.py      # ❌ MISSING: SSE event publisher + stream adapter
│   │   │   └── run_service.py       # ❌ MISSING: create_run, get_run_detail, human review
│   │   │
│   │   ├── orchestration/
│   │   │   └── state_machine.py     # ❌ MISSING: Stage queue, claim, execute, advance, retry
│   │   │
│   │   ├── worker.py                # ❌ MISSING: Dedicated worker process entrypoint
│   │   │
│   │   └── alembic/
│   │       ├── env.py           # ✅ Migration environment wired to all 9 ORM models
│   │       └── versions/
│   │           └── 0001_initial_architecture.py # ✅ Initial migration: all 9 tables + indexes
│   │
│   └── frontend/                # React 19 + TypeScript + Vite 6
│       ├── index.html
│       ├── package.json         # React 19, Vite 6, Tailwind 4, Framer Motion, Lucide, TanStack
│       ├── tsconfig.json
│       ├── vite.config.ts
│       └── src/
│           ├── main.tsx
│           ├── index.css        # Tailwind v4, dark theme, Inter font
│           ├── App.tsx          # ❌ FAKE: 4-state machine (upload/pipeline/waiting/verdict),
│           │                    #    polling at 300ms, no SSE, no run IDs, no human review
│           ├── components/
│           │   ├── Header.tsx          # ✅ Static header component
│           │   ├── UploadForm.tsx      # ⚠️  PDF drag-and-drop, no metadata fields
│           │   ├── PipelineTracker.tsx # ❌ FAKE: 7 hardcoded stages via setTimeout timers
│           │   └── VerdictCard.tsx     # ⚠️  Displays ReviewResult, no branch grouping/consensus
│           ├── lib/
│           │   ├── api.ts      # ❌ OLD: single uploadContract() POST to /api/upload
│           │   └── utils.ts
│           └── types/
│               └── index.ts    # ❌ OLD: flat ClauseFlag/ReviewResult/PipelineStatus types
│
├── eda/                         # Streamlit exploratory data analysis
│   ├── app.py
│   └── pages/
│       ├── 1_Atticus.py         # CUAD dataset analysis (510 contracts, 41 categories)
│       ├── 2_Legal_Clauses.py   # LEDGAR dataset analysis (100 provision types)
│       └── 3_Combined.py        # Cross-dataset analysis, token budget, training readiness
│
├── scripts/
│   └── download_datasets.py     # Downloads CUAD + LEDGAR from HuggingFace → Parquet in data/
│
└── data/                        # Gitignored — populated by download_datasets.py
    ├── atticus/                 # CUAD dataset (Harvey fine-tuning source)
    └── legal_clauses/           # LEDGAR dataset (Kira fine-tuning source)
```

**Legend:** ✅ Implemented · ⚠️ Partially implemented · ❌ Missing / needs replacement

---

## 5. Tech Stack

| Layer | Technology |
|---|---|
| **Backend API** | FastAPI 0.111+, Uvicorn, python-multipart |
| **LLM Provider (Phase 1)** | Google Gemini (`gemini-2.5-flash`) via `google-genai` SDK |
| **LLM Provider (Phase 2+)** | Local fine-tuned models via vLLM/Ollama (behind same `StructuredLLMProvider` interface) |
| **Database** | PostgreSQL with SQLAlchemy 2.0 (async + sync engines) |
| **Migrations** | Alembic 1.13+ |
| **PDF Parsing** | Docling 2.21+ (primary), Tesseract OCR (fallback), pdfplumber (low-priority fallback) |
| **Settings** | Pydantic Settings + python-dotenv |
| **SSE Streaming** | sse-starlette 2.1+ |
| **Frontend** | React 19, TypeScript, Vite 6, Tailwind CSS 4, Framer Motion, Lucide React, TanStack Query |
| **EDA** | Streamlit, Plotly, Seaborn, scikit-learn, pandas, pyarrow |
| **Fine-tuning Data** | CUAD (Atticus), LEDGAR (LexGLUE) — downloaded via `scripts/download_datasets.py` |

---

## 6. What Each Component Does

### Backend — Implemented (✅)

| Component | What It Does |
|---|---|
| `config.py` | `Settings` class with pydantic-settings. Reads `GEMINI_API_KEY`, `POSTGRES_DSN`, worker lease duration, max retries, parser/OCR toggles from `.env`. |
| `db/session.py` | Dual SQLAlchemy engines: async (asyncpg) for API/SSE handlers, sync (psycopg2) for worker/Alembic. Session factories with proper scoping rules. |
| `db/models.py` | 9 ORM models covering runs, stages, findings, evidence, parsed clauses, policy versions, compliance corpora, run events, human reviews. Includes lease/retry fields for stage queue. |
| `providers/base.py` | `StructuredLLMProvider` abstract base class. Error hierarchy: `InvalidSchemaOutputError`, `TransientProviderError`, `RateLimitError`, `NonRetryableProviderError`. Raw capture hooks for audit. |
| `providers/google_provider.py` | `GeminiProvider` with Gemini structured-output mode (`response_mime_type="application/json"`). Exponential backoff with jitter, rate-limit awareness, token budget, raw request/response capture. |
| `agents/reviewer.py` | Three agent classes: `HarveyReviewerAgent`, `KiraReviewerAgent`, `FinalReviewerAgent`. Each takes `reviewer_index` (1/2/3) mapping to distinct prompt roles: issue_discovery, false_positive_challenge, exploitability_impact. All use provider injection. |
| `agents/validator.py` | `HarveyValidatorAgent` and `KiraValidatorAgent`. Hallucination detection (clause_uid not in index), deduplication, evidence quality scoring, severity/issue_type normalization. |
| `models/schemas.py` | Full `run-state-contract`: 20+ Pydantic models (RunStatus, StageStatus, Finding, EvidenceRef, BranchReviewOutput, ValidatorOutput, AdminMergeOutput, FinalVerdict, RunEvent, HumanReviewPayload, etc.). Enums for all literals. Legacy prototype models kept for backwards compat. |
| `services/policy_repository.py` | Harvey lineage service. `resolve_policy_lineage()` keyed by `tenant_id + policy_family_id + version_number`. `load_prior_policy_versions()` for historical comparison. Raises `MissingLineageError` with `blocked_reason = "blocked_missing_lineage"`. |
| `alembic/env.py` | Migration environment. Imports all 9 ORM models. Configures online/offline modes. Falls back to Settings for DSN if not in alembic.ini. |
| `alembic/versions/0001_*.py` | Initial migration. Creates all 9 tables with indexes for stage queue claiming, policy lineage lookup, compliance corpora lookup, SSE replay ordering, and human review audit. |
| `requirements.txt` | Grouped dependencies: FastAPI, google-genai, docling, SQLAlchemy, alembic, psycopg2, asyncpg, sse-starlette, pydantic-settings. |

### Backend — Missing (❌)

| Component | What It Must Do |
|---|---|
| `services/parser.py` | Docling-first PDF parsing with OCR fallback. `parse_pdf_to_canonical_document()` and `build_clause_index()`. Emit clause records with `clause_uid`, page, bbox, normalized text, extraction confidence. |
| `services/compliance_repository.py` | Kira corpora access. `load_internal_playbook_rules()`, `load_external_compliance_rules()`, `resolve_applicable_corpora()`. Filtered by tenant, jurisdiction, regime, effective date. |
| `services/event_stream.py` | Persisted event publisher. `append_run_event()` for transactional writes. `stream_run_events()` for SSE replay + live emission. |
| `services/run_service.py` | Application service. `create_run()`, `get_run_detail()`, `list_run_events()`, `submit_human_review()`, `finalize_run_if_approved()`. Validates upload metadata, lineage, scope, human-review payloads. |
| `orchestration/state_machine.py` | Deterministic execution graph. `claim_next_stage()`, `execute_stage()`, `advance_stage()`, `retry_stage()`, `mark_stage_failed()`, `mark_run_blocked()`. Implements exact stage ordering, max-two-round policy, mandatory human handoff. Idempotent writes. |
| `worker.py` | Dedicated worker process. `run_worker_loop()` polls/claims leased stages, executes state machine stages, refreshes leases, recovers expired work. Dead-letter handling after max retries. Separate entrypoint from FastAPI. |
| `agents/admin.py` | Admin-layer agents. `AdminMergeAgent` (merge Harvey + Kira outputs), `AgreementCheckAgent` (compare 3 final-reviewer outputs, determine 2-of-3 agreement), `AdminDeltaInstructionBuilder` (round-1 disputed-only re-review instructions). |
| `routes/contracts.py` | **Replace entirely.** Remove old `/api/upload`. Add: `POST /api/runs` (202 Accepted, PDF + metadata), `GET /api/runs/{run_id}`, `GET /api/runs/{run_id}/events` (SSE), `POST /api/runs/{run_id}/human-review`. Keep `GET /api/health`. |

### Frontend — Needs Replacement (❌/⚠️)

| Component | Current State | Required State |
|---|---|---|
| `App.tsx` | Fake 4-state machine with polling. No run IDs, no SSE. | Backend-driven: create run, subscribe to SSE, render real states (uploading/running/blocked/awaiting_human_review/finalized/rejected/failed). |
| `UploadForm.tsx` | PDF drag-and-drop only. | Add required metadata inputs: `tenant_id`, `policy_family_id`, `policy_version`, jurisdiction, regime. Call `createRun()`. |
| `PipelineTracker.tsx` | 7 hardcoded stages via `setTimeout`. | Render real backend stage statuses from SSE events. Show all 15+ stages including Harvey/Kira branches, validators, admin merge, final reviewers, agreement check, human review gate. |
| `VerdictCard.tsx` | Flat risk summary with clause flags. | Run-aware verdict: grouped findings by branch and consensus state, evidence anchors, exploitability/impact, `unresolved_by_consensus` markers, human review outcome. |
| `api.ts` | Single `uploadContract()` POST. | `createRun()`, `getRun()`, `subscribeToRunEvents()` (SSE with reconnect/replay), `submitHumanReview()`. |
| `types/index.ts` | Flat `ClauseFlag`, `ReviewResult`, `PipelineStatus`. | Full `run-state-contract` interfaces: `RunDetail`, `RunEvent`, `Finding`, `EvidenceRef`, `HumanReviewPayload`, `HumanReviewResult`, enums. |
| `HumanReviewPanel.tsx` | Does not exist. | Mandatory review UI: approve, edit-and-approve, reject. Per-finding edit with reason capture. Sends typed payload to backend. |

---

## 7. Good to Know — Quirks, Conventions, Gotchas

### Environment Requirements
- **No `.env` file exists.** The app requires `GEMINI_API_KEY` and `POSTGRES_DSN` environment variables. Create `.env` with at minimum:
  ```
  GEMINI_API_KEY=your_key_here
  POSTGRES_DSN=postgresql://user:pass@localhost:5432/verdict
  ```
- **No `alembic.ini` file exists.** The migration environment is written but cannot be executed without it. Create one pointing to `app/backend/alembic/` with the Postgres DSN.

### Current Backend Is Scaffolding, Not Runtime
- The backend has substantial architecture in place (provider abstraction, ORM models, Alembic migration, agent classes, schemas) but the **runtime pipeline does not execute**. There is no state machine, no worker, no parser service, no event stream, no run service, no admin agents.
- `routes/contracts.py` is still the **old single-endpoint prototype**: uses `pdfplumber` directly, calls a monolithic `review_contract()` (which doesn't even exist in the current reviewer.py — it was the old version), returns hardcoded "all stages done" responses.
- `main.py` has hardcoded CORS origins (`http://localhost:5173`) instead of using `Settings.allowed_frontend_origins`.

### Frontend Is Entirely a Fake Demo
- `PipelineTracker.tsx` advances stages via `setTimeout` timers — completely disconnected from backend state.
- `App.tsx` uses refs for dual async path sync and polls at 300ms in "waiting" state — an anti-pattern that will be replaced by SSE subscription.
- No error states, no retry/blocked/failed UI states, no human review panel.

### Database
- **Dual engine pattern:** async (asyncpg) for API handlers, sync (psycopg2) for worker/Alembic. This is intentional — Alembic and the worker cannot operate in async context.
- **Stage queue uses `SELECT FOR UPDATE SKIP LOCKED`** for worker claiming. The migration includes a specialized index `ix_stage_executions_claim` for this.
- **9 tables** are defined in the initial migration. All have proper foreign keys, indexes, and uniqueness constraints.

### Provider Boundary
- `GeminiProvider` uses Gemini's **structured-output mode** (`response_mime_type="application/json"` + `response_schema` binding). This is NOT free-text JSON parsing — the model is constrained at generation time.
- The provider includes **retry/backoff with full jitter**, rate-limit awareness (429 with `retry_after_seconds`), and **raw request/response capture hooks** for audit (becomes the fine-tuning dataset later).
- Error classification maps google-genai SDK exceptions to our hierarchy: 429 → `RateLimitError`, 5xx → `TransientProviderError`, 4xx → `NonRetryableProviderError`.

### Agent Differentiation
- Three reviewers per branch are **independent parallel passes** with different prompts, NOT sequential critique/revision:
  - Reviewer 1: **Issue discovery** — exhaustive, err on side of inclusion
  - Reviewer 2: **False-positive challenge** — discard standard boilerplate, keep only material issues
  - Reviewer 3: **Exploitability impact** — asymmetric risk, worst-case liability, downstream business impact
- This prevents self-reinforcing hallucinations that would occur if reviewers built on each other's outputs.

### "Issues" Definition
A finding qualifies as an issue if it represents: liability exposure, open clauses, ambiguity, exploitability, weakened protections, or compliance failures. See the full definition in the stage graph section above.

### Fine-Tuning Strategy
- **Do NOT fine-tune one monolithic model.** Each role (Harvey reviewer, Kira reviewer, validator, admin adjudicator) is fine-tuned independently.
- **CUAD dataset** → Harvey agents (clause annotation, conflict detection).
- **LEDGAR dataset** → Kira agents (provision classification, compliance rules).
- Fine-tuning dataset is built from **persisted raw inputs, prompts, outputs, evidence, human corrections, and final decisions** — all captured by the provider boundary and human review gate.

### Known Gaps in Architecture Definition
- "Previous policy conflict" is not yet formally defined (direct contradiction vs. scope mismatch vs. version regression vs. exception mismatch).
- Harvey scope needs clarification: check only prior versions of same policy, or all organizational policies?
- Kira scope needs clarification: internal policy only, or broader compliance/risk engine?
- These are tracked as open questions in `.orchestrator/issues.md`.

---

## 8. What's Needed to Finalize Phase 1

### Backend (8 components)
1. `services/parser.py` — Docling PDF parsing + OCR fallback
2. `services/compliance_repository.py` — Kira corpora loaders
3. `services/event_stream.py` — SSE event publisher + stream adapter
4. `services/run_service.py` — Application service (create, get, review, finalize)
5. `orchestration/state_machine.py` — Stage queue execution graph
6. `worker.py` — Dedicated worker process
7. `agents/admin.py` — Admin merge, agreement check, delta instruction builder
8. `routes/contracts.py` — Replace old upload endpoint with async run API

### Frontend (7 components)
1. `HumanReviewPanel.tsx` — New: mandatory review UI
2. `App.tsx` — Replace fake flow with backend-driven run state + SSE
3. `UploadForm.tsx` — Add metadata inputs (tenant_id, policy_family_id, etc.)
4. `PipelineTracker.tsx` — Replace timers with real stage status rendering
5. `VerdictCard.tsx` — Run-aware verdict with branch grouping and consensus
6. `api.ts` — Replace upload client with run API client + SSE
7. `types/index.ts` — Replace flat types with full run-state-contract interfaces

### Infrastructure
1. Create `.env` file with `GEMINI_API_KEY` and `POSTGRES_DSN`
2. Create `alembic.ini` for migration execution
3. Run `alembic upgrade head` to create all 9 tables
4. Start worker process separately from FastAPI server

---

*Last updated: 2026-04-03. Maintained by the AI Orchestrator.*
```

---

This is the complete `orchestrator.md`. It covers:

1. **Project Overview** — what Verdict is (multi-agent legal contract review)
2. **Architecture** — provider boundary pattern, stage queue, SSE, human gate
3. **Folder Structure** — every file marked with ✅/⚠️/❌ status
4. **Tech Stack** — all languages, frameworks, tools
5. **Good to Know** — missing `.env`, no `alembic.ini`, fake frontend, dual DB engines, agent differentiation, fine-tuning strategy, known architecture gaps

**Want me to write this to the file?**
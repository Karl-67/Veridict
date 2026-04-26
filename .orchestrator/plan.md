# Task

[Pasted text #1 — 47 lines]:
I will now send you the project rubric, that has everything required for the project, All of these should be met fully, and completely. I want you at the end to make a md file of the things that you can’t touch or make at this point in time, i want you to check the features, and check if the prompting is at it’s best for our use case. 
We should have the infrastructure for rag where you can just add (contracts/policies)pdfs, and it’s then added to the model knowledge base such that Harvey can actually check with them so they don’t have contracts that contradict with anything new or have policies that contradict with anything older. The contracts and policies that you can see at the moment are for training, we don’t have current contracts that will be used for rag, Harvey should have access to this rag information at the beginning so Harvey knows the context from the policies or contracts in addition to the contract the user uploads for review. 
Search for the Best platform for Deployment and put it in an md file, want to deploy a fine tuned gemma 4 26b models with 3 non fine tuned ones. everything you see within the system Harvey will have 3 other harveys to verify it’s work and kira the same. 
The problem we want to solve is to make an application for organizations that handle large contract volumes and want to reduce legal spend and review time. 
I also want you at the end to make an md file with every change made and to what extent do we currently.
We also want you to make a testing suit, of how to prove that fine tuned models were better then non fine tuned models, we want numbers, at the moment i don’t have finetuned models in the codebase, so you will make the pipeline with an interface so we can add the agents later on. 
Only Harvey will have access to rag. 
Harvey will check the context with other policies and give possible contradictions, and Kira will check if the sent (input) clauses and contracts have holes within them. 
The admin will make the consensus between the two outputs. 

Here is the whole project rubric which everything should be fully met. 
Live demo, public endpoint, end-to-end user flow.
Deployed API URL, cloud architecture, end-to-end behavior.
Architecture diagram, repo services, Docker services, API boundaries.
Repo, docs, deployment link, demo readiness, poster if required.
Project framing, problem statement or research framing, novelty/publishability evidence.
Architecture, repo, model/pipeline logic, deployed behavior.
Service boundary, code, container, endpoint contract, role in the system.
Service boundary, code, container, endpoint contract, role in the system.
External API code, request flow, orchestration logic, validation, request limits.
Tradeoffs section, benchmarks, experiments, measurements.
Demo behavior, outputs, logs, error cases, failure handling, test evidence.
Architecture docs, endpoint specs, service responsibilities, schemas.
Input schemas, payload constraints, validation code, limits/rate controls.
Error behavior, logs, timeout/retry policy, fallback behavior, docs.
Dockerfiles, image list, Docker Compose, Kubernetes manifests.
Deployment diagram, cloud setup, secrets strategy, cost notes.
Project statement, slides, docs, intro framing.
Baselines, comparisons, benchmark section, experiments.
Results, justification section, comparative evidence.
Business case, deployer/payer claim, target venue, paper draft, benchmark artifact.
Live presentation/demo.
Slides, verbal explanation, diagrams, walkthrough.
Metrics, benchmarks, tests, dashboards, tables, visuals.
Live answers, pacing, confidence, command of details.
Slides, poster, demo UI/UX, narrative impact.
Problem framing, system choice, comparison to common baselines/known demos.
Design decisions beyond minimum compliance, thoughtful constraints or clever system choices.
Repo tests, CI logs, demo of tests, coverage of unit/integration/E2E.
Golden datasets, regression checks, data validation, LLM evaluation logic, thresholds.
Commit history, authorship pattern, feature progression, issue linkage if any.
Branches, PRs/review notes, repo cleanliness, README, prompt version tracking if relevant.
Automation scripts, CI/CD, pipeline DAG, promotion/rollback logic.
MLflow/W&B/equivalent, metric history, thresholds, model/prompt selection logic.
Prometheus/Grafana/equivalent, dashboards, latency/error/throughput metrics, ML-specific signals.
Technical docs, business docs, runbook, tradeoffs section, endpoint docs, cost estimate.
Evidence of above-and-beyond work that is not already captured elsewhere.

this is everything i want you to know and do, do your best, my life depends on your output.

━━━ BACKGROUND RESEARCH (context only) ━━━
## Existing Solutions & Libraries

**Commercial comparables:** Harvey (legal AI workspace, document storage, due diligence, workflow agents), Kira (extraction-heavy contract review, provision models, Quick Study training), Ironclad (CLM integration, playbooks, clause detection, redlining), Luminance (enterprise contract intelligence, drafting support, portfolio insight). Gap: little public benchmark transparency, hard to know when AI is wrong, limited explainability beyond citations.

**Open-source/research:** PAKTON (multi-agent contract QA with RAG, similar architecture to Harvey/Kira/Admin); CUAD (510 contracts, 41 clause types, 13k+ labels); ContractNLI (contradiction/entailment reasoning); CLAUSE benchmark (tests subtle legal discrepancies).

**Tech stack:** Docling/PyMuPDF for extraction (pdfplumber currently used, should upgrade); LlamaIndex/LangChain/Haystack for chunking; pgvector/Qdrant for vector DB; bge-reranker/Cohere for reranking; vLLM/TGI for inference; Ragas/DeepEval for evaluation.

## Technical Approaches & Trade-offs

**RAG scope:** Harvey-only (no Kira RAG). Harvey retrieves from policy/contract PDFs; Kira focuses on internal holes in uploaded contract. Admin merges both. Hybrid retrieval (BM25 + embeddings) beats vector-only. Required metadata: `tenant_id`, `doc_type`, `policy_family_id`, `version`, `jurisdiction`, `source_path`, `page`, `chunk_hash`.

**Contradiction checking:** Same policy family only (safer, cheaper) vs. all-tenant search (catches more but increases false positives). Recommend phase 1 uses family + explicitly linked playbooks.

**Deployment:** Modal (Gemma + vLLM, H200 guidance, model cache volumes, public URL) > Runpod Serverless (cost, scale-to-zero) > HF Inference Endpoints (managed, expensive) > Koyeb. Suggested: Vercel frontend, Render/Fly/Modal CPU API, Neon/Supabase Postgres + pgvector, Modal vLLM for inference.

**Fine-tuned vs. baseline:** Identical prompts, retrieval context, decoding params. Metrics: JSON parse rate, contradiction F1/precision/recall, citation accuracy, hallucination rate, severity calibration, latency/cost. Use paired eval, bootstrap CI, McNemar test. Minimum claim: "fine-tuned beats base by X points on contradiction F1, reduces hallucinated citations by Y% on N examples."

## Architectural Patterns

**Current state:** 12-stage pipeline fully implemented end-to-end (create_run → parse_ocr_normalize → clause_index → harvey_context_load → kira_context_load → harvey_review_block → kira_review_block → admin_merge → final_review_block → awaiting_human_review → finalized). Multi-tenant auth, 3-reviewer branches (Harvey: issue_discovery/false_positive_challenge/exploitability_impact; Kira: same structure), admin deduplication, human review gate, vote aggregation with re-rounds, SSE event stream, exponential retry with jitter.

**Prompting issues:** No chain-of-thought elicitation; role-specific system prompts in user turn (not system role); schema hint lacks field descriptions; temperature 0.3 acceptable but validator should be 0.1; Harvey prompt missing RAG context integration.

**Test & monitoring gaps:** No repo tests exist (rubric requires unit/integration/E2E, golden datasets, LLM eval logic, thresholds); no Prometheus/Grafana; no MLflow/W&B experiment tracking; no CI/CD.

## Known Pitfalls & Challenges

- **No true RAG:** Currently Harvey loads only structured JSON from DB tables; PDF ingestion, chunking, embedding, retrieval pipeline entirely missing.
- **No fine-tuned weights:** Training pipeline complete; no trained model artifacts in codebase; all runs use base models.
- **No benchmark results:** No side-by-side evaluation runner; fine-tuning impact unproven.
- **No deployment:** Zero Docker, docker-compose, Kubernetes, cloud setup, public endpoint.
- **Parser quality:** pdfplumber first-pass; should upgrade to Docling for better evidence anchoring.
- **RISK-001:** Extraction confidence not gated downstream; low-confidence clauses not filtered before review.
- **RISK-002:** No ETL for CUAD/LEDGAR/MAUD parquets into ComplianceCorpus; corpus seeded manually.
- **RISK-008:** llama3.2:3b quality ceiling; coercion keeps pipeline running but cannot improve reasoning.

# Implementation Plan

## Shared Dependencies

`stage-topology`: active stages = create_run, ingest_pdf, parse_ocr_normalize, clause_index, harvey_context_load, kira_context_load, harvey_review_block, kira_review_block, admin_merge, awaiting_human_review, finalized; final_review_block removed (used by: app/backend/services/run_service.py, app/backend/orchestration/state_machine.py, app/frontend/src/components/PipelineTracker.tsx, docs/ARCHITECTURE.md)

`harvey-trio-contract`: 3 Harvey reviewers (issue_discovery, false_positive_challenge, exploitability_impact) + 3 Kira reviewers same structure; Admin is merge-only, no admin reviewers (used by: app/backend/agents/reviewer.py, app/backend/agents/admin.py, app/backend/orchestration/state_machine.py)

`harvey-rag-only`: only Harvey reviewers query pgvector RAG; Kira blocked at service layer (used by: app/backend/services/rag_retrieval.py, app/backend/agents/reviewer.py)

`evidence-schema`: findings carry contract_evidence[] and rag_citations[]; Harvey contradictions require ≥1 rag_citation, Kira findings require ≥1 contract_evidence (used by: app/backend/models/schemas.py, app/backend/agents/validator.py, app/frontend/src/types/index.ts)

`auth-derived-tenancy`: tenant_id/workspace_id derived from JWT membership only, never request body (used by: app/backend/routes/rag.py, app/backend/routes/contracts.py)

`rag-storage-contract`: pgvector tables for source_documents, document_versions, chunks, embeddings, ingestion_jobs, retrieval_traces with metadata {tenant_id, doc_type, policy_family_id, version, jurisdiction, source_path, page, chunk_hash} (used by: app/backend/db/models.py, app/backend/services/rag_ingestion.py, app/backend/services/rag_retrieval.py)

`parser-confidence-contract`: Docling primary → OCR → pdfplumber fallback; per-clause confidence propagated; <0.6 = warning, <0.3 = blocked unless override (used by: app/backend/services/parser.py, app/backend/orchestration/state_machine.py)

`model-registry-contract`: configs/models.yaml lists 1 fine-tuned Gemma 26B + 3 baselines; missing endpoints report `N/A - weights pending` not crash (used by: scripts/eval_*.py, docs/EVALUATION_PLAN.md)

`observability-contract`: Prometheus metrics for run status, stage duration, provider latency, JSON repair, retrieval hits, citation failures, queue age, retry count (used by: app/backend/services/metrics.py, app/backend/main.py, app/backend/worker.py)

## Files

### app/backend/services/run_service.py (MODIFY)
- Remove `final_review_block` from `STAGE_SEQUENCE`; new runs use `stage-topology`.
- Update `_load_full_findings()` source priority to {admin, harvey, kira} only.
- Update `_build_final_verdict()` to expose Harvey trio consensus, Kira findings, Admin merged findings, unresolved_by_consensus flags, evidence per `evidence-schema`.
- Update `submit_human_review()` and `finalize_run_if_approved()` to finalize directly after admin_merge + human review.
- Add legacy compatibility branch: existing runs with final_review_block render read-only but never re-enqueue.
- Tenant derivation in run creation must use `auth-derived-tenancy`.

### app/backend/orchestration/state_machine.py (MODIFY)
- Delete `_enqueue_final_review_stage()` and `FinalReviewerAgent` import.
- `harvey_review_block` fans out to 3 Harvey reviewers per `harvey-trio-contract`, each receiving uploaded contract clauses + ranked RAG retrieval trace from `harvey_context_load`.
- `kira_review_block` fans out to 3 Kira reviewers; must NOT call `rag_retrieval.py`.
- `admin_merge` consumes Harvey trio + Kira trio outputs only; transitions directly to `awaiting_human_review`.
- Fix `_stage_output()` ordering by (round_number DESC, attempt_number DESC, finished_at DESC) — closes BUG-012.
- Honor `parser-confidence-contract` blocked state by halting before review stages and emitting blocked SSE event.
- SSE events emit only stages in `stage-topology`.

### app/backend/agents/reviewer.py (MODIFY)
- Remove `FinalReviewerAgent`.
- Define `HarveyReviewer` with role variants: `issue_discovery`, `false_positive_challenge`, `exploitability_impact`.
- Each Harvey reviewer prompt: contradiction-checking task, must cite `rag_citations` by chunk_id, must cite `contract_evidence` by clause_id, no chain-of-thought, strict JSON, uncertainty flag required when confidence<0.7.
- Define `KiraReviewer` mirroring 3 roles; prompt focuses on internal holes/ambiguity/missing protections; explicitly forbidden from rag_citations.
- Move role instructions to provider system role (via `providers/base.py` system field).
- Default reviewer temperature 0.2; pass through provider call.
- Output schema matches `evidence-schema`: `{findings: [{contract_evidence, rag_citations, severity, exploitability, business_impact, unresolved_by_consensus, rationale, uncertainty}]}`.

### app/backend/agents/admin.py (MODIFY)
- `ConsensusAdmin.merge()` accepts `(harvey_trio_outputs, kira_trio_outputs)`; deduplicates findings via clause_id + finding_type clustering.
- `AgreementAdmin.check()` computes Harvey 3-way agreement and Kira 3-way agreement; returns `consensus_state ∈ {unanimous, majority, split}`.
- Remove all final/admin reviewer code paths.
- Output schema includes `merged_findings`, `consensus_state`, `unresolved_by_consensus`, `harvey_agreement`, `kira_agreement`.

### app/backend/agents/validator.py (MODIFY)
- Validator temperature 0.1.
- `validate_harvey_finding()`: reject if `rag_citations` empty; reject if any chunk_id not in run's retrieval_trace; reject if contract_evidence clause_id not in parsed clauses.
- `validate_kira_finding()`: reject if `contract_evidence` empty; reject if any `rag_citations` present.
- Return structured `ValidationError {code, field, message}`; codes: `MISSING_RAG_CITATION`, `INVALID_CHUNK_ID`, `KIRA_RAG_FORBIDDEN`, `MISSING_CONTRACT_EVIDENCE`, `MALFORMED_JSON`.

### app/backend/models/schemas.py (MODIFY)
- Add Pydantic models: `ContractEvidence(clause_id, page, span, text, confidence)`, `RagCitation(chunk_id, document_id, version, page, source_path, chunk_hash, score)`, `RetrievalTraceItem`, `HarveyReviewerOutput`, `HarveyTrioConsensus`, `KiraReviewerOutput`, `AdminConsensusOutput`, `RagDocumentCreate`, `RagDocumentResponse`, `RagIngestionStatus`, `ModelRegistryEntry`, `EvalMetricRow`.
- Update `Finding`, `ReviewResult`, `FinalVerdict` with branch grouping, `consensus_state`, evidence fields, `exploitability`, `business_impact`, `unresolved_by_consensus`.
- Drop active `final_reviewer` references; keep optional fields tagged `legacy=True`.

### app/backend/db/models.py (MODIFY)
- Add ORM models: `RagSourceDocument`, `RagDocumentVersion`, `RagChunk`, `RagEmbedding(vector pgvector(N))`, `RagIngestionJob(status, error, started_at, finished_at)`, `RagRetrievalTrace(run_id, clause_id, chunk_ids[], scores[], created_at)`.
- Extend `FindingRecord` JSON to carry `contract_evidence`, `rag_citations`, `consensus_state`, `business_impact`, `exploitability`, `unresolved_by_consensus`.
- Indexes: `(tenant_id, workspace_id, policy_family_id, doc_type)`, unique `(document_id, version)`, unique `(version_id, chunk_hash)`, `(run_id, clause_id)` on traces, ivfflat or hnsw on embedding column.

### app/backend/alembic/versions/0003_add_harvey_rag.py (CREATE)
- `CREATE EXTENSION IF NOT EXISTS vector`.
- Create rag_source_documents, rag_document_versions, rag_chunks, rag_embeddings, rag_ingestion_jobs, rag_retrieval_traces.
- Add finding JSONB schema upgrade for new evidence fields with default `{}`.
- Add indexes per `rag-storage-contract`.
- Idempotent re: legacy final_review_block rows (do not delete).

### app/backend/services/parser.py (MODIFY)
- Add `parse_document(path) → ParsedDoc` orchestrator: try `parse_with_docling()`, on fail/empty try `parse_with_ocr_fallback()` (tesseract via pytesseract), else `parse_with_pdfplumber_fallback()`.
- `compute_clause_confidence()` blends extractor confidence + OCR signal + heuristic (text length, char dist).
- Return `{pages[], clauses[{id, text, page, bbox, confidence, source_extractor}]}` consumed by `parser-confidence-contract`.
- Preserve existing public function signatures used by clause_index stage.

### app/backend/services/rag_ingestion.py (CREATE)
- `RagIngestionService` with: `create_ingestion_job(file, doc_type, policy_family_id, jurisdiction, version_label, tenant_id, workspace_id)`, `ingest_document(job_id)`, `chunk_document(parsed_doc, size, overlap)`, `compute_file_hash(bytes)`, `compute_chunk_hash(text)`, `embed_chunks(chunks)`, `activate_new_version(version_id)`, `soft_delete_previous_active(document_id)`, `mark_job_failed(job_id, error)`.
- Validate doc_type ∈ {policy, reference_contract, playbook}; enforce 50MB / 500 page limit; reject duplicate file_hash with 409; dedupe chunks by chunk_hash within version.
- New version activated only after successful embedding; on failure prior active version remains.
- Async via worker queue.

### app/backend/services/rag_retrieval.py (CREATE)
- `HarveyRagRetriever` with: `retrieve_for_run(run_id, clauses) → list[RetrievalTraceItem]`, `retrieve_for_clause(clause, scope) → list[RagCitation]`, `hybrid_search(query, scope, k)`, `vector_search`, `text_search` (postgres tsvector BM25-ish), `rerank_results` (bge-reranker hook, no-op stub if unavailable), `persist_retrieval_trace`, `validate_citation_ids(chunk_ids, run_id)`.
- Scope filter: `(tenant_id, workspace_id, active_version, policy_family_id ∈ {target, linked_playbooks, linked_reference_contracts})`.
- Caller identity guard: raise `RagAccessForbidden` if caller role != harvey.

### app/backend/services/embeddings.py (CREATE)
- `EmbeddingProvider` ABC with `embed_texts(list[str]) → list[list[float]]`, `dimensions: int`.
- Implementations: `LocalEmbeddingProvider` (sentence-transformers), `OpenAICompatibleEmbeddingProvider` (Ollama nomic-embed-text default).
- `get_embedding_provider()` factory from settings.
- Batch size 32, normalize L2.

### app/backend/services/metrics.py (CREATE)
- Prometheus client setup; counters/histograms per `observability-contract`: `runs_total{status}`, `stage_duration_seconds{stage}`, `provider_latency_seconds{provider,model}`, `provider_failures_total`, `json_repair_total`, `retrieval_hits_total`, `citation_validation_failures_total{code}`, `queue_age_seconds`, `retry_total{stage}`, `worker_lease_expiry_total`.
- `setup_metrics(app)` mounts `/metrics`.

### app/backend/routes/rag.py (CREATE)
- `APIRouter(prefix="/api/rag")`.
- `POST /documents` (admin only): multipart upload → enqueue ingestion → return job_id.
- `GET /documents`: list for caller's tenant/workspace.
- `GET /documents/{id}`: detail with active version, chunk count.
- `GET /ingestions/{job_id}`: status + error.
- `DELETE /documents/{id}`: soft-delete active version.
- All endpoints derive tenant via `auth-derived-tenancy`; reject if user role not admin/workspace_admin.

### app/backend/routes/contracts.py (MODIFY)
- Remove `tenant_id` form parameter from `POST /api/runs`; derive from JWT.
- Findings response includes `evidence-schema` fields.
- Retry endpoint must not enqueue `final_review_block`.
- Add `parser_confidence_state` field to run detail response.

### app/backend/main.py (MODIFY)
- Mount `rag_router`.
- Call `setup_metrics(app)` to expose `/metrics`.
- Replace hardcoded CORS origins with `settings.cors_origins`.
- Startup hook validates: DB connectable, embedding provider reachable, `configs/models.yaml` parseable.

### app/backend/core/config.py (MODIFY)
- Add: `parser_primary` (docling), `ocr_enabled`, `pdfplumber_fallback_enabled`, `rag_max_file_mb=50`, `rag_max_pages=500`, `rag_chunk_size=800`, `rag_chunk_overlap=100`, `rag_top_k=20`, `rag_rerank_top_k=5`, `embedding_provider`, `embedding_dimensions`, `pgvector_enabled`, `model_registry_path`, `metrics_enabled`, `cors_origins: list[str]`, `reviewer_temperature=0.2`, `validator_temperature=0.1`.

### app/backend/providers/base.py (MODIFY)
- Provider interface: `complete(system: str, user: str, temperature: float, response_format: dict|None) → ProviderResponse`.
- Add `ModelEndpoint` dataclass with `name, role, is_finetuned, provider_url, api_key_env, enabled, timeout_seconds, cost_per_1k`.
- Strict JSON response_format honored when supported.

### app/backend/providers/google_provider.py (MODIFY)
- Use Gemini system_instruction for system prompt.
- Per-call temperature.
- Wrap with `record_provider_call()` metric.

### app/backend/providers/openrouter_provider.py (MODIFY)
- Use OpenAI-compat `messages=[{role:system},{role:user}]`.
- Per-call temperature.
- Wrap with `record_provider_call()` metric.

### app/backend/services/policy_repository.py (MODIFY)
- Add `get_policy_family(family_id)`, `list_linked_playbooks(family_id)`, `list_reference_contracts_for_family(family_id)`, `resolve_harvey_rag_scope(run) → RagScope`.

### app/backend/services/compliance_repository.py (MODIFY)
- Add docstring clarifying this is Kira's structured corpus only, not pgvector RAG.
- Assert no caller queries `rag_chunks`/`rag_embeddings`.

### app/backend/worker.py (MODIFY)
- Add metrics: queue age on dequeue, retry counter on failed jobs, lease expiry counter.
- Process new job type `rag_ingestion` via `RagIngestionService.ingest_document`.
- Skip claiming any `final_review_block` job.

### app/backend/requirements.txt (MODIFY)
- Add: `docling`, `pytesseract`, `pgvector`, `sentence-transformers`, `prometheus-client`, `mlflow`, `pytest`, `pytest-asyncio`, `httpx`, `respx`.

### app/frontend/src/types/index.ts (MODIFY)
- Add types matching `evidence-schema` and RAG schemas.
- Remove `final_review_block` from stage union; add `awaiting_human_review`, `blocked`, `retrying` states.

### app/frontend/src/lib/api.ts (MODIFY)
- Add: `uploadRagDocument`, `listRagDocuments`, `getRagDocument`, `getRagIngestionStatus`, `deleteRagDocument`.
- Update run mappers for new evidence fields and parser confidence state.

### app/frontend/src/components/PipelineTracker.tsx (MODIFY)
- Stage list per `stage-topology`; remove final_review_block.
- Render parser confidence warning/blocked badge.
- Show "Harvey 1/2/3" sub-state under harvey_review_block.

### app/frontend/src/components/VerdictCard.tsx (MODIFY)
- Sections: Harvey Trio (with consensus_state badge), Kira Trio, Admin Merged, Human Action.
- Render contract_evidence and rag_citations as separate citation chips; Harvey citations link to source PDF page via document_id+page.
- Show unresolved_by_consensus banner.

### app/frontend/src/components/HumanReviewPanel.tsx (MODIFY)
- Display Admin merged findings with approve/edit/reject per finding.
- Show Harvey + Kira agreement badges.
- Show validator warnings inline.

### app/frontend/src/components/AdminPage.tsx (MODIFY)
- Add tab/section rendering `<RagDocumentPanel/>` for admin/workspace_admin role.

### app/frontend/src/components/RagDocumentPanel.tsx (CREATE)
- Components: `RagDocumentPanel`, `RagUploadForm` (file, doc_type select, policy_family_id, jurisdiction, version_label), `RagIngestionStatusList`, `RagDocumentTable`, `RagDocumentDetailDrawer`.
- Polls `/api/rag/ingestions/{job_id}` until terminal status.

### app/frontend/src/App.tsx (MODIFY)
- Remove final_review_block routing assumptions.
- Route human review entry after `awaiting_human_review`.

### app/frontend/src/components/AIEngineInsights.tsx (MODIFY)
- Update copy: "3 Harvey + 3 Kira reviewers, Admin consensus merge, Harvey-only RAG".

### configs/models.yaml (CREATE)
- Entries: `gemma_26b_finetuned` (enabled:false, is_finetuned:true), `gemma_26b_base` (enabled:false, is_finetuned:false), `baseline_legal_1`, `baseline_legal_2`.
- Each: name, role_support, provider_url, api_key_env, enabled, is_finetuned, decoding{temperature,top_p,max_tokens}, timeout_seconds, notes.

### scripts/eval_model_registry.py (CREATE)
- `ModelRegistry`, `load_model_registry(path)`, `validate_model_registry()`, `iter_enabled_models()`, `mark_missing_as_pending()`.
- Health-checks each enabled endpoint; disabled fine-tuned → emits `N/A - weights pending` row.

### scripts/eval_finetune_vs_baseline.py (CREATE)
- `EvalRunner.run_eval_suite(dataset_path, models)`: load CUAD/ContractNLI fixtures, run identical prompts/retrieval/decoding across models, capture per-role and full-pipeline outputs.
- `evaluate_role_outputs`, `evaluate_full_pipeline`, `write_markdown_report`, `write_json_results`.
- Paired comparison + bootstrap CI + McNemar.

### scripts/eval_metrics.py (CREATE)
- `json_validity_rate`, `contradiction_prf`, `citation_accuracy`, `hallucinated_citation_rate`, `severity_calibration` (Brier/ECE), `admin_agreement_rate`, `latency_cost_summary`, `bootstrap_confidence_interval(n=1000)`, `mcnemar_test`.

### tests/conftest.py (CREATE)
- Fixtures: `db_session` (test postgres + pgvector), `fake_provider`, `sample_contract_pdf`, `sample_policy_pdf`, `auth_admin_user`, `auth_member_user`, `seeded_rag_corpus`.

### tests/test_stage_topology.py (CREATE)
- Assert new run stages == `stage-topology`.
- Assert no final_review_block rows for new runs.
- Assert SSE event stream excludes final_review_block.
- Assert legacy run with final_review_block still finalizes.

### tests/test_harvey_trio_consensus.py (CREATE)
- Assert exactly 3 Harvey + 3 Kira reviewer outputs per run.
- Assert agreement calculation for unanimous/majority/split fixtures.
- Assert admin merge handles unresolved consensus.

### tests/test_rag_ingestion.py (CREATE)
- Upload → job created → completion creates active version.
- Duplicate file hash → 409.
- Chunk hash dedupe within version.
- Failed embedding → prior active version retained.
- Tenant A cannot see tenant B documents.

### tests/test_rag_retrieval.py (CREATE)
- Filter by tenant/workspace/policy_family/jurisdiction.
- Kira caller raises `RagAccessForbidden`.
- Retrieval trace persisted with chunk_ids.
- `validate_citation_ids` rejects foreign chunk_ids.

### tests/test_parser_confidence.py (CREATE)
- Docling primary path returns clauses with confidence.
- Image-only PDF triggers OCR fallback.
- Corrupt PDF triggers pdfplumber fallback then blocked state.
- Confidence <0.3 → blocked; <0.6 → warning; override path audited.

### tests/test_validator_evidence.py (CREATE)
- Harvey finding without rag_citations → `MISSING_RAG_CITATION`.
- Harvey citation with chunk_id not in trace → `INVALID_CHUNK_ID`.
- Kira finding with rag_citations → `KIRA_RAG_FORBIDDEN`.
- Kira finding without contract_evidence → `MISSING_CONTRACT_EVIDENCE`.
- Valid findings pass.

### tests/test_run_lifecycle.py (CREATE)
- E2E: upload → parse → harvey_context_load → kira_context_load → harvey/kira review → admin_merge → awaiting_human_review → finalized.
- Findings endpoint includes evidence + consensus.
- Human approve/edit/reject flows.

### tests/test_eval_metrics.py (CREATE)
- Unit tests for each metric in `scripts/eval_metrics.py`.
- Disabled fine-tuned endpoint produces `N/A - weights pending`.

### Dockerfile.api (CREATE)
- python:3.11-slim base; install tesseract-ocr, poppler-utils for Docling/OCR.
- Copy app/backend, install requirements.
- Run `uvicorn app.backend.main:app --host 0.0.0.0 --port 8000`.

### Dockerfile.worker (CREATE)
- Same base + system deps as api.
- Run `python -m app.backend.worker`.

### Dockerfile.frontend (CREATE)
- node:20-alpine build stage → nginx:alpine serve stage.
- Build Vite app, serve dist on port 80.

### docker-compose.yml (CREATE)
- Services: `postgres` (pgvector/pgvector:pg16, named volume), `api` (Dockerfile.api, depends_on postgres healthy), `worker` (Dockerfile.worker), `frontend` (Dockerfile.frontend), optional `ollama`.
- Healthchecks on postgres and api.
- Env via `.env`; no secrets committed.

### .github/workflows/ci.yml (CREATE)
- Jobs: `backend-test` (ruff, mypy optional, pytest with postgres+pgvector service), `frontend-build` (npm ci, tsc, build), `docker-build` (build all Dockerfiles).
- Upload pytest junit + coverage artifacts.

### .github/workflows/eval.yml (CREATE)
- `workflow_dispatch` only.
- Loads model API keys from secrets; runs `scripts/eval_finetune_vs_baseline.py`; uploads markdown + JSON reports as artifacts.
- Missing fine-tuned endpoint → `N/A - weights pending`, not failure.

### docs/CURRENT_LIMITATIONS.md (CREATE)
- Sections: Impossible Now, Blocked by Missing Weights, Blocked by Missing Secrets/Cloud, Deferred by Scope, Implemented but Not Benchmark-Proven.
- List: no fine-tuned Gemma 26B weights, no production RAG corpus until customer PDFs uploaded, no live deployment URL until Modal/Vercel secrets set, benchmark superiority claims pending eval run.

### docs/CHANGELOG_IMPLEMENTATION.md (CREATE)
- Per-file change log with rubric extent rating (full/partial/pending).
- Sections per milestone: pipeline topology, RAG, evaluation, deployment, observability, tests, docs.

### docs/DEPLOYMENT_RESEARCH.md (CREATE)
- Compare Modal vs RunPod Serverless vs HF Inference Endpoints vs Koyeb on: VRAM for Gemma 26B (needs ≥48GB → H100/H200 or 2×A100), cold start, public URL, secrets, scale-to-zero, monthly demo cost, production cost.
- Recommendation: Vercel (frontend) + Modal CPU (FastAPI/worker) + Neon Postgres+pgvector + Modal vLLM H200 (inference).

### docs/EVALUATION_PLAN.md (CREATE)
- Test suite: 1 fine-tuned Gemma 26B vs 3 baselines on identical prompts/retrieval/decoding.
- Metrics, paired eval, bootstrap CI, McNemar.
- Datasets: CUAD, ContractNLI subset, internal golden set.
- Reporting: per-model × per-role × full-pipeline tables.
- Claim policy: no superiority claim until p<0.05 + CI excludes 0.

### docs/API_SPEC.md (CREATE)
- Document all run + RAG endpoints with schemas, auth requirements, file limits, error codes, SSE event types, retry/timeout policy, evidence/citation rules.

### docs/ARCHITECTURE.md (CREATE)
- Service boundaries diagram (frontend/api/worker/postgres+pgvector/inference).
- Pipeline DAG per `stage-topology`; 3 Harvey + 3 Kira + Admin merge + human review.
- Harvey-only RAG flow; Kira blocked path.
- Deployment topology.

### docs/RAG_DESIGN.md (CREATE)
- Ingestion → parsing → chunking (800 tok / 100 overlap) → embedding → pgvector.
- Hybrid retrieval (vector + tsvector BM25) + optional bge-reranker.
- Metadata schema, retrieval traces, citation validation.
- Versioning, dedupe, rollback semantics.

### docs/RUNBOOK.md (CREATE)
- Local setup, migrations, docker-compose up, demo data seeding, RAG ingestion walkthrough, run lifecycle demo, metrics dashboard pointer, eval runner usage, deployment, secrets, rollback, troubleshooting.

### app/README.md (MODIFY)
- Update architecture summary to 3 Harvey + 3 Kira + Admin merge + human review + Harvey-only RAG.
- Link to all docs/*.md.
- Remove stale Anthropic-only references.

### AGENTS.md (MODIFY)
- Record active topology, Harvey-only RAG rule, evidence schema, and doc update requirement after architecture changes.

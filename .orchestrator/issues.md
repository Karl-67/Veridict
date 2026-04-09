# Issues / Work Log

Automatically maintained by AI Orchestrator and the project-memory skill.

---

## Open Risks

### RISK-001 — Parser confidence not propagated
**Status:** Open
`parse_pdf_to_canonical_document` returns clauses but per-clause `extraction_confidence` is not yet gated on by downstream agents.
**Acceptance:** `build_clause_index` filters/marks low-confidence clauses; state machine checks confidence before reviewer dispatch.

### RISK-002 — Corpus ingestion has no ETL pipeline
**Status:** Open
`data/atticus/` and `data/legal_clauses/` parquet files exist but no script loads them into `ComplianceCorpusRecord`. Corpus seeded manually on 2026-04-08 via SQL (demo-tenant/default/v1, US/general).
**Acceptance:** At least one corpus type loadable via `resolve_applicable_corpora` from DB with version/jurisdiction/effective-date populated.

### RISK-008 — Small model (llama3.2:3b) quality ceiling
**Status:** Open
llama3.2 is 3B parameters. Analysis quality is limited — the coercion and json-repair layers keep the pipeline running but cannot improve the model's reasoning. Larger models (7B+) recommended for production-quality legal analysis.
**Acceptance:** Document minimum recommended model size, or confirm llama3.2 quality is acceptable for the use case.

---

## Phase 1 Exit Criteria

| # | Checkpoint | Status |
|---|-----------|--------|
| A | Parser returns confidence-scored clauses (RISK-001) | Open |
| B | Compliance corpus loadable from DB (RISK-002) | Partial (manual seed only) |
| C | Alembic migration runs clean | Done |
| D | No run reaches `run_finalized` without `human_approved` | Done |
| E | All LLM calls through `StructuredLLMProvider` | Done |
| F | SSE persists and replays from `last_event_id` | Done |
| G | All agent classes wired to state machine | Done |
| H | Full end-to-end pipeline verified | **Done 2026-04-09** |

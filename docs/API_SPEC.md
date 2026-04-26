# API Spec

## Runs

- `POST /api/runs`: upload contract PDF. Tenant must come from auth membership, not request body.
- `GET /api/runs/{id}`: run detail, stages, verdict, blocked reason.
- `GET /api/runs/{id}/events`: SSE events.
- `POST /api/runs/{id}/human-review`: approve, edit, or reject Admin merged findings.
- `POST /api/runs/{id}/retry`: retry blocked/failed stages without re-enqueuing `final_review_block`.

## RAG

- `POST /api/rag/documents`: admin/workspace admin PDF upload. Form fields: `file`, `doc_type`, `policy_family_id`, `jurisdiction`, `version_label`.
- `GET /api/rag/documents`: tenant-scoped document list.
- `GET /api/rag/documents/{id}`: document detail.
- `GET /api/rag/ingestions/{job_id}`: ingestion status.
- `DELETE /api/rag/documents/{id}`: soft delete active version.

## Evidence Rules

- Harvey findings require at least one RAG citation.
- Kira findings require at least one contract evidence anchor and must not include RAG citations.
- Citations must reference chunks found in the run retrieval trace.

## SSE Events

Only active topology stages are emitted for new runs: `create_run`, `ingest_pdf`, `parse_ocr_normalize`, `clause_index`, `harvey_context_load`, `kira_review_block`, `admin_merge`, `awaiting_human_review`, `finalized`.

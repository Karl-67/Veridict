# RAG Design

## Ingestion

Uploaded PDFs are parsed, chunked with 800 token windows and 100 token overlap, embedded, then activated as a new version only after embedding succeeds.

## Storage

- `rag_source_documents`: tenant/workspace document identity.
- `rag_document_versions`: active and historical versions.
- `rag_chunks`: deduplicated chunk text and metadata.
- `rag_embeddings`: pgvector embeddings.
- `rag_ingestion_jobs`: async status.
- `rag_retrieval_traces`: run/clause citation audit trail.

## Retrieval

Hybrid retrieval combines text search and vector search. The current scaffold uses grounded text retrieval as the dependable path and leaves pgvector ANN tuning behind `vector_search`.

Harvey is the only component that performs retrieval. It returns citation candidates and retrieval traces; it does not create final issue findings.

## Validation

Kira findings may reference Harvey-provided citations, but Kira must not query RAG directly. Admin consensus validates that output citations point to chunks present in the run retrieval trace.

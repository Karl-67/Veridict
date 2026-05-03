from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backend.core.config import Settings, get_settings
from app.backend.db.models import RagChunk, RagDocumentVersion, RagRetrievalTrace, RagSourceDocument, RunRecord
from app.backend.models.schemas import RagCitation, RetrievalTraceItem


class RagAccessForbidden(PermissionError):
    pass


@dataclass
class RagScope:
    tenant_id: str
    workspace_id: str | None
    policy_family_id: str | None
    jurisdiction: str | None


class HarveyRagRetriever:
    def __init__(self, session: Session, settings: Settings | None = None, caller_role: str = "harvey") -> None:
        if caller_role != "harvey":
            raise RagAccessForbidden("Only Harvey reviewers may query pgvector RAG")
        self.session = session
        self.settings = settings or get_settings()

    def retrieve_for_run(self, run_id: str, clauses: list[dict]) -> list[RetrievalTraceItem]:
        run = self.session.get(RunRecord, run_id)
        if run is None:
            return []
        scope = RagScope(
            tenant_id=run.tenant_id,
            workspace_id=getattr(run, "workspace_id", None),
            policy_family_id=run.policy_family_id,
            jurisdiction=run.jurisdiction,
        )
        traces: list[RetrievalTraceItem] = []
        for clause in clauses:
            citations = self.retrieve_for_clause(clause, scope)
            traces.append(
                RetrievalTraceItem(
                    run_id=run_id,
                    clause_id=clause.get("clause_uid") or clause.get("id") or "unknown",
                    query_text=clause.get("normalized_text") or clause.get("text") or "",
                    strategy="hybrid",
                    citations=citations,
                    retrieved_at=datetime.utcnow(),
                )
            )
            self.persist_retrieval_trace(run_id, traces[-1].clause_id, citations)
        self.session.flush()
        return traces

    def retrieve_for_clause(self, clause: dict, scope: RagScope) -> list[RagCitation]:
        query = clause.get("normalized_text") or clause.get("text") or ""
        results = self.hybrid_search(query, scope, self.settings.rag_top_k)
        return self.rerank_results(results)[: self.settings.rag_rerank_top_k]

    def hybrid_search(self, query: str, scope: RagScope, k: int) -> list[RagCitation]:
        text_results = self.text_search(query, scope, k)
        vector_results = self.vector_search(query, scope, k)
        by_chunk: dict[str, RagCitation] = {}
        for item in text_results + vector_results:
            existing = by_chunk.get(item.chunk_id)
            if existing is None or item.score > existing.score:
                by_chunk[item.chunk_id] = item
        return sorted(by_chunk.values(), key=lambda item: item.score, reverse=True)[:k]

    def vector_search(self, query: str, scope: RagScope, k: int) -> list[RagCitation]:
        # Placeholder until pgvector query tuning lands; text search keeps citations grounded.
        return self.text_search(query, scope, k)

    def text_search(self, query: str, scope: RagScope, k: int) -> list[RagCitation]:
        terms = {term.lower().strip(".,;:()[]{}") for term in query.split() if len(term) > 3}

        # Build base query — always scoped to tenant and active versions only.
        base_stmt = (
            select(RagChunk, RagDocumentVersion, RagSourceDocument)
            .join(RagDocumentVersion, RagDocumentVersion.id == RagChunk.version_id)
            .join(RagSourceDocument, RagSourceDocument.id == RagDocumentVersion.document_id)
            .where(
                RagSourceDocument.tenant_id == scope.tenant_id,
                RagSourceDocument.is_deleted.is_(False),
                RagDocumentVersion.is_active.is_(True),
            )
            .limit(max(k * 8, 64))
        )
        if scope.policy_family_id:
            base_stmt = base_stmt.where(RagSourceDocument.policy_family_id == scope.policy_family_id)

        # Try progressively looser scopes so metadata mismatches don't silently
        # hide documents that were legitimately uploaded to the corpus.
        # Pass 1: workspace + jurisdiction (strictest)
        # Pass 2: workspace only
        # Pass 3: tenant-wide (loosest — always finds something if docs exist)
        scopes_to_try: list[object] = []
        stmt_strict = base_stmt
        if scope.workspace_id:
            stmt_strict = stmt_strict.where(RagSourceDocument.workspace_id == scope.workspace_id)
        if scope.jurisdiction:
            stmt_strict = stmt_strict.where(RagSourceDocument.jurisdiction == scope.jurisdiction)
        scopes_to_try.append(stmt_strict)

        if scope.jurisdiction:
            stmt_no_jur = base_stmt
            if scope.workspace_id:
                stmt_no_jur = stmt_no_jur.where(RagSourceDocument.workspace_id == scope.workspace_id)
            scopes_to_try.append(stmt_no_jur)

        scopes_to_try.append(base_stmt)  # tenant-wide fallback

        rows = []
        for stmt in scopes_to_try:
            rows = self.session.execute(stmt).all()
            if rows:
                break

        def _score_row(chunk, _version, _document) -> float:
            if not terms:
                return 0.1
            chunk_terms = {term.lower().strip(".,;:()[]{}") for term in chunk.text.split()}
            overlap = len(terms & chunk_terms)
            return min(1.0, overlap / max(1, len(terms)))

        citations: list[RagCitation] = []
        for chunk, version, document in rows:
            score = _score_row(chunk, version, document)
            citations.append(
                RagCitation(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    version=version.version_label or str(version.version),
                    page=chunk.page_number or 1,
                    source_path=document.source_path,
                    chunk_hash=chunk.chunk_hash,
                    score=score,
                )
            )

        # Sort by score descending; if everything scored 0 (no term overlap), keep top-k
        # by DB order so Harvey still gets policy context rather than an empty corpus.
        return sorted(citations, key=lambda item: item.score, reverse=True)[:k]

    def rerank_results(self, results: list[RagCitation]) -> list[RagCitation]:
        return sorted(results, key=lambda item: item.score, reverse=True)

    def persist_retrieval_trace(self, run_id: str, clause_id: str, citations: list[RagCitation]) -> None:
        self.session.add(
            RagRetrievalTrace(
                run_id=run_id,
                clause_id=clause_id,
                chunk_ids=[citation.chunk_id for citation in citations],
                scores=[citation.score for citation in citations],
            )
        )

    def validate_citation_ids(self, chunk_ids: list[str], run_id: str) -> bool:
        traces = self.session.scalars(select(RagRetrievalTrace).where(RagRetrievalTrace.run_id == run_id)).all()
        allowed = {chunk_id for trace in traces for chunk_id in (trace.chunk_ids or [])}
        return set(chunk_ids).issubset(allowed)

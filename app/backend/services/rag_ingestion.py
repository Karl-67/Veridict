from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.backend.core.config import Settings, get_settings
from app.backend.db.models import (
    RagChunk,
    RagDocumentVersion,
    RagEmbedding,
    RagIngestionJob,
    RagSourceDocument,
)
from app.backend.services.embeddings import get_embedding_provider
from app.backend.services.parser import ParsedDoc, parse_document

VALID_DOC_TYPES = {"policy", "reference_contract", "playbook"}


@dataclass
class RagChunkInput:
    text: str
    page: int | None
    metadata: dict


class RagIngestionService:
    def __init__(self, session: AsyncSession | Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    @staticmethod
    def compute_file_hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def compute_chunk_hash(text: str) -> str:
        return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

    async def create_ingestion_job(
        self,
        file: UploadFile,
        doc_type: str,
        policy_family_id: str | None,
        jurisdiction: str | None,
        version_label: str | None,
        tenant_id: str,
        workspace_id: str | None,
    ) -> RagIngestionJob:
        if doc_type not in VALID_DOC_TYPES:
            raise HTTPException(status_code=400, detail="Invalid doc_type")
        data = await file.read()
        max_bytes = self.settings.rag_max_file_mb * 1024 * 1024
        if len(data) > max_bytes:
            raise HTTPException(status_code=413, detail=f"RAG documents are limited to {self.settings.rag_max_file_mb}MB")
        file_hash = self.compute_file_hash(data)
        existing = await self.session.execute(
            select(RagSourceDocument).where(
                RagSourceDocument.tenant_id == tenant_id,
                RagSourceDocument.workspace_id == workspace_id,
                RagSourceDocument.file_hash == file_hash,
                RagSourceDocument.is_deleted.is_(False),
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate RAG document")

        storage_dir = Path(self.settings.rag_storage_path) / tenant_id
        storage_dir.mkdir(parents=True, exist_ok=True)
        filename = file.filename or f"{file_hash}.pdf"
        storage_path = storage_dir / f"{file_hash}_{Path(filename).name}"
        storage_path.write_bytes(data)

        source = RagSourceDocument(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            doc_type=doc_type,
            policy_family_id=policy_family_id,
            jurisdiction=jurisdiction,
            original_filename=filename,
            source_path=str(storage_path),
            file_hash=file_hash,
        )
        self.session.add(source)
        await self.session.flush()

        version_number = 1
        version = RagDocumentVersion(
            document_id=source.id,
            version=version_number,
            version_label=version_label or "v1",
            is_active=False,
        )
        self.session.add(version)
        await self.session.flush()

        job = RagIngestionJob(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            doc_type=doc_type,
            policy_family_id=policy_family_id,
            jurisdiction=jurisdiction,
            version_label=version_label,
            source_document_id=source.id,
            version_id=version.id,
            status="pending",
        )
        self.session.add(job)
        await self.session.flush()
        return job

    def ingest_document(self, job_id: str) -> RagIngestionJob:
        if not isinstance(self.session, Session):
            raise RuntimeError("ingest_document uses a synchronous worker session")
        job = self.session.get(RagIngestionJob, job_id)
        if job is None:
            raise ValueError(f"RAG ingestion job not found: {job_id}")
        try:
            job.status = "running"
            job.started_at = datetime.utcnow()
            self.session.flush()
            version = self.session.get(RagDocumentVersion, job.version_id)
            source = self.session.get(RagSourceDocument, job.source_document_id)
            if version is None or source is None:
                raise ValueError("Ingestion job is missing source document/version")
            parsed = parse_document(source.source_path)
            if len(parsed.pages) > self.settings.rag_max_pages:
                raise ValueError(f"Document exceeds {self.settings.rag_max_pages} pages")
            chunks = self.chunk_document(parsed, self.settings.rag_chunk_size, self.settings.rag_chunk_overlap)
            self.embed_chunks(version.id, chunks)
            self.activate_new_version(version.id)
            job.status = "completed"
            job.finished_at = datetime.utcnow()
            self.session.commit()
            return job
        except Exception as exc:
            self.mark_job_failed(job_id, str(exc))
            raise

    def chunk_document(self, parsed_doc: ParsedDoc, size: int, overlap: int) -> list[RagChunkInput]:
        chunks: list[RagChunkInput] = []
        seen_hashes: set[str] = set()
        for clause in parsed_doc.clauses:
            words = clause.text.split()
            step = max(1, size - overlap)
            for start in range(0, len(words), step):
                text = " ".join(words[start : start + size]).strip()
                if not text:
                    continue
                digest = self.compute_chunk_hash(text)
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)
                chunks.append(
                    RagChunkInput(
                        text=text,
                        page=clause.page,
                        metadata={"page": clause.page, "source_extractor": clause.source_extractor, "clause_id": clause.id},
                    )
                )
        return chunks

    def embed_chunks(self, version_id: str, chunks: list[RagChunkInput]) -> None:
        if not isinstance(self.session, Session):
            raise RuntimeError("embed_chunks uses a synchronous worker session")
        provider = get_embedding_provider(self.settings)
        embeddings = provider.embed_texts([chunk.text for chunk in chunks])
        for index, (chunk_input, embedding) in enumerate(zip(chunks, embeddings)):
            chunk = RagChunk(
                version_id=version_id,
                chunk_index=index,
                text=chunk_input.text,
                chunk_hash=self.compute_chunk_hash(chunk_input.text),
                page_number=chunk_input.page,
                chunk_metadata=chunk_input.metadata,
            )
            self.session.add(chunk)
            self.session.flush()
            self.session.add(RagEmbedding(chunk_id=chunk.id, embedding=embedding, model_name=provider.model_name))

    def activate_new_version(self, version_id: str) -> None:
        if not isinstance(self.session, Session):
            raise RuntimeError("activate_new_version uses a synchronous worker session")
        version = self.session.get(RagDocumentVersion, version_id)
        if version is None:
            raise ValueError("Version not found")
        self.soft_delete_previous_active(version.document_id)
        version.is_active = True
        version.activated_at = datetime.utcnow()

    def soft_delete_previous_active(self, document_id: str) -> None:
        if not isinstance(self.session, Session):
            raise RuntimeError("soft_delete_previous_active uses a synchronous worker session")
        active_versions = self.session.scalars(
            select(RagDocumentVersion).where(
                RagDocumentVersion.document_id == document_id,
                RagDocumentVersion.is_active.is_(True),
            )
        ).all()
        for version in active_versions:
            version.is_active = False
            version.deleted_at = datetime.utcnow()

    def mark_job_failed(self, job_id: str, error: str) -> None:
        if not isinstance(self.session, Session):
            raise RuntimeError("mark_job_failed uses a synchronous worker session")
        job = self.session.get(RagIngestionJob, job_id)
        if job is not None:
            job.status = "failed"
            job.error = error
            job.finished_at = datetime.utcnow()
            self.session.commit()


async def count_document_chunks(session: AsyncSession, document_id: str) -> int:
    result = await session.execute(
        select(func.count(RagChunk.id))
        .join(RagDocumentVersion, RagDocumentVersion.id == RagChunk.version_id)
        .where(RagDocumentVersion.document_id == document_id)
    )
    return int(result.scalar() or 0)

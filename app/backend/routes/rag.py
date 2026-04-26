from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select

from app.backend.core.config import SettingsDep
from app.backend.db.models import RagChunk, RagDocumentVersion, RagIngestionJob, RagSourceDocument
from app.backend.db.session import DbSession
from app.backend.models.schemas import RagDocumentResponse, RagIngestionStatus
from app.backend.services.auth_service import require_auth
from app.backend.services.rag_ingestion import RagIngestionService

router = APIRouter(prefix="/api/rag", tags=["rag"])


def _tenant_from_token(token: dict) -> str:
    tenant_id = token.get("org_id") or token.get("sub")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenant membership in token")
    return str(tenant_id)


def _workspace_from_token(token: dict) -> str | None:
    return token.get("workspace_id")


def _require_rag_admin(token: dict) -> None:
    if token.get("org_role") not in {"org_admin", "workspace_admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="RAG admin access required")


async def _document_response(db: DbSession, document: RagSourceDocument) -> RagDocumentResponse:
    active_result = await db.execute(
        select(RagDocumentVersion).where(
            RagDocumentVersion.document_id == document.id,
            RagDocumentVersion.is_active.is_(True),
        )
    )
    active = active_result.scalars().first()
    chunk_count = 0
    if active is not None:
        result = await db.execute(select(func.count(RagChunk.id)).where(RagChunk.version_id == active.id))
        chunk_count = int(result.scalar() or 0)
    return RagDocumentResponse(
        document_id=document.id,
        doc_type=document.doc_type,
        source_path=document.source_path,
        version=(active.version_label if active else None) or "pending",
        tenant_id=document.tenant_id,
        workspace_id=document.workspace_id,
        active=active is not None,
        chunk_count=chunk_count,
        created_at=document.created_at,
        file_hash=document.file_hash,
    )


@router.post("/documents", status_code=status.HTTP_202_ACCEPTED)
async def upload_rag_document(
    db: DbSession,
    settings: SettingsDep,
    token: dict = Depends(require_auth),
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    policy_family_id: str | None = Form(None),
    jurisdiction: str | None = Form(None),
    version_label: str | None = Form(None),
) -> dict:
    _require_rag_admin(token)
    service = RagIngestionService(db, settings)
    job = await service.create_ingestion_job(
        file=file,
        doc_type=doc_type,
        policy_family_id=policy_family_id,
        jurisdiction=jurisdiction,
        version_label=version_label,
        tenant_id=_tenant_from_token(token),
        workspace_id=_workspace_from_token(token),
    )
    return {"job_id": job.id, "document_id": job.source_document_id, "state": job.status}


@router.get("/documents", response_model=list[RagDocumentResponse])
async def list_rag_documents(db: DbSession, token: dict = Depends(require_auth)) -> list[RagDocumentResponse]:
    tenant_id = _tenant_from_token(token)
    result = await db.execute(
        select(RagSourceDocument)
        .where(RagSourceDocument.tenant_id == tenant_id, RagSourceDocument.is_deleted.is_(False))
        .order_by(RagSourceDocument.created_at.desc())
    )
    documents = result.scalars().unique().all()
    return [await _document_response(db, document) for document in documents]


@router.get("/documents/{document_id}", response_model=RagDocumentResponse)
async def get_rag_document(document_id: str, db: DbSession, token: dict = Depends(require_auth)) -> RagDocumentResponse:
    document = await db.get(RagSourceDocument, document_id)
    if document is None or document.tenant_id != _tenant_from_token(token) or document.is_deleted:
        raise HTTPException(status_code=404, detail="RAG document not found")
    return await _document_response(db, document)


@router.get("/ingestions/{job_id}", response_model=RagIngestionStatus)
async def get_ingestion_status(job_id: str, db: DbSession, token: dict = Depends(require_auth)) -> RagIngestionStatus:
    job = await db.get(RagIngestionJob, job_id)
    if job is None or job.tenant_id != _tenant_from_token(token):
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    chunk_count = 0
    if job.version_id:
        result = await db.execute(select(func.count(RagChunk.id)).where(RagChunk.version_id == job.version_id))
        chunk_count = int(result.scalar() or 0)
    state = "done" if job.status == "completed" else job.status
    return RagIngestionStatus(
        job_id=job.id,
        document_id=job.source_document_id,
        state=state,
        chunks_processed=chunk_count,
        total_chunks=chunk_count if job.status == "completed" else None,
        error_detail=job.error,
        started_at=job.started_at,
        completed_at=job.finished_at,
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rag_document(document_id: str, db: DbSession, token: dict = Depends(require_auth)) -> None:
    _require_rag_admin(token)
    document = await db.get(RagSourceDocument, document_id)
    if document is None or document.tenant_id != _tenant_from_token(token):
        raise HTTPException(status_code=404, detail="RAG document not found")
    document.is_deleted = True
    document.updated_at = datetime.utcnow()
    versions = await db.execute(select(RagDocumentVersion).where(RagDocumentVersion.document_id == document_id))
    for version in versions.scalars().all():
        if version.is_active:
            version.is_active = False
            version.deleted_at = datetime.utcnow()

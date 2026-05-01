from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.backend.db.models import ContractCommentRecord, FindingCommentRecord
from app.backend.db.session import DbSession
from app.backend.services.auth_service import require_auth

router = APIRouter(prefix="/api", tags=["comments"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CommentOut(BaseModel):
    id: str
    author_id: str
    author_name: str
    job_title: str | None
    avatar_color: str
    body: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CommentCreate(BaseModel):
    body: str


class CommentUpdate(BaseModel):
    body: str


# ---------------------------------------------------------------------------
# Run-level (contract) comments
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/comments", response_model=list[CommentOut])
async def list_contract_comments(run_id: str, db: DbSession, token: dict = Depends(require_auth)) -> list[CommentOut]:
    result = await db.execute(
        select(ContractCommentRecord)
        .options(selectinload(ContractCommentRecord.author))
        .where(ContractCommentRecord.run_id == run_id, ContractCommentRecord.is_deleted.is_(False))
        .order_by(ContractCommentRecord.created_at.asc())
    )
    rows = result.scalars().all()
    return [
        CommentOut(
            id=r.id,
            author_id=r.author_id,
            author_name=r.author.display_name or "Unknown",
            job_title=r.author.job_title,
            avatar_color=r.author.avatar_color or "#6366f1",
            body=r.body,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post("/runs/{run_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def create_contract_comment(
    run_id: str,
    body: CommentCreate,
    db: DbSession,
    token: dict = Depends(require_auth),
) -> CommentOut:
    record = ContractCommentRecord(
        id=str(uuid.uuid4()),
        run_id=run_id,
        author_id=token["sub"],
        body=body.body.strip(),
    )
    db.add(record)
    await db.flush()
    await db.refresh(record, ["author"])
    return CommentOut(
        id=record.id,
        author_id=record.author_id,
        author_name=record.author.display_name or "Unknown",
        job_title=record.author.job_title,
        avatar_color=record.author.avatar_color or "#6366f1",
        body=record.body,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.patch("/runs/{run_id}/comments/{comment_id}", response_model=CommentOut)
async def update_contract_comment(
    run_id: str,
    comment_id: str,
    body: CommentUpdate,
    db: DbSession,
    token: dict = Depends(require_auth),
) -> CommentOut:
    record = (await db.execute(
        select(ContractCommentRecord).where(
            ContractCommentRecord.id == comment_id,
            ContractCommentRecord.run_id == run_id,
        )
    )).scalar_one_or_none()
    if not record or record.is_deleted:
        raise HTTPException(status_code=404, detail="Comment not found")
    if record.author_id != token["sub"]:
        raise HTTPException(status_code=403, detail="Cannot edit another user's comment")
    record.body = body.body.strip()
    record.updated_at = __import__("datetime").datetime.utcnow()
    await db.flush()
    await db.refresh(record, ["author"])
    return CommentOut(
        id=record.id, author_id=record.author_id,
        author_name=record.author.display_name or "Unknown",
        job_title=record.author.job_title,
        avatar_color=record.author.avatar_color or "#6366f1",
        body=record.body, created_at=record.created_at, updated_at=record.updated_at,
    )


@router.delete("/runs/{run_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract_comment(
    run_id: str,
    comment_id: str,
    db: DbSession,
    token: dict = Depends(require_auth),
) -> None:
    record = (await db.execute(
        select(ContractCommentRecord).where(
            ContractCommentRecord.id == comment_id,
            ContractCommentRecord.run_id == run_id,
        )
    )).scalar_one_or_none()
    if not record or record.is_deleted:
        raise HTTPException(status_code=404, detail="Comment not found")
    if record.author_id != token["sub"]:
        raise HTTPException(status_code=403, detail="Cannot delete another user's comment")
    record.is_deleted = True


# ---------------------------------------------------------------------------
# Finding-level comments
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/findings/{finding_id}/comments", response_model=list[CommentOut])
async def list_finding_comments(run_id: str, finding_id: str, db: DbSession) -> list[CommentOut]:
    result = await db.execute(
        select(FindingCommentRecord)
        .options(selectinload(FindingCommentRecord.author))
        .where(
            FindingCommentRecord.run_id == run_id,
            FindingCommentRecord.finding_id == finding_id,
            FindingCommentRecord.is_deleted.is_(False),
        )
        .order_by(FindingCommentRecord.created_at.asc())
    )
    rows = result.scalars().all()
    return [
        CommentOut(
            id=r.id, author_id=r.author_id, author_name=r.author.display_name, job_title=r.author.job_title, avatar_color=r.author.avatar_color, body=r.body, created_at=r.created_at, updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post("/runs/{run_id}/findings/{finding_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def create_finding_comment(
    run_id: str,
    finding_id: str,
    body: CommentCreate,
    db: DbSession,
    token: dict = Depends(require_auth),
) -> CommentOut:
    record = FindingCommentRecord(
        id=str(uuid.uuid4()),
        run_id=run_id,
        finding_id=finding_id,
        author_id=token["sub"],
        body=body.body.strip(),
    )
    db.add(record)
    await db.flush()
    await db.refresh(record, ["author"])
    return CommentOut(
        id=record.id, author_id=record.author_id, author_name=record.author.display_name,
        job_title=record.author.job_title,
        avatar_color=record.author.avatar_color,
        body=record.body, created_at=record.created_at, updated_at=record.updated_at,
    )


@router.patch("/runs/{run_id}/findings/{finding_id}/comments/{comment_id}", response_model=CommentOut)
async def update_finding_comment(
    run_id: str,
    finding_id: str,
    comment_id: str,
    body: CommentUpdate,
    db: DbSession,
    token: dict = Depends(require_auth),
) -> CommentOut:
    record = (await db.execute(
        select(FindingCommentRecord).where(FindingCommentRecord.id == comment_id)
    )).scalar_one_or_none()
    if not record or record.is_deleted:
        raise HTTPException(status_code=404, detail="Comment not found")
    if record.author_id != token["sub"]:
        raise HTTPException(status_code=403, detail="Cannot edit another user's comment")
    record.body = body.body.strip()
    record.updated_at = __import__("datetime").datetime.utcnow()
    await db.flush()
    await db.refresh(record, ["author"])
    return CommentOut(
        id=record.id, author_id=record.author_id, author_name=record.author.display_name,
        job_title=record.author.job_title,
        avatar_color=record.author.avatar_color,
        body=record.body, created_at=record.created_at, updated_at=record.updated_at,
    )


@router.delete("/runs/{run_id}/findings/{finding_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_finding_comment(
    run_id: str,
    finding_id: str,
    comment_id: str,
    db: DbSession,
    token: dict = Depends(require_auth),
) -> None:
    record = (await db.execute(
        select(FindingCommentRecord).where(FindingCommentRecord.id == comment_id)
    )).scalar_one_or_none()
    if not record or record.is_deleted:
        raise HTTPException(status_code=404, detail="Comment not found")
    if record.author_id != token["sub"]:
        raise HTTPException(status_code=403, detail="Cannot delete another user's comment")
    record.is_deleted = True

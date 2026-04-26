from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from app.backend.core.config import SettingsDep
from app.backend.db.session import DbSession, get_session_factory
from app.backend.models.schemas import HumanReviewPayload, HumanReviewResult, RunCreateResponse, RunDetail
from app.backend.services.event_stream import list_run_events, stream_run_events
from app.backend.db.models import RunRecord
from app.backend.services.run_service import create_run, get_run_detail, submit_human_review, _load_full_findings
from app.backend.services.auth_service import require_auth
from sqlalchemy import select

router = APIRouter(prefix="/api", tags=["runs"])

_FAILURE_LOG = Path("logs/failures.jsonl")


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/failures")
async def get_failures(limit: int = 50) -> list[dict]:
    """Return the last `limit` entries from the structured failure log."""
    if not _FAILURE_LOG.exists():
        return []
    lines = _FAILURE_LOG.read_text(encoding="utf-8").splitlines()
    entries: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(entries) >= limit:
            break
    return entries


@router.post("/runs", response_model=RunCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def post_run(
    db: DbSession,
    settings: SettingsDep,
    token: dict = Depends(require_auth),
    file: UploadFile = File(...),
    policy_family_id: str = Form(...),
    policy_version: int = Form(...),
    jurisdiction: str = Form(...),
    regime: str = Form(...),
    effective_date: str | None = Form(None),
) -> RunCreateResponse:
    return await create_run(
        db,
        settings,
        file=file,
        tenant_id=str(token.get("org_id") or token.get("sub")),
        policy_family_id=policy_family_id,
        policy_version=policy_version,
        jurisdiction=jurisdiction,
        regime=regime,
        effective_date=effective_date,
    )


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str, db: DbSession) -> RunDetail:
    return await get_run_detail(db, run_id)


@router.get("/runs/{run_id}/events")
async def get_run_events(run_id: str, after: int = 0) -> EventSourceResponse:
    return EventSourceResponse(stream_run_events(get_session_factory(), run_id, after_sequence=after))


@router.get("/runs/{run_id}/events/list")
async def get_run_events_list(run_id: str, after: int = 0):
    return await list_run_events(get_session_factory(), run_id, after_sequence=after)


@router.post("/runs/{run_id}/start-review")
async def start_review(run_id: str, db: DbSession):
    result = await db.execute(select(RunRecord).where(RunRecord.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "awaiting_human_review":
        raise HTTPException(status_code=409, detail="Run is not awaiting human review")
    run.status = "under_review"
    db.add(run)
    await db.commit()
    return {"run_id": run_id, "state": "under_review"}


@router.post("/runs/{run_id}/human-review", response_model=HumanReviewResult)
async def post_human_review(run_id: str, payload: HumanReviewPayload, db: DbSession) -> HumanReviewResult:
    return await submit_human_review(db, run_id, payload)


@router.post("/runs/{run_id}/retry")
async def retry_run(run_id: str, db: DbSession):
    from app.backend.db.models import StageExecutionRecord
    result = await db.execute(select(RunRecord).where(RunRecord.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in ("blocked", "failed"):
        raise HTTPException(status_code=409, detail="Only blocked or failed runs can be retried")

    # Reset the blocked/failed stage(s) back to pending
    stages_result = await db.execute(
        select(StageExecutionRecord).where(StageExecutionRecord.run_id == run_id)
    )
    for stage in stages_result.scalars().all():
        if stage.status in ("blocked", "failed", "running"):
            stage.status = "pending"
            stage.error_detail = None
            stage.retry_count = 0
            stage.lease_expires_at = None
            stage.worker_id = None
            db.add(stage)

    run.status = "processing"
    run.blocked_reason = None
    db.add(run)
    await db.commit()
    return {"run_id": run_id, "state": "processing"}


@router.get("/runs/{run_id}/findings")
async def get_run_findings(run_id: str, db: DbSession):
    result = await db.execute(select(RunRecord).where(RunRecord.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    findings = await _load_full_findings(db, run_id)
    return [f.model_dump(mode="json") for f in findings]


@router.get("/runs/{run_id}/file")
async def get_run_file(run_id: str, db: DbSession) -> FileResponse:
    result = await db.execute(select(RunRecord).where(RunRecord.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    path = Path(run.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(path, media_type="application/pdf", filename=run.original_filename)

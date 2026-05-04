from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from app.backend.core.limiter import limiter, _key_by_user
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.backend.core.config import SettingsDep
from app.backend.db.session import DbSession, get_session_factory
from app.backend.models.schemas import HumanReviewPayload, HumanReviewResult, RunCreateResponse, RunDetail
from app.backend.services.event_stream import list_run_events, stream_run_events
from app.backend.db.models import ParsedClauseRecord, RunRecord
from app.backend.services.run_service import create_run, get_run_detail, load_harvey_findings, submit_human_review, _load_full_findings
from app.backend.services.auth_service import require_auth
from app.backend.services.workspace_access import assert_run_access
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

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
@limiter.limit("20/hour", key_func=_key_by_user)
async def post_run(
    request: Request,
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


@router.get("/runs/active", response_model=RunDetail | None)
async def get_active_run(db: DbSession, token: dict = Depends(require_auth)) -> RunDetail | None:
    """Return the most recent actionable run for the current user.

    Returns runs in created/processing state first; falls back to the most recent
    failed/blocked run from the last 24 hours so the frontend can show a retry button
    instead of a permanent grey spinner.
    """
    from sqlalchemy import select, desc
    from datetime import timedelta
    from app.backend.db.models import RunRecord
    tenant_id = str(token.get("org_id") or token.get("sub"))

    run = (await db.execute(
        select(RunRecord)
        .where(RunRecord.tenant_id == tenant_id, RunRecord.status.in_(["created", "processing"]))
        .order_by(desc(RunRecord.created_at))
        .limit(1)
    )).scalar_one_or_none()

    if run is None:
        from datetime import datetime
        cutoff = datetime.utcnow() - timedelta(hours=24)
        run = (await db.execute(
            select(RunRecord)
            .where(
                RunRecord.tenant_id == tenant_id,
                RunRecord.status.in_(["failed", "blocked"]),
                RunRecord.created_at >= cutoff,
            )
            .order_by(desc(RunRecord.created_at))
            .limit(1)
        )).scalar_one_or_none()

    if run is None:
        return None
    from app.backend.services.run_service import get_run_detail
    return await get_run_detail(db, run.id)


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str, db: DbSession, token: dict = Depends(require_auth)) -> RunDetail:
    await assert_run_access(db, run_id, token)
    return await get_run_detail(db, run_id)


@router.get("/runs/{run_id}/events")
async def get_run_events(run_id: str, db: DbSession, after: int = 0, token: dict = Depends(require_auth)) -> EventSourceResponse:
    await assert_run_access(db, run_id, token)
    return EventSourceResponse(stream_run_events(get_session_factory(), run_id, after_sequence=after))


@router.get("/runs/{run_id}/events/list")
async def get_run_events_list(run_id: str, db: DbSession, after: int = 0, token: dict = Depends(require_auth)):
    await assert_run_access(db, run_id, token)
    return await list_run_events(get_session_factory(), run_id, after_sequence=after)


@router.post("/runs/{run_id}/start-review")
async def start_review(run_id: str, db: DbSession, token: dict = Depends(require_auth)):
    run = await assert_run_access(db, run_id, token)
    if run.status != "awaiting_human_review":
        raise HTTPException(status_code=409, detail="Run is not awaiting human review")
    run.status = "under_review"
    db.add(run)
    await db.commit()
    return {"run_id": run_id, "state": "under_review"}


@router.post("/runs/{run_id}/human-review", response_model=HumanReviewResult)
async def post_human_review(
    run_id: str,
    payload: HumanReviewPayload,
    db: DbSession,
    token: dict = Depends(require_auth),
) -> HumanReviewResult:
    await assert_run_access(db, run_id, token)
    return await submit_human_review(db, run_id, payload)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, db: DbSession, token: dict = Depends(require_auth)):
    from app.backend.db.models import StageExecutionRecord
    run = await assert_run_access(db, run_id, token)
    if run.status not in ("created", "processing"):
        raise HTTPException(status_code=409, detail="Only active runs can be cancelled")
    run.status = "cancelled"
    stages_result = await db.execute(
        select(StageExecutionRecord).where(StageExecutionRecord.run_id == run_id)
    )
    for stage in stages_result.scalars().all():
        if stage.status in ("pending", "retrying"):
            stage.status = "cancelled"
            stage.lease_expires_at = None
    await db.commit()
    return {"run_id": run_id, "state": "cancelled"}


@router.post("/runs/{run_id}/retry")
async def retry_run(run_id: str, db: DbSession, token: dict = Depends(require_auth)):
    from app.backend.db.models import StageExecutionRecord
    run = await assert_run_access(db, run_id, token)
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
async def get_run_findings(run_id: str, db: DbSession, token: dict = Depends(require_auth)):
    await assert_run_access(db, run_id, token)
    findings = await _load_full_findings(db, run_id)
    return [f.model_dump(mode="json") for f in findings]


@router.get("/runs/{run_id}/harvey-findings")
async def get_run_harvey_findings(run_id: str, db: DbSession, token: dict = Depends(require_auth)):
    await assert_run_access(db, run_id, token)
    findings = await load_harvey_findings(db, run_id)
    return [f.model_dump(mode="json") for f in findings]


class EditorSavePayload(BaseModel):
    content: str
    author_name: str | None = None


@router.get("/runs/{run_id}/editor")
async def get_editor_content(run_id: str, db: DbSession, token: dict = Depends(require_auth)):
    run = await assert_run_access(db, run_id, token)

    editor_state = (run.verdict_payload or {}).get("editor_state")
    if editor_state:
        return editor_state

    # Bootstrap from parsed clauses (ordered by page then vertical position)
    clauses_result = await db.execute(
        select(ParsedClauseRecord)
        .where(ParsedClauseRecord.run_id == run_id)
        .order_by(ParsedClauseRecord.page_number, ParsedClauseRecord.bbox_y0)
    )
    clauses = clauses_result.scalars().all()
    if clauses:
        paragraphs = [f"<p>{c.normalized_text}</p>" for c in clauses if c.normalized_text.strip()]
        content = "\n".join(paragraphs)
    else:
        content = "<p>Contract text not yet extracted. Run the pipeline first.</p>"

    return {"content": content, "last_edited_by": None, "last_edited_at": None, "version": 0}


@router.put("/runs/{run_id}/editor")
async def save_editor_content(run_id: str, body: EditorSavePayload, db: DbSession, token: dict = Depends(require_auth)):
    run = await assert_run_access(db, run_id, token)

    current = dict(run.verdict_payload or {})
    current_version = (current.get("editor_state") or {}).get("version", 0) or 0
    new_state = {
        "content": body.content,
        "last_edited_by": body.author_name or "Unknown",
        "last_edited_at": datetime.utcnow().isoformat(),
        "version": current_version + 1,
    }
    current["editor_state"] = new_state
    run.verdict_payload = current
    flag_modified(run, "verdict_payload")
    db.add(run)
    await db.commit()
    return new_state


@router.get("/runs/{run_id}/file")
async def get_run_file(run_id: str, db: DbSession, token: dict = Depends(require_auth)) -> FileResponse:
    run = await assert_run_access(db, run_id, token)
    path = Path(run.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(path, media_type="application/pdf", filename=run.original_filename)

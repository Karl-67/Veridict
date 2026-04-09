from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile, status
from sse_starlette.sse import EventSourceResponse

from app.backend.core.config import SettingsDep
from app.backend.db.session import DbSession, get_session_factory
from app.backend.models.schemas import HumanReviewPayload, HumanReviewResult, RunCreateResponse, RunDetail
from app.backend.services.event_stream import list_run_events, stream_run_events
from app.backend.services.run_service import create_run, get_run_detail, submit_human_review

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
    file: UploadFile = File(...),
    tenant_id: str = Form(...),
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
        tenant_id=tenant_id,
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


@router.post("/runs/{run_id}/human-review", response_model=HumanReviewResult)
async def post_human_review(run_id: str, payload: HumanReviewPayload, db: DbSession) -> HumanReviewResult:
    return await submit_human_review(db, run_id, payload)

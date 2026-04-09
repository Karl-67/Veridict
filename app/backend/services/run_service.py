"""
Application service for run lifecycle operations.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.core.config import Settings
from app.backend.db.models import FindingRecord, HumanReviewRecord, RunRecord, StageExecutionRecord
from app.backend.models.schemas import FinalVerdict, HumanReviewPayload, HumanReviewResult, RunCreateResponse, RunDetail, StageStatus

STAGE_SEQUENCE = [
    "create_run",
    "ingest_pdf",
    "parse_ocr_normalize",
    "clause_index",
    "harvey_context_load",
    "kira_context_load",
    "harvey_review_block",
    "kira_review_block",
    "admin_merge",
    "final_review_block",
    "awaiting_human_review",
    "finalized",
]


def _parse_effective_date(value: str | None):
    if not value:
        return None
    from datetime import date

    return date.fromisoformat(value)


async def create_run(
    session: AsyncSession,
    settings: Settings,
    *,
    file: UploadFile,
    tenant_id: str,
    policy_family_id: str,
    policy_version: int,
    jurisdiction: str,
    regime: str,
    effective_date: str | None,
) -> RunCreateResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF uploads are accepted.")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded PDF is empty.")

    document_hash = hashlib.sha256(contents).hexdigest()
    storage_dir = Path(settings.document_storage_path)
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_path = storage_dir / f"{document_hash}.pdf"
    storage_path.write_bytes(contents)

    run = RunRecord(
        tenant_id=tenant_id,
        original_filename=file.filename,
        storage_path=str(storage_path),
        file_hash=document_hash,
        policy_family_id=policy_family_id,
        policy_version_number=policy_version,
        jurisdiction=jurisdiction,
        regime=regime,
        effective_date=_parse_effective_date(effective_date),
        status="created",
    )
    session.add(run)
    await session.flush()

    for stage_order, stage_name in enumerate(STAGE_SEQUENCE, start=1):
        session.add(
            StageExecutionRecord(
                run_id=run.id,
                stage_name=stage_name,
                stage_order=stage_order,
                round_number=1,
                attempt_number=1,
                status="pending",
                max_retries=settings.max_stage_retries,
            )
        )

    from app.backend.services.event_stream import async_append_run_event as append_run_event

    await append_run_event(session, run.id, "run_created", {"filename": file.filename})
    await session.flush()
    return RunCreateResponse(run_id=run.id, state="created", created_at=run.created_at)


def _map_stage_state(record: StageExecutionRecord) -> str:
    mapping = {
        "pending": "pending",
        "claimed": "running",
        "running": "running",
        "completed": "done",
        "failed": "failed",
        "retrying": "retrying",
    }
    return mapping.get(record.status, "pending")


def _build_final_verdict(run: RunRecord, findings: list[FindingRecord], human_action: str | None) -> FinalVerdict | None:
    if run.verdict_payload is not None:
        return FinalVerdict.model_validate(run.verdict_payload)
    if human_action is None:
        return None
    risk = "low"
    for finding in findings:
        if finding.severity == "critical":
            risk = "critical"
            break
        if finding.severity == "high":
            risk = "high"
        elif finding.severity == "medium" and risk == "low":
            risk = "medium"
    return FinalVerdict(
        run_id=run.id,
        finalized_at=run.updated_at,
        overall_risk_level=risk,  # type: ignore[arg-type]
        findings=[],
        summary=f"{len(findings)} findings were reviewed.",
        recommendations=[finding.recommendation for finding in findings if finding.recommendation],
        human_action=human_action,  # type: ignore[arg-type]
        unresolved_finding_count=sum(1 for finding in findings if finding.is_disputed),
    )


async def get_run_detail(session: AsyncSession, run_id: str) -> RunDetail:
    run = await session.get(RunRecord, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")

    stages_result = await session.execute(
        select(StageExecutionRecord).where(StageExecutionRecord.run_id == run_id).order_by(StageExecutionRecord.created_at.asc())
    )
    finding_result = await session.execute(select(FindingRecord).where(FindingRecord.run_id == run_id))
    review_result = await session.execute(
        select(HumanReviewRecord).where(HumanReviewRecord.run_id == run_id, HumanReviewRecord.is_run_level.is_(True))
    )

    findings = finding_result.scalars().all()
    run_review = review_result.scalars().first()
    stages = [
        StageStatus(
            stage_name=stage.stage_name,
            state=_map_stage_state(stage),  # type: ignore[arg-type]
            retry_count=stage.retry_count,
            max_retries=stage.max_retries,
            started_at=stage.started_at,
            completed_at=stage.finished_at,
            error_detail=stage.failure_reason,
        )
        for stage in stages_result.scalars().all()
    ]
    verdict = _build_final_verdict(run, findings, run_review.action if run_review else None)
    return RunDetail(
        run_id=run.id,
        state=run.status,  # type: ignore[arg-type]
        stages=stages,
        filename=run.original_filename,
        tenant_id=run.tenant_id,
        policy_family_id=run.policy_family_id,
        policy_version_number=run.policy_version_number,
        jurisdiction=run.jurisdiction,
        regime=run.regime,
        effective_date=run.effective_date.isoformat() if run.effective_date else None,
        created_at=run.created_at,
        updated_at=run.updated_at,
        verdict=verdict,
        blocked_reason=run.blocked_reason,
    )


async def submit_human_review(session: AsyncSession, run_id: str, payload: HumanReviewPayload) -> HumanReviewResult:
    run = await session.get(RunRecord, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    if run.status != "awaiting_human_review":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run is not awaiting human review.")
    if payload.run_action == "edited" and not payload.finding_actions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Edited reviews require per-finding edits.")
    if payload.run_action == "rejected" and not payload.rejection_reason:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rejected reviews require a rejection reason.")

    from app.backend.services.event_stream import async_append_run_event as append_run_event

    for finding_action in payload.finding_actions:
        finding = await session.get(FindingRecord, finding_action.finding_id)
        if finding is None or finding.run_id != run_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid finding_id: {finding_action.finding_id}")
        session.add(
            HumanReviewRecord(
                run_id=run_id,
                finding_id=finding.id,
                reviewer_id=payload.reviewer_id,
                reviewer_role="human_reviewer",
                action=finding_action.action,
                original_finding_snapshot={"issue": finding.issue, "severity": finding.severity},
                edited_finding_snapshot={"edit_delta": finding_action.edit_delta} if finding_action.edit_delta else None,
                edit_justification=finding_action.edit_delta,
            )
        )

    session.add(
        HumanReviewRecord(
            run_id=run_id,
            finding_id=None,
            reviewer_id=payload.reviewer_id,
            reviewer_role="human_reviewer",
            action=payload.run_action,
            is_run_level=True,
            rejection_reason=payload.rejection_reason,
        )
    )

    if payload.run_action == "rejected":
        run.status = "rejected"
        await append_run_event(session, run_id, "human_rejected", {"reviewer_id": payload.reviewer_id, "reason": payload.rejection_reason})
        return HumanReviewResult(run_id=run_id, run_action="rejected", state="rejected")

    run.status = "processing"
    await append_run_event(
        session,
        run_id,
        "human_edited" if payload.run_action == "edited" else "human_approved",
        {"reviewer_id": payload.reviewer_id},
    )
    verdict = await finalize_run_if_approved(session, run_id, payload.run_action)
    return HumanReviewResult(run_id=run_id, run_action=payload.run_action, state="finalized", verdict=verdict)


async def finalize_run_if_approved(session: AsyncSession, run_id: str, human_action: str) -> FinalVerdict:
    run = await session.get(RunRecord, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    finding_result = await session.execute(select(FindingRecord).where(FindingRecord.run_id == run_id))
    findings = finding_result.scalars().all()
    verdict = _build_final_verdict(run, findings, human_action)
    if verdict is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run cannot be finalized yet.")

    from app.backend.services.event_stream import async_append_run_event as append_run_event

    run.status = "finalized"
    run.verdict_payload = verdict.model_dump(mode="json")
    finalized_stage = (
        await session.execute(
            select(StageExecutionRecord).where(
                StageExecutionRecord.run_id == run_id,
                StageExecutionRecord.stage_name == "finalized",
            )
        )
    ).scalars().first()
    if finalized_stage is not None:
        finalized_stage.status = "completed"
        finalized_stage.finished_at = run.updated_at
    await append_run_event(session, run_id, "run_finalized", {"human_action": human_action})
    return verdict

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
from app.backend.models.schemas import EvidenceRef, Finding, FinalVerdict, HumanReviewPayload, HumanReviewResult, RunCreateResponse, RunDetail, StageStatus

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


def _finding_record_to_finding(fr: FindingRecord) -> Finding | None:
    """Convert a FindingRecord DB row into a Finding schema object with synthetic evidence."""
    try:
        clause_text = fr.clause_text or fr.issue or ""
        return Finding.model_construct(
            finding_id=str(fr.id),
            clause_uid=fr.clause_uid or "unknown",
            issue_type="liability_exposure",
            severity=fr.severity,  # type: ignore[arg-type]
            exploitability="medium",
            business_impact="medium",
            description=fr.issue,
            recommendation="negotiate",
            recommendation_detail=fr.recommendation or "",
            evidence=[
                EvidenceRef.model_construct(
                    page=1,
                    bbox=[0.0, 0.0, 0.0, 0.0],
                    normalized_text=clause_text,
                    extraction_confidence=1.0,
                )
            ],
            branch="harvey",
            agent_role=fr.source_agent or "unknown",
            round_number=fr.round_number,
            consensus_status=None,
            unresolved_by_consensus=False,
            human_edited=False,
            human_edit_delta=None,
        )
    except Exception:
        return None


async def _load_full_findings(session: AsyncSession, run_id: str) -> list[Finding]:
    """Load Finding objects: primary source is admin_merge, supplemented by FindingRecord table.

    The admin_merge LLM sometimes aggressively deduplicates down to 1 finding. To ensure
    the UI shows all meaningful findings, we also load unique findings from the DB and merge.
    """
    # 1. Load from admin_merge structured_output (full Finding schema, proper evidence)
    stage_result = await session.execute(
        select(StageExecutionRecord).where(
            StageExecutionRecord.run_id == run_id,
            StageExecutionRecord.stage_name == "admin_merge",
            StageExecutionRecord.status == "completed",
        )
    )
    stage = stage_result.scalars().first()
    merged_findings: list[Finding] = []
    seen_clause_uids: set[str] = set()
    if stage and stage.structured_output:
        for f in stage.structured_output.get("merged_findings", []):
            try:
                finding = Finding.model_validate(f)
                merged_findings.append(finding)
                seen_clause_uids.add(finding.clause_uid)
            except Exception:
                continue

    # 2. Supplement with FindingRecord entries not already covered.
    #    Use the highest-priority source agent: prefer final_reviewer > admin > harvey/kira.
    #    Deduplicate by clause_uid — keep one representative finding per clause.
    db_result = await session.execute(
        select(FindingRecord)
        .where(FindingRecord.run_id == run_id)
        .order_by(FindingRecord.created_at.asc())
    )
    db_findings = db_result.scalars().all()

    # Group by clause_uid, pick the best representative per clause
    best_by_clause: dict[str, FindingRecord] = {}
    priority = {"final_reviewer": 0, "admin": 1, "harvey": 2, "kira": 3}
    for fr in db_findings:
        uid = fr.clause_uid or fr.id
        if uid in seen_clause_uids:
            continue
        existing = best_by_clause.get(uid)
        if existing is None:
            best_by_clause[uid] = fr
        else:
            rank = lambda r: min(priority.get(p, 9) for p in priority if (r.source_agent or "").startswith(p))
            if rank(fr) < rank(existing):
                best_by_clause[uid] = fr

    for fr in best_by_clause.values():
        finding = _finding_record_to_finding(fr)
        if finding is not None:
            merged_findings.append(finding)

    return merged_findings


def _build_final_verdict(
    run: RunRecord,
    findings: list[FindingRecord],
    human_action: str | None,
    full_findings: list[Finding] | None = None,
) -> FinalVerdict | None:
    if run.verdict_payload is not None:
        cached = FinalVerdict.model_validate(run.verdict_payload)
        # Backfill findings if the cached payload has none (legacy runs stored before this fix)
        if not cached.findings and full_findings:
            cached = cached.model_copy(update={"findings": full_findings})
        return cached
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
        findings=full_findings or [],
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
    full_findings = await _load_full_findings(session, run_id)
    verdict = _build_final_verdict(run, findings, run_review.action if run_review else None, full_findings=full_findings)
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
    full_findings = await _load_full_findings(session, run_id)
    verdict = _build_final_verdict(run, findings, human_action, full_findings=full_findings)
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

"""
Application service for run lifecycle operations.

Tenant derivation: tenant_id must be derived from the JWT membership claims by
the caller (route handler) — never from request body (auth-derived-tenancy).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.core.config import Settings
from app.backend.db.models import FindingRecord, HumanReviewRecord, ParsedClauseRecord, RunRecord, StageExecutionRecord
from app.backend.models.schemas import (
    AdminMergeOutput,
    ContractEvidence,
    EvidenceRef,
    Finding,
    FinalVerdict,
    HumanReviewPayload,
    HumanReviewResult,
    RagCitation,
    ReviewBlockResult,
    RunCreateResponse,
    RunDetail,
    StageStatus,
)

# Active stage topology for new runs.
STAGE_SEQUENCE: list[str] = [
    "create_run",
    "ingest_pdf",
    "parse_ocr_normalize",
    "clause_index",
    "harvey_context_load",
    "kira_context_load",
    "harvey_review_block",
    "kira_review_block",
    "admin_merge",
    "awaiting_human_review",
    "finalized",
]

_STAGE_ORDER: dict[str, int] = {stage_name: index for index, stage_name in enumerate(STAGE_SEQUENCE, start=1)}

# Stages that exist only in legacy runs and must never be re-enqueued.
_LEGACY_STAGES = frozenset({"final_review_block"})


def _parse_effective_date(value: str | None):
    if not value:
        return None
    from datetime import date

    return date.fromisoformat(value)


def _is_legacy_run(stage_names: list[str]) -> bool:
    """Return True when this run contains stages from the old topology."""
    return bool(_LEGACY_STAGES & set(stage_names))


def _source_priority(source_agent: str | None) -> int:
    """Lower value = higher priority. final_reviewer is excluded (returns 9)."""
    agent = source_agent or ""
    if agent.startswith("admin"):
        return 0
    if agent.startswith("harvey"):
        return 1
    if agent.startswith("kira"):
        return 2
    return 9


def _map_stage_state(record: StageExecutionRecord) -> str:
    mapping = {
        "pending": "pending",
        "claimed": "running",
        "running": "running",
        "completed": "done",
        "failed": "failed",
        "retrying": "retrying",
        "blocked": "blocked",
    }
    return mapping.get(record.status, "pending")


def _coerce_contract_evidence(raw_items: list | None, fallback_clause_uid: str) -> list[ContractEvidence]:
    coerced: list[ContractEvidence] = []
    for item in raw_items or []:
        if not isinstance(item, dict):
            continue
        text = item.get("text") or item.get("excerpt") or item.get("normalized_text") or ""
        if not text:
            continue
        try:
            coerced.append(
                ContractEvidence.model_construct(
                    schema_version=item.get("schema_version", 2),
                    clause_id=item.get("clause_id") or item.get("clause_uid") or fallback_clause_uid,
                    page=item.get("page") or 1,
                    span=item.get("span"),
                    text=text,
                    confidence=item.get("confidence", item.get("extraction_confidence", 1.0)),
                )
            )
        except Exception:
            continue

    return coerced


def _coerce_rag_citations(raw_items: list | None) -> list[RagCitation]:
    coerced: list[RagCitation] = []
    for item in raw_items or []:
        if not isinstance(item, dict):
            continue
        try:
            coerced.append(
                RagCitation.model_construct(
                    schema_version=item.get("schema_version", 2),
                    chunk_id=item.get("chunk_id", ""),
                    document_id=item.get("document_id", item.get("source_document_id", "")),
                    version=item.get("version", item.get("version_label", "")),
                    page=item.get("page") or 1,
                    source_path=item.get("source_path", ""),
                    chunk_hash=item.get("chunk_hash", ""),
                    score=item.get("score", 0.0),
                )
            )
        except Exception:
            continue
    return coerced


def _finding_record_to_finding(
    fr: FindingRecord,
    clause_lookup: dict[str, tuple[int, str]] | None = None,
) -> Finding | None:
    """Convert a FindingRecord DB row into a Finding schema object.

    clause_lookup maps clause_uid → (page_number, normalized_text) from
    ParsedClauseRecord so highlights land on the right page with the real text.
    """
    try:
        clause_uid = fr.clause_uid or "unknown"
        agent = fr.source_agent or "unknown"
        branch = "kira" if agent.startswith("kira") else "harvey"

        # Prefer actual parsed clause text + page for accurate highlighting.
        page_num = 1
        clause_text = fr.clause_text or fr.issue or ""
        if clause_lookup and clause_uid in clause_lookup:
            page_num, parsed_text = clause_lookup[clause_uid]
            if parsed_text:
                clause_text = parsed_text

        contract_evidence = _coerce_contract_evidence(fr.contract_evidence, clause_uid)
        rag_citations = _coerce_rag_citations(fr.rag_citations)
        return Finding.model_construct(
            finding_id=str(fr.id),
            clause_uid=clause_uid,
            issue_type="liability_exposure",
            severity=fr.severity,  # type: ignore[arg-type]
            exploitability=fr.exploitability or "medium",
            business_impact=fr.business_impact or "medium",
            description=fr.issue,
            recommendation="negotiate",
            recommendation_detail=fr.recommendation or "",
            recommended_change=fr.recommended_change,
            contract_evidence=contract_evidence,
            rag_citations=rag_citations,
            evidence=[
                EvidenceRef.model_construct(
                    schema_version=1,
                    document_hash="",
                    parser_version="",
                    clause_uid=clause_uid,
                    page=evidence.page if contract_evidence else page_num,
                    bbox=[0.0, 0.0, 0.0, 0.0],
                    normalized_text=evidence.text,
                    extraction_confidence=evidence.confidence,
                )
                for evidence in contract_evidence
            ],
            branch=branch,
            agent_role=agent,
            round_number=fr.round_number or 1,
            consensus_status=fr.consensus_state,
            consensus_state=fr.consensus_state,
            unresolved_by_consensus=fr.unresolved_by_consensus,
            human_edited=False,
            human_edit_delta=None,
        )
    except Exception:
        return None


async def _load_branch_stage_outputs(
    session: AsyncSession,
    run_id: str,
) -> tuple[ReviewBlockResult | None, ReviewBlockResult | None, AdminMergeOutput | None]:
    """Load structured outputs from legacy Harvey, active Kira, and Admin stages.

    For multi-round stages the latest completed round is used.
    """
    result = await session.execute(
        select(StageExecutionRecord).where(
            StageExecutionRecord.run_id == run_id,
            StageExecutionRecord.stage_name.in_(["harvey_review_block", "kira_review_block", "admin_merge"]),
            StageExecutionRecord.status == "completed",
        )
    )
    # Keep the highest round_number per stage_name.
    stages_by_name: dict[str, StageExecutionRecord] = {}
    for stage in result.scalars().all():
        existing = stages_by_name.get(stage.stage_name)
        if existing is None or (stage.round_number or 0) > (existing.round_number or 0):
            stages_by_name[stage.stage_name] = stage

    harvey_block: ReviewBlockResult | None = None
    kira_block: ReviewBlockResult | None = None
    admin_out: AdminMergeOutput | None = None

    if (s := stages_by_name.get("harvey_review_block")) and s.structured_output:
        try:
            harvey_block = ReviewBlockResult.model_validate(s.structured_output)
        except Exception:
            pass

    if (s := stages_by_name.get("kira_review_block")) and s.structured_output:
        try:
            kira_block = ReviewBlockResult.model_validate(s.structured_output)
        except Exception:
            pass

    if (s := stages_by_name.get("admin_merge")) and s.structured_output:
        try:
            admin_out = AdminMergeOutput.model_validate(s.structured_output)
        except Exception:
            pass

    return harvey_block, kira_block, admin_out


async def _load_full_findings(session: AsyncSession, run_id: str) -> list[Finding]:
    """Load Finding objects with source priority admin > harvey > kira.

    final_reviewer is no longer a valid source and is skipped.
    """
    inactive_result = await session.execute(
        select(FindingRecord.id).where(
            FindingRecord.run_id == run_id,
            (FindingRecord.dismissed_at.is_not(None)) | (FindingRecord.accepted_at.is_not(None)),
        )
    )
    inactive_finding_ids = {str(row[0]) for row in inactive_result.all()}

    # Load run to read accepted/dismissed admin finding IDs persisted on verdict_payload.
    run_record = (await session.execute(select(RunRecord).where(RunRecord.id == run_id))).scalar_one_or_none()
    admin_accepted: set[str] = set((run_record.verdict_payload or {}).get("accepted_admin_finding_ids") or []) if run_record else set()
    admin_dismissed: set[str] = set((run_record.verdict_payload or {}).get("dismissed_admin_finding_ids") or []) if run_record else set()
    admin_inactive = admin_accepted | admin_dismissed

    # 1. Primary: admin_merge structured output (latest round).
    stage_result = await session.execute(
        select(StageExecutionRecord)
        .where(
            StageExecutionRecord.run_id == run_id,
            StageExecutionRecord.stage_name == "admin_merge",
            StageExecutionRecord.status == "completed",
        )
        .order_by(StageExecutionRecord.round_number.desc())
    )
    stage = stage_result.scalars().first()
    def _dedup_key(clause_uid: str | None, description: str | None) -> tuple[str, str]:
        # Normalize on (clause_uid, description) only — issue_type is unreliable across sources
        # (admin_merge uses Finding.issue_type, FindingRecord rows have no equivalent column),
        # so any tuple that includes it produces phantom duplicates.
        norm_desc = " ".join((description or "").lower().split())[:200]
        return (clause_uid or "", norm_desc)

    merged_findings: list[Finding] = []
    seen_finding_keys: set[tuple[str, str]] = set()
    admin_findings_raw = stage.structured_output.get("merged_findings", []) if stage and stage.structured_output else []
    if stage and stage.structured_output:
        for f in admin_findings_raw:
            try:
                finding = Finding.model_validate(f)
                if finding.finding_id in inactive_finding_ids:
                    continue
                if finding.finding_id in admin_inactive:
                    continue
                key = _dedup_key(finding.clause_uid, finding.description)
                if key in seen_finding_keys:
                    continue
                merged_findings.append(finding)
                seen_finding_keys.add(key)
            except Exception:
                continue

    # 2. Supplement with FindingRecord rows not already covered.
    # Exclude findings that the user has dismissed or accepted via the editor.
    db_result = await session.execute(
        select(FindingRecord)
        .where(
            FindingRecord.run_id == run_id,
            FindingRecord.dismissed_at.is_(None),
            FindingRecord.accepted_at.is_(None),
        )
        .order_by(FindingRecord.created_at.asc())
    )
    db_findings = db_result.scalars().all()

    # Build clause lookup for accurate page numbers and clause text.
    clause_result = await session.execute(
        select(
            ParsedClauseRecord.clause_uid,
            ParsedClauseRecord.page_number,
            ParsedClauseRecord.normalized_text,
        ).where(ParsedClauseRecord.run_id == run_id)
    )
    clause_lookup: dict[str, tuple[int, str]] = {
        row.clause_uid: (row.page_number, row.normalized_text)
        for row in clause_result.all()
    }

    selected_records: list[FindingRecord] = []
    seen_db_keys: set[tuple[str, str]] = set()
    for fr in db_findings:
        agent = fr.source_agent or ""
        if agent.startswith("final_reviewer"):
            continue
        key = _dedup_key(fr.clause_uid, fr.issue)
        if key in seen_finding_keys or key in seen_db_keys:
            continue
        seen_db_keys.add(key)
        selected_records.append(fr)

    selected_records.sort(key=lambda fr: (_source_priority(fr.source_agent), fr.created_at))
    for fr in selected_records:
        finding = _finding_record_to_finding(fr, clause_lookup=clause_lookup)
        if finding is not None:
            merged_findings.append(finding)

    logger.info(
        "_load_full_findings: run=%s admin_findings=%d db_kept=%d total=%d",
        run_id, len(admin_findings_raw), len(selected_records), len(merged_findings),
    )
    return merged_findings


async def load_harvey_findings(session: AsyncSession, run_id: str) -> list[Finding]:
    """Load Harvey-origin findings as a separate policy/precedent conflict lane."""
    clause_result = await session.execute(
        select(
            ParsedClauseRecord.clause_uid,
            ParsedClauseRecord.page_number,
            ParsedClauseRecord.normalized_text,
        ).where(ParsedClauseRecord.run_id == run_id)
    )
    clause_lookup: dict[str, tuple[int, str]] = {
        row.clause_uid: (row.page_number, row.normalized_text)
        for row in clause_result.all()
    }

    result = await session.execute(
        select(FindingRecord)
        .where(
            FindingRecord.run_id == run_id,
            FindingRecord.source_agent.like("harvey%"),
            FindingRecord.dismissed_at.is_(None),
        )
        .order_by(FindingRecord.created_at.asc())
    )
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for record in result.scalars().all():
        finding = _finding_record_to_finding(record, clause_lookup=clause_lookup)
        if finding is None:
            continue
        key = (finding.clause_uid, " ".join(finding.description.lower().split())[:200])
        if key in seen:
            continue
        seen.add(key)
        findings.append(finding)
    return findings


def _annotate_consensus(
    findings: list[Finding],
    harvey_block: ReviewBlockResult | None,
    kira_block: ReviewBlockResult | None,
) -> list[Finding]:
    """Overlay consensus_status and unresolved_by_consensus from branch block results."""
    harvey_consensus_uids: set[str] = set()
    if harvey_block:
        for f in harvey_block.aggregated_findings:
            if f.consensus_status == "consensus":
                harvey_consensus_uids.add(f.clause_uid)

    kira_consensus_uids: set[str] = set()
    if kira_block:
        for f in kira_block.aggregated_findings:
            if f.consensus_status == "consensus":
                kira_consensus_uids.add(f.clause_uid)

    annotated: list[Finding] = []
    for f in findings:
        # If branch block has consensus data for this clause, overlay it.
        if f.consensus_status is not None:
            annotated.append(f)
            continue

        if f.branch == "harvey":
            if harvey_block is None:
                annotated.append(f)
            elif f.clause_uid in harvey_consensus_uids:
                annotated.append(f.model_copy(update={"consensus_status": "consensus", "unresolved_by_consensus": False}))
            else:
                annotated.append(f.model_copy(update={"consensus_status": "unresolved_by_consensus", "unresolved_by_consensus": True}))
        elif f.branch == "kira":
            if kira_block is None:
                annotated.append(f)
            elif f.clause_uid in kira_consensus_uids:
                annotated.append(f.model_copy(update={"consensus_status": "consensus", "unresolved_by_consensus": False}))
            else:
                annotated.append(f.model_copy(update={"consensus_status": "unresolved_by_consensus", "unresolved_by_consensus": True}))
        else:
            annotated.append(f)
    return annotated


def _build_final_verdict(
    run: RunRecord,
    findings: list[FindingRecord],
    human_action: str | None,
    full_findings: list[Finding] | None = None,
    harvey_block: ReviewBlockResult | None = None,
    kira_block: ReviewBlockResult | None = None,
    admin_block: AdminMergeOutput | None = None,
) -> FinalVerdict | None:
    """Build FinalVerdict exposing Harvey RAG context, Kira findings, Admin merged findings,
    unresolved_by_consensus flags, and evidence per evidence-schema.
    """
    if run.verdict_payload is not None:
        # Backfill fields added after old runs were finalized so legacy payloads still validate.
        payload: dict = {**run.verdict_payload}
        payload.setdefault("run_id", run.id)
        payload.setdefault("finalized_at", (run.updated_at or run.created_at).isoformat())
        payload.setdefault("overall_risk_level", "low")
        payload.setdefault("summary", "")
        payload.setdefault("recommendations", [])
        payload.setdefault("human_action", "approved")
        cached = FinalVerdict.model_validate(payload)
        # Backfill findings if the cached payload has none (legacy runs stored before this fix).
        if not cached.findings and full_findings:
            annotated = _annotate_consensus(full_findings, harvey_block, kira_block)
            cached = cached.model_copy(update={"findings": annotated})
        return cached

    if human_action is None:
        return None

    # Annotate full_findings with consensus data from Harvey/Kira block results.
    verdict_findings = _annotate_consensus(full_findings or [], harvey_block, kira_block)

    # Derive overall risk from annotated findings.
    risk = "low"
    for f in verdict_findings:
        sev = f.severity if hasattr(f, "severity") else None
        if sev == "critical":
            risk = "critical"
            break
        if sev == "high":
            risk = "high"
        elif sev == "medium" and risk == "low":
            risk = "medium"

    unresolved_count = sum(1 for f in verdict_findings if getattr(f, "unresolved_by_consensus", False))

    recommendations: list[str] = []
    for fr in findings:
        if fr.accepted_at is not None or fr.dismissed_at is not None:
            continue
        if fr.recommended_change:
            recommendations.append(fr.recommended_change)
        elif fr.recommendation:
            recommendations.append(fr.recommendation)

    # Build summary incorporating branch breakdown.
    harvey_count = sum(1 for f in verdict_findings if getattr(f, "branch", None) == "harvey")
    kira_count = sum(1 for f in verdict_findings if getattr(f, "branch", None) == "kira")
    admin_merged_count = len(admin_block.merged_findings) if admin_block else 0
    summary = (
        f"{len(verdict_findings)} findings reviewed "
        f"(Harvey: {harvey_count}, Kira: {kira_count}; "
        f"admin-merged: {admin_merged_count}; "
        f"unresolved by consensus: {unresolved_count})."
    )

    clause_verdicts = admin_block.clause_verdicts if admin_block else []

    return FinalVerdict(
        run_id=run.id,
        finalized_at=run.updated_at,
        overall_risk_level=risk,  # type: ignore[arg-type]
        findings=verdict_findings,
        clause_verdicts=clause_verdicts,
        summary=summary,
        recommendations=recommendations,
        human_action=human_action,  # type: ignore[arg-type]
        unresolved_finding_count=unresolved_count,
    )


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
    """Create a new analysis run.

    tenant_id must be derived from JWT membership by the caller
    (auth-derived-tenancy — never from request body).
    """
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

    for stage_name in STAGE_SEQUENCE:
        session.add(
            StageExecutionRecord(
                run_id=run.id,
                stage_name=stage_name,
                stage_order=_STAGE_ORDER[stage_name],
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
    all_stages = stages_result.scalars().all()

    stage_names = [s.stage_name for s in all_stages]
    is_legacy = _is_legacy_run(stage_names)

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
        for stage in all_stages
    ]

    full_findings = await _load_full_findings(session, run_id)

    # Legacy runs: render verdict read-only from cached payload; never re-enqueue.
    if is_legacy:
        verdict = _build_final_verdict(run, findings, run_review.action if run_review else None, full_findings=full_findings)
    else:
        harvey_block, kira_block, admin_block = await _load_branch_stage_outputs(session, run_id)
        verdict = _build_final_verdict(
            run,
            findings,
            run_review.action if run_review else None,
            full_findings=full_findings,
            harvey_block=harvey_block,
            kira_block=kira_block,
            admin_block=admin_block,
        )

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
    if run.status not in ("awaiting_human_review", "under_review"):
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

    # Finalize directly after admin_merge + human review — no final_review_block.
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

    # Check whether this is a legacy run before loading branch outputs.
    stages_result = await session.execute(
        select(StageExecutionRecord.stage_name).where(StageExecutionRecord.run_id == run_id)
    )
    stage_names = [row[0] for row in stages_result.all()]
    is_legacy = _is_legacy_run(stage_names)

    if is_legacy:
        verdict = _build_final_verdict(run, findings, human_action, full_findings=full_findings)
    else:
        harvey_block, kira_block, admin_block = await _load_branch_stage_outputs(session, run_id)
        verdict = _build_final_verdict(
            run,
            findings,
            human_action,
            full_findings=full_findings,
            harvey_block=harvey_block,
            kira_block=kira_block,
            admin_block=admin_block,
        )

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

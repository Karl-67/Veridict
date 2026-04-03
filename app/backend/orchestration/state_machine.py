"""
Deterministic stage execution graph.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session, aliased

from app.backend.agents.admin import AdminMergeAgent, ReviewBlockAggregator
from app.backend.agents.reviewer import FinalReviewerAgent, HarveyReviewerAgent, KiraReviewerAgent
from app.backend.agents.validator import HarveyValidatorAgent, KiraValidatorAgent
from app.backend.core.config import Settings
from app.backend.db.models import FindingRecord, ParsedClauseRecord, RunRecord, StageExecutionRecord
from app.backend.models.schemas import BranchReviewOutput, ReviewBlockResult, ValidatorOutput
from app.backend.services.compliance_repository import MissingComplianceScopeError, resolve_applicable_corpora
from app.backend.services.event_stream import append_run_event
from app.backend.services.parser import build_clause_index, parse_pdf_to_canonical_document
from app.backend.services.policy_repository import MissingLineageError, load_prior_policy_versions, resolve_policy_lineage


def claim_next_stage(session: Session, settings: Settings, worker_id: str) -> StageExecutionRecord | None:
    now = datetime.utcnow()
    predecessor = aliased(StageExecutionRecord)
    stage = session.scalars(
        select(StageExecutionRecord)
        .join(RunRecord, RunRecord.id == StageExecutionRecord.run_id)
        .where(
            StageExecutionRecord.stage_name != "finalized",
            RunRecord.status.in_(["created", "processing"]),
            StageExecutionRecord.status.in_(["pending", "retrying"]),
            or_(StageExecutionRecord.lease_expires_at.is_(None), StageExecutionRecord.lease_expires_at < now),
            ~exists(
                select(predecessor.id).where(
                    predecessor.run_id == StageExecutionRecord.run_id,
                    predecessor.stage_order < StageExecutionRecord.stage_order,
                    predecessor.status != "completed",
                )
            ),
        )
        .order_by(StageExecutionRecord.stage_order.asc(), StageExecutionRecord.created_at.asc())
        .with_for_update(skip_locked=True)
    ).first()
    if stage is None:
        return None
    stage.status = "running"
    stage.worker_id = worker_id
    stage.started_at = now
    stage.lease_expires_at = now + timedelta(seconds=settings.worker_lease_duration_seconds)
    stage.run.status = "processing"
    append_run_event(session, stage.run_id, "stage_started", {"stage_name": stage.stage_name})
    session.commit()
    session.refresh(stage)
    return stage


def advance_stage(session: Session, stage: StageExecutionRecord, structured_output: dict | None = None) -> None:
    stage.status = "completed"
    stage.finished_at = datetime.utcnow()
    stage.structured_output = structured_output
    append_run_event(session, stage.run_id, "stage_completed", {"stage_name": stage.stage_name})
    if stage.stage_name == "awaiting_human_review":
        stage.run.status = "awaiting_human_review"
        append_run_event(session, stage.run_id, "awaiting_human_review", {"stage_name": stage.stage_name})
    session.commit()


def retry_stage(session: Session, stage: StageExecutionRecord, error_detail: str) -> None:
    stage.retry_count += 1
    if stage.retry_count >= stage.max_retries:
        mark_stage_failed(session, stage, error_detail)
        return
    stage.status = "retrying"
    stage.failure_reason = error_detail
    stage.lease_expires_at = None
    append_run_event(session, stage.run_id, "stage_retrying", {"stage_name": stage.stage_name, "error": error_detail})
    session.commit()


def mark_stage_failed(session: Session, stage: StageExecutionRecord, error_detail: str) -> None:
    stage.status = "failed"
    stage.failure_reason = error_detail
    stage.finished_at = datetime.utcnow()
    stage.run.status = "failed"
    append_run_event(session, stage.run_id, "stage_failed", {"stage_name": stage.stage_name, "error": error_detail})
    session.commit()


def mark_run_blocked(session: Session, run: RunRecord, blocked_reason: str) -> None:
    run.status = "blocked"
    run.blocked_reason = blocked_reason
    append_run_event(session, run.id, "stage_failed", {"stage_name": "blocked", "error": blocked_reason})
    session.commit()


def queue_disputed_findings_for_reround(session: Session, run: RunRecord, disputed_finding_ids: list[str]) -> None:
    run.current_round += 1
    for stage_name in ("final_review_block",):
        session.add(
            StageExecutionRecord(
                run_id=run.id,
                stage_name=stage_name,
                stage_order=10,
                round_number=run.current_round,
                attempt_number=1,
                status="pending",
                max_retries=5,
                structured_output={"disputed_finding_ids": disputed_finding_ids},
            )
        )
    session.commit()


def _provider(settings: Settings):
    from app.backend.providers.google_provider import build_gemini_provider

    return build_gemini_provider(
        api_key=settings.gemini_api_key,
        model_name=settings.gemini_model_name,
        max_retries=settings.max_stage_retries,
    )


def _load_clause_index(session: Session, run_id: str) -> list[dict]:
    clause_records = session.scalars(
        select(ParsedClauseRecord).where(ParsedClauseRecord.run_id == run_id).order_by(ParsedClauseRecord.page_number.asc())
    ).all()
    return build_clause_index(
        type(
            "CanonicalDoc",
            (),
            {
                "clauses": [
                    {
                        "document_hash": clause.document_hash,
                        "parser_version": clause.parser_version,
                        "clause_uid": clause.clause_uid,
                        "page": clause.page_number,
                        "bbox": [clause.bbox_x0 or 0.0, clause.bbox_y0 or 0.0, clause.bbox_x1 or 0.0, clause.bbox_y1 or 0.0],
                        "normalized_text": clause.normalized_text,
                        "extraction_confidence": clause.extraction_confidence or 0.0,
                        "ocr_used": clause.ocr_used,
                    }
                    for clause in clause_records
                ]
            },
        )()
    )


def _stage_output(session: Session, run_id: str, stage_name: str) -> dict:
    stage = session.scalars(
        select(StageExecutionRecord).where(StageExecutionRecord.run_id == run_id, StageExecutionRecord.stage_name == stage_name)
    ).first()
    return stage.structured_output if stage and stage.structured_output else {}


def _to_finding_record(stage: StageExecutionRecord, finding) -> FindingRecord:
    return FindingRecord(
        run_id=stage.run_id,
        stage_execution_id=stage.id,
        source_agent=finding.agent_role,
        round_number=finding.round_number,
        clause_uid=finding.clause_uid,
        clause_text=finding.description,
        issue=finding.description,
        severity=finding.severity,
        recommendation=finding.recommendation_detail,
        is_disputed=finding.consensus_status == "disputed" or finding.unresolved_by_consensus,
        is_confirmed=finding.consensus_status == "consensus",
    )


async def _run_harvey_review_block(clause_index: list[dict], context: dict, settings: Settings, round_number: int) -> ReviewBlockResult:
    provider = _provider(settings)
    reviewers = [HarveyReviewerAgent(provider, index) for index in (1, 2, 3)]
    review_outputs = [await reviewer.review(clause_index, context) for reviewer in reviewers]
    review_outputs = [
        output.model_copy(update={"findings": [finding.model_copy(update={"round_number": round_number}) for finding in output.findings]})
        for output in review_outputs
    ]
    votes = [await reviewer.vote(review_outputs) for reviewer in reviewers]
    return ReviewBlockAggregator().aggregate(
        branch="harvey",
        review_outputs=review_outputs,
        reviewer_votes=votes,
        round_number=round_number,
        max_reruns=5,
    )


async def _run_kira_review_block(clause_index: list[dict], context: dict, settings: Settings, round_number: int) -> ReviewBlockResult:
    provider = _provider(settings)
    reviewers = [KiraReviewerAgent(provider, index) for index in (1, 2, 3)]
    review_outputs = [await reviewer.review(clause_index, context) for reviewer in reviewers]
    review_outputs = [
        output.model_copy(update={"findings": [finding.model_copy(update={"round_number": round_number}) for finding in output.findings]})
        for output in review_outputs
    ]
    votes = [await reviewer.vote(review_outputs) for reviewer in reviewers]
    return ReviewBlockAggregator().aggregate(
        branch="kira",
        review_outputs=review_outputs,
        reviewer_votes=votes,
        round_number=round_number,
        max_reruns=5,
    )


async def _run_final_review_block(clause_index: list[dict], merged_findings: list[dict], settings: Settings, round_number: int) -> ReviewBlockResult:
    provider = _provider(settings)
    reviewers = [FinalReviewerAgent(provider, index) for index in (1, 2, 3)]
    review_outputs = [await reviewer.review(clause_index, merged_findings, round_number=round_number) for reviewer in reviewers]
    votes = [await reviewer.vote(review_outputs) for reviewer in reviewers]
    return ReviewBlockAggregator().aggregate(
        branch="final",
        review_outputs=review_outputs,
        reviewer_votes=votes,
        round_number=round_number,
        max_reruns=5,
    )


def execute_stage(session: Session, stage: StageExecutionRecord, settings: Settings) -> None:
    run = stage.run
    try:
        if stage.stage_name == "create_run":
            advance_stage(session, stage, {"run_id": run.id})
            return

        if stage.stage_name == "ingest_pdf":
            if not Path(run.storage_path).exists():
                raise FileNotFoundError(f"Missing document at {run.storage_path}")
            advance_stage(session, stage, {"storage_path": run.storage_path})
            return

        if stage.stage_name == "parse_ocr_normalize":
            parsed = parse_pdf_to_canonical_document(Path(run.storage_path).read_bytes(), settings)
            for clause in parsed.clauses:
                session.merge(
                    ParsedClauseRecord(
                        run_id=run.id,
                        clause_uid=clause["clause_uid"],
                        document_hash=clause["document_hash"],
                        parser_version=clause["parser_version"],
                        page_number=clause["page"],
                        bbox_x0=clause["bbox"][0],
                        bbox_y0=clause["bbox"][1],
                        bbox_x1=clause["bbox"][2],
                        bbox_y1=clause["bbox"][3],
                        normalized_text=clause["normalized_text"],
                        extraction_confidence=clause["extraction_confidence"],
                        ocr_used=clause["ocr_used"],
                    )
                )
            advance_stage(session, stage, {"document_hash": parsed.document_hash, "low_confidence": parsed.low_confidence})
            return

        if stage.stage_name == "clause_index":
            clause_index = _load_clause_index(session, run.id)
            advance_stage(session, stage, {"clause_count": len(clause_index)})
            return

        if stage.stage_name == "harvey_context_load":
            lineage = resolve_policy_lineage(run.tenant_id, run.policy_family_id or "", run.policy_version_number or 0)
            advance_stage(
                session,
                stage,
                {
                    "lineage": lineage,
                    "prior_versions": load_prior_policy_versions(run.tenant_id, run.policy_family_id or "", run.policy_version_number or 0),
                    "playbook_rules": lineage.get("rules_payload", []),
                },
            )
            return

        if stage.stage_name == "kira_context_load":
            advance_stage(session, stage, resolve_applicable_corpora(run.tenant_id, run.jurisdiction, run.regime, run.effective_date))
            return

        if stage.stage_name == "harvey_review_block":
            clause_index = _load_clause_index(session, run.id)
            context = _stage_output(session, run.id, "harvey_context_load")
            result = asyncio.run(_run_harvey_review_block(clause_index, context, settings, stage.round_number))
            if result.rerun_required:
                session.add(
                    StageExecutionRecord(
                        run_id=run.id,
                        stage_name=stage.stage_name,
                        stage_order=stage.stage_order,
                        round_number=stage.round_number + 1,
                        attempt_number=1,
                        status="pending",
                        max_retries=5,
                    )
                )
                advance_stage(session, stage, result.model_dump(mode="json"))
                return
            validator = HarveyValidatorAgent(_provider(settings))
            aggregate_output = BranchReviewOutput(
                branch="harvey",
                reviewer_index=result.accepted_reviewer_indexes[0] if result.accepted_reviewer_indexes else 1,
                findings=result.aggregated_findings,
                raw_response_id=None,
            )
            validated = asyncio.run(validator.validate([aggregate_output], [clause["clause_uid"] for clause in clause_index]))
            for finding in validated.validated_findings:
                session.add(_to_finding_record(stage, finding))
            advance_stage(
                session,
                stage,
                {
                    "review_block": result.model_dump(mode="json"),
                    "validated_output": validated.model_dump(mode="json"),
                },
            )
            return

        if stage.stage_name == "kira_review_block":
            clause_index = _load_clause_index(session, run.id)
            context = _stage_output(session, run.id, "kira_context_load")
            result = asyncio.run(_run_kira_review_block(clause_index, context, settings, stage.round_number))
            if result.rerun_required:
                session.add(
                    StageExecutionRecord(
                        run_id=run.id,
                        stage_name=stage.stage_name,
                        stage_order=stage.stage_order,
                        round_number=stage.round_number + 1,
                        attempt_number=1,
                        status="pending",
                        max_retries=5,
                    )
                )
                advance_stage(session, stage, result.model_dump(mode="json"))
                return
            validator = KiraValidatorAgent(_provider(settings))
            aggregate_output = BranchReviewOutput(
                branch="kira",
                reviewer_index=result.accepted_reviewer_indexes[0] if result.accepted_reviewer_indexes else 1,
                findings=result.aggregated_findings,
                raw_response_id=None,
            )
            validated = asyncio.run(
                validator.validate(
                    [aggregate_output],
                    [clause["clause_uid"] for clause in clause_index],
                    run.jurisdiction or "",
                    run.regime or "",
                )
            )
            for finding in validated.validated_findings:
                session.add(_to_finding_record(stage, finding))
            advance_stage(
                session,
                stage,
                {
                    "review_block": result.model_dump(mode="json"),
                    "validated_output": validated.model_dump(mode="json"),
                },
            )
            return

        if stage.stage_name == "admin_merge":
            harvey_output = _stage_output(session, run.id, "harvey_review_block").get("validated_output", {})
            kira_output = _stage_output(session, run.id, "kira_review_block").get("validated_output", {})
            merged = AdminMergeAgent().merge(
                ValidatorOutput.model_validate(harvey_output),
                ValidatorOutput.model_validate(kira_output),
            )
            for finding in merged.merged_findings:
                session.add(_to_finding_record(stage, finding))
            advance_stage(session, stage, merged.model_dump(mode="json"))
            return

        if stage.stage_name == "final_review_block":
            clause_index = _load_clause_index(session, run.id)
            merged = _stage_output(session, run.id, "admin_merge").get("merged_findings", [])
            result = asyncio.run(_run_final_review_block(clause_index, merged, settings, stage.round_number))
            if result.rerun_required:
                session.add(
                    StageExecutionRecord(
                        run_id=run.id,
                        stage_name=stage.stage_name,
                        stage_order=stage.stage_order,
                        round_number=stage.round_number + 1,
                        attempt_number=1,
                        status="pending",
                        max_retries=5,
                    )
                )
                append_run_event(session, run.id, "consensus_unresolved", {"stage_name": stage.stage_name, "round_number": stage.round_number})
                advance_stage(session, stage, result.model_dump(mode="json"))
                return
            for finding in result.aggregated_findings:
                session.add(_to_finding_record(stage, finding))
            advance_stage(session, stage, result.model_dump(mode="json"))
            return

        if stage.stage_name == "awaiting_human_review":
            advance_stage(session, stage, {"status": "awaiting_human_review"})
            return

        advance_stage(session, stage, {"placeholder": True})
    except (MissingLineageError, MissingComplianceScopeError) as exc:
        mark_run_blocked(session, run, getattr(exc, "blocked_reason", str(exc)))
    except Exception as exc:
        retry_stage(session, stage, str(exc))

"""
Deterministic stage execution graph.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)
_FAILURE_LOG = Path("logs/failures.jsonl")


def _write_failure_log(run_id: str, stage_name: str, error_detail: str, retry_count: int) -> None:
    """Append one JSON line to logs/failures.jsonl for every permanent stage failure."""
    try:
        _FAILURE_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "run_id": run_id,
            "stage": stage_name,
            "error": error_detail,
            "retry_count": retry_count,
        }
        with _FAILURE_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception as exc:
        logger.warning("Failed to write failure log: %s", exc)

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.backend.agents.admin import AdminMergeAgent, ReviewBlockAggregator
from app.backend.agents.reviewer import HarveyReviewerAgent, KiraReviewerAgent
from app.backend.agents.validator import KiraValidatorAgent
from app.backend.core.config import Settings
from app.backend.db.models import FindingRecord, ParsedClauseRecord, RunRecord, StageExecutionRecord
from app.backend.models.schemas import BranchReviewOutput, ReviewBlockResult, ValidatorOutput
from app.backend.services.compliance_repository import MissingComplianceScopeError, resolve_applicable_corpora
from app.backend.services.event_stream import append_run_event
from app.backend.services.parser import build_clause_index, parse_pdf_to_canonical_document
from app.backend.services.policy_repository import MissingLineageError, load_prior_policy_versions, resolve_policy_lineage
from app.backend.services.rag_retrieval import HarveyRagRetriever

# Stages from retired topology that must never be re-enqueued or claimed.
_LEGACY_STAGES = frozenset({"final_review_block", "harvey_review_block", "kira_context_load"})


def claim_next_stage(session: Session, settings: Settings, worker_id: str) -> StageExecutionRecord | None:
    now = datetime.utcnow()
    predecessor = aliased(StageExecutionRecord)
    stage = session.scalars(
        select(StageExecutionRecord)
        .join(RunRecord, RunRecord.id == StageExecutionRecord.run_id)
        .where(
            StageExecutionRecord.stage_name != "finalized",
            StageExecutionRecord.stage_name.not_in(_LEGACY_STAGES),
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
    _write_failure_log(stage.run_id, stage.stage_name, error_detail, stage.retry_count)
    session.commit()


def mark_run_blocked(session: Session, run: RunRecord, blocked_reason: str) -> None:
    run.status = "blocked"
    run.blocked_reason = blocked_reason
    append_run_event(session, run.id, "stage_failed", {"stage_name": "blocked", "error": blocked_reason})
    _write_failure_log(run.id, "blocked", blocked_reason, 0)
    session.commit()



def _provider(settings: Settings):
    from app.backend.providers.openrouter_provider import build_openrouter_provider, build_ollama_provider

    if settings.llm_provider == "ollama":
        return build_ollama_provider(
            base_url=settings.ollama_base_url,
            model_name=settings.ollama_model,
            max_retries=settings.max_stage_retries,
        )
    return build_openrouter_provider(
        api_key=settings.openrouter_api_key,
        model_name=settings.openrouter_model,
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
    """Return the structured_output of the latest completed execution for a stage.

    Stages like kira_review_block can have multiple rounds; we want the
    highest round_number that has a non-null structured_output (i.e. the
    final round that wrote validated_output, not an intermediate rerun row).
    """
    stages = session.scalars(
        select(StageExecutionRecord)
        .where(
            StageExecutionRecord.run_id == run_id,
            StageExecutionRecord.stage_name == stage_name,
            StageExecutionRecord.structured_output.isnot(None),
        )
        .order_by(
            StageExecutionRecord.round_number.desc(),
            StageExecutionRecord.attempt_number.desc(),
            StageExecutionRecord.finished_at.desc(),
        )
    ).all()
    # Prefer the row that contains validated_output (final round)
    for stage in stages:
        if stage.structured_output and "validated_output" in stage.structured_output:
            return stage.structured_output
    # Fall back to latest round with any output
    if stages:
        return stages[0].structured_output or {}
    return {}


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
    try:
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
    finally:
        await provider.aclose()


async def _run_kira_review_block(clause_index: list[dict], context: dict, settings: Settings, round_number: int) -> ReviewBlockResult:
    provider = _provider(settings)
    try:
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
    finally:
        await provider.aclose()



def _check_parser_confidence(session: Session, run_id: str) -> tuple[bool, str]:
    """Returns (is_blocked, reason). Blocks if any clause confidence < 0.3 per parser-confidence-contract."""
    min_conf = session.scalar(
        select(func.min(ParsedClauseRecord.extraction_confidence)).where(
            ParsedClauseRecord.run_id == run_id,
            ParsedClauseRecord.extraction_confidence.isnot(None),
        )
    )
    if min_conf is not None and float(min_conf) < 0.3:
        return True, f"Minimum clause extraction confidence {min_conf:.2f} < 0.3; manual override required before review"
    return False, ""


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
            clause_index = _load_clause_index(session, run.id)
            rag_trace_dicts: list[dict] = []
            try:
                rag_retriever = HarveyRagRetriever(session)
                rag_trace = rag_retriever.retrieve_for_run(run.id, clause_index)
                rag_trace_dicts = [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
                    for item in rag_trace
                ]
            except Exception as rag_exc:
                logger.warning("Harvey RAG retrieval failed for run %s: %s", run.id, rag_exc)
            advance_stage(
                session,
                stage,
                {
                    "lineage": lineage,
                    "prior_versions": load_prior_policy_versions(run.tenant_id, run.policy_family_id or "", run.policy_version_number or 0),
                    "playbook_rules": (lambda rp: rp.get("rules", []) if isinstance(rp, dict) else (rp or []))(lineage.get("rules_payload")),
                    "rag_trace": rag_trace_dicts,
                },
            )
            return

        if stage.stage_name == "kira_context_load":
            advance_stage(session, stage, resolve_applicable_corpora(run.tenant_id, run.jurisdiction, run.regime, run.effective_date))
            return

        if stage.stage_name == "kira_review_block":
            clause_index = _load_clause_index(session, run.id)

            # Honor parser-confidence-contract: block before review if confidence < 0.3
            is_blocked, blocked_reason = _check_parser_confidence(session, run.id)
            if is_blocked:
                mark_run_blocked(session, run, blocked_reason)
                return

            # Kira finds the problems. Harvey RAG evidence is passed in as read-only context.
            harvey_context = _stage_output(session, run.id, "harvey_context_load")
            kira_context = resolve_applicable_corpora(run.tenant_id, run.jurisdiction, run.regime, run.effective_date)
            context = {**kira_context, "harvey_rag_trace": harvey_context.get("rag_trace", [])}
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
            kira_output = _stage_output(session, run.id, "kira_review_block").get("validated_output", {})
            harvey_output = {
                "schema_version": 2,
                "branch": "harvey",
                "validated_findings": [],
                "hallucinated_clause_uids": [],
                "notes": "Harvey supplied RAG evidence only; Kira is the problem-finding branch.",
            }
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

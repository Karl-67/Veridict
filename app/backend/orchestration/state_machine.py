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

from app.backend.services.metrics import (
    finding_severity_total,
    findings_per_run,
    kira_iterations_per_run,
    kira_panel_votes_total,
)
from app.backend.agents.admin import AdminMergeAgent, ReviewBlockAggregator
from app.backend.agents.reviewer import (
    HarveyReviewer,
    KiraWorker,
    KiraPanelReviewer,
    aggregate_kira_panel_feedback,
)
from app.backend.agents.validator import KiraValidatorAgent
from app.backend.db.models import RagChunk
from app.backend.core.config import Settings
from app.backend.db.models import FindingRecord, ParsedClauseRecord, RunRecord, StageExecutionRecord
from app.backend.models.schemas import BranchReviewOutput, ReviewBlockResult
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
    from app.backend.providers.openrouter_provider import (
        build_openrouter_provider, build_ollama_provider, build_vllm_provider,
    )

    if settings.llm_provider == "ollama":
        return build_ollama_provider(
            base_url=settings.ollama_base_url,
            model_name=settings.ollama_model,
            max_retries=settings.max_stage_retries,
        )
    if settings.llm_provider == "vllm":
        return build_vllm_provider(
            base_url=settings.vllm_base_url,
            model_name=settings.vllm_base_model,
            max_retries=settings.max_stage_retries,
        )
    return build_openrouter_provider(
        api_key=settings.openrouter_api_key,
        model_name=settings.openrouter_model,
        max_retries=settings.max_stage_retries,
    )


def _kira_provider(settings: Settings):
    """Returns a provider for Kira. Uses the fine-tuned cloud endpoint when configured."""
    if settings.kira_model_url:
        from app.backend.providers.openrouter_provider import build_ollama_provider
        return build_ollama_provider(
            base_url=settings.kira_model_url,
            model_name=settings.kira_model_name,
            max_retries=settings.max_stage_retries,
        )
    return _provider(settings)


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
    kwargs = {}
    if stage.stage_name != "admin_merge":
        kwargs["id"] = finding.finding_id
    return FindingRecord(
        **kwargs,
        run_id=stage.run_id,
        stage_execution_id=stage.id,
        source_agent=finding.agent_role,
        round_number=finding.round_number,
        clause_uid=finding.clause_uid,
        clause_text=finding.description,
        issue=finding.description,
        severity=finding.severity,
        recommendation=finding.recommendation_detail,
        recommended_change=getattr(finding, "recommended_change", None),
        is_disputed=finding.consensus_status == "disputed" or finding.unresolved_by_consensus,
        is_confirmed=finding.consensus_status == "consensus",
        contract_evidence=[
            e.model_dump(mode="json") if hasattr(e, "model_dump") else e
            for e in (getattr(finding, "contract_evidence", None) or [])
        ],
        rag_citations=[
            c.model_dump(mode="json") if hasattr(c, "model_dump") else c
            for c in (getattr(finding, "rag_citations", None) or [])
        ],
        consensus_state=finding.consensus_status,
        business_impact=getattr(finding, "business_impact", None),
        exploitability=getattr(finding, "exploitability", None),
        unresolved_by_consensus=getattr(finding, "unresolved_by_consensus", False),
    )


def _load_rag_chunks_from_trace(session: Session, harvey_context: dict) -> list[dict]:
    """Resolve chunk texts from the rag_trace stored by harvey_context_load."""
    rag_trace = harvey_context.get("rag_trace", [])
    chunk_meta: dict[str, str] = {}  # chunk_id -> source_path
    for trace_item in rag_trace:
        for citation in trace_item.get("citations", []):
            chunk_id = citation.get("chunk_id")
            if chunk_id:
                chunk_meta[chunk_id] = citation.get("source_path", "")
    if not chunk_meta:
        return []
    chunk_records = session.scalars(
        select(RagChunk).where(RagChunk.id.in_(list(chunk_meta.keys())))
    ).all()
    return [
        {
            "chunk_id": chunk.id,
            "text": chunk.text,
            "source_path": chunk_meta.get(chunk.id, ""),
        }
        for chunk in chunk_records
    ]


async def _run_harvey_review_block(
    clause_index: list[dict],
    policy_context: dict,
    rag_chunks: list[dict],
    settings: Settings,
    round_number: int,
) -> dict:
    """Sequential 3-stage Harvey pipeline.

    Stage 1 (contradiction_finder)  — exhaustive discovery on contract + RAG.
    Stage 2 (regression_challenger) — receives stage-1 findings, filters to material regressions.
    Stage 3 (downstream_risk)       — receives stage-2 findings, enriches with downstream consequences.

    Each stage sees the prior stage's output, not the raw contract independently.
    """
    provider = _provider(settings)
    try:
        r1 = HarveyReviewer(provider, 1)
        r2 = HarveyReviewer(provider, 2)
        r3 = HarveyReviewer(provider, 3)

        # Stage 1: exhaustive contradiction discovery
        initial_output = await r1.review(clause_index, policy_context, rag_chunks)
        initial_findings = initial_output.findings

        # Stage 2: challenge — filters stage-1 findings to genuine regressions
        challenged_findings = await r2.challenge(initial_findings, clause_index, policy_context, rag_chunks)

        # Stage 3: downstream risk enrichment of validated findings
        final_findings = await r3.assess_risk(challenged_findings, clause_index, policy_context, rag_chunks)

        return {
            "aggregated_findings": [f.model_dump(mode="json") for f in final_findings],
            "pipeline": {
                "stage1_initial_count": len(initial_findings),
                "stage2_challenged_count": len(challenged_findings),
                "stage3_final_count": len(final_findings),
            },
        }
    finally:
        await provider.aclose()


async def _run_admin_merge(
    harvey_findings: list,
    kira_findings: list,
    settings: Settings,
):
    from app.backend.models.schemas import Finding
    provider = _provider(settings)
    try:
        harvey = [Finding.model_validate(f) if isinstance(f, dict) else f for f in harvey_findings]
        kira = [Finding.model_validate(f) if isinstance(f, dict) else f for f in kira_findings]
        return await AdminMergeAgent(provider).merge(harvey, kira)
    finally:
        await provider.aclose()


_KIRA_MAX_ITERATIONS = 3


async def _run_kira_review_block(
    clause_index: list[dict],
    compliance_context: dict,
    settings: Settings,
    max_iterations: int = _KIRA_MAX_ITERATIONS,
) -> dict:
    """Worker-panel loop for Kira.

    1. Worker analyses the contract.
    2. 3 panel reviewers each vote approve/reject with feedback.
    3. If 2+ approve → done.
    4. If 2+ reject → aggregate feedback → worker revises → repeat from step 2.
    5. After max_iterations, pass whatever the worker last produced.
    """
    kira_provider = _kira_provider(settings)
    base_provider = _provider(settings)
    try:
        worker = KiraWorker(kira_provider)
        panel = [KiraPanelReviewer(base_provider, i) for i in (1, 2, 3)]

        current_findings = await worker.analyze(clause_index, compliance_context)
        best_findings = list(current_findings)  # keep best non-empty result across iterations
        iterations: list[dict] = []

        for iteration in range(1, max_iterations + 1):
            decisions = [await reviewer.review(current_findings, clause_index) for reviewer in panel]
            approval_count = sum(1 for d in decisions if d.decision == "approve")
            approved = approval_count >= 2

            iterations.append({
                "iteration": iteration,
                "finding_count": len(current_findings),
                "decisions": [d.model_dump() for d in decisions],
                "approval_count": approval_count,
                "approved": approved,
            })

            if approved:
                break

            if iteration < max_iterations:
                feedback = aggregate_kira_panel_feedback(decisions)
                current_findings = await worker.revise(
                    clause_index, compliance_context, current_findings, feedback, iteration + 1
                )
                if current_findings:
                    best_findings = list(current_findings)

        # Prefer current_findings; fall back to best non-empty set if revision zeroed out results
        final = current_findings if current_findings else best_findings

        for iter_data in iterations:
            for d in iter_data["decisions"]:
                kira_panel_votes_total.labels(decision=d["decision"]).inc()
        kira_iterations_per_run.observe(len(iterations))

        return {
            "final_findings": [f.model_dump(mode="json") for f in final],
            "iterations": iterations,
            "total_iterations": len(iterations),
            "approved": iterations[-1]["approved"] if iterations else False,
        }
    finally:
        await kira_provider.aclose()
        await base_provider.aclose()



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
                        order_index=clause.get("order_index"),
                    )
                )
            # Prime the pdf2docx cache now so the editor has full formatting on first open.
            try:
                from pdf2docx import Converter as _Cv
                _storage_path = run.storage_path
                _docx_cache = Path(_storage_path).with_suffix(".original.docx")
                if not _docx_cache.exists():
                    _cv = _Cv(str(_storage_path))
                    _cv.convert(str(_docx_cache), start=0, end=None)
                    _cv.close()
            except Exception as _e:
                logger.warning("pdf2docx priming failed for %s: %s", run.id, _e)
            advance_stage(session, stage, {"document_hash": parsed.document_hash, "low_confidence": parsed.low_confidence})
            return

        if stage.stage_name == "clause_index":
            clause_index = _load_clause_index(session, run.id)
            advance_stage(session, stage, {"clause_count": len(clause_index)})
            return

        if stage.stage_name == "harvey_context_load":
            clause_index = _load_clause_index(session, run.id)
            try:
                lineage = resolve_policy_lineage(run.tenant_id, run.policy_family_id or "", run.policy_version_number or 0)
                prior_versions = load_prior_policy_versions(run.tenant_id, run.policy_family_id or "", run.policy_version_number or 0)
                playbook_rules = (lambda rp: rp.get("rules", []) if isinstance(rp, dict) else (rp or []))(lineage.get("rules_payload"))
            except MissingLineageError:
                lineage = {}
                prior_versions = []
                playbook_rules = []
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
                    "prior_versions": prior_versions,
                    "playbook_rules": playbook_rules,
                    "rag_trace": rag_trace_dicts,
                },
            )
            return

        if stage.stage_name == "kira_context_load":
            advance_stage(session, stage, resolve_applicable_corpora(run.tenant_id, run.jurisdiction, run.regime, run.effective_date))
            return

        if stage.stage_name == "harvey_review_block":
            clause_index = _load_clause_index(session, run.id)
            harvey_context = _stage_output(session, run.id, "harvey_context_load")
            policy_context = {
                "lineage": harvey_context.get("lineage"),
                "prior_versions": harvey_context.get("prior_versions", []),
                "playbook_rules": harvey_context.get("playbook_rules", []),
            }
            rag_chunks = _load_rag_chunks_from_trace(session, harvey_context)
            result = asyncio.run(
                _run_harvey_review_block(clause_index, policy_context, rag_chunks, settings, stage.round_number)
            )
            from app.backend.models.schemas import Finding as _HarveyFinding
            aggregated = result.get("aggregated_findings", [])
            for finding_dict in aggregated:
                finding_obj = _HarveyFinding.model_validate(finding_dict) if isinstance(finding_dict, dict) else finding_dict
                session.add(_to_finding_record(stage, finding_obj))
                finding_severity_total.labels(severity=finding_obj.severity, branch="harvey").inc()
            findings_per_run.labels(branch="harvey").observe(len(aggregated))
            advance_stage(session, stage, result)
            return

        if stage.stage_name == "kira_review_block":
            clause_index = _load_clause_index(session, run.id)

            is_blocked, blocked_reason = _check_parser_confidence(session, run.id)
            if is_blocked:
                mark_run_blocked(session, run, blocked_reason)
                return

            try:
                compliance_context = resolve_applicable_corpora(
                    run.tenant_id, run.jurisdiction, run.regime, run.effective_date
                )
            except MissingComplianceScopeError:
                compliance_context = {"jurisdiction": run.jurisdiction or "", "regime": run.regime or "", "internal_rules": [], "external_rules": []}
            kira_result = asyncio.run(
                _run_kira_review_block(clause_index, compliance_context, settings)
            )

            # Deserialise final findings and run the hallucination validator
            from app.backend.models.schemas import Finding as _Finding
            final_findings = [
                _Finding.model_validate(f) for f in kira_result.get("final_findings", [])
            ]
            aggregate_output = BranchReviewOutput(
                branch="kira",
                reviewer_index=1,
                findings=final_findings,
                raw_response_id=None,
            )
            validator = KiraValidatorAgent(_kira_provider(settings))
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
                finding_severity_total.labels(severity=finding.severity, branch="kira").inc()
            findings_per_run.labels(branch="kira").observe(len(validated.validated_findings))
            advance_stage(
                session,
                stage,
                {
                    "review_block": kira_result,
                    "validated_output": validated.model_dump(mode="json"),
                },
            )
            return

        if stage.stage_name == "admin_merge":
            # Harvey aggregated findings (cross_contract, no validator)
            harvey_block = _stage_output(session, run.id, "harvey_review_block")
            harvey_findings_raw = harvey_block.get("aggregated_findings", [])

            # Kira validated findings (intra_contract)
            kira_block = _stage_output(session, run.id, "kira_review_block")
            kira_validated = kira_block.get("validated_output", {})
            kira_findings_raw = kira_validated.get("validated_findings", [])

            merged = asyncio.run(_run_admin_merge(harvey_findings_raw, kira_findings_raw, settings))
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

"""
Verdict validator agents.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app.backend.models.schemas import BranchReviewOutput, Finding, ValidatorOutput
from app.backend.providers.base import StructuredLLMProvider
from app.backend.agents.reviewer import _coerce_issue_type, _coerce_level, _VALID_SEVERITIES

# Validators must run at low temperature for deterministic structural checks.
_VALIDATOR_TEMPERATURE = 0.1

_VALIDATOR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["hallucinated_clause_uids", "finding_verdicts"],
    "properties": {
        "hallucinated_clause_uids": {"type": "array", "items": {"type": "string"}},
        "inapplicable_regime_flags": {"type": "array", "items": {"type": "string"}},
        "finding_verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["finding_id", "retain"],
                "properties": {
                    "finding_id": {"type": "string"},
                    "retain": {"type": "boolean"},
                    "normalised_severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                    },
                    "normalised_issue_type": {
                        "type": "string",
                        "enum": [
                            "liability_exposure",
                            "open_clause",
                            "ambiguity",
                            "exploitability",
                            "weakened_protection",
                            "compliance_failure",
                        ],
                    },
                    "evidence_quality_score": {"type": "number"},
                },
            },
        },
        "notes": {"type": "string"},
    },
}


# ---------------------------------------------------------------------------
# Structured validation errors
# ---------------------------------------------------------------------------


@dataclass
class ValidationError:
    """Returned by validate_harvey_finding / validate_kira_finding on rejection."""

    code: str   # MISSING_RAG_CITATION | INVALID_CHUNK_ID | KIRA_RAG_FORBIDDEN
                #   | MISSING_CONTRACT_EVIDENCE | MALFORMED_JSON
    field: str
    message: str


def validate_harvey_finding(
    finding: Finding,
    retrieval_trace_chunk_ids: set[str],
    parsed_clause_uids: set[str],
) -> ValidationError | None:
    """
    Enforce evidence-schema rules for Harvey findings.

    Returns a ValidationError describing the first violation, or None if valid.
    """
    rag_citations: list = getattr(finding, "rag_citations", [])
    contract_evidence: list = getattr(finding, "contract_evidence", getattr(finding, "evidence", []))

    if not rag_citations:
        return ValidationError(
            code="MISSING_RAG_CITATION",
            field="rag_citations",
            message=f"Harvey finding {finding.finding_id} must include at least one RAG citation.",
        )

    for citation in rag_citations:
        chunk_id: str = getattr(citation, "chunk_id", None) or str(citation)
        if chunk_id not in retrieval_trace_chunk_ids:
            return ValidationError(
                code="INVALID_CHUNK_ID",
                field="rag_citations.chunk_id",
                message=(
                    f"Harvey finding {finding.finding_id}: chunk_id {chunk_id!r} "
                    "is not present in this run's retrieval trace."
                ),
            )

    for ev in contract_evidence:
        ev_clause_uid: str = getattr(ev, "clause_uid", None) or str(ev)
        if ev_clause_uid not in parsed_clause_uids:
            return ValidationError(
                code="MISSING_CONTRACT_EVIDENCE",
                field="contract_evidence.clause_uid",
                message=(
                    f"Harvey finding {finding.finding_id}: contract_evidence clause_uid "
                    f"{ev_clause_uid!r} is not in the parsed clause index."
                ),
            )

    return None


def validate_kira_finding(finding: Finding) -> ValidationError | None:
    """
    Enforce evidence-schema rules for Kira findings.

    Returns a ValidationError describing the first violation, or None if valid.
    """
    contract_evidence: list = getattr(finding, "contract_evidence", getattr(finding, "evidence", []))
    rag_citations: list = getattr(finding, "rag_citations", [])

    if not contract_evidence:
        return ValidationError(
            code="MISSING_CONTRACT_EVIDENCE",
            field="contract_evidence",
            message=f"Kira finding {finding.finding_id} must include at least one contract evidence anchor.",
        )

    if rag_citations:
        return ValidationError(
            code="KIRA_RAG_FORBIDDEN",
            field="rag_citations",
            message=(
                f"Kira finding {finding.finding_id} must not include RAG citations "
                "(Kira is blocked from pgvector RAG at the service layer)."
            ),
        )

    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_reviewer_outputs(branch_outputs: list[BranchReviewOutput]) -> list[Finding]:
    findings: list[Finding] = []
    for output in branch_outputs:
        findings.extend(output.findings)
    return findings


def _score_evidence_quality(finding: Finding) -> float:
    evidence = getattr(finding, "contract_evidence", getattr(finding, "evidence", []))
    if not evidence:
        return 0.0
    return sum(ev.extraction_confidence for ev in evidence) / len(evidence)


def _deduplicate_overlapping_findings(findings: list[Finding], finding_verdicts: list[dict]) -> list[Finding]:
    verdicts_by_id = {verdict["finding_id"]: verdict for verdict in finding_verdicts}
    retained = [finding for finding in findings if verdicts_by_id.get(finding.finding_id, {}).get("retain", True)]
    grouped: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for finding in retained:
        grouped[(finding.clause_uid, finding.issue_type)].append(finding)

    deduped: list[Finding] = []
    for group in grouped.values():
        primary = max(
            group,
            key=lambda finding: verdicts_by_id.get(
                finding.finding_id,
                {},
            ).get("evidence_quality_score", _score_evidence_quality(finding)),
        )
        verdict = verdicts_by_id.get(primary.finding_id, {})
        merged_evidence = []
        seen_keys: set[tuple[str, int]] = set()
        evidence_field = getattr(primary, "contract_evidence", getattr(primary, "evidence", []))
        for finding in group:
            ev_list = getattr(finding, "contract_evidence", getattr(finding, "evidence", []))
            for evidence in ev_list:
                key = (evidence.clause_uid, evidence.page)
                if key not in seen_keys:
                    seen_keys.add(key)
                    merged_evidence.append(evidence)
        raw_severity = verdict.get("normalised_severity", primary.severity)
        raw_issue_type = verdict.get("normalised_issue_type", primary.issue_type)
        update: dict[str, Any] = {
            "severity": _coerce_level(raw_severity, _VALID_SEVERITIES, primary.severity),
            "issue_type": _coerce_issue_type(raw_issue_type) if raw_issue_type else primary.issue_type,
        }
        # Preserve the correct evidence field name.
        if hasattr(primary, "contract_evidence"):
            update["contract_evidence"] = merged_evidence
        else:
            update["evidence"] = merged_evidence
        deduped.append(primary.model_copy(update=update))
    return deduped


def _build_prompt(branch: str, branch_outputs: list[BranchReviewOutput], known_clause_uids: list[str], extra_context: str) -> str:
    findings_block = "\n".join(
        f"finding_id={finding.finding_id} clause_uid={finding.clause_uid} severity={finding.severity} "
        f"issue_type={finding.issue_type} reviewer={output.reviewer_index}"
        for output in branch_outputs
        for finding in output.findings
    )
    return (
        f"You are the {branch} validator.\n"
        f"{extra_context}\n\n"
        f"Known clause_uids: {', '.join(known_clause_uids)}\n\n"
        "Review the reviewer outputs, mark hallucinated clause_uids, normalize duplicate findings, "
        "and return only JSON matching the schema.\n\n"
        f"{findings_block or '(no findings)'}"
    )


# ---------------------------------------------------------------------------
# Validator agents
# ---------------------------------------------------------------------------


class HarveyValidatorAgent:
    def __init__(self, provider: StructuredLLMProvider) -> None:
        self._provider = provider

    async def validate(self, branch_outputs: list[BranchReviewOutput], known_clause_uids: list[str]) -> ValidatorOutput:
        prompt = _build_prompt(
            "harvey",
            branch_outputs,
            known_clause_uids,
            "This branch checks contract text against internal policy lineage only.",
        )
        raw = await self._provider.generate_structured_output(prompt, _VALIDATOR_RESPONSE_SCHEMA)
        known_set = set(known_clause_uids)
        hallucinated = {uid for uid in raw.get("hallucinated_clause_uids", []) if uid not in known_set}
        all_findings = _normalize_reviewer_outputs(branch_outputs)
        eligible = [f for f in all_findings if f.clause_uid not in hallucinated]
        validated = _deduplicate_overlapping_findings(eligible, raw.get("finding_verdicts", []))
        if not validated and all_findings:
            validated = all_findings
        return ValidatorOutput(
            branch="harvey",
            validated_findings=validated,
            hallucinated_clause_uids=list(hallucinated),
            notes=raw.get("notes"),
        )


class KiraValidatorAgent:
    def __init__(self, provider: StructuredLLMProvider) -> None:
        self._provider = provider

    async def validate(
        self,
        branch_outputs: list[BranchReviewOutput],
        known_clause_uids: list[str],
        jurisdiction: str,
        regime: str,
    ) -> ValidatorOutput:
        prompt = _build_prompt(
            "kira",
            branch_outputs,
            known_clause_uids,
            f"This branch checks external compliance for jurisdiction={jurisdiction} regime={regime}.",
        )
        raw = await self._provider.generate_structured_output(prompt, _VALIDATOR_RESPONSE_SCHEMA)
        known_set = set(known_clause_uids)
        # Only trust hallucination flags for UIDs that genuinely don't exist in the parsed index.
        # Small models frequently (incorrectly) flag real UIDs as hallucinated.
        hallucinated = {uid for uid in raw.get("hallucinated_clause_uids", []) if uid not in known_set}
        all_findings = _normalize_reviewer_outputs(branch_outputs)
        eligible = [f for f in all_findings if f.clause_uid not in hallucinated]
        validated = _deduplicate_overlapping_findings(eligible, raw.get("finding_verdicts", []))
        # Last-resort: if the validator zeroed out a non-empty input, pass findings through unmodified.
        if not validated and all_findings:
            validated = all_findings
        return ValidatorOutput(
            branch="kira",
            validated_findings=validated,
            hallucinated_clause_uids=list(hallucinated),
            inapplicable_regime_flags=raw.get("inapplicable_regime_flags", []),
            notes=raw.get("notes"),
        )

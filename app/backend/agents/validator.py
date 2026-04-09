"""
Verdict validator agents.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.backend.models.schemas import BranchReviewOutput, Finding, ValidatorOutput
from app.backend.providers.base import StructuredLLMProvider
from app.backend.agents.reviewer import _coerce_issue_type, _coerce_level, _VALID_SEVERITIES

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


def _normalize_reviewer_outputs(branch_outputs: list[BranchReviewOutput]) -> list[Finding]:
    findings: list[Finding] = []
    for output in branch_outputs:
        findings.extend(output.findings)
    return findings


def _score_evidence_quality(finding: Finding) -> float:
    if not finding.evidence:
        return 0.0
    return sum(evidence.extraction_confidence for evidence in finding.evidence) / len(finding.evidence)


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
        for finding in group:
            for evidence in finding.evidence:
                key = (evidence.clause_uid, evidence.page)
                if key not in seen_keys:
                    seen_keys.add(key)
                    merged_evidence.append(evidence)
        raw_severity = verdict.get("normalised_severity", primary.severity)
        raw_issue_type = verdict.get("normalised_issue_type", primary.issue_type)
        deduped.append(
            primary.model_copy(
                update={
                    "evidence": merged_evidence,
                    "severity": _coerce_level(raw_severity, _VALID_SEVERITIES, primary.severity),
                    "issue_type": _coerce_issue_type(raw_issue_type) if raw_issue_type else primary.issue_type,
                }
            )
        )
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
        hallucinated = set(raw.get("hallucinated_clause_uids", []))
        eligible = [finding for finding in _normalize_reviewer_outputs(branch_outputs) if finding.clause_uid not in hallucinated]
        return ValidatorOutput(
            branch="harvey",
            validated_findings=_deduplicate_overlapping_findings(eligible, raw.get("finding_verdicts", [])),
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
        hallucinated = set(raw.get("hallucinated_clause_uids", []))
        eligible = [finding for finding in _normalize_reviewer_outputs(branch_outputs) if finding.clause_uid not in hallucinated]
        return ValidatorOutput(
            branch="kira",
            validated_findings=_deduplicate_overlapping_findings(eligible, raw.get("finding_verdicts", [])),
            hallucinated_clause_uids=list(hallucinated),
            inapplicable_regime_flags=raw.get("inapplicable_regime_flags", []),
            notes=raw.get("notes"),
        )

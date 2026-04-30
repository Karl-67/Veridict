"""
Admin-layer orchestration agents.

AdminMergeAgent: LLM-based synthesiser. Receives Harvey's cross-contract findings
and Kira's intra-contract findings; produces per-clause ClauseVerdicts with
intra_comment (what's wrong inside the contract) and cross_comment (what conflicts
with prior policy / knowledge base).

ConsensusAdmin / AgreementAdmin / ReviewBlockAggregator: deterministic helpers
used during Harvey and Kira review blocks to compute 2-of-3 agreement.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field

from app.backend.models.schemas import (
    AdminMergeOutput,
    BranchReviewOutput,
    ClauseVerdict,
    Finding,
    ReviewBlockResult,
    ReviewerVote,
    ValidatorOutput,
)
from app.backend.providers.base import StructuredLLMProvider

ConsensusState = Literal["unanimous", "majority", "split"]


# ---------------------------------------------------------------------------
# Deterministic consensus helpers (used by Harvey and Kira review blocks)
# ---------------------------------------------------------------------------


class TrioMergeOutput(BaseModel):
    merged_findings: list[Finding]
    consensus_state: ConsensusState
    unresolved_by_consensus: list[str] = Field(default_factory=list)
    harvey_agreement: ConsensusState
    kira_agreement: ConsensusState
    deduplication_log: list[dict] = Field(default_factory=list)


def _merge_evidence(findings: list[Finding]) -> list:
    seen: set[tuple[str, int]] = set()
    merged = []
    for f in findings:
        for ev in (f.evidence or []):
            ref = (ev.clause_uid, ev.page)
            if ref not in seen:
                seen.add(ref)
                merged.append(ev)
    return merged


def _branch_consensus(
    trio_outputs: list[BranchReviewOutput],
) -> tuple[ConsensusState, list[Finding], list[str]]:
    """Cluster findings by (clause_uid, issue_type), compute 2-of-3 agreement."""
    key_to_findings: dict[str, list[Finding]] = defaultdict(list)
    key_to_voters: dict[str, set[int]] = defaultdict(set)

    for output in trio_outputs:
        for finding in output.findings:
            key = f"{finding.clause_uid}|{finding.issue_type}"
            key_to_findings[key].append(finding)
            key_to_voters[key].add(output.reviewer_index)

    if not key_to_findings:
        return "unanimous", [], []

    canonical: list[Finding] = []
    unresolved_ids: list[str] = []
    unanimous_count = 0
    has_split = False

    for key, findings in key_to_findings.items():
        voter_count = len(key_to_voters[key])
        primary = findings[0]
        merged_ev = _merge_evidence(findings)

        if voter_count >= 3:
            unanimous_count += 1
            is_unresolved = False
            status = "consensus"
        elif voter_count >= 2:
            is_unresolved = False
            status = "consensus"
        else:
            has_split = True
            is_unresolved = True
            status = "unresolved_by_consensus"
            unresolved_ids.append(primary.finding_id)

        canonical.append(
            primary.model_copy(
                update={
                    "evidence": merged_ev,
                    "consensus_status": status,
                    "unresolved_by_consensus": is_unresolved,
                }
            )
        )

    if has_split:
        agreement: ConsensusState = "split"
    elif unanimous_count == len(key_to_findings):
        agreement = "unanimous"
    else:
        agreement = "majority"

    return agreement, canonical, unresolved_ids


_AGREEMENT_RANK: dict[str, int] = {"split": 0, "majority": 1, "unanimous": 2}


class AgreementAdmin:
    def check(
        self,
        harvey_trio_outputs: list[BranchReviewOutput],
        kira_trio_outputs: list[BranchReviewOutput],
    ) -> ConsensusState:
        harvey_agreement, _, _ = _branch_consensus(harvey_trio_outputs)
        kira_agreement, _, _ = _branch_consensus(kira_trio_outputs)
        return min(harvey_agreement, kira_agreement, key=lambda s: _AGREEMENT_RANK[s])


class ConsensusAdmin:
    _agreement_admin = AgreementAdmin()

    def merge(
        self,
        harvey_trio_outputs: list[BranchReviewOutput],
        kira_trio_outputs: list[BranchReviewOutput],
    ) -> TrioMergeOutput:
        harvey_agreement, harvey_findings, harvey_unresolved = _branch_consensus(harvey_trio_outputs)
        kira_agreement, kira_findings, kira_unresolved = _branch_consensus(kira_trio_outputs)

        seen: dict[str, Finding] = {}
        deduplication_log: list[dict] = []

        for finding in [*harvey_findings, *kira_findings]:
            key = f"{finding.clause_uid}|{finding.issue_type}"
            if key not in seen:
                seen[key] = finding
            else:
                existing = seen[key]
                existing_refs = {(e.clause_uid, e.page) for e in (existing.evidence or [])}
                extra_ev = [ev for ev in (finding.evidence or []) if (ev.clause_uid, ev.page) not in existing_refs]
                seen[key] = existing.model_copy(update={"evidence": (existing.evidence or []) + extra_ev})
                deduplication_log.append({
                    "kept_finding_id": existing.finding_id,
                    "discarded_finding_id": finding.finding_id,
                    "key": key,
                })

        all_unresolved = list(dict.fromkeys(harvey_unresolved + kira_unresolved))
        overall: ConsensusState = min(harvey_agreement, kira_agreement, key=lambda s: _AGREEMENT_RANK[s])

        return TrioMergeOutput(
            merged_findings=list(seen.values()),
            consensus_state=overall,
            unresolved_by_consensus=all_unresolved,
            harvey_agreement=harvey_agreement,
            kira_agreement=kira_agreement,
            deduplication_log=deduplication_log,
        )


class ReviewBlockAggregator:
    """Deterministic aggregator: deduplicates findings from a review block by
    (clause_uid, issue_type, description) and returns a ReviewBlockResult."""

    def aggregate(
        self,
        branch: str,
        review_outputs: list[BranchReviewOutput],
        reviewer_votes: list[ReviewerVote],
        round_number: int,
        max_reruns: int = 5,
    ) -> ReviewBlockResult:
        findings: list[Finding] = []
        seen: set[str] = set()
        for output in review_outputs:
            for finding in output.findings:
                key = f"{finding.clause_uid}|{finding.issue_type}|{finding.description}"
                if key in seen:
                    continue
                seen.add(key)
                findings.append(finding)
        return ReviewBlockResult(
            branch=branch,
            round_number=round_number,
            rerun_required=False,
            escalated=False,
            accepted_reviewer_indexes=[o.reviewer_index for o in review_outputs],
            aggregated_findings=findings,
            reviewer_outputs=review_outputs,
            reviewer_votes=reviewer_votes,
            aggregate_summary=f"{len(findings)} unique {branch} findings.",
        )


# ---------------------------------------------------------------------------
# Admin output schema for LLM structured output
# ---------------------------------------------------------------------------

_CLAUSE_VERDICT_ITEM_SCHEMA: dict = {
    "type": "object",
    "required": ["clause_uid", "severity", "contributing_finding_ids"],
    "properties": {
        "clause_uid": {"type": "string"},
        "intra_comment": {
            "type": "string",
            "description": (
                "Clear, actionable summary of Kira's internal-contract findings for this clause. "
                "Include the recommended change. Omit if no Kira findings for this clause."
            ),
        },
        "cross_comment": {
            "type": "string",
            "description": (
                "Clear, actionable summary of Harvey's cross-contract/policy findings. "
                "State which prior policy or knowledge-base document is contradicted. "
                "Omit if no Harvey findings for this clause."
            ),
        },
        "severity": {
            "type": "string",
            "enum": ["low", "medium", "high", "critical"],
            "description": "Highest severity across all findings for this clause.",
        },
        "contributing_finding_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "All finding_ids that contributed to this verdict entry.",
        },
    },
}

_ADMIN_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "required": ["clause_verdicts"],
    "properties": {
        "clause_verdicts": {
            "type": "array",
            "items": _CLAUSE_VERDICT_ITEM_SCHEMA,
        },
    },
}

# ---------------------------------------------------------------------------
# Admin prompt helpers
# ---------------------------------------------------------------------------


def _format_findings_for_admin(findings: list[Finding], label: str) -> str:
    if not findings:
        return f"{label}: (none)"
    lines = [f"{label}:"]
    for f in findings:
        rec = f.recommended_change or f.recommendation_detail or ""
        evidence = "; ".join(
            getattr(e, "text", "") if not isinstance(e, dict) else str(e.get("text") or "")
            for e in (getattr(f, "contract_evidence", None) or [])[:3]
        )
        lines.append(
            f"  finding_id={f.finding_id} clause={f.clause_uid} "
            f"severity={f.severity} type={f.issue_type}\n"
            f"  description: {f.description}\n"
            f"  contract_evidence: {evidence or '(none)'}\n"
            f"  recommended_change: {rec}"
        )
    return "\n".join(lines)


_ADMIN_SYSTEM = """\
[ADMIN — Consensus Reviewer]
You are the Admin Reviewer. You receive two sets of independent findings about a contract:

- HARVEY FINDINGS (cross_contract): contradictions between this contract and prior policy
  versions or knowledge-base documents. Each Harvey finding points to a policy regression,
  conflict, or downstream enforcement risk.

- KIRA FINDINGS (intra_contract): internal contract integrity problems — ambiguities,
  missing protections, exploitable gaps. Each Kira finding includes a recommended_change.

Your task:
For every clause_uid that has at least one finding (from either branch), produce one
ClauseVerdict entry containing:
  - intra_comment: synthesise Kira's findings for this clause into a single, clear,
    actionable comment that includes the recommended change. Null if no Kira findings.
  - cross_comment: synthesise Harvey's findings for this clause into a single, clear,
    actionable comment that names the prior policy or document being contradicted.
    Null if no Harvey findings.
  - severity: the highest severity level across all findings for this clause.
  - contributing_finding_ids: all finding_ids (from either branch) for this clause.

Rules:
- One ClauseVerdict per clause_uid. Deduplicate overlapping findings across branches.
- Keep every contributing finding grounded in the supplied contract_evidence; do not move
  a finding to a title, heading, party name, or signature label unless that quoted evidence
  is itself the legal issue.
- Write comments in plain English for a senior lawyer to act on immediately.
- Do NOT include chain-of-thought. Return strict JSON only."""


# ---------------------------------------------------------------------------
# LLM-based AdminMergeAgent
# ---------------------------------------------------------------------------


class AdminMergeAgent:
    """Synthesises Harvey cross-contract findings and Kira intra-contract findings
    into per-clause ClauseVerdicts with intra_comment and cross_comment."""

    def __init__(self, provider: StructuredLLMProvider) -> None:
        self._provider = provider

    async def merge(
        self,
        harvey_findings: list[Finding],
        kira_findings: list[Finding],
    ) -> AdminMergeOutput:
        harvey_block = _format_findings_for_admin(harvey_findings, "HARVEY FINDINGS (cross_contract)")
        kira_block = _format_findings_for_admin(kira_findings, "KIRA FINDINGS (intra_contract)")

        prompt = (
            f"{_ADMIN_SYSTEM}\n\n"
            f"{harvey_block}\n\n"
            f"{kira_block}\n\n"
            "Return ONLY a JSON object matching the schema. No explanation, no chain-of-thought."
        )

        raw = await self._provider.generate_structured_output(prompt, _ADMIN_OUTPUT_SCHEMA)

        clause_verdicts: list[ClauseVerdict] = []
        for item in raw.get("clause_verdicts", []):
            if not isinstance(item, dict) or not item.get("clause_uid"):
                continue
            severity = item.get("severity", "medium")
            if severity not in ("low", "medium", "high", "critical"):
                severity = "medium"
            clause_verdicts.append(
                ClauseVerdict(
                    clause_uid=item["clause_uid"],
                    intra_comment=item.get("intra_comment") or None,
                    cross_comment=item.get("cross_comment") or None,
                    severity=severity,  # type: ignore[arg-type]
                    contributing_finding_ids=item.get("contributing_finding_ids", []),
                )
            )

        # Combined finding list for backwards-compat (merged_findings field)
        all_findings = [*harvey_findings, *kira_findings]

        return AdminMergeOutput(
            merged_findings=all_findings,
            clause_verdicts=clause_verdicts,
            deduplication_log=[
                {"source": "admin_llm", "clause_verdict_count": len(clause_verdicts)}
            ],
        )

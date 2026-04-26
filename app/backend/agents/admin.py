"""
Admin-layer orchestration agents.
Implements the `harvey-trio-contract` shared dependency: Admin is merge-only,
no admin reviewers. ConsensusAdmin deduplicates findings via clause_uid +
issue_type clustering across both trios and computes 3-way agreement per branch.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field

from app.backend.models.schemas import (
    AdminMergeOutput,
    BranchReviewOutput,
    Finding,
    ReviewBlockResult,
    ReviewerVote,
    ValidatorOutput,
)

ConsensusState = Literal["unanimous", "majority", "split"]


class TrioMergeOutput(BaseModel):
    merged_findings: list[Finding]
    consensus_state: ConsensusState
    unresolved_by_consensus: list[str] = Field(
        default_factory=list,
        description="finding_ids where no 2-of-3 agreement was reached in either branch.",
    )
    harvey_agreement: ConsensusState
    kira_agreement: ConsensusState
    deduplication_log: list[dict] = Field(default_factory=list)


def _merge_evidence(findings: list[Finding]) -> list:
    seen: set[tuple[str, int]] = set()
    merged = []
    for f in findings:
        for ev in f.evidence:
            ref = (ev.clause_uid, ev.page)
            if ref not in seen:
                seen.add(ref)
                merged.append(ev)
    return merged


def _branch_consensus(
    trio_outputs: list[BranchReviewOutput],
) -> tuple[ConsensusState, list[Finding], list[str]]:
    """
    Cluster findings by (clause_uid, issue_type), compute 3-way agreement.
    Returns (branch_agreement, canonical_findings, unresolved_finding_ids).
    """
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
            status = "consensus"
            is_unresolved = False
        elif voter_count >= 2:
            status = "consensus"
            is_unresolved = False
        else:
            has_split = True
            status = "unresolved_by_consensus"
            is_unresolved = True
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
    """Computes Harvey 3-way and Kira 3-way agreement; returns consensus_state."""

    def check(
        self,
        harvey_trio_outputs: list[BranchReviewOutput],
        kira_trio_outputs: list[BranchReviewOutput],
    ) -> ConsensusState:
        harvey_agreement, _, _ = _branch_consensus(harvey_trio_outputs)
        kira_agreement, _, _ = _branch_consensus(kira_trio_outputs)
        return min(harvey_agreement, kira_agreement, key=lambda s: _AGREEMENT_RANK[s])


class ConsensusAdmin:
    """Merge-only admin: deduplicates harvey + kira trio outputs into one finding set."""

    _agreement_admin = AgreementAdmin()

    def merge(
        self,
        harvey_trio_outputs: list[BranchReviewOutput],
        kira_trio_outputs: list[BranchReviewOutput],
    ) -> TrioMergeOutput:
        harvey_agreement, harvey_findings, harvey_unresolved = _branch_consensus(harvey_trio_outputs)
        kira_agreement, kira_findings, kira_unresolved = _branch_consensus(kira_trio_outputs)

        # Cross-branch dedup: same clause_uid + issue_type in both branches → merge evidence
        seen: dict[str, Finding] = {}
        deduplication_log: list[dict] = []

        for finding in [*harvey_findings, *kira_findings]:
            key = f"{finding.clause_uid}|{finding.issue_type}"
            if key not in seen:
                seen[key] = finding
            else:
                existing = seen[key]
                existing_refs = {(e.clause_uid, e.page) for e in existing.evidence}
                extra_ev = [ev for ev in finding.evidence if (ev.clause_uid, ev.page) not in existing_refs]
                seen[key] = existing.model_copy(update={"evidence": existing.evidence + extra_ev})
                deduplication_log.append(
                    {
                        "kept_finding_id": existing.finding_id,
                        "discarded_finding_id": finding.finding_id,
                        "key": key,
                    }
                )

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
    """Small deterministic aggregator for the active Kira problem-finding block."""

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
            accepted_reviewer_indexes=[output.reviewer_index for output in review_outputs],
            aggregated_findings=findings,
            reviewer_outputs=review_outputs,
            reviewer_votes=reviewer_votes,
            aggregate_summary=f"{len(findings)} unique {branch} findings.",
        )


class AdminMergeAgent:
    """Compatibility facade used by the state machine.

    Active architecture: Harvey contributes RAG evidence, Kira contributes
    findings, Admin creates the consensus output.
    """

    def merge(self, harvey_output: ValidatorOutput, kira_output: ValidatorOutput) -> AdminMergeOutput:
        del harvey_output
        return AdminMergeOutput(
            merged_findings=kira_output.validated_findings,
            deduplication_log=[
                {
                    "source": "admin_consensus",
                    "note": "Kira findings merged with Harvey RAG evidence context.",
                }
            ],
        )

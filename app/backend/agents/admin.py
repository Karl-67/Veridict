"""
Admin-layer orchestration agents.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from app.backend.models.schemas import (
    AdminMergeOutput,
    AgreementDecision,
    BranchReviewOutput,
    Finding,
    ReviewBlockResult,
    ReviewerVote,
    ValidatorOutput,
)


class AdminMergeAgent:
    def merge(self, harvey: ValidatorOutput, kira: ValidatorOutput) -> AdminMergeOutput:
        merged: list[Finding] = []
        deduplication_log: list[dict] = []
        seen: dict[tuple[str, str, str], Finding] = {}

        for finding in [*harvey.validated_findings, *kira.validated_findings]:
            key = (finding.clause_uid, finding.issue_type, finding.severity)
            existing = seen.get(key)
            if existing is None:
                seen[key] = finding
                merged.append(finding)
                continue
            evidence = existing.evidence + [ref for ref in finding.evidence if ref not in existing.evidence]
            seen[key] = existing.model_copy(update={"evidence": evidence})
            deduplication_log.append(
                {"kept_finding_id": existing.finding_id, "discarded_finding_id": finding.finding_id, "key": key}
            )

        return AdminMergeOutput(merged_findings=list(seen.values()), deduplication_log=deduplication_log)


class AgreementCheckAgent:
    def check(self, reviewer_outputs: list[list[Finding]], *, round_number: int) -> AgreementDecision:
        grouped: dict[tuple[str, str, str], list[Finding]] = defaultdict(list)
        for findings in reviewer_outputs:
            for finding in findings:
                grouped[(finding.clause_uid, finding.issue_type, finding.severity)].append(finding)

        consensus_findings: list[Finding] = []
        disputed_finding_ids: list[str] = []
        for findings in grouped.values():
            if len(findings) >= 2:
                consensus_findings.append(findings[0].model_copy(update={"consensus_status": "consensus"}))
            else:
                disputed_finding_ids.append(findings[0].finding_id)

        return AgreementDecision(
            round_number=round_number,
            consensus_findings=consensus_findings,
            disputed_finding_ids=disputed_finding_ids,
            all_consensus=not disputed_finding_ids,
        )


class AdminDeltaInstructionBuilder:
    def build(self, disputed_findings: list[Finding]) -> str:
        if not disputed_findings:
            return "No disputed findings."
        counts = Counter(finding.issue_type for finding in disputed_findings)
        issues = ", ".join(f"{issue}={count}" for issue, count in counts.items())
        return (
            "Re-review only the disputed findings. "
            "Confirm whether the cited clause truly supports the issue, severity, and recommendation. "
            f"Disputed mix: {issues}."
        )


class ReviewBlockAggregator:
    threshold = 0.90

    @staticmethod
    def _key(finding: Finding) -> str:
        return f"{finding.clause_uid}|{finding.issue_type}|{finding.severity}"

    def _aggregate_from_reviewers(
        self,
        branch: str,
        review_outputs: list[BranchReviewOutput],
        accepted_reviewer_indexes: list[int],
        keys: set[str],
        round_number: int,
    ) -> ReviewBlockResult:
        by_key: dict[str, list[Finding]] = defaultdict(list)
        for output in review_outputs:
            if output.reviewer_index not in accepted_reviewer_indexes:
                continue
            for finding in output.findings:
                key = self._key(finding)
                if key in keys:
                    by_key[key].append(finding)

        aggregated: list[Finding] = []
        for findings in by_key.values():
            primary = min(findings, key=lambda finding: len(finding.description))
            merged_evidence = []
            seen_refs: set[tuple[str, int]] = set()
            for finding in findings:
                for evidence in finding.evidence:
                    key = (evidence.clause_uid, evidence.page)
                    if key not in seen_refs:
                        seen_refs.add(key)
                        merged_evidence.append(evidence)
            aggregated.append(
                primary.model_copy(
                    update={
                        "evidence": merged_evidence,
                        "consensus_status": "consensus",
                        "round_number": round_number,
                    }
                )
            )

        return ReviewBlockResult(
            branch=branch,
            round_number=round_number,
            accepted_reviewer_indexes=accepted_reviewer_indexes,
            aggregated_findings=aggregated,
            aggregate_summary=f"Accepted reviewers: {accepted_reviewer_indexes}",
        )

    def aggregate(
        self,
        *,
        branch: str,
        review_outputs: list[BranchReviewOutput],
        reviewer_votes: list[ReviewerVote],
        round_number: int,
        max_reruns: int = 5,
    ) -> ReviewBlockResult:
        key_to_supporters: dict[str, list[int]] = defaultdict(list)
        vote_by_reviewer = {vote.reviewer_index: vote for vote in reviewer_votes}

        for vote in reviewer_votes:
            if vote.correctness_score < self.threshold:
                continue
            for key in vote.accepted_finding_keys:
                key_to_supporters[key].append(vote.reviewer_index)

        acceptable_keys = {key for key, supporters in key_to_supporters.items() if len(set(supporters)) >= 2}
        if acceptable_keys:
            accepted_reviewer_indexes = sorted(
                {
                    reviewer_index
                    for key, supporters in key_to_supporters.items()
                    if key in acceptable_keys
                    for reviewer_index in supporters
                    if vote_by_reviewer[reviewer_index].correctness_score >= self.threshold
                }
            )
            return self._aggregate_from_reviewers(
                branch,
                review_outputs,
                accepted_reviewer_indexes,
                acceptable_keys,
                round_number,
            ).model_copy(update={"reviewer_outputs": review_outputs, "reviewer_votes": reviewer_votes})

        if round_number >= max_reruns:
            all_keys = {self._key(finding) for output in review_outputs for finding in output.findings}
            escalated = self._aggregate_from_reviewers(
                branch,
                review_outputs,
                [output.reviewer_index for output in review_outputs],
                all_keys,
                round_number,
            )
            return escalated.model_copy(
                update={
                    "escalated": True,
                    "reviewer_outputs": review_outputs,
                    "reviewer_votes": reviewer_votes,
                    "aggregate_summary": "Escalated after max reruns; merged all reviewer answers.",
                }
            )

        return ReviewBlockResult(
            branch=branch,
            round_number=round_number,
            rerun_required=True,
            reviewer_outputs=review_outputs,
            reviewer_votes=reviewer_votes,
            aggregate_summary="No 2 reviewers met the agreement key and 0.90 score threshold.",
        )

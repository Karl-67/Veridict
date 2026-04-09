"""
Verdict reviewer agents.

Reviewers own prompt construction and typed result assembly.
Providers own transport and structured-output enforcement.
"""

from __future__ import annotations

import uuid
from typing import Literal

from app.backend.models.schemas import BranchReviewOutput, EvidenceRef, Finding, ReviewerVote
from app.backend.providers.base import StructuredLLMProvider

# ---------------------------------------------------------------------------
# Enum coercion — small models often return plausible-but-wrong values.
# We map the most common deviations to a valid literal before Pydantic sees it.
# ---------------------------------------------------------------------------

_VALID_ISSUE_TYPES = {
    "liability_exposure", "open_clause", "ambiguity",
    "exploitability", "weakened_protection", "compliance_failure",
}
_ISSUE_TYPE_MAP: dict[str, str] = {
    # indemnification / liability variants
    "indemnification": "liability_exposure",
    "indemnity": "liability_exposure",
    "liability": "liability_exposure",
    "limitation_of_liability": "liability_exposure",
    "unlimited_liability": "liability_exposure",
    # vague / undefined clause variants
    "termination": "open_clause",
    "payment": "open_clause",
    "force_majeure": "open_clause",
    "notice": "open_clause",
    "undefined_term": "open_clause",
    "missing_term": "open_clause",
    # protection / IP / confidentiality variants
    "warranty": "weakened_protection",
    "intellectual_property": "weakened_protection",
    "ip": "weakened_protection",
    "confidentiality": "weakened_protection",
    "data_protection": "weakened_protection",
    "non_compete": "weakened_protection",
    # compliance variants
    "regulatory": "compliance_failure",
    "gdpr": "compliance_failure",
    "anti_bribery": "compliance_failure",
}

_VALID_SEVERITIES = {"low", "medium", "high", "critical"}
_VALID_RECOMMENDATIONS = {"negotiate", "reject", "accept_with_note", "seek_legal_advice"}


def _coerce_issue_type(value: str) -> str:
    v = value.lower().strip().replace(" ", "_").replace("-", "_")
    if v in _VALID_ISSUE_TYPES:
        return v
    if v in _ISSUE_TYPE_MAP:
        return _ISSUE_TYPE_MAP[v]
    # Keyword-based fallback
    if any(k in v for k in ("liab", "indemn", "penalty", "damages")):
        return "liability_exposure"
    if any(k in v for k in ("comply", "regulat", "gdpr", "law", "statute")):
        return "compliance_failure"
    if any(k in v for k in ("vague", "ambig", "unclear", "undefined")):
        return "ambiguity"
    if any(k in v for k in ("exploit", "attack", "weaponiz")):
        return "exploitability"
    if any(k in v for k in ("protect", "weak", "ip", "warrant", "confid")):
        return "weakened_protection"
    return "open_clause"  # safest generic fallback


def _coerce_level(value: str, valid: set[str], default: str) -> str:
    v = value.lower().strip() if isinstance(value, str) else default
    return v if v in valid else default


def _coerce_recommendation(value: str) -> str:
    v = value.lower().strip().replace(" ", "_").replace("-", "_") if isinstance(value, str) else "seek_legal_advice"
    if v in _VALID_RECOMMENDATIONS:
        return v
    if "reject" in v:
        return "reject"
    if "accept" in v or "note" in v:
        return "accept_with_note"
    if "negot" in v:
        return "negotiate"
    return "seek_legal_advice"


def _normalize_vote_raw(raw: dict, reviewer_index: int) -> dict:
    """Coerce model vote output to valid ranges before Pydantic sees it."""
    # correctness_score: model may use 0-10 or 0-100 scale instead of 0-1
    score = raw.get("correctness_score", 0.0)
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.5
    if score > 1.0:
        # Detect scale: >10 → assume 0-100, else assume 0-10
        score = score / 100.0 if score > 10 else score / 10.0
    score = max(0.0, min(1.0, score))

    # supported_reviewer_indexes: filter to valid 1-3
    raw_supported = raw.get("supported_reviewer_indexes", [])
    if not isinstance(raw_supported, list):
        raw_supported = []
    supported = [
        int(i) for i in raw_supported
        if isinstance(i, (int, float)) and 1 <= int(i) <= 3
    ]

    # accepted_finding_keys: must be a list of strings
    raw_keys = raw.get("accepted_finding_keys", [])
    if not isinstance(raw_keys, list):
        raw_keys = []
    accepted_keys = [str(k) for k in raw_keys if isinstance(k, str)]

    return {
        "reviewer_index": reviewer_index,
        "supported_reviewer_indexes": supported,
        "accepted_finding_keys": accepted_keys,
        "correctness_score": score,
        "rationale": raw.get("rationale"),
    }


def _normalize_finding_item(item: dict) -> dict:
    """Coerce model output fields to valid enum values before Pydantic validation."""
    item = dict(item)
    item["issue_type"] = _coerce_issue_type(item.get("issue_type", ""))
    item["severity"] = _coerce_level(item.get("severity", ""), _VALID_SEVERITIES, "medium")
    item["exploitability"] = _coerce_level(item.get("exploitability", ""), _VALID_SEVERITIES, "medium")
    item["business_impact"] = _coerce_level(item.get("business_impact", ""), _VALID_SEVERITIES, "medium")
    item["recommendation"] = _coerce_recommendation(item.get("recommendation", ""))
    return item

ReviewerRole = Literal["issue_discovery", "false_positive_challenge", "exploitability_impact"]

_ROLE_BY_INDEX: dict[int, ReviewerRole] = {
    1: "issue_discovery",
    2: "false_positive_challenge",
    3: "exploitability_impact",
}

_FINDING_ITEM_SCHEMA: dict = {
    "type": "object",
    "required": [
        "clause_uid",
        "issue_type",
        "severity",
        "exploitability",
        "business_impact",
        "description",
        "recommendation",
        "recommendation_detail",
    ],
    "properties": {
        "clause_uid": {"type": "string"},
        "issue_type": {
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
        "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "exploitability": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "business_impact": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "description": {"type": "string"},
        "recommendation": {
            "type": "string",
            "enum": ["negotiate", "reject", "accept_with_note", "seek_legal_advice"],
        },
        "recommendation_detail": {"type": "string"},
    },
}

REVIEWER_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "required": ["findings"],
    "properties": {"findings": {"type": "array", "items": _FINDING_ITEM_SCHEMA}},
}

REVIEWER_VOTE_SCHEMA: dict = {
    "type": "object",
    "required": ["supported_reviewer_indexes", "accepted_finding_keys", "correctness_score"],
    "properties": {
        "supported_reviewer_indexes": {
            "type": "array",
            "items": {"type": "integer"},
        },
        "accepted_finding_keys": {
            "type": "array",
            "items": {"type": "string"},
        },
        "correctness_score": {"type": "number"},
        "rationale": {"type": "string"},
    },
}

_ISSUE_DISCOVERY_SYSTEM = """\
You are a meticulous legal contract reviewer performing an exhaustive issue-discovery pass.
Surface every plausible issue tied to the supplied clause_uid values.
Flag liability exposure, open clauses, ambiguity, exploitability, weakened protections, and compliance failures."""

_FALSE_POSITIVE_CHALLENGE_SYSTEM = """\
You are a rigorous legal contract reviewer performing a false-positive challenge pass.
Keep only material issues that a senior transactional attorney would care about.
Discard immaterial boilerplate concerns and weak findings."""

_EXPLOITABILITY_IMPACT_SYSTEM = """\
You are a legal contract reviewer specializing in exploitability and business impact.
Focus on clauses a sophisticated counterparty could weaponize and quantify the practical downside."""

_SYSTEM_BY_ROLE: dict[ReviewerRole, str] = {
    "issue_discovery": _ISSUE_DISCOVERY_SYSTEM,
    "false_positive_challenge": _FALSE_POSITIVE_CHALLENGE_SYSTEM,
    "exploitability_impact": _EXPLOITABILITY_IMPACT_SYSTEM,
}


def _format_clauses(clause_index: list[dict]) -> str:
    return "\n\n".join(
        f"[{clause['clause_uid']}] page={clause['page']}\n{clause['normalized_text']}"
        for clause in clause_index
    )


def _format_policy_context(context: dict) -> str:
    parts: list[str] = []
    lineage = context.get("lineage")
    if lineage:
        parts.append(
            f"Lineage tenant={lineage.get('tenant_id')} family={lineage.get('policy_family_id')} version={lineage.get('version_number')}"
        )
    for prior in context.get("prior_versions", []):
        parts.append(f"Prior version {prior.get('version_number')}: {prior.get('change_summary') or 'n/a'}")
    rules = context.get("playbook_rules", [])
    if rules:
        parts.append("Playbook rules:")
        parts.extend(f"- {rule}" for rule in rules[:50])
    return "\n".join(parts) or "(no policy context)"


def _format_compliance_context(context: dict) -> str:
    parts: list[str] = [
        f"Jurisdiction: {context.get('jurisdiction', 'n/a')}",
        f"Regime: {context.get('regime', 'n/a')}",
    ]
    internal_rules = context.get("internal_rules", [])
    external_rules = context.get("external_rules", [])
    if internal_rules:
        parts.append("Internal rules:")
        parts.extend(f"- {rule}" for rule in internal_rules[:50])
    if external_rules:
        parts.append("External rules:")
        parts.extend(f"- {rule}" for rule in external_rules[:50])
    return "\n".join(parts)


def _format_findings(findings: list[dict]) -> str:
    if not findings:
        return "(no merged findings)"
    return "\n".join(
        f"[{finding.get('finding_id')}] clause={finding.get('clause_uid')} severity={finding.get('severity')} "
        f"type={finding.get('issue_type')} description={finding.get('description')}"
        for finding in findings
    )


def _finding_key(finding: Finding) -> str:
    return f"{finding.clause_uid}|{finding.issue_type}|{finding.severity}"


def _format_branch_review_output(output: BranchReviewOutput) -> str:
    if not output.findings:
        return f"Reviewer {output.reviewer_index}: no findings"
    lines = [
        f"Reviewer {output.reviewer_index}: key={_finding_key(finding)} description={finding.description}"
        for finding in output.findings
    ]
    return "\n".join(lines)


def _assemble_branch_output(
    raw: dict,
    *,
    branch: str,
    reviewer_index: int,
    agent_role: str,
    clause_index: list[dict],
    round_number: int,
) -> BranchReviewOutput:
    clauses_by_uid = {clause["clause_uid"]: clause for clause in clause_index}
    findings: list[Finding] = []

    for raw_item in raw.get("findings", []):
        item = _normalize_finding_item(raw_item)
        clause_uid = item.get("clause_uid")
        clause = clauses_by_uid.get(clause_uid)
        if not clause:
            continue
        findings.append(
            Finding(
                finding_id=str(uuid.uuid4()),
                clause_uid=clause_uid,
                issue_type=item["issue_type"],
                severity=item["severity"],
                exploitability=item["exploitability"],
                business_impact=item["business_impact"],
                description=item.get("description", ""),
                recommendation=item["recommendation"],
                recommendation_detail=item.get("recommendation_detail", ""),
                evidence=[
                    EvidenceRef(
                        document_hash=clause["document_hash"],
                        parser_version=clause["parser_version"],
                        clause_uid=clause_uid,
                        page=clause["page"],
                        bbox=clause["bbox"],
                        normalized_text=clause["normalized_text"],
                        extraction_confidence=clause["extraction_confidence"],
                    )
                ],
                branch=branch,  # type: ignore[arg-type]
                agent_role=agent_role,
                round_number=round_number,
            )
        )

    return BranchReviewOutput(
        branch=branch,  # type: ignore[arg-type]
        reviewer_index=reviewer_index,
        findings=findings,
        raw_response_id=None,
    )


class HarveyReviewerAgent:
    def __init__(self, provider: StructuredLLMProvider, reviewer_index: int) -> None:
        if reviewer_index not in (1, 2, 3):
            raise ValueError("reviewer_index must be 1, 2, or 3")
        self._provider = provider
        self._reviewer_index = reviewer_index
        self._role = _ROLE_BY_INDEX[reviewer_index]

    @property
    def agent_role(self) -> str:
        return f"harvey_reviewer_{self._reviewer_index}"

    async def review(self, clause_index: list[dict], policy_context: dict) -> BranchReviewOutput:
        prompt = (
            f"{_SYSTEM_BY_ROLE[self._role]}\n\n"
            "## Policy Context\n"
            f"{_format_policy_context(policy_context)}\n\n"
            "## Contract Clauses\n"
            f"{_format_clauses(clause_index)}\n\n"
            "Return only a JSON object matching the schema."
        )
        raw = await self._provider.generate_structured_output(prompt, REVIEWER_OUTPUT_SCHEMA)
        return _assemble_branch_output(
            raw,
            branch="harvey",
            reviewer_index=self._reviewer_index,
            agent_role=self.agent_role,
            clause_index=clause_index,
            round_number=1,
        )

    async def vote(self, review_outputs: list[BranchReviewOutput]) -> ReviewerVote:
        prompt = (
            "You are reviewer "
            f"{self._reviewer_index}. Review the other reviewers' outputs and state who you agree with.\n\n"
            + "\n\n".join(_format_branch_review_output(output) for output in review_outputs)
            + "\n\nReturn JSON only. accepted_finding_keys must use the exact format clause_uid|issue_type|severity."
        )
        raw = await self._provider.generate_structured_output(prompt, REVIEWER_VOTE_SCHEMA)
        return ReviewerVote(**_normalize_vote_raw(raw, self._reviewer_index))


class KiraReviewerAgent:
    def __init__(self, provider: StructuredLLMProvider, reviewer_index: int) -> None:
        if reviewer_index not in (1, 2, 3):
            raise ValueError("reviewer_index must be 1, 2, or 3")
        self._provider = provider
        self._reviewer_index = reviewer_index
        self._role = _ROLE_BY_INDEX[reviewer_index]

    @property
    def agent_role(self) -> str:
        return f"kira_reviewer_{self._reviewer_index}"

    async def review(self, clause_index: list[dict], compliance_context: dict) -> BranchReviewOutput:
        prompt = (
            f"{_SYSTEM_BY_ROLE[self._role]}\n\n"
            "## Compliance Context\n"
            f"{_format_compliance_context(compliance_context)}\n\n"
            "## Contract Clauses\n"
            f"{_format_clauses(clause_index)}\n\n"
            "Return only a JSON object matching the schema."
        )
        raw = await self._provider.generate_structured_output(prompt, REVIEWER_OUTPUT_SCHEMA)
        return _assemble_branch_output(
            raw,
            branch="kira",
            reviewer_index=self._reviewer_index,
            agent_role=self.agent_role,
            clause_index=clause_index,
            round_number=1,
        )

    async def vote(self, review_outputs: list[BranchReviewOutput]) -> ReviewerVote:
        prompt = (
            "You are reviewer "
            f"{self._reviewer_index}. Review the other reviewers' outputs and state who you agree with.\n\n"
            + "\n\n".join(_format_branch_review_output(output) for output in review_outputs)
            + "\n\nReturn JSON only. accepted_finding_keys must use the exact format clause_uid|issue_type|severity."
        )
        raw = await self._provider.generate_structured_output(prompt, REVIEWER_VOTE_SCHEMA)
        return ReviewerVote(**_normalize_vote_raw(raw, self._reviewer_index))


class FinalReviewerAgent:
    def __init__(self, provider: StructuredLLMProvider, reviewer_index: int) -> None:
        if reviewer_index not in (1, 2, 3):
            raise ValueError("reviewer_index must be 1, 2, or 3")
        self._provider = provider
        self._reviewer_index = reviewer_index
        self._role = _ROLE_BY_INDEX[reviewer_index]

    @property
    def agent_role(self) -> str:
        return f"final_reviewer_{self._reviewer_index}"

    async def review(
        self,
        clause_index: list[dict],
        merged_findings: list[dict],
        *,
        round_number: int = 1,
        delta_instructions: str | None = None,
    ) -> BranchReviewOutput:
        delta_block = f"\n\n## Delta Instructions\n{delta_instructions}" if delta_instructions else ""
        prompt = (
            f"{_SYSTEM_BY_ROLE[self._role]}\n\n"
            "## Merged Findings\n"
            f"{_format_findings(merged_findings)}\n\n"
            "## Contract Clauses\n"
            f"{_format_clauses(clause_index)}"
            f"{delta_block}\n\n"
            "Return only a JSON object matching the schema."
        )
        raw = await self._provider.generate_structured_output(prompt, REVIEWER_OUTPUT_SCHEMA)
        return _assemble_branch_output(
            raw,
            branch="harvey",
            reviewer_index=self._reviewer_index,
            agent_role=self.agent_role,
            clause_index=clause_index,
            round_number=round_number,
        )

    async def vote(self, review_outputs: list[BranchReviewOutput]) -> ReviewerVote:
        prompt = (
            "You are reviewer "
            f"{self._reviewer_index}. Review the other reviewers' outputs and state who you agree with.\n\n"
            + "\n\n".join(_format_branch_review_output(output) for output in review_outputs)
            + "\n\nReturn JSON only. accepted_finding_keys must use the exact format clause_uid|issue_type|severity."
        )
        raw = await self._provider.generate_structured_output(prompt, REVIEWER_VOTE_SCHEMA)
        return ReviewerVote(**_normalize_vote_raw(raw, self._reviewer_index))

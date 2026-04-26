"""
Verdict reviewer agents.

Reviewers own prompt construction and typed result assembly.
Providers own transport and structured-output enforcement.

Active architecture:
  Harvey retrieves RAG evidence; Kira finds contract problems; Admin merges the
  consensus output. Harvey reviewer classes are retained for legacy runs and
  offline experiments only.
"""

from __future__ import annotations

import uuid
from typing import Literal

from app.backend.models.schemas import BranchReviewOutput, EvidenceRef, Finding, ReviewerVote
from app.backend.providers.base import StructuredLLMProvider

# ---------------------------------------------------------------------------
# Enum coercion — small models often return plausible-but-wrong values.
# ---------------------------------------------------------------------------

_VALID_ISSUE_TYPES = {
    "liability_exposure", "open_clause", "ambiguity",
    "exploitability", "weakened_protection", "compliance_failure",
}
_ISSUE_TYPE_MAP: dict[str, str] = {
    "indemnification": "liability_exposure",
    "indemnity": "liability_exposure",
    "liability": "liability_exposure",
    "limitation_of_liability": "liability_exposure",
    "unlimited_liability": "liability_exposure",
    "termination": "open_clause",
    "payment": "open_clause",
    "force_majeure": "open_clause",
    "notice": "open_clause",
    "undefined_term": "open_clause",
    "missing_term": "open_clause",
    "warranty": "weakened_protection",
    "intellectual_property": "weakened_protection",
    "ip": "weakened_protection",
    "confidentiality": "weakened_protection",
    "data_protection": "weakened_protection",
    "non_compete": "weakened_protection",
    "regulatory": "compliance_failure",
    "gdpr": "compliance_failure",
    "anti_bribery": "compliance_failure",
}

_VALID_SEVERITIES = {"low", "medium", "high", "critical"}
_VALID_RECOMMENDATIONS = {"negotiate", "reject", "accept_with_note", "seek_legal_advice"}

DEFAULT_REVIEWER_TEMPERATURE = 0.2


def _coerce_issue_type(value: str) -> str:
    v = value.lower().strip().replace(" ", "_").replace("-", "_")
    if v in _VALID_ISSUE_TYPES:
        return v
    if v in _ISSUE_TYPE_MAP:
        return _ISSUE_TYPE_MAP[v]
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
    return "open_clause"


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
    score = raw.get("correctness_score", 0.0)
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.5
    if score > 1.0:
        score = score / 100.0 if score > 10 else score / 10.0
    score = max(0.0, min(1.0, score))

    raw_supported = raw.get("supported_reviewer_indexes", [])
    if not isinstance(raw_supported, list):
        raw_supported = []
    supported = [
        int(i) for i in raw_supported
        if isinstance(i, (int, float)) and 1 <= int(i) <= 3
    ]

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
    item = dict(item)
    item["issue_type"] = _coerce_issue_type(item.get("issue_type", ""))
    item["severity"] = _coerce_level(item.get("severity", ""), _VALID_SEVERITIES, "medium")
    item["exploitability"] = _coerce_level(item.get("exploitability", ""), _VALID_SEVERITIES, "medium")
    item["business_impact"] = _coerce_level(item.get("business_impact", ""), _VALID_SEVERITIES, "medium")
    item["recommendation"] = _coerce_recommendation(item.get("recommendation", ""))
    if not isinstance(item.get("contract_evidence"), list):
        item["contract_evidence"] = []
    if not isinstance(item.get("rag_citations"), list):
        item["rag_citations"] = []
    item["uncertainty"] = bool(item.get("uncertainty", False))
    if "rationale" not in item or not isinstance(item.get("rationale"), str):
        item["rationale"] = ""
    if "unresolved_by_consensus" not in item:
        item["unresolved_by_consensus"] = False
    return item


ReviewerRole = Literal["issue_discovery", "false_positive_challenge", "exploitability_impact"]

_ROLE_BY_INDEX: dict[int, ReviewerRole] = {
    1: "issue_discovery",
    2: "false_positive_challenge",
    3: "exploitability_impact",
}

# ---------------------------------------------------------------------------
# JSON schemas for structured LLM output
# ---------------------------------------------------------------------------

_FINDING_ITEM_SCHEMA_BASE: dict = {
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
        "contract_evidence",
        "rationale",
        "uncertainty",
        "unresolved_by_consensus",
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
        "contract_evidence": {
            "type": "array",
            "items": {"type": "string"},
            "description": "clause_uid values that directly support this finding.",
        },
        "rationale": {
            "type": "string",
            "description": "Single-sentence explanation for the finding, no chain-of-thought.",
        },
        "uncertainty": {
            "type": "boolean",
            "description": "Set true when model confidence for this finding is below 0.7.",
        },
        "unresolved_by_consensus": {
            "type": "boolean",
            "description": "True when the finding could not be resolved by reviewer consensus.",
        },
    },
}

# Harvey schema adds rag_citations (required, ≥1 for contradiction findings)
_HARVEY_FINDING_ITEM_SCHEMA: dict = {
    **_FINDING_ITEM_SCHEMA_BASE,
    "required": [*_FINDING_ITEM_SCHEMA_BASE["required"], "rag_citations"],
    "properties": {
        **_FINDING_ITEM_SCHEMA_BASE["properties"],
        "rag_citations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "RAG chunk_ids from the policy/compliance corpus that contradict or confirm this clause.",
        },
    },
}

HARVEY_REVIEWER_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "required": ["findings"],
    "properties": {"findings": {"type": "array", "items": _HARVEY_FINDING_ITEM_SCHEMA}},
}

# Kira schema omits rag_citations entirely (service layer blocks access)
KIRA_REVIEWER_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "required": ["findings"],
    "properties": {"findings": {"type": "array", "items": _FINDING_ITEM_SCHEMA_BASE}},
}

# Keep for backward compat with vote calls
REVIEWER_OUTPUT_SCHEMA = HARVEY_REVIEWER_OUTPUT_SCHEMA

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

# ---------------------------------------------------------------------------
# System role prompts — role instructions passed as system context
# ---------------------------------------------------------------------------

_HARVEY_ISSUE_DISCOVERY_SYSTEM = """\
[SYSTEM ROLE: Harvey Issue Discovery]
You are a meticulous legal contract reviewer performing an exhaustive issue-discovery pass.
Surface every plausible issue tied to the supplied clause_uid values.
Flag liability exposure, open clauses, ambiguity, exploitability, weakened protections, and compliance failures.

CRITICAL RULES:
- You MUST cite at least one rag_citation (chunk_id from the policy corpus) for every \
contradiction finding. Findings that contradict policy without a rag_citation will be discarded.
- You MUST cite at least one contract_evidence (clause_uid) per finding.
- Do NOT include chain-of-thought. Return strict JSON only.
- Set uncertainty=true for any finding where your confidence is below 0.7.
- Do not fabricate chunk_ids. Only cite chunk_ids that were present in the RAG context."""

_HARVEY_FALSE_POSITIVE_CHALLENGE_SYSTEM = """\
[SYSTEM ROLE: Harvey False-Positive Challenge]
You are a rigorous legal contract reviewer performing a false-positive challenge pass.
Keep only material issues that a senior transactional attorney would care about.
Discard immaterial boilerplate concerns and weak findings.

CRITICAL RULES:
- For every finding you retain, cite at least one rag_citation (chunk_id) from the policy \
corpus that confirms this is a real issue, and at least one contract_evidence (clause_uid).
- Do NOT include chain-of-thought. Return strict JSON only.
- Set uncertainty=true when your confidence for a finding is below 0.7.
- Do not fabricate chunk_ids. Only cite chunk_ids that were present in the RAG context."""

_HARVEY_EXPLOITABILITY_IMPACT_SYSTEM = """\
[SYSTEM ROLE: Harvey Exploitability & Business Impact]
You are a legal contract reviewer specializing in exploitability and business impact.
Focus on clauses a sophisticated counterparty could weaponize. Quantify the practical downside.

CRITICAL RULES:
- For each finding, cite at least one rag_citation (chunk_id) showing the policy/regulation \
violated or enabling the exploit, and at least one contract_evidence (clause_uid).
- Do NOT include chain-of-thought. Return strict JSON only.
- Set uncertainty=true when your confidence is below 0.7.
- Do not fabricate chunk_ids. Only cite chunk_ids that were present in the RAG context."""

_KIRA_ISSUE_DISCOVERY_SYSTEM = """\
[SYSTEM ROLE: Kira Issue Discovery]
You are a meticulous legal contract reviewer performing an exhaustive issue-discovery pass \
focused on internal contract integrity: holes, ambiguities, and missing protections.
Surface every plausible issue tied to the supplied clause_uid values.

CRITICAL RULES:
- You MUST cite at least one contract_evidence (clause_uid) per finding.
- You are STRICTLY FORBIDDEN from citing or referencing RAG chunk_ids or any external corpus. \
Your analysis is based solely on the contract text provided.
- Do NOT include chain-of-thought. Return strict JSON only.
- Set uncertainty=true for any finding where your confidence is below 0.7."""

_KIRA_FALSE_POSITIVE_CHALLENGE_SYSTEM = """\
[SYSTEM ROLE: Kira False-Positive Challenge]
You are a rigorous legal contract reviewer performing a false-positive challenge pass \
focused on internal contract integrity.
Keep only material issues: internal inconsistencies, missing protections, and genuine ambiguities \
that a senior attorney would flag.

CRITICAL RULES:
- For every finding you retain, cite at least one contract_evidence (clause_uid).
- You are STRICTLY FORBIDDEN from citing or referencing RAG chunk_ids or any external corpus.
- Do NOT include chain-of-thought. Return strict JSON only.
- Set uncertainty=true when your confidence for a finding is below 0.7."""

_KIRA_EXPLOITABILITY_IMPACT_SYSTEM = """\
[SYSTEM ROLE: Kira Exploitability & Business Impact — Contract-Only]
You are a legal contract reviewer specializing in exploitability and business impact, \
working exclusively from the contract text.
Focus on internal clause weaknesses, missing protections, and ambiguous language a \
sophisticated counterparty could exploit from within the four corners of the document.

CRITICAL RULES:
- Cite at least one contract_evidence (clause_uid) per finding.
- You are STRICTLY FORBIDDEN from citing or referencing RAG chunk_ids or any external corpus.
- Do NOT include chain-of-thought. Return strict JSON only.
- Set uncertainty=true when your confidence is below 0.7."""

_HARVEY_SYSTEM_BY_ROLE: dict[ReviewerRole, str] = {
    "issue_discovery": _HARVEY_ISSUE_DISCOVERY_SYSTEM,
    "false_positive_challenge": _HARVEY_FALSE_POSITIVE_CHALLENGE_SYSTEM,
    "exploitability_impact": _HARVEY_EXPLOITABILITY_IMPACT_SYSTEM,
}

_KIRA_SYSTEM_BY_ROLE: dict[ReviewerRole, str] = {
    "issue_discovery": _KIRA_ISSUE_DISCOVERY_SYSTEM,
    "false_positive_challenge": _KIRA_FALSE_POSITIVE_CHALLENGE_SYSTEM,
    "exploitability_impact": _KIRA_EXPLOITABILITY_IMPACT_SYSTEM,
}

# ---------------------------------------------------------------------------
# Prompt formatters
# ---------------------------------------------------------------------------


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
            f"Lineage tenant={lineage.get('tenant_id')} family={lineage.get('policy_family_id')} "
            f"version={lineage.get('version_number')}"
        )
    for prior in context.get("prior_versions", []):
        parts.append(f"Prior version {prior.get('version_number')}: {prior.get('change_summary') or 'n/a'}")
    rules = context.get("playbook_rules", [])
    if rules:
        parts.append("Playbook rules:")
        parts.extend(f"- {rule}" for rule in rules[:50])
    return "\n".join(parts) or "(no policy context)"


def _format_rag_context(rag_chunks: list[dict]) -> str:
    """Format RAG retrieval results for Harvey prompts."""
    if not rag_chunks:
        return "(no RAG context retrieved)"
    parts: list[str] = []
    for chunk in rag_chunks:
        chunk_id = chunk.get("chunk_id", "unknown")
        text = chunk.get("text", "")
        source = chunk.get("source_path", "")
        parts.append(f"[chunk_id={chunk_id}] source={source}\n{text}")
    return "\n\n".join(parts)


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


# ---------------------------------------------------------------------------
# Assembly helpers
# ---------------------------------------------------------------------------


def _assemble_branch_output(
    raw: dict,
    *,
    branch: str,
    reviewer_index: int,
    agent_role: str,
    clause_index: list[dict],
    round_number: int,
    require_rag_citations: bool = False,
    require_contract_evidence: bool = True,
) -> BranchReviewOutput:
    clauses_by_uid = {clause["clause_uid"]: clause for clause in clause_index}
    findings: list[Finding] = []

    for raw_item in raw.get("findings", []):
        item = _normalize_finding_item(raw_item)
        clause_uid = item.get("clause_uid")
        clause = clauses_by_uid.get(clause_uid)
        if not clause:
            continue

        contract_evidence: list[str] = item.get("contract_evidence", [])
        rag_citations: list[str] = item.get("rag_citations", [])

        # Enforce evidence-schema invariants
        if require_contract_evidence and not contract_evidence:
            continue
        if require_rag_citations and not rag_citations:
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
                unresolved_by_consensus=item.get("unresolved_by_consensus", False),
            )
        )

    return BranchReviewOutput(
        branch=branch,  # type: ignore[arg-type]
        reviewer_index=reviewer_index,
        findings=findings,
        raw_response_id=None,
    )


# ---------------------------------------------------------------------------
# Harvey reviewers — query pgvector RAG; require rag_citations
# ---------------------------------------------------------------------------


class HarveyReviewer:
    """Harvey branch reviewer with RAG citation enforcement."""

    temperature: float = DEFAULT_REVIEWER_TEMPERATURE

    def __init__(self, provider: StructuredLLMProvider, reviewer_index: int) -> None:
        if reviewer_index not in (1, 2, 3):
            raise ValueError("reviewer_index must be 1, 2, or 3")
        self._provider = provider
        self._reviewer_index = reviewer_index
        self._role: ReviewerRole = _ROLE_BY_INDEX[reviewer_index]

    @property
    def agent_role(self) -> str:
        return f"harvey_reviewer_{self._reviewer_index}"

    async def review(
        self,
        clause_index: list[dict],
        policy_context: dict,
        rag_chunks: list[dict] | None = None,
    ) -> BranchReviewOutput:
        system_block = _HARVEY_SYSTEM_BY_ROLE[self._role]
        rag_block = _format_rag_context(rag_chunks or [])
        prompt = (
            f"{system_block}\n\n"
            "## Policy Context\n"
            f"{_format_policy_context(policy_context)}\n\n"
            "## RAG Context (cite chunk_ids from this section in rag_citations)\n"
            f"{rag_block}\n\n"
            "## Contract Clauses\n"
            f"{_format_clauses(clause_index)}\n\n"
            "Return ONLY a JSON object matching the schema. No explanation, no chain-of-thought."
        )
        raw = await self._provider.generate_structured_output(prompt, HARVEY_REVIEWER_OUTPUT_SCHEMA)
        return _assemble_branch_output(
            raw,
            branch="harvey",
            reviewer_index=self._reviewer_index,
            agent_role=self.agent_role,
            clause_index=clause_index,
            round_number=1,
            require_rag_citations=True,
            require_contract_evidence=True,
        )

    async def vote(self, review_outputs: list[BranchReviewOutput]) -> ReviewerVote:
        prompt = (
            f"You are Harvey reviewer {self._reviewer_index}. "
            "Review the other reviewers' outputs below and state who you agree with.\n\n"
            + "\n\n".join(_format_branch_review_output(output) for output in review_outputs)
            + "\n\nReturn JSON only. accepted_finding_keys must use the exact format "
            "clause_uid|issue_type|severity."
        )
        raw = await self._provider.generate_structured_output(prompt, REVIEWER_VOTE_SCHEMA)
        return ReviewerVote(**_normalize_vote_raw(raw, self._reviewer_index))


# ---------------------------------------------------------------------------
# Kira reviewers — contract-only analysis; rag_citations explicitly forbidden
# ---------------------------------------------------------------------------


class KiraReviewer:
    """Kira branch reviewer; contract-only, no RAG access per harvey-rag-only contract."""

    temperature: float = DEFAULT_REVIEWER_TEMPERATURE

    def __init__(self, provider: StructuredLLMProvider, reviewer_index: int) -> None:
        if reviewer_index not in (1, 2, 3):
            raise ValueError("reviewer_index must be 1, 2, or 3")
        self._provider = provider
        self._reviewer_index = reviewer_index
        self._role: ReviewerRole = _ROLE_BY_INDEX[reviewer_index]

    @property
    def agent_role(self) -> str:
        return f"kira_reviewer_{self._reviewer_index}"

    async def review(
        self,
        clause_index: list[dict],
        compliance_context: dict,
    ) -> BranchReviewOutput:
        system_block = _KIRA_SYSTEM_BY_ROLE[self._role]
        prompt = (
            f"{system_block}\n\n"
            "## Compliance Context\n"
            f"{_format_compliance_context(compliance_context)}\n\n"
            "## Contract Clauses\n"
            f"{_format_clauses(clause_index)}\n\n"
            "Return ONLY a JSON object matching the schema. No explanation, no chain-of-thought. "
            "Do NOT include rag_citations in your response."
        )
        raw = await self._provider.generate_structured_output(prompt, KIRA_REVIEWER_OUTPUT_SCHEMA)
        return _assemble_branch_output(
            raw,
            branch="kira",
            reviewer_index=self._reviewer_index,
            agent_role=self.agent_role,
            clause_index=clause_index,
            round_number=1,
            require_rag_citations=False,
            require_contract_evidence=True,
        )

    async def vote(self, review_outputs: list[BranchReviewOutput]) -> ReviewerVote:
        prompt = (
            f"You are Kira reviewer {self._reviewer_index}. "
            "Review the other reviewers' outputs below and state who you agree with.\n\n"
            + "\n\n".join(_format_branch_review_output(output) for output in review_outputs)
            + "\n\nReturn JSON only. accepted_finding_keys must use the exact format "
            "clause_uid|issue_type|severity."
        )
        raw = await self._provider.generate_structured_output(prompt, REVIEWER_VOTE_SCHEMA)
        return ReviewerVote(**_normalize_vote_raw(raw, self._reviewer_index))


# ---------------------------------------------------------------------------
# Backward-compat aliases — callers referencing the old names still work
# ---------------------------------------------------------------------------

HarveyReviewerAgent = HarveyReviewer
KiraReviewerAgent = KiraReviewer

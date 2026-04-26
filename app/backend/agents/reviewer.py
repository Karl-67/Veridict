"""
Verdict reviewer agents.

Harvey — sequential 3-stage pipeline (not parallel independent passes):
  Stage 1  HarveyReviewer(1) contradiction_finder   — exhaustive discovery on contract + RAG
  Stage 2  HarveyReviewer(2) regression_challenger  — receives stage-1 findings, filters to
                                                       material regressions only
  Stage 3  HarveyReviewer(3) downstream_risk        — receives stage-2 findings, enriches each
                                                       with downstream enforcement gap / liability

  The sequential dependency is intentional: regression_challenger only makes sense if it
  sees what contradiction_finder found. Running them independently wastes the role
  differentiation. The filtered output from stage 3 goes directly to admin.

Kira — worker + panel loop:
  KiraWorker (1 instance)        — analyses the contract, must provide recommended_change
  KiraPanelReviewer (3 instances) — each votes approve/reject with specific feedback
  2-of-3 approvals → pass to admin
  2+ rejections → aggregate feedback → worker revises → panel re-reviews (max 3 iterations)

Fine-tuning contract: see agents/base.py.
  KiraWorker      → FineTunableAgent (LEDGAR, priority 1)
  HarveyReviewer  → FineTunableAgent (CUAD, priority 2)
  KiraPanelReviewer → BaselineAgent (reviews fine-tuned worker)
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.backend.agents.base import BaselineAgent, FineTunableAgent
from app.backend.models.schemas import BranchReviewOutput, EvidenceRef, Finding, ReviewerVote
from app.backend.providers.base import StructuredLLMProvider

# ---------------------------------------------------------------------------
# Enum coercion helpers
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
    v = (
        value.lower().strip().replace(" ", "_").replace("-", "_")
        if isinstance(value, str)
        else "seek_legal_advice"
    )
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
    supported = [int(i) for i in raw_supported if isinstance(i, (int, float)) and 1 <= int(i) <= 3]
    raw_keys = raw.get("accepted_finding_keys", [])
    if not isinstance(raw_keys, list):
        raw_keys = []
    return {
        "reviewer_index": reviewer_index,
        "supported_reviewer_indexes": supported,
        "accepted_finding_keys": [str(k) for k in raw_keys if isinstance(k, str)],
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
    if not isinstance(item.get("rationale"), str):
        item["rationale"] = ""
    if "unresolved_by_consensus" not in item:
        item["unresolved_by_consensus"] = False
    if not isinstance(item.get("recommended_change"), str):
        item["recommended_change"] = None
    return item


# ---------------------------------------------------------------------------
# JSON schemas for structured LLM output
# ---------------------------------------------------------------------------

_FINDING_ITEM_SCHEMA_BASE: dict = {
    "type": "object",
    "required": [
        "clause_uid", "issue_type", "severity", "exploitability", "business_impact",
        "description", "recommendation", "recommendation_detail",
        "contract_evidence", "rationale", "uncertainty", "unresolved_by_consensus",
    ],
    "properties": {
        "clause_uid": {"type": "string"},
        "issue_type": {
            "type": "string",
            "enum": [
                "liability_exposure", "open_clause", "ambiguity",
                "exploitability", "weakened_protection", "compliance_failure",
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
        },
        "rationale": {"type": "string"},
        "uncertainty": {"type": "boolean"},
        "unresolved_by_consensus": {"type": "boolean"},
    },
}

HARVEY_FINDING_ITEM_SCHEMA: dict = {
    **_FINDING_ITEM_SCHEMA_BASE,
    "required": [*_FINDING_ITEM_SCHEMA_BASE["required"], "rag_citations"],
    "properties": {
        **_FINDING_ITEM_SCHEMA_BASE["properties"],
        "rag_citations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "chunk_ids from the RAG context.",
        },
    },
}

HARVEY_REVIEWER_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "required": ["findings"],
    "properties": {"findings": {"type": "array", "items": HARVEY_FINDING_ITEM_SCHEMA}},
}

KIRA_FINDING_ITEM_SCHEMA: dict = {
    **_FINDING_ITEM_SCHEMA_BASE,
    "required": [*_FINDING_ITEM_SCHEMA_BASE["required"], "recommended_change"],
    "properties": {
        **_FINDING_ITEM_SCHEMA_BASE["properties"],
        "recommended_change": {
            "type": "string",
            "description": "Concrete suggested rewrite that fixes this issue.",
        },
    },
}

KIRA_WORKER_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "required": ["findings"],
    "properties": {"findings": {"type": "array", "items": KIRA_FINDING_ITEM_SCHEMA}},
}

KIRA_PANEL_DECISION_SCHEMA: dict = {
    "type": "object",
    "required": ["decision"],
    "properties": {
        "decision": {"type": "string", "enum": ["approve", "reject"]},
        "feedback": {"type": "string"},
        "finding_concerns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "concern": {"type": "string"},
                },
            },
        },
    },
}

REVIEWER_VOTE_SCHEMA: dict = {
    "type": "object",
    "required": ["supported_reviewer_indexes", "accepted_finding_keys", "correctness_score"],
    "properties": {
        "supported_reviewer_indexes": {"type": "array", "items": {"type": "integer"}},
        "accepted_finding_keys": {"type": "array", "items": {"type": "string"}},
        "correctness_score": {"type": "number"},
        "rationale": {"type": "string"},
    },
}


# ---------------------------------------------------------------------------
# Kira panel reviewer decision
# ---------------------------------------------------------------------------


class KiraReviewerDecision(BaseModel):
    reviewer_index: int
    decision: Literal["approve", "reject"]
    feedback: str | None = None
    finding_concerns: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Harvey prompts — each stage receives the prior stage's output
# ---------------------------------------------------------------------------

_HARVEY_CONTRADICTION_FINDER = """\
[HARVEY STAGE 1 — Contradiction Finder]
You are a legal policy continuity analyst performing an exhaustive first-pass discovery.
Compare every contract clause against the prior policy versions and knowledge-base documents
in the RAG Context below.

Flag clauses that:
- Directly contradict a rule, obligation, or term in a prior policy version.
- Remove or substantially weaken a protection established in a prior version.
- Conflict with another contract or regulatory standard in the knowledge base.
- Introduce language inconsistent with the organisation's established policy history.

Err on the side of inclusion — your output will be reviewed by the Regression Challenger
in the next stage, so flag every plausible contradiction.

CRITICAL RULES:
- You MUST cite at least one rag_citation (chunk_id from the RAG Context) for EVERY finding.
- Do NOT flag internal contract problems — that is Kira's job.
- Do NOT include chain-of-thought. Return strict JSON only.
- Set uncertainty=true when confidence is below 0.7.
- Do not fabricate chunk_ids. Only cite IDs present in the RAG Context."""

_HARVEY_REGRESSION_CHALLENGER = """\
[HARVEY STAGE 2 — Regression Challenger]
You are a legal policy continuity analyst. The Contradiction Finder has identified the
following potential issues in the contract. Your job is to filter this list down to only
the findings that represent genuine, material regressions from prior policy.

CONTRADICTION FINDER FINDINGS:
{prior_findings}

For each finding above, decide:
- KEEP if it represents a real regression a senior legal counsel would act on.
- DISCARD if it is a legitimate documented policy update, a restatement in different words
  with equivalent effect, or a minor structural/formatting change with no substantive impact.
- ADJUST severity downward if the issue is real but less severe than flagged.

Return only the findings you are keeping (with any adjustments). A finding missing from
your response is treated as discarded.

CRITICAL RULES:
- Every finding you keep MUST retain at least one rag_citation.
- Do NOT add new findings — only filter and adjust what the Contradiction Finder produced.
- Do NOT include chain-of-thought. Return strict JSON only."""

_HARVEY_DOWNSTREAM_RISK = """\
[HARVEY STAGE 3 — Downstream Risk Analyst]
You are a legal policy continuity analyst specialising in downstream consequences.
The following contradictions have been validated by the Regression Challenger:

VALIDATED CONTRADICTION FINDINGS:
{prior_findings}

For each finding, enrich it by assessing what downstream enforcement gap, loophole, or
liability this contradiction creates:
- Can the counterparty exploit the inconsistency between this clause and prior policy?
- Does it create an unenforceable obligation because it conflicts with a prior commitment?
- Could it be weaponised in a dispute as evidence of waiver or policy regression?
- What is the worst-case downstream consequence if this is not corrected?

Update each finding's description, severity, and recommendation_detail to reflect the
downstream risk. Do not discard findings — enrich all of them.

CRITICAL RULES:
- Preserve all rag_citations from the validated findings.
- You may increase severity but not decrease it.
- Do NOT include chain-of-thought. Return strict JSON only."""

HarveyRole = Literal["contradiction_finder", "regression_challenger", "downstream_risk"]

_HARVEY_ROLE_BY_INDEX: dict[int, HarveyRole] = {
    1: "contradiction_finder",
    2: "regression_challenger",
    3: "downstream_risk",
}

# ---------------------------------------------------------------------------
# Kira worker and panel prompts
# ---------------------------------------------------------------------------

_KIRA_WORKER_INITIAL = """\
[KIRA WORKER — Contract Integrity Analyst]
You are a legal contract integrity analyst. Review the contract clauses below for internal
issues: problems within the four corners of this document.

Flag clauses that have:
- AMBIGUITY: vague or undefined terms that could be interpreted against our interests.
- MISSING PROTECTIONS: standard protections absent or insufficiently covered.
- EXPLOITABLE GAPS: language a sophisticated counterparty could weaponise.
- IMBALANCED TERMS: disproportionate obligations or risks loaded against us.

For EVERY finding you MUST provide a recommended_change: a specific, concrete suggested
rewrite. Generic advice ("clarify this term") is not acceptable — write the actual text.

CRITICAL RULES:
- You MUST cite at least one contract_evidence (clause_uid) per finding.
- You are STRICTLY FORBIDDEN from referencing RAG chunk_ids or any external corpus.
- Do NOT include chain-of-thought. Return strict JSON only.
- Set uncertainty=true when confidence is below 0.7."""

_KIRA_WORKER_REVISION = """\
[KIRA WORKER — Revision Pass]
Your previous contract analysis was reviewed by the panel and requires changes.
The panel's feedback is below. Revise your findings accordingly.

PANEL FEEDBACK:
{feedback}

CURRENT FINDINGS (revise these):
{current_findings}

You must:
- Address every specific concern raised.
- Remove findings flagged as false positives.
- Add material issues the panel says you missed.
- Replace any recommended_change that was flagged as too generic with actual rewrite text.
- Keep findings the panel did not raise concerns about.

CRITICAL RULES:
- You MUST cite at least one contract_evidence (clause_uid) per finding.
- Do NOT reference RAG chunk_ids or any external corpus.
- Do NOT include chain-of-thought. Return strict JSON only."""

_KIRA_PANEL_REVIEWER = """\
[KIRA PANEL REVIEWER]
You are a senior legal reviewer on the Kira review panel. The Kira analyst has produced
contract findings. Decide whether these are ready to pass to the admin reviewer.

Assess against:
1. COMPLETENESS — Are obvious material issues missing?
2. ACCURACY — Are findings real issues, or boilerplate that is not a problem?
3. ACTIONABILITY — Is each recommended_change a concrete rewrite, not vague advice?
4. SEVERITY CALIBRATION — Are severities appropriate for a senior lawyer's bar?

Decide APPROVE if findings meet the bar. REJECT if they need changes.
If rejecting, your feedback must be specific and actionable. Name exactly what to change."""


# ---------------------------------------------------------------------------
# Prompt formatters
# ---------------------------------------------------------------------------


def _format_clauses(clause_index: list[dict]) -> str:
    return "\n\n".join(
        f"[{c['clause_uid']}] page={c['page']}\n{c['normalized_text']}"
        for c in clause_index
    )


def _format_policy_context(context: dict) -> str:
    parts: list[str] = []
    lineage = context.get("lineage")
    if lineage:
        parts.append(
            f"Lineage tenant={lineage.get('tenant_id')} "
            f"family={lineage.get('policy_family_id')} "
            f"version={lineage.get('version_number')}"
        )
    for prior in context.get("prior_versions", []):
        parts.append(
            f"Prior version {prior.get('version_number')}: "
            f"{prior.get('change_summary') or 'n/a'}"
        )
    rules = context.get("playbook_rules", [])
    if rules:
        parts.append("Playbook rules:")
        parts.extend(f"- {rule}" for rule in rules[:50])
    return "\n".join(parts) or "(no policy context)"


def _format_rag_context(rag_chunks: list[dict]) -> str:
    if not rag_chunks:
        return "(no RAG context retrieved)"
    return "\n\n".join(
        f"[chunk_id={c.get('chunk_id', 'unknown')}] source={c.get('source_path', '')}\n{c.get('text', '')}"
        for c in rag_chunks
    )


def _format_compliance_context(context: dict) -> str:
    parts: list[str] = [
        f"Jurisdiction: {context.get('jurisdiction', 'n/a')}",
        f"Regime: {context.get('regime', 'n/a')}",
    ]
    for rule in context.get("internal_rules", [])[:50]:
        parts.append(f"- {rule}")
    return "\n".join(parts)


def _format_findings_for_stage(findings: list[Finding]) -> str:
    if not findings:
        return "(none)"
    lines: list[str] = []
    for f in findings:
        lines.append(
            f"finding_id={f.finding_id} clause={f.clause_uid} "
            f"severity={f.severity} type={f.issue_type}\n"
            f"  description: {f.description}\n"
            f"  rag_citations: {[e for e in (getattr(f, 'rag_citations', None) or [])]}\n"
            f"  rationale: {f.description}"
        )
    return "\n\n".join(lines)


def _format_findings_for_panel(findings: list[Finding]) -> str:
    if not findings:
        return "(none)"
    lines: list[str] = []
    for f in findings:
        lines.append(
            f"finding_id={f.finding_id}\n"
            f"  clause={f.clause_uid} severity={f.severity} type={f.issue_type}\n"
            f"  description: {f.description}\n"
            f"  recommended_change: {f.recommended_change or '(none)'}"
        )
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Assembly helper
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
    finding_scope: str = "intra_contract",
) -> BranchReviewOutput:
    clauses_by_uid = {c["clause_uid"]: c for c in clause_index}
    findings: list[Finding] = []

    for raw_item in raw.get("findings", []):
        item = _normalize_finding_item(raw_item)
        clause_uid = item.get("clause_uid")
        clause = clauses_by_uid.get(clause_uid)
        if not clause:
            continue
        if require_contract_evidence and not item.get("contract_evidence"):
            continue
        if require_rag_citations and not item.get("rag_citations"):
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
                finding_scope=finding_scope,  # type: ignore[arg-type]
                recommended_change=item.get("recommended_change"),
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
# Harvey reviewer — sequential 3-stage pipeline
# Fine-tune candidate: CUAD dataset, priority 2
# ---------------------------------------------------------------------------


class HarveyReviewer(FineTunableAgent):
    """Harvey branch reviewer.

    Run in sequence: reviewer_index 1 → 2 → 3.
    Each stage receives the prior stage's findings as input.

    Fine-tuning: CUAD dataset (clause annotation, conflict detection), priority 2.
    fine_tune_checkpoint should be set once a checkpoint is available; the provider
    factory will route to the fine-tuned endpoint automatically.
    """

    fine_tune_dataset = "CUAD"
    fine_tune_priority = 2
    fine_tune_checkpoint: str | None = None

    temperature: float = DEFAULT_REVIEWER_TEMPERATURE

    def __init__(self, provider: StructuredLLMProvider, reviewer_index: int) -> None:
        if reviewer_index not in (1, 2, 3):
            raise ValueError("reviewer_index must be 1, 2, or 3")
        self._provider = provider
        self._reviewer_index = reviewer_index
        self._role: HarveyRole = _HARVEY_ROLE_BY_INDEX[reviewer_index]

    @property
    def agent_role(self) -> str:
        return f"harvey_{self._role}"

    async def review(
        self,
        clause_index: list[dict],
        policy_context: dict,
        rag_chunks: list[dict] | None = None,
    ) -> BranchReviewOutput:
        """Stage 1 only — contradiction_finder initial discovery pass."""
        assert self._reviewer_index == 1, "review() is only for stage 1 (contradiction_finder)"
        prompt = (
            f"{_HARVEY_CONTRADICTION_FINDER}\n\n"
            "## Policy Context\n"
            f"{_format_policy_context(policy_context)}\n\n"
            "## RAG Context\n"
            f"{_format_rag_context(rag_chunks or [])}\n\n"
            "## Contract Clauses\n"
            f"{_format_clauses(clause_index)}\n\n"
            "Return ONLY a JSON object matching the schema."
        )
        raw = await self._provider.generate_structured_output(prompt, HARVEY_REVIEWER_OUTPUT_SCHEMA)
        return _assemble_branch_output(
            raw,
            branch="harvey",
            reviewer_index=1,
            agent_role=self.agent_role,
            clause_index=clause_index,
            round_number=1,
            require_rag_citations=True,
            require_contract_evidence=True,
            finding_scope="cross_contract",
        )

    async def challenge(
        self,
        prior_findings: list[Finding],
        clause_index: list[dict],
        policy_context: dict,
        rag_chunks: list[dict] | None = None,
    ) -> list[Finding]:
        """Stage 2 — regression_challenger filters contradiction_finder's output."""
        assert self._reviewer_index == 2, "challenge() is only for stage 2 (regression_challenger)"
        prior_block = _format_findings_for_stage(prior_findings)
        prompt = (
            _HARVEY_REGRESSION_CHALLENGER.format(prior_findings=prior_block) + "\n\n"
            "## Policy Context\n"
            f"{_format_policy_context(policy_context)}\n\n"
            "## RAG Context\n"
            f"{_format_rag_context(rag_chunks or [])}\n\n"
            "## Contract Clauses (for reference)\n"
            f"{_format_clauses(clause_index)}\n\n"
            "Return ONLY a JSON object matching the schema."
        )
        raw = await self._provider.generate_structured_output(prompt, HARVEY_REVIEWER_OUTPUT_SCHEMA)
        output = _assemble_branch_output(
            raw,
            branch="harvey",
            reviewer_index=2,
            agent_role=self.agent_role,
            clause_index=clause_index,
            round_number=1,
            require_rag_citations=True,
            require_contract_evidence=True,
            finding_scope="cross_contract",
        )
        return output.findings

    async def assess_risk(
        self,
        prior_findings: list[Finding],
        clause_index: list[dict],
        policy_context: dict,
        rag_chunks: list[dict] | None = None,
    ) -> list[Finding]:
        """Stage 3 — downstream_risk enriches the validated findings."""
        assert self._reviewer_index == 3, "assess_risk() is only for stage 3 (downstream_risk)"
        prior_block = _format_findings_for_stage(prior_findings)
        prompt = (
            _HARVEY_DOWNSTREAM_RISK.format(prior_findings=prior_block) + "\n\n"
            "## Policy Context\n"
            f"{_format_policy_context(policy_context)}\n\n"
            "## RAG Context\n"
            f"{_format_rag_context(rag_chunks or [])}\n\n"
            "## Contract Clauses (for reference)\n"
            f"{_format_clauses(clause_index)}\n\n"
            "Return ONLY a JSON object matching the schema."
        )
        raw = await self._provider.generate_structured_output(prompt, HARVEY_REVIEWER_OUTPUT_SCHEMA)
        output = _assemble_branch_output(
            raw,
            branch="harvey",
            reviewer_index=3,
            agent_role=self.agent_role,
            clause_index=clause_index,
            round_number=1,
            require_rag_citations=True,
            require_contract_evidence=True,
            finding_scope="cross_contract",
        )
        return output.findings


# ---------------------------------------------------------------------------
# Kira worker — the analyst
# Fine-tune candidate: LEDGAR dataset, priority 1
# ---------------------------------------------------------------------------


class KiraWorker(FineTunableAgent):
    """Performs the initial contract analysis and revises based on panel feedback.

    Fine-tuning: LEDGAR dataset (provision classification, compliance rules), priority 1.
    This is the highest-priority fine-tuning target. The KiraPanelReviewers must stay
    as baseline models to serve as an unbiased quality gate against this fine-tuned worker.

    When fine_tune_checkpoint is set, the provider factory routes inference to the
    fine-tuned endpoint. No prompt changes are needed.
    """

    fine_tune_dataset = "LEDGAR"
    fine_tune_priority = 1
    fine_tune_checkpoint: str | None = None

    temperature: float = DEFAULT_REVIEWER_TEMPERATURE

    def __init__(self, provider: StructuredLLMProvider) -> None:
        self._provider = provider

    @property
    def agent_role(self) -> str:
        return "kira_worker"

    async def analyze(
        self,
        clause_index: list[dict],
        compliance_context: dict,
    ) -> list[Finding]:
        prompt = (
            f"{_KIRA_WORKER_INITIAL}\n\n"
            "## Compliance Context\n"
            f"{_format_compliance_context(compliance_context)}\n\n"
            "## Contract Clauses\n"
            f"{_format_clauses(clause_index)}\n\n"
            "Return ONLY a JSON object matching the schema."
        )
        raw = await self._provider.generate_structured_output(prompt, KIRA_WORKER_OUTPUT_SCHEMA)
        result = _assemble_branch_output(
            raw,
            branch="kira",
            reviewer_index=1,
            agent_role=self.agent_role,
            clause_index=clause_index,
            round_number=1,
            require_rag_citations=False,
            require_contract_evidence=True,
            finding_scope="intra_contract",
        )
        return result.findings

    async def revise(
        self,
        clause_index: list[dict],
        compliance_context: dict,
        current_findings: list[Finding],
        aggregated_feedback: str,
        iteration: int,
    ) -> list[Finding]:
        prompt = (
            _KIRA_WORKER_REVISION.format(
                feedback=aggregated_feedback,
                current_findings=_format_findings_for_panel(current_findings),
            ) + "\n\n"
            "## Compliance Context\n"
            f"{_format_compliance_context(compliance_context)}\n\n"
            "## Contract Clauses\n"
            f"{_format_clauses(clause_index)}\n\n"
            "Return ONLY a JSON object matching the schema."
        )
        raw = await self._provider.generate_structured_output(prompt, KIRA_WORKER_OUTPUT_SCHEMA)
        result = _assemble_branch_output(
            raw,
            branch="kira",
            reviewer_index=1,
            agent_role=self.agent_role,
            clause_index=clause_index,
            round_number=iteration,
            require_rag_citations=False,
            require_contract_evidence=True,
            finding_scope="intra_contract",
        )
        return result.findings


# ---------------------------------------------------------------------------
# Kira panel reviewers — must stay as baseline (non-fine-tuned)
# ---------------------------------------------------------------------------


class KiraPanelReviewer(BaselineAgent):
    """Reviews KiraWorker output. Votes approve/reject with specific feedback.

    MUST STAY BASELINE — do not fine-tune this agent.
    The panel's value is precisely that it is an unbiased model reviewing a fine-tuned
    worker. A fine-tuned panel shares the worker's biases and blind spots and will
    not catch hallucinations or drift introduced by fine-tuning.
    """

    baseline_reason = (
        "Acts as quality gate against fine-tuned KiraWorker. "
        "Must stay baseline to catch worker hallucinations and fine-tuning drift."
    )

    temperature: float = DEFAULT_REVIEWER_TEMPERATURE

    def __init__(self, provider: StructuredLLMProvider, reviewer_index: int) -> None:
        if reviewer_index not in (1, 2, 3):
            raise ValueError("reviewer_index must be 1, 2, or 3")
        self._provider = provider
        self._reviewer_index = reviewer_index

    @property
    def agent_role(self) -> str:
        return f"kira_panel_reviewer_{self._reviewer_index}"

    async def review(self, worker_findings: list[Finding]) -> KiraReviewerDecision:
        findings_block = _format_findings_for_panel(worker_findings)
        prompt = (
            f"{_KIRA_PANEL_REVIEWER}\n\n"
            "## Kira Worker Findings\n"
            f"{findings_block}\n\n"
            "Return ONLY a JSON object matching the schema."
        )
        raw = await self._provider.generate_structured_output(prompt, KIRA_PANEL_DECISION_SCHEMA)
        decision = raw.get("decision", "reject")
        if decision not in ("approve", "reject"):
            decision = "reject"
        return KiraReviewerDecision(
            reviewer_index=self._reviewer_index,
            decision=decision,  # type: ignore[arg-type]
            feedback=raw.get("feedback") or None,
            finding_concerns=raw.get("finding_concerns") or [],
        )


# ---------------------------------------------------------------------------
# Feedback aggregation
# ---------------------------------------------------------------------------


def aggregate_kira_panel_feedback(decisions: list[KiraReviewerDecision]) -> str:
    parts: list[str] = []
    for d in decisions:
        if d.decision != "reject":
            continue
        if d.feedback:
            parts.append(f"Reviewer {d.reviewer_index}:\n{d.feedback}")
        for concern in d.finding_concerns:
            fid = concern.get("finding_id", "unknown")
            parts.append(f"Reviewer {d.reviewer_index} [finding {fid}]: {concern.get('concern', '')}")
    return "\n\n".join(parts) if parts else "(no specific feedback)"


# ---------------------------------------------------------------------------
# Backward-compat aliases
# ---------------------------------------------------------------------------

HarveyReviewerAgent = HarveyReviewer
KiraReviewerAgent = KiraWorker

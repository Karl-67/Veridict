"""
Verdict reviewer agents.

Harvey — parallel independent analysis + peer cross-evaluation + 2-of-3 vote:
  HarveyReviewer(1) contradiction_finder  — finds contradictions between contract and prior policy/RAG
  HarveyReviewer(2) regression_challenger — finds material regressions vs established standards
  HarveyReviewer(3) downstream_risk       — finds liability exposure and enforcement gaps

  All 3 run independently on the raw contract (parallel). Then each evaluates the other two's
  findings (cross-evaluation). Vote: 2-of-3 approve → merge findings → admin.
  2+ reject → retry all 3 from scratch (max 3 iterations).

Kira — worker + panel loop:
  KiraWorker (1 instance)        — analyses the contract, must provide recommended_change
  KiraPanelReviewer (3 instances) — each votes approve/reject with specific feedback
  2-of-3 approvals → pass to admin
  2+ rejections → aggregate feedback → worker revises → panel re-reviews (max 3 iterations)

Fine-tuning contract: see agents/base.py.
  KiraWorker        → FineTunableAgent (LEDGAR, priority 1)
  HarveyReviewer    → FineTunableAgent (CUAD, priority 2)
  KiraPanelReviewer → FineTunableAgent (same fine-tuned weights as KiraWorker; each has a
                       distinct prompt — worker produces findings, panel votes on them;
                       all four Kira agents share one LoRA checkpoint via verdict-vllm-kira)
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.backend.agents.base import BaselineAgent, FineTunableAgent
from app.backend.models.schemas import BranchReviewOutput, ContractEvidence, EvidenceRef, Finding, RagCitation, ReviewerVote
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


_GENERIC_REWRITE_TERMS = (
    "clarify",
    "revise",
    "negotiate",
    "consider",
    "seek legal advice",
    "should be amended",
    "should be revised",
    "add language",
)


def _is_concrete_rewrite(value: str | None) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if len(text) < 20:
        return False
    lowered = text.lower()
    if lowered in _GENERIC_REWRITE_TERMS:
        return False
    if any(term in lowered for term in _GENERIC_REWRITE_TERMS) and len(text.split()) < 12:
        return False
    return True


def _contract_evidence_from_raw(raw_items: list, clause: dict) -> list[ContractEvidence]:
    evidence: list[ContractEvidence] = []
    clause_text = str(clause.get("normalized_text", ""))
    clause_uid = str(clause.get("clause_uid", ""))
    page = int(clause.get("page") or 1)
    confidence = float(clause.get("extraction_confidence") or 1.0)

    for raw in raw_items:
        if isinstance(raw, str):
            text = raw.strip()
            span = None
        elif isinstance(raw, dict):
            text = str(raw.get("text") or raw.get("excerpt") or raw.get("normalized_text") or "").strip()
            span = raw.get("span")
        else:
            continue

        if not text:
            continue

        normalized_text = " ".join(text.split())
        normalized_clause = " ".join(clause_text.split())
        if normalized_text not in normalized_clause:
            # Keep anchors grounded in the selected parser clause. If the model
            # cannot quote text from that clause, fall back to the clause itself
            # rather than hallucinating a span elsewhere in the PDF.
            normalized_text = normalized_clause
            span = None

        evidence.append(
            ContractEvidence(
                clause_id=clause_uid,
                page=page,
                span=span,
                text=normalized_text,
                confidence=confidence,
            )
        )

    return evidence


def _rag_citations_from_raw(raw_items: list) -> list[RagCitation]:
    citations: list[RagCitation] = []
    for raw in raw_items:
        if isinstance(raw, str):
            chunk_id = raw
            item: dict = {}
        elif isinstance(raw, dict):
            item = raw
            chunk_id = str(item.get("chunk_id") or "")
        else:
            continue
        if not chunk_id:
            continue
        citations.append(
            RagCitation.model_construct(
                schema_version=item.get("schema_version", 2),
                chunk_id=chunk_id,
                document_id=item.get("document_id", ""),
                version=item.get("version", ""),
                page=item.get("page") or 1,
                source_path=item.get("source_path", ""),
                chunk_hash=item.get("chunk_hash", ""),
                score=item.get("score", 0.0),
            )
        )
    return citations


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
            "description": (
                "Exact short quote(s) copied verbatim from the selected clause text. "
                "Do not summarize. Do not quote headings, document titles, party names, "
                "or signature labels unless that exact text is the legal issue."
            ),
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
## Task
Find every clause in this contract that directly conflicts with the organization's prior \
policy versions or knowledge-base documents in the RAG Context.

A contradiction exists when:
- A prior policy explicitly permits X, but this contract restricts or prohibits X
- A prior policy requires X, but this contract omits or weakens that requirement
- This contract introduces a term that cannot coexist with an existing commitment

## Examples

EXAMPLE 1 — Direct conflict:
Prior policy (chunk_id: corp-policy-2023-04): "All vendor indemnification is capped at \
2× annual contract value."
Contract clause [C-14]: "Vendor shall indemnify Client for all losses without limitation."
→ Flag: C-14 removes the 2× cap from corp-policy-2023-04. Creates unlimited indemnification \
exposure that directly contradicts the standard policy ceiling.

EXAMPLE 2 — Weakened protection:
Prior policy (chunk_id: master-terms-v3): "Payment terms shall not exceed Net-30 without \
CFO approval."
Contract clause [C-22]: "Payment due within 90 days of invoice."
→ Flag: C-22 sets Net-90 without CFO approval, violating master-terms-v3's 30-day ceiling.

EXAMPLE 3 — Not a contradiction (do NOT flag):
Prior policy allows "standard commercial terms." Contract uses industry-standard language \
that achieves equivalent legal effect with different wording.
→ Skip: stylistic variation, no substantive conflict.

## Instructions
- Flag every plausible contradiction — err toward inclusion
- Cite the chunk_id from the RAG Context for EVERY finding (mandatory — skip if no citation exists)
- Do NOT flag internal contract issues (vague terms, missing protections) — that is Kira's job
- Set uncertainty=true when you cannot confirm the conflict with certainty
- Do NOT fabricate chunk_ids — only cite IDs present in the RAG Context above
- Return strict JSON only, no chain-of-thought"""

_HARVEY_REGRESSION_CHALLENGER = """\
## Task
Find clauses where this contract is materially worse than the organization's established \
standards — genuine downgrades that a senior lawyer would flag for negotiation.

A material regression is:
- A protection that existed in prior agreements or policy that is weakened or absent here
- A term that shifts risk or obligation to our organization beyond the established baseline
- A clause that removes a right or remedy available under the prior standard

This is NOT about stylistic changes or documented policy updates.

## Examples

EXAMPLE 1 — Material regression:
Prior standard (chunk_id: std-vendor-terms-2022): "Either party may terminate for \
convenience with 30 days notice."
Contract clause [C-8]: "Client may only terminate for cause."
→ Flag: C-8 removes the for-convenience termination right. Prior standard guaranteed this \
exit right — its removal locks us in without recourse.

EXAMPLE 2 — Regression in liability allocation:
Prior template (chunk_id: msa-template-v5): "Each party excludes consequential damages."
Contract clause [C-31]: "Client bears all consequential damages from vendor performance."
→ Flag: C-31 shifts all consequential damages to Client. The prior MSA template had mutual \
exclusions — this is a one-sided downgrade.

EXAMPLE 3 — Not a regression (do NOT flag):
Contract omits a provision that was optional in prior agreements. Both versions achieve \
equivalent protection through different mechanisms.
→ Skip: equivalent protection exists, no material downgrade.

## Instructions
- Only flag genuine downgrades — not every difference from prior policy
- Every finding must cite a RAG chunk_id showing the prior higher standard
- Analyze from the raw contract directly — do NOT depend on any other agent's output
- Set uncertainty=true if the regression is ambiguous
- Return strict JSON only, no chain-of-thought"""

_HARVEY_DOWNSTREAM_RISK = """\
## Task
Identify enforcement gaps, liability exposure, and exploitable loopholes in this \
contract's language — issues that may not surface until the contract is invoked in a \
dispute or audit.

A downstream risk is:
- Language a sophisticated counterparty could interpret against our interests
- A missing mechanism that leaves us without a remedy in a plausible dispute scenario
- An obligation that becomes unenforceable due to vague or conflicting definitions
- Language that could be used as evidence of policy waiver in litigation

## Examples

EXAMPLE 1 — Exploitable definition gap:
Contract clause [C-5]: "Vendor shall provide services at industry standard quality."
→ Flag: "Industry standard" is undefined and unanchored. In a dispute the vendor can argue \
any minimal effort qualifies. Worst case: no SLA breach is provable. Severity: HIGH. \
Cite RAG chunk showing prior contracts defined specific, measurable benchmarks.

EXAMPLE 2 — Waiver risk:
Prior policy (chunk_id: legal-ops-memo-2024): "Our standard allows 30 days breach notice."
Contract clause [C-19]: "Client shall provide written notice of any breach within 10 days."
→ Flag: C-19 cuts our breach response window to 10 days. If Client misses this deadline \
even once, the counterparty gains a waiver argument. The inconsistency with our 30-day \
standard creates litigation risk.

EXAMPLE 3 — Enforcement gap:
Contract clause [C-27]: "Disputes shall be resolved by mutual agreement."
→ Flag: No arbitration, mediation, or jurisdiction clause. If mutual agreement fails, \
there is no enforceable mechanism. Jurisdiction would be contested in any litigation.

## Instructions
- Assess what happens when this contract is actually invoked, not just whether it reads well
- Every finding must cite a RAG chunk_id showing the relevant prior policy or standard
- Focus on worst-case interpretations — sophisticated counterparty, adversarial reading
- Analyze from the raw contract directly — do NOT depend on any other agent's output
- Return strict JSON only, no chain-of-thought"""

_HARVEY_PEER_EVALUATOR = """\
## Task
Review the findings submitted by two other Harvey agents and vote on whether their \
analysis is ready to pass to the Admin reviewer.

## Agents you are reviewing
{peer_roles}

## Their findings
{peer_findings}

## What to check

1. GROUNDEDNESS — Is each finding supported by actual contract text (clause_uid) and RAG \
evidence (chunk_id)? If a finding cites a chunk_id or clause_uid that does not match the \
claim in its description, flag it.

2. MATERIALITY — Is each finding a real issue a senior lawyer would act on? Flag anything \
trivial, already resolved in the contract text, or based on a misreading.

3. COMPLETENESS — Based on the contract clauses and RAG context you have access to, did \
these agents miss any significant issue within their respective domains?

## How to vote

APPROVE if:
- Findings are grounded in evidence you can verify
- Issues are material and non-trivial
- Analysis is substantially complete (minor gaps are acceptable)

REJECT if:
- One or more findings cite evidence that does not support the claim
- Material issues within the agents' scope were missed
- A finding is based on a clear misreading of the contract

## Feedback format (required if rejecting)
Be specific. Name the finding_id and what exactly is wrong.
  WRONG: "Findings need improvement"
  RIGHT: "Finding F-3 cites chunk_id 'corp-policy-2023-04' but that chunk addresses \
payment terms, not indemnification — the citation does not support the claim."

Return strict JSON only, no chain-of-thought."""

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

RECOMMENDED_CHANGE FORMATTING RULES (mandatory):
- Begin your replacement text with the original section number and title verbatim
  (e.g. if the clause starts with "2. Indemnification", your recommended_change MUST start
  with "2. Indemnification").
- Preserve paragraph structure and line breaks where present in the original clause.
- Output ONLY the replacement clause text — do NOT prepend commentary, preambles, or
  explanations such as "I recommend...", "The revised clause reads:", etc.
- If the original clause is multi-paragraph, your replacement MUST keep the same number
  of paragraphs (or more, if you are splitting an ambiguous paragraph for clarity).
- Do NOT strip the section heading from your replacement.

CRITICAL RULES:
- You MUST cite at least one contract_evidence (clause_uid) per finding.
- You are STRICTLY FORBIDDEN from referencing RAG chunk_ids or any external corpus.
- Do NOT include chain-of-thought. Return strict JSON only.
- Set uncertainty=true when confidence is below 0.7.
- When writing recommended_change, keep the full contract structure in mind: you are
  editing one clause within a multi-section document. Your rewrite must remain coherent
  with the surrounding sections listed in the Contract Structure above."""

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

RECOMMENDED_CHANGE FORMATTING RULES (mandatory):
- Begin each replacement text with the original section number and title verbatim
  (e.g. if the clause starts with "2. Indemnification", your recommended_change MUST start
  with "2. Indemnification").
- Preserve paragraph structure and line breaks where present in the original clause.
- Output ONLY the replacement clause text — do NOT prepend commentary, preambles, or
  explanations such as "I recommend...", "The revised clause reads:", etc.
- If the original clause is multi-paragraph, your replacement MUST keep the same number
  of paragraphs (or more, if splitting an ambiguous paragraph for clarity).
- Do NOT strip the section heading from your replacement.

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
5. SECTION HEADING PRESERVATION — For EVERY finding, verify that the worker's
   recommended_change begins with the same section number and title as the original
   clause (e.g. "2. Indemnification\n\n..."). If a recommended_change omits or strips
   the section heading, you MUST REJECT the finding and state in your feedback:
   "Finding <finding_id>: recommended_change must begin with the original section number
   and title (e.g. '2. Indemnification')." Do not approve findings where the replacement
   text silently drops the section label.

Decide APPROVE if findings meet the bar. REJECT if they need changes.
If rejecting, your feedback must be specific and actionable. Name exactly what to change."""


# ---------------------------------------------------------------------------
# Prompt formatters
# ---------------------------------------------------------------------------


def _format_clauses(clause_index: list[dict]) -> str:
    parts: list[str] = []
    for c in clause_index:
        heading = c.get("section_heading") or ""
        # Prepend the section heading before normalized_text so the model sees it as
        # part of the clause. This ensures recommended_change rewrites include the heading.
        prefix = f"{heading}\n\n" if heading else ""
        parts.append(f"[{c['clause_uid']}] page={c['page']}\n{prefix}{c['normalized_text']}")
    return "\n\n".join(parts)


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


_KIRA_NEIGHBOR_WINDOW = 2  # clauses before and after the target to include as neighbors


def _build_kira_context(clause_index: list[dict], target_uid: str | None = None) -> str:
    """Build a contract-structure block for Kira's prompts.

    Always includes:
    - A numbered list of ALL section headings (so the model sees the full document shape).
    - When target_uid is given: the full text of the target clause plus the
      _KIRA_NEIGHBOR_WINDOW clauses immediately before and after it, so the model
      can see what surrounds the clause it is rewriting.

    This prevents the model from composing recommended_change in isolation and
    stripping section numbers/titles.
    """
    # --- Section structure (all headings) ---
    heading_lines: list[str] = []
    for i, c in enumerate(clause_index, start=1):
        heading = c.get("section_heading") or ""
        uid = c.get("clause_uid", f"clause_{i}")
        if heading:
            heading_lines.append(f"  {i}. [{uid}] {heading}")
        else:
            # Fall back to first line of text as a label so every clause is listed.
            first_line = (c.get("normalized_text") or "").split("\n")[0][:80]
            heading_lines.append(f"  {i}. [{uid}] {first_line}")

    structure_block = "Contract Structure (all sections):\n" + "\n".join(heading_lines)

    # --- Neighbor window around the target clause ---
    if target_uid is None:
        return structure_block

    uids = [c["clause_uid"] for c in clause_index]
    try:
        idx = uids.index(target_uid)
    except ValueError:
        return structure_block

    lo = max(0, idx - _KIRA_NEIGHBOR_WINDOW)
    hi = min(len(clause_index) - 1, idx + _KIRA_NEIGHBOR_WINDOW)
    window_parts: list[str] = []
    for j in range(lo, hi + 1):
        c = clause_index[j]
        label = "(TARGET CLAUSE)" if j == idx else ""
        heading = c.get("section_heading") or ""
        prefix = f"{heading}\n\n" if heading else ""
        window_parts.append(
            f"[{c['clause_uid']}] page={c['page']} {label}\n{prefix}{c['normalized_text']}"
        )
    neighbor_block = (
        f"Neighboring Clauses (window of {_KIRA_NEIGHBOR_WINDOW} before/after the target):\n\n"
        + "\n\n---\n\n".join(window_parts)
    )

    return f"{structure_block}\n\n{neighbor_block}"


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


def _fuzzy_match_clause(
    clause_uid: str | None,
    clauses_by_uid: dict[str, dict],
    clause_index: list[dict],
) -> tuple[str | None, dict | None]:
    """Try to find a clause even when the model returns an imprecise uid.

    Attempts (in order):
    1. Exact match (already tried by caller)
    2. Case-insensitive match
    3. Numeric extraction: "clause_3" / "clause_03" / "3" all resolve to the
       clause whose uid contains that number
    4. Falls back to None if nothing matches.
    """
    if not clause_uid:
        return None, None

    # Case-insensitive
    lower = clause_uid.lower()
    for uid, clause in clauses_by_uid.items():
        if uid.lower() == lower:
            return uid, clause

    # Extract trailing digits and match against clause uids containing the same number
    import re as _re
    digits = _re.sub(r"[^0-9]", "", clause_uid)
    if digits:
        target_num = int(digits)
        for uid, clause in clauses_by_uid.items():
            uid_digits = _re.sub(r"[^0-9]", "", uid)
            if uid_digits and int(uid_digits) == target_num:
                return uid, clause

    return None, None


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
            resolved_uid, clause = _fuzzy_match_clause(clause_uid, clauses_by_uid, clause_index)
            if clause:
                clause_uid = resolved_uid
                item["clause_uid"] = clause_uid
        if not clause:
            continue
        if require_contract_evidence and not item.get("contract_evidence"):
            # Small local models often omit contract_evidence but include clause_uid — use it.
            if clause_uid:
                item["contract_evidence"] = [clause_uid]
            else:
                continue
        if require_rag_citations and not item.get("rag_citations"):
            continue
        contract_evidence = _contract_evidence_from_raw(item.get("contract_evidence", []), clause)
        if require_contract_evidence and not contract_evidence:
            continue
        rag_citations = _rag_citations_from_raw(item.get("rag_citations", []))
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
                contract_evidence=contract_evidence,
                rag_citations=rag_citations,
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
    """Harvey branch reviewer — parallel independent analysis + peer cross-evaluation.

    All 3 instances run independently on the raw contract (no prior-stage input).
    After analysis, each evaluates the other two's findings and votes approve/reject.
    2-of-3 approvals → findings pass to admin; else all 3 retry from scratch.

    Fine-tuning: CUAD dataset (clause annotation, conflict detection), priority 2.
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

    def _role_prompt(self) -> str:
        return {
            "contradiction_finder": _HARVEY_CONTRADICTION_FINDER,
            "regression_challenger": _HARVEY_REGRESSION_CHALLENGER,
            "downstream_risk": _HARVEY_DOWNSTREAM_RISK,
        }[self._role]

    async def analyze(
        self,
        clause_index: list[dict],
        policy_context: dict,
        rag_chunks: list[dict] | None = None,
        round_number: int = 1,
    ) -> BranchReviewOutput:
        """Independent analysis — each Harvey analyzes the raw contract without prior-stage input."""
        prompt = (
            f"{self._role_prompt()}\n\n"
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
            reviewer_index=self._reviewer_index,
            agent_role=self.agent_role,
            clause_index=clause_index,
            round_number=round_number,
            require_rag_citations=True,
            require_contract_evidence=True,
            finding_scope="cross_contract",
        )

    async def evaluate_peers(
        self,
        peer_findings: list[Finding],
        clause_index: list[dict],
        policy_context: dict,
        rag_chunks: list[dict] | None = None,
        peer_roles: list[str] | None = None,
    ) -> KiraReviewerDecision:
        """Cross-evaluation: review the other two Harveys' findings and vote approve/reject."""
        roles_block = (
            "\n".join(f"- {r}" for r in (peer_roles or ["unknown", "unknown"]))
        )
        findings_block = _format_findings_for_stage(peer_findings)
        prompt = (
            _HARVEY_PEER_EVALUATOR.format(
                peer_roles=roles_block,
                peer_findings=findings_block,
            ) + "\n\n"
            "## Policy Context\n"
            f"{_format_policy_context(policy_context)}\n\n"
            "## RAG Context\n"
            f"{_format_rag_context(rag_chunks or [])}\n\n"
            "## Contract Clauses\n"
            f"{_format_clauses(clause_index)}\n\n"
            "Return ONLY a JSON object matching the schema."
        )
        raw = await self._provider.generate_structured_output(prompt, KIRA_PANEL_DECISION_SCHEMA)
        decision_str = str(raw.get("decision", "reject")).lower().strip()
        decision: Literal["approve", "reject"] = "approve" if decision_str == "approve" else "reject"
        return KiraReviewerDecision(
            reviewer_index=self._reviewer_index,
            decision=decision,
            feedback=raw.get("feedback"),
            finding_concerns=raw.get("finding_concerns", []),
        )

    # ------------------------------------------------------------------
    # Legacy sequential methods — kept for backward compatibility only.
    # The new pipeline calls analyze() + evaluate_peers() instead.
    # ------------------------------------------------------------------

    async def review(
        self,
        clause_index: list[dict],
        policy_context: dict,
        rag_chunks: list[dict] | None = None,
    ) -> BranchReviewOutput:
        return await self.analyze(clause_index, policy_context, rag_chunks)

    async def challenge(
        self,
        prior_findings: list[Finding],
        clause_index: list[dict],
        policy_context: dict,
        rag_chunks: list[dict] | None = None,
    ) -> list[Finding]:
        out = await self.analyze(clause_index, policy_context, rag_chunks)
        return out.findings

    async def assess_risk(
        self,
        prior_findings: list[Finding],
        clause_index: list[dict],
        policy_context: dict,
        rag_chunks: list[dict] | None = None,
    ) -> list[Finding]:
        out = await self.analyze(clause_index, policy_context, rag_chunks)
        return out.findings


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
        contract_context = _build_kira_context(clause_index)
        prompt = (
            f"{_KIRA_WORKER_INITIAL}\n\n"
            "## Contract Structure\n"
            f"{contract_context}\n\n"
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
        contract_context = _build_kira_context(clause_index)
        prompt = (
            _KIRA_WORKER_REVISION.format(
                feedback=aggregated_feedback,
                current_findings=_format_findings_for_panel(current_findings),
            ) + "\n\n"
            "## Contract Structure\n"
            f"{contract_context}\n\n"
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


class KiraPanelReviewer(FineTunableAgent):
    """Reviews KiraWorker output. Votes approve/reject with specific feedback.

    Fine-tuned on the same LEDGAR checkpoint as KiraWorker — all four Kira agents
    (worker + 3 panel reviewers) share one LoRA adapter served by verdict-vllm-kira.
    Each agent has its own distinct system prompt, making them functionally distinct
    despite sharing weights.
    """

    fine_tune_dataset = "LEDGAR"
    fine_tune_priority = 1
    fine_tune_checkpoint: str | None = None

    temperature: float = DEFAULT_REVIEWER_TEMPERATURE

    def __init__(self, provider: StructuredLLMProvider, reviewer_index: int) -> None:
        if reviewer_index not in (1, 2, 3):
            raise ValueError("reviewer_index must be 1, 2, or 3")
        self._provider = provider
        self._reviewer_index = reviewer_index

    @property
    def agent_role(self) -> str:
        return f"kira_panel_reviewer_{self._reviewer_index}"

    async def review(
        self,
        worker_findings: list[Finding],
        clause_index: list[dict] | None = None,
    ) -> KiraReviewerDecision:
        findings_block = _format_findings_for_panel(worker_findings)
        context_block = _build_kira_context(clause_index or []) if clause_index else ""
        context_section = (
            f"## Contract Structure\n{context_block}\n\n" if context_block else ""
        )
        prompt = (
            f"{_KIRA_PANEL_REVIEWER}\n\n"
            f"{context_section}"
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

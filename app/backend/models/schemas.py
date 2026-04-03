"""
Verdict — Pydantic schema definitions.
Implements the `run-state-contract` shared dependency.
Schema version: 1
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Schema version sentinel — bump when fields are added/removed so persisted
# records remain interpretable after model evolution.
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Enums / Literals
# ---------------------------------------------------------------------------

BranchName = Literal["harvey", "kira"]

IssueType = Literal[
    "liability_exposure",
    "open_clause",
    "ambiguity",
    "exploitability",
    "weakened_protection",
    "compliance_failure",
]

RecommendationType = Literal[
    "negotiate",
    "reject",
    "accept_with_note",
    "seek_legal_advice",
]

ExploitabilityLevel = Literal["low", "medium", "high", "critical"]

BusinessImpactLevel = Literal["low", "medium", "high", "critical"]

ConsensusStatus = Literal["consensus", "disputed", "unresolved_by_consensus"]

HumanAction = Literal["approved", "edited", "rejected"]

StageState = Literal["pending", "running", "done", "failed", "blocked", "retrying"]

RunState = Literal[
    "created",
    "processing",
    "awaiting_human_review",
    "finalized",
    "rejected",
    "blocked",
    "failed",
]

EventType = Literal[
    "run_created",
    "stage_started",
    "stage_completed",
    "stage_failed",
    "stage_retrying",
    "consensus_unresolved",
    "awaiting_human_review",
    "human_edited",
    "human_rejected",
    "human_approved",
    "run_finalized",
]

SeverityLevel = Literal["low", "medium", "high", "critical"]

# ---------------------------------------------------------------------------
# Document parsing — docling-canonical-parser
# ---------------------------------------------------------------------------


class EvidenceRef(BaseModel):
    """Canonical clause anchor produced by the Docling parser."""

    schema_version: int = SCHEMA_VERSION
    document_hash: str = Field(..., description="SHA-256 of the raw PDF bytes.")
    parser_version: str = Field(..., description="Docling version string.")
    clause_uid: str = Field(..., description="Stable unique identifier for this clause within the document.")
    page: int = Field(..., ge=1, description="1-indexed page number.")
    bbox: list[float] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="Bounding box [x0, y0, x1, y1] in PDF points.",
    )
    normalized_text: str = Field(..., description="Whitespace-normalised clause text.")
    extraction_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Parser extraction confidence (1.0 = native text, lower = OCR)."
    )


class ParsedClause(BaseModel):
    """One clause entry from build_clause_index()."""

    schema_version: int = SCHEMA_VERSION
    clause_uid: str
    page: int = Field(..., ge=1)
    bbox: list[float] = Field(..., min_length=4, max_length=4)
    normalized_text: str
    extraction_confidence: float = Field(..., ge=0.0, le=1.0)
    section_heading: Optional[str] = None


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


class Finding(BaseModel):
    """A single clause-level finding produced by any reviewer or admin agent."""

    schema_version: int = SCHEMA_VERSION
    finding_id: str = Field(..., description="Unique finding identifier (UUID).")
    clause_uid: str = Field(..., description="References ParsedClause / EvidenceRef.clause_uid.")
    issue_type: IssueType
    severity: SeverityLevel
    exploitability: ExploitabilityLevel
    business_impact: BusinessImpactLevel
    description: str = Field(..., description="Human-readable description of the issue.")
    recommendation: RecommendationType
    recommendation_detail: str = Field(..., description="Specific recommended action.")
    evidence: list[EvidenceRef]
    # Provenance
    branch: BranchName
    agent_role: str = Field(..., description="E.g. 'harvey_reviewer_1', 'kira_validator', 'admin_merge'.")
    round_number: int = Field(..., ge=1, description="Final-review round this finding originated from.")
    # Consensus tracking
    consensus_status: Optional[ConsensusStatus] = None
    unresolved_by_consensus: bool = False
    # Human edit overlay (populated post human-review)
    human_edited: bool = False
    human_edit_delta: Optional[str] = None


# ---------------------------------------------------------------------------
# Agent branch outputs
# ---------------------------------------------------------------------------


class BranchReviewOutput(BaseModel):
    """Output from one Harvey or Kira reviewer instance."""

    schema_version: int = SCHEMA_VERSION
    branch: BranchName
    reviewer_index: Annotated[int, Field(ge=1, le=3)]
    findings: list[Finding]
    raw_response_id: Optional[str] = Field(
        None, description="Provider-level response ID for audit."
    )


class ReviewerVote(BaseModel):
    schema_version: int = SCHEMA_VERSION
    reviewer_index: Annotated[int, Field(ge=1, le=3)]
    supported_reviewer_indexes: list[Annotated[int, Field(ge=1, le=3)]] = Field(default_factory=list)
    accepted_finding_keys: list[str] = Field(default_factory=list)
    correctness_score: float = Field(..., ge=0.0, le=1.0)
    rationale: Optional[str] = None


class ReviewBlockResult(BaseModel):
    schema_version: int = SCHEMA_VERSION
    branch: str
    round_number: int = Field(..., ge=1)
    rerun_required: bool = False
    escalated: bool = False
    accepted_reviewer_indexes: list[int] = Field(default_factory=list)
    aggregated_findings: list[Finding] = Field(default_factory=list)
    reviewer_outputs: list[BranchReviewOutput] = Field(default_factory=list)
    reviewer_votes: list[ReviewerVote] = Field(default_factory=list)
    aggregate_summary: Optional[str] = None


class ValidatorOutput(BaseModel):
    """Output from HarveyValidatorAgent or KiraValidatorAgent."""

    schema_version: int = SCHEMA_VERSION
    branch: BranchName
    validated_findings: list[Finding]
    hallucinated_clause_uids: list[str] = Field(
        default_factory=list,
        description="clause_uids the validator determined were hallucinated.",
    )
    inapplicable_regime_flags: list[str] = Field(
        default_factory=list,
        description="Kira only: regime references flagged as inapplicable.",
    )
    notes: Optional[str] = None


class AdminMergeOutput(BaseModel):
    """Merged finding set produced by AdminMergeAgent."""

    schema_version: int = SCHEMA_VERSION
    merged_findings: list[Finding]
    deduplication_log: list[dict] = Field(
        default_factory=list,
        description="Records of duplicate finding groups that were merged.",
    )


class AgreementDecision(BaseModel):
    """Output from AgreementCheckAgent after a final-review round."""

    schema_version: int = SCHEMA_VERSION
    round_number: int = Field(..., ge=1)
    consensus_findings: list[Finding]
    disputed_finding_ids: list[str] = Field(
        default_factory=list, description="finding_ids where reviewers disagreed."
    )
    all_consensus: bool


# ---------------------------------------------------------------------------
# Final verdict
# ---------------------------------------------------------------------------


class FinalVerdict(BaseModel):
    """Emitted by finalize_run_if_approved(). The authoritative output of a run."""

    schema_version: int = SCHEMA_VERSION
    run_id: str
    finalized_at: datetime
    overall_risk_level: SeverityLevel
    findings: list[Finding]
    summary: str
    recommendations: list[str]
    human_action: HumanAction
    human_reviewer_id: Optional[str] = None
    unresolved_finding_count: int = 0


# ---------------------------------------------------------------------------
# Run and stage state
# ---------------------------------------------------------------------------


class StageLease(BaseModel):
    """Lease issued when a worker claims a stage."""

    schema_version: int = SCHEMA_VERSION
    lease_token: str
    expires_at: datetime
    worker_id: str


class StageStatus(BaseModel):
    """Current state of one stage execution."""

    schema_version: int = SCHEMA_VERSION
    stage_name: str
    state: StageState
    retry_count: int = 0
    max_retries: int = 3
    lease: Optional[StageLease] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_detail: Optional[str] = None


class RunStatus(BaseModel):
    """Top-level run state summary."""

    schema_version: int = SCHEMA_VERSION
    run_id: str
    state: RunState
    stages: list[StageStatus]
    current_stage_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    blocked_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# API request / response shapes
# ---------------------------------------------------------------------------


class RunCreateResponse(BaseModel):
    """Returned by POST /runs when a new run is created."""

    schema_version: int = SCHEMA_VERSION
    run_id: str
    state: RunState
    created_at: datetime


class RunSummary(BaseModel):
    """Lightweight run record for list views."""

    schema_version: int = SCHEMA_VERSION
    run_id: str
    state: RunState
    filename: str
    tenant_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    overall_risk_level: Optional[SeverityLevel] = None


class RunDetail(BaseModel):
    """Full run detail returned by GET /runs/{run_id}."""

    schema_version: int = SCHEMA_VERSION
    run_id: str
    state: RunState
    stages: list[StageStatus]
    filename: str
    tenant_id: Optional[str] = None
    policy_family_id: Optional[str] = None
    policy_version_number: Optional[int] = None
    jurisdiction: Optional[str] = None
    regime: Optional[str] = None
    effective_date: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    verdict: Optional[FinalVerdict] = None
    blocked_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# SSE event stream — sse-run-events
# ---------------------------------------------------------------------------


class RunEvent(BaseModel):
    """One persisted run event, served via SSE."""

    schema_version: int = SCHEMA_VERSION
    event_id: str
    run_id: str
    event_type: EventType
    payload: dict
    emitted_at: datetime
    sequence: int = Field(..., ge=0, description="Monotonically increasing sequence number within a run.")


# ---------------------------------------------------------------------------
# Human review gate — human-review-gate
# ---------------------------------------------------------------------------


class HumanReviewAction(BaseModel):
    """A single reviewer action on one finding during human review."""

    schema_version: int = SCHEMA_VERSION
    finding_id: str
    action: HumanAction
    edit_delta: Optional[str] = Field(
        None, description="JSON patch or free-text delta when action is 'edited'."
    )
    reviewer_id: str
    reviewed_at: datetime


class HumanReviewPayload(BaseModel):
    """Request body for POST /runs/{run_id}/review."""

    schema_version: int = SCHEMA_VERSION
    run_action: HumanAction
    reviewer_id: str
    finding_actions: list[HumanReviewAction] = Field(
        default_factory=list,
        description="Per-finding edits. Required when run_action is 'edited'.",
    )
    rejection_reason: Optional[str] = Field(
        None, description="Required when run_action is 'rejected'."
    )


class HumanReviewResult(BaseModel):
    """Response body from POST /runs/{run_id}/review."""

    schema_version: int = SCHEMA_VERSION
    run_id: str
    run_action: HumanAction
    state: RunState
    verdict: Optional[FinalVerdict] = None


# ---------------------------------------------------------------------------
# Legacy prototype models — kept temporarily for backwards compat during
# migration of existing routes. Remove once routes/contracts.py is updated.
# ---------------------------------------------------------------------------


class ClauseFlag(BaseModel):
    clause: str
    issue: str
    severity: Literal["low", "medium", "high"]


class ReviewResult(BaseModel):
    clause_flags: list[ClauseFlag]
    risk_level: Literal["low", "medium", "high"]
    summary: str
    recommendations: list[str]


class PipelineStage(BaseModel):
    name: str
    status: Literal["pending", "running", "done"]


class PipelineStatus(BaseModel):
    stages: list[PipelineStage]
    current_stage: int


class UploadResponse(BaseModel):
    success: bool
    pipeline: PipelineStatus
    result: ReviewResult | None = None
    error: str | None = None

"""
Verdict — Pydantic schema definitions.
Implements the `run-state-contract` and `evidence-schema` shared dependencies.
Schema version: 2
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Schema version sentinel — bump when fields are added/removed so persisted
# records remain interpretable after model evolution.
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 2

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
    "under_review",
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

HarveyReviewerRole = Literal["issue_discovery", "false_positive_challenge", "exploitability_impact"]
KiraReviewerRole = Literal["issue_discovery", "false_positive_challenge", "exploitability_impact"]

RagDocType = Literal["policy", "reference_contract", "playbook"]

IngestionJobState = Literal["pending", "running", "done", "failed"]

ModelType = Literal["fine_tuned", "baseline"]

ModelStatus = Literal["available", "pending"]

SearchStrategy = Literal["vector", "text", "hybrid"]

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
# Evidence — evidence-schema
# ---------------------------------------------------------------------------


class ContractEvidence(BaseModel):
    """A grounded anchor into the reviewed contract.
    Required on all Kira findings (≥1); optional on Harvey."""

    schema_version: int = SCHEMA_VERSION
    clause_id: str = Field(..., description="References ParsedClause.clause_uid.")
    page: int = Field(..., ge=1, description="1-indexed page number.")
    span: Optional[tuple[int, int]] = Field(
        None, description="Character offsets [start, end] within normalized_text."
    )
    text: str = Field(..., description="Verbatim excerpt supporting this finding.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Parser extraction confidence for this span.")


class RagCitation(BaseModel):
    """A grounded reference into the pgvector RAG corpus.
    Required on all Harvey contradiction findings (≥1); Kira is blocked from RAG."""

    schema_version: int = SCHEMA_VERSION
    chunk_id: str = Field(..., description="Primary key in the chunks table.")
    document_id: str = Field(..., description="Parent source_document identifier.")
    version: str = Field(..., description="Document version label.")
    page: int = Field(..., ge=1, description="1-indexed page where this chunk originated.")
    source_path: str = Field(..., description="Storage path of the source document.")
    chunk_hash: str = Field(..., description="SHA-256 of the chunk text for deduplication.")
    score: float = Field(..., ge=0.0, le=1.0, description="Retrieval relevance score.")


class RetrievalTraceItem(BaseModel):
    """Persisted record of one retrieval call during a run stage."""

    schema_version: int = SCHEMA_VERSION
    run_id: str
    clause_id: str = Field(..., description="The clause that triggered this retrieval.")
    query_text: str
    strategy: SearchStrategy
    citations: list[RagCitation] = Field(default_factory=list)
    retrieved_at: datetime


# ---------------------------------------------------------------------------
# Findings — evidence-schema
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

    # evidence-schema: Harvey requires ≥1 rag_citation; Kira requires ≥1 contract_evidence
    contract_evidence: list[ContractEvidence] = Field(
        default_factory=list,
        description="Contract-grounded evidence anchors. Required (≥1) for Kira findings.",
    )
    rag_citations: list[RagCitation] = Field(
        default_factory=list,
        description="RAG corpus citations. Required (≥1) for Harvey contradiction findings.",
    )

    # Provenance
    branch: BranchName
    agent_role: str = Field(..., description="E.g. 'harvey_issue_discovery', 'kira_false_positive_challenge'.")
    round_number: int = Field(..., ge=1, description="Final-review round this finding originated from.")

    # Consensus tracking
    consensus_state: Optional[ConsensusStatus] = None
    unresolved_by_consensus: bool = False

    # Human edit overlay (populated post human-review)
    human_edited: bool = False
    human_edit_delta: Optional[str] = None

    # Legacy — kept for backwards compat; remove once all routes migrated
    evidence: Optional[list[EvidenceRef]] = Field(
        None,
        description="Legacy EvidenceRef list.",
        json_schema_extra={"legacy": True},
    )
    consensus_status: Optional[ConsensusStatus] = Field(
        None,
        description="Legacy alias for consensus_state.",
        json_schema_extra={"legacy": True},
    )


# ---------------------------------------------------------------------------
# Legacy Harvey trio agent outputs — retained for old runs/offline experiments
# ---------------------------------------------------------------------------


class HarveyReviewerOutput(BaseModel):
    """Legacy output from one of the three Harvey reviewer roles."""

    schema_version: int = SCHEMA_VERSION
    role: HarveyReviewerRole
    findings: list[Finding]
    raw_response_id: Optional[str] = Field(
        None, description="Provider-level response ID for audit."
    )


class HarveyTrioConsensus(BaseModel):
    """Legacy aggregated consensus across all three Harvey reviewer outputs."""

    schema_version: int = SCHEMA_VERSION
    reviewer_outputs: list[HarveyReviewerOutput] = Field(
        ..., min_length=3, max_length=3
    )
    consensus_findings: list[Finding] = Field(default_factory=list)
    unresolved_finding_ids: list[str] = Field(default_factory=list)
    consensus_state: ConsensusStatus
    round_number: int = Field(..., ge=1)


# ---------------------------------------------------------------------------
# Kira trio agent outputs — harvey-trio-contract (same structure)
# ---------------------------------------------------------------------------


class KiraReviewerOutput(BaseModel):
    """Output from one of the three Kira reviewer roles."""

    schema_version: int = SCHEMA_VERSION
    role: KiraReviewerRole
    findings: list[Finding]
    raw_response_id: Optional[str] = Field(
        None, description="Provider-level response ID for audit."
    )


class KiraTrioConsensus(BaseModel):
    """Aggregated consensus across all three Kira reviewer outputs."""

    schema_version: int = SCHEMA_VERSION
    reviewer_outputs: list[KiraReviewerOutput] = Field(
        ..., min_length=3, max_length=3
    )
    consensus_findings: list[Finding] = Field(default_factory=list)
    unresolved_finding_ids: list[str] = Field(default_factory=list)
    consensus_state: ConsensusStatus
    round_number: int = Field(..., ge=1)


# ---------------------------------------------------------------------------
# Admin merge output — harvey-trio-contract (merge-only, no admin reviewers)
# ---------------------------------------------------------------------------


class AdminConsensusOutput(BaseModel):
    """Merged finding set produced by AdminMergeAgent (merge-only, no reviewer role)."""

    schema_version: int = SCHEMA_VERSION
    merged_findings: list[Finding]
    harvey_unresolved_ids: list[str] = Field(default_factory=list)
    kira_unresolved_ids: list[str] = Field(default_factory=list)
    deduplication_log: list[dict] = Field(
        default_factory=list,
        description="Records of duplicate finding groups that were merged.",
    )


# ---------------------------------------------------------------------------
# Agent branch outputs (existing — kept for worker compatibility)
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
    """Merged finding set produced by AdminMergeAgent (legacy shape)."""

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

    # Branch-grouped findings
    harvey_findings: list[Finding] = Field(default_factory=list)
    kira_findings: list[Finding] = Field(default_factory=list)
    consensus_state: Optional[ConsensusStatus] = None
    unresolved_by_consensus: list[str] = Field(
        default_factory=list, description="finding_ids unresolved by consensus."
    )

    summary: str
    recommendations: list[str]
    human_action: HumanAction
    human_reviewer_id: Optional[str] = None
    unresolved_finding_count: int = 0

    # Legacy — flat findings list; kept for backwards compat
    findings: Optional[list[Finding]] = Field(
        None,
        description="Legacy flat findings list.",
        json_schema_extra={"legacy": True},
    )


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
# RAG document management — rag-storage-contract
# ---------------------------------------------------------------------------


class RagDocumentCreate(BaseModel):
    """Request body for uploading a new RAG source document."""

    doc_type: RagDocType
    policy_family_id: Optional[str] = None
    jurisdiction: Optional[str] = None
    version_label: Optional[str] = None


class RagDocumentResponse(BaseModel):
    """Response shape for a RAG source document record."""

    schema_version: int = SCHEMA_VERSION
    document_id: str
    doc_type: RagDocType
    source_path: str
    version: str
    tenant_id: str
    workspace_id: Optional[str] = None
    active: bool
    chunk_count: int = 0
    created_at: datetime
    file_hash: Optional[str] = None


class RagIngestionStatus(BaseModel):
    """Status of a background ingestion job."""

    schema_version: int = SCHEMA_VERSION
    job_id: str
    document_id: Optional[str] = None
    state: IngestionJobState
    chunks_processed: int = 0
    total_chunks: Optional[int] = None
    error_detail: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Model registry — model-registry-contract
# ---------------------------------------------------------------------------


class ModelRegistryEntry(BaseModel):
    """One model entry from configs/models.yaml."""

    schema_version: int = SCHEMA_VERSION
    model_id: str = Field(..., description="Unique identifier for this model.")
    display_name: str
    model_type: ModelType
    endpoint: Optional[str] = Field(
        None, description="Inference endpoint URL. 'N/A - weights pending' when unavailable."
    )
    weights_path: Optional[str] = None
    enabled: bool = True
    status: ModelStatus = "available"
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# Evaluation metrics — eval scripts
# ---------------------------------------------------------------------------


class EvalMetricRow(BaseModel):
    """One row in an evaluation results table."""

    schema_version: int = SCHEMA_VERSION
    model_id: str
    metric_name: str
    value: float
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    n_samples: int = 0
    dataset_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Legacy prototype models — kept for backwards compat during route migration.
# Remove once routes/contracts.py is fully updated.
# ---------------------------------------------------------------------------


class ClauseFlag(BaseModel):
    clause: str
    issue: str
    severity: Literal["low", "medium", "high"]


class ReviewResult(BaseModel):
    """Structured review result with branch grouping and consensus tracking."""

    schema_version: int = SCHEMA_VERSION
    run_id: Optional[str] = None

    # Branch-grouped findings
    harvey_findings: list[Finding] = Field(default_factory=list)
    kira_findings: list[Finding] = Field(default_factory=list)
    consensus_state: Optional[ConsensusStatus] = None
    unresolved_by_consensus: list[str] = Field(
        default_factory=list, description="finding_ids unresolved by consensus."
    )

    overall_risk_level: Optional[SeverityLevel] = None
    summary: str = ""
    recommendations: list[str] = Field(default_factory=list)

    # Human review fields
    human_action: Optional[HumanAction] = None
    human_reviewer_id: Optional[str] = None

    # Legacy flat fields — kept for route backwards compat
    clause_flags: Optional[list[ClauseFlag]] = Field(
        None,
        description="Legacy clause flags.",
        json_schema_extra={"legacy": True},
    )
    risk_level: Optional[Literal["low", "medium", "high"]] = Field(
        None,
        description="Legacy risk level string.",
        json_schema_extra={"legacy": True},
    )


class PipelineStage(BaseModel):
    name: str
    status: Literal["pending", "running", "done", "failed", "blocked", "retrying"]


class PipelineStatus(BaseModel):
    stages: list[PipelineStage]
    current_stage: int


class UploadResponse(BaseModel):
    success: bool
    pipeline: PipelineStatus
    result: ReviewResult | None = None
    error: str | None = None

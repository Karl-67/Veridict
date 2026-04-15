"""
ORM models backing:
  - run-state-contract       (RunRecord, StageExecutionRecord, FindingRecord,
                               EvidenceRecord, RunEventRecord)
  - postgres-stage-queue     (lease / retry fields on StageExecutionRecord)
  - docling-canonical-parser (ParsedClauseRecord with bbox, confidence, uid)
  - policy-lineage-and-corpora (PolicyVersionRecord, ComplianceCorpusRecord)
  - human-review-gate        (HumanReviewRecord with per-finding edit provenance)
"""

from __future__ import annotations

import uuid
from datetime import datetime, date

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, relationship


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# RunRecord
# Represents a single contract-review run from upload through final verdict.
# ---------------------------------------------------------------------------


class RunRecord(Base):
    __tablename__ = "runs"

    id: str = Column(String(36), primary_key=True, default=_uuid)

    # Upload metadata
    tenant_id: str = Column(String(255), nullable=False, index=True)
    original_filename: str = Column(String(512), nullable=False)
    storage_path: str = Column(String(1024), nullable=False)
    file_hash: str = Column(String(64), nullable=False)  # SHA-256 hex

    # Lineage / scope metadata (Harvey policy + Kira corpora keys)
    policy_family_id: str = Column(String(255), nullable=True)
    policy_version_number: int = Column(Integer, nullable=True)
    jurisdiction: str = Column(String(128), nullable=True)
    regime: str = Column(String(128), nullable=True)
    effective_date: date = Column(Date, nullable=True)

    # Run lifecycle
    status: str = Column(
        String(32),
        nullable=False,
        default="pending",
        # pending | running | awaiting_human_review | blocked | finalized | failed
    )
    blocked_reason: str = Column(Text, nullable=True)
    current_round: int = Column(Integer, nullable=False, default=1)

    # Final verdict payload (populated by AdminMergeAgent after approval)
    verdict_payload: dict = Column(JSON, nullable=True)

    created_at: datetime = Column(DateTime, nullable=False, default=_now)
    updated_at: datetime = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    # Relationships
    stage_executions = relationship(
        "StageExecutionRecord", back_populates="run", cascade="all, delete-orphan"
    )
    findings = relationship(
        "FindingRecord", back_populates="run", cascade="all, delete-orphan"
    )
    parsed_clauses = relationship(
        "ParsedClauseRecord", back_populates="run", cascade="all, delete-orphan"
    )
    events = relationship(
        "RunEventRecord", back_populates="run", cascade="all, delete-orphan"
    )
    human_reviews = relationship(
        "HumanReviewRecord", back_populates="run", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# StageExecutionRecord
# One row per stage attempt.  Implements the postgres-stage-queue lease
# protocol: a worker atomically sets lease_expires_at and worker_id when
# claiming a stage; after completion it sets finished_at.
# ---------------------------------------------------------------------------


class StageExecutionRecord(Base):
    __tablename__ = "stage_executions"

    id: str = Column(String(36), primary_key=True, default=_uuid)
    run_id: str = Column(
        String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    stage_name: str = Column(
        String(64),
        nullable=False,
        # create_run | ingest_pdf | parse_ocr_normalize | clause_index
        # | harvey_context_load | kira_context_load
        # | harvey_review_block | kira_review_block | admin_merge
        # | final_review_block | awaiting_human_review | finalized
    )
    stage_order: int = Column(Integer, nullable=False, default=0)
    round_number: int = Column(Integer, nullable=False, default=1)
    attempt_number: int = Column(Integer, nullable=False, default=1)

    # Postgres-stage-queue lease fields
    status: str = Column(
        String(32),
        nullable=False,
        default="pending",
        # pending | claimed | running | completed | failed | retrying
    )
    worker_id: str = Column(String(255), nullable=True)
    lease_expires_at: datetime = Column(DateTime, nullable=True)
    retry_count: int = Column(Integer, nullable=False, default=0)
    max_retries: int = Column(Integer, nullable=False, default=3)

    # Execution detail
    started_at: datetime = Column(DateTime, nullable=True)
    finished_at: datetime = Column(DateTime, nullable=True)
    failure_reason: str = Column(Text, nullable=True)

    # Raw LLM provider response captured for audit / replay
    raw_provider_response: dict = Column(JSON, nullable=True)
    # Structured output extracted from the raw response
    structured_output: dict = Column(JSON, nullable=True)

    created_at: datetime = Column(DateTime, nullable=False, default=_now)
    updated_at: datetime = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    # Relationships
    run = relationship("RunRecord", back_populates="stage_executions")
    findings = relationship(
        "FindingRecord",
        back_populates="stage_execution",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id", "stage_name", "round_number", "attempt_number",
            name="uq_stage_execution_idempotency",
        ),
    )


# ---------------------------------------------------------------------------
# FindingRecord
# A single flagged clause or compliance issue produced by any agent stage.
# ---------------------------------------------------------------------------


class FindingRecord(Base):
    __tablename__ = "findings"

    id: str = Column(String(36), primary_key=True, default=_uuid)
    run_id: str = Column(
        String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_execution_id: str = Column(
        String(36),
        ForeignKey("stage_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Source references
    source_agent: str = Column(String(64), nullable=False)
    source_rule_id: str = Column(String(255), nullable=True)   # Kira corpus rule ID
    prior_version_ref: str = Column(String(255), nullable=True)  # Harvey prior-version key
    round_number: int = Column(Integer, nullable=False, default=1)

    # Finding content
    clause_uid: str = Column(String(128), nullable=True, index=True)
    clause_text: str = Column(Text, nullable=True)
    issue: str = Column(Text, nullable=False)
    severity: str = Column(String(16), nullable=False)  # low | medium | high
    recommendation: str = Column(Text, nullable=True)

    # Consensus / dispute state
    is_disputed: bool = Column(Boolean, nullable=False, default=False)
    dispute_reason: str = Column(Text, nullable=True)
    is_confirmed: bool = Column(Boolean, nullable=False, default=False)

    created_at: datetime = Column(DateTime, nullable=False, default=_now)
    updated_at: datetime = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    # Relationships
    run = relationship("RunRecord", back_populates="findings")
    stage_execution = relationship("StageExecutionRecord", back_populates="findings")
    evidence = relationship(
        "EvidenceRecord", back_populates="finding", cascade="all, delete-orphan"
    )
    human_reviews = relationship("HumanReviewRecord", back_populates="finding")


# ---------------------------------------------------------------------------
# EvidenceRecord
# Anchors a finding to exact locations in the parsed document.
# ---------------------------------------------------------------------------


class EvidenceRecord(Base):
    __tablename__ = "evidence"

    id: str = Column(String(36), primary_key=True, default=_uuid)
    finding_id: str = Column(
        String(36),
        ForeignKey("findings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Document anchor (mirrors ParsedClauseRecord bbox/page fields)
    clause_uid: str = Column(String(128), nullable=False)
    page_number: int = Column(Integer, nullable=True)
    bbox_x0: float = Column(Float, nullable=True)
    bbox_y0: float = Column(Float, nullable=True)
    bbox_x1: float = Column(Float, nullable=True)
    bbox_y1: float = Column(Float, nullable=True)

    # Verbatim excerpt supporting the finding
    excerpt: str = Column(Text, nullable=False)
    extraction_confidence: float = Column(Float, nullable=True)  # 0.0–1.0

    created_at: datetime = Column(DateTime, nullable=False, default=_now)

    # Relationships
    finding = relationship("FindingRecord", back_populates="evidence")


# ---------------------------------------------------------------------------
# ParsedClauseRecord
# Stores the canonical Docling output for each extracted clause.
# Keyed by (run_id, clause_uid) for stable referencing across re-parses.
# ---------------------------------------------------------------------------


class ParsedClauseRecord(Base):
    __tablename__ = "parsed_clauses"

    id: str = Column(String(36), primary_key=True, default=_uuid)
    run_id: str = Column(
        String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # docling-canonical-parser stability fields
    clause_uid: str = Column(String(128), nullable=False)  # deterministic hash of position
    document_hash: str = Column(String(64), nullable=False)  # SHA-256 of source PDF bytes
    parser_version: str = Column(String(32), nullable=False)  # e.g. "docling-2.1.0"

    # Location
    page_number: int = Column(Integer, nullable=False)
    bbox_x0: float = Column(Float, nullable=True)
    bbox_y0: float = Column(Float, nullable=True)
    bbox_x1: float = Column(Float, nullable=True)
    bbox_y1: float = Column(Float, nullable=True)

    # Content
    normalized_text: str = Column(Text, nullable=False)
    extraction_confidence: float = Column(Float, nullable=True)  # 0.0–1.0

    # OCR fallback indicator
    ocr_used: bool = Column(Boolean, nullable=False, default=False)

    created_at: datetime = Column(DateTime, nullable=False, default=_now)

    # Relationships
    run = relationship("RunRecord", back_populates="parsed_clauses")

    __table_args__ = (
        UniqueConstraint(
            "run_id", "clause_uid", name="uq_parsed_clause_per_run"
        ),
    )


# ---------------------------------------------------------------------------
# PolicyVersionRecord
# Harvey lineage store.  Keyed by (tenant_id, policy_family_id, version_number).
# ---------------------------------------------------------------------------


class PolicyVersionRecord(Base):
    __tablename__ = "policy_versions"

    id: str = Column(String(36), primary_key=True, default=_uuid)

    # policy-lineage-and-corpora primary key
    tenant_id: str = Column(String(255), nullable=False, index=True)
    policy_family_id: str = Column(String(255), nullable=False)
    version_number: int = Column(Integer, nullable=False)

    # Payload
    policy_name: str = Column(String(512), nullable=True)
    effective_from: date = Column(Date, nullable=True)
    effective_to: date = Column(Date, nullable=True)
    rules_payload: dict = Column(JSON, nullable=False)  # structured Harvey rules

    # Lineage links
    parent_version_number: int = Column(Integer, nullable=True)
    change_summary: str = Column(Text, nullable=True)

    created_at: datetime = Column(DateTime, nullable=False, default=_now)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "policy_family_id", "version_number",
            name="uq_policy_version",
        ),
    )


# ---------------------------------------------------------------------------
# ComplianceCorpusRecord
# Kira corpora store.  Versioned by tenant, corpus type, jurisdiction, regime,
# and effective dates.
# ---------------------------------------------------------------------------


class ComplianceCorpusRecord(Base):
    __tablename__ = "compliance_corpora"

    id: str = Column(String(36), primary_key=True, default=_uuid)

    # policy-lineage-and-corpora Kira keys
    tenant_id: str = Column(String(255), nullable=False, index=True)
    corpus_type: str = Column(String(64), nullable=False)  # internal_playbook | external
    jurisdiction: str = Column(String(128), nullable=False)
    regime: str = Column(String(128), nullable=False)
    effective_from: date = Column(Date, nullable=False)
    effective_to: date = Column(Date, nullable=True)

    # Payload
    corpus_name: str = Column(String(512), nullable=True)
    rules_payload: dict = Column(JSON, nullable=False)  # list of rule dicts
    source_url: str = Column(String(1024), nullable=True)

    created_at: datetime = Column(DateTime, nullable=False, default=_now)
    updated_at: datetime = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "corpus_type", "jurisdiction", "regime", "effective_from",
            name="uq_compliance_corpus",
        ),
    )


# ---------------------------------------------------------------------------
# ContractRecord
# A named contract entity that groups one or more versioned runs together.
# ---------------------------------------------------------------------------


class ContractRecord(Base):
    __tablename__ = "contracts"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    name: str = Column(String(512), nullable=False)
    tenant_id: str = Column(String(255), nullable=False, index=True)

    created_at: datetime = Column(DateTime, nullable=False, default=_now)
    updated_at: datetime = Column(DateTime, nullable=False, default=_now, onupdate=_now)

    versions = relationship(
        "ContractVersionRecord",
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="ContractVersionRecord.id",
    )


# ---------------------------------------------------------------------------
# ContractVersionRecord
# One row per uploaded version of a contract.
# Main branch: branch_letter is NULL, label = "v1", "v2", "v3"
# Branch:      branch_letter = "a"/"b"/"c", label = "v1a", "v2b"
# ---------------------------------------------------------------------------


class ContractVersionRecord(Base):
    __tablename__ = "contract_versions"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    contract_id: int = Column(
        Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: str = Column(
        String(36), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, unique=True
    )

    main_version: int = Column(Integer, nullable=False)       # 1, 2, 3 …
    branch_letter: str = Column(String(4), nullable=True)     # null = main | 'a','b','c' = branch
    branch_name: str = Column(String(255), nullable=True)     # optional user-provided label

    label: str = Column(String(32), nullable=False)           # "v1", "v1a", "v2b" …

    created_at: datetime = Column(DateTime, nullable=False, default=_now)

    contract = relationship("ContractRecord", back_populates="versions")
    run = relationship("RunRecord")


# ---------------------------------------------------------------------------
# RunEventRecord
# Persisted SSE event stream for a run (sse-run-events dependency).
# Append-only; never updated after insert.
# ---------------------------------------------------------------------------


class RunEventRecord(Base):
    __tablename__ = "run_events"

    id: BigInteger = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id: str = Column(
        String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    event_type: str = Column(
        String(64),
        nullable=False,
        # run_created | stage_started | stage_completed | stage_failed |
        # stage_retrying | consensus_unresolved | awaiting_human_review |
        # human_edited | human_rejected | human_approved | run_finalized
    )
    payload: dict = Column(JSON, nullable=False, default=dict)
    sequence_number: int = Column(Integer, nullable=False)  # monotonic per run

    created_at: datetime = Column(DateTime, nullable=False, default=_now)

    # Relationships
    run = relationship("RunRecord", back_populates="events")

    __table_args__ = (
        UniqueConstraint(
            "run_id", "sequence_number", name="uq_run_event_sequence"
        ),
    )


# ---------------------------------------------------------------------------
# HumanReviewRecord
# human-review-gate: one row per finding-level human action within a run.
# Captures edit provenance for full audit trail.
# ---------------------------------------------------------------------------


class HumanReviewRecord(Base):
    __tablename__ = "human_reviews"

    id: str = Column(String(36), primary_key=True, default=_uuid)
    run_id: str = Column(
        String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    finding_id: str = Column(
        String(36),
        ForeignKey("findings.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Reviewer identity
    reviewer_id: str = Column(String(255), nullable=False)
    reviewer_role: str = Column(String(64), nullable=True)

    # Action taken
    action: str = Column(
        String(32),
        nullable=False,
        # approve | reject | edit | escalate
    )

    # For edits: capture before/after for audit provenance
    original_finding_snapshot: dict = Column(JSON, nullable=True)
    edited_finding_snapshot: dict = Column(JSON, nullable=True)
    edit_justification: str = Column(Text, nullable=True)

    # For run-level approval/rejection
    is_run_level: bool = Column(Boolean, nullable=False, default=False)
    rejection_reason: str = Column(Text, nullable=True)

    created_at: datetime = Column(DateTime, nullable=False, default=_now)

    # Relationships
    run = relationship("RunRecord", back_populates="human_reviews")
    finding = relationship("FindingRecord", back_populates="human_reviews")

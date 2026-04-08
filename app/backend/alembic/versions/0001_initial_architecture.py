"""initial_architecture

Revision ID: 0001
Revises:
Create Date: 2026-04-03

Shared dependencies: postgres-stage-queue, run-state-contract, docling-canonical-parser,
                     policy-lineage-and-corpora, sse-run-events, human-review-gate
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # runs  (postgres-stage-queue, run-state-contract, human-review-gate)
    # ------------------------------------------------------------------
    op.create_table(
        "runs",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("policy_family_id", sa.String(255), nullable=True),
        sa.Column("policy_version_number", sa.Integer(), nullable=True),
        sa.Column("jurisdiction", sa.String(128), nullable=True),
        sa.Column("regime", sa.String(128), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("current_round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("verdict_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_runs_run_id", "runs", ["id"], unique=True)
    op.create_index("ix_runs_tenant_id", "runs", ["tenant_id"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index(
        "ix_runs_tenant_policy_lineage",
        "runs",
        ["tenant_id", "policy_family_id", "policy_version_number"],
    )

    # ------------------------------------------------------------------
    # stage_executions  (postgres-stage-queue)
    # ------------------------------------------------------------------
    op.create_table(
        "stage_executions",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage_name", sa.String(64), nullable=False),
        sa.Column("stage_order", sa.Integer(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="pending",
            comment="pending | claimed | running | completed | failed | retrying",
        ),
        sa.Column("worker_id", sa.String(255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("raw_provider_response", postgresql.JSONB(), nullable=True),
        sa.Column("structured_output", postgresql.JSONB(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "stage_name", "round_number", "attempt_number", name="uq_stage_execution_idempotency"),
    )
    op.create_index("ix_stage_executions_run_id", "stage_executions", ["run_id"])
    op.create_index("ix_stage_executions_status", "stage_executions", ["status"])
    op.create_index(
        "ix_stage_executions_claim",
        "stage_executions",
        ["status", "stage_order", "lease_expires_at"],
    )

    # ------------------------------------------------------------------
    # parsed_clauses  (docling-canonical-parser)
    # ------------------------------------------------------------------
    op.create_table(
        "parsed_clauses",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clause_uid", sa.String(128), nullable=False),
        sa.Column("document_hash", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(32), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("bbox_x0", sa.Float(), nullable=True),
        sa.Column("bbox_y0", sa.Float(), nullable=True),
        sa.Column("bbox_x1", sa.Float(), nullable=True),
        sa.Column("bbox_y1", sa.Float(), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column("ocr_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "clause_uid", name="uq_parsed_clause_per_run"),
    )
    op.create_index("ix_parsed_clauses_run_id", "parsed_clauses", ["run_id"])
    op.create_index("ix_parsed_clauses_clause_uid", "parsed_clauses", ["clause_uid"], unique=False)
    op.create_index(
        "ix_parsed_clauses_run_clause",
        "parsed_clauses",
        ["run_id", "clause_uid"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # findings  (run-state-contract)
    # ------------------------------------------------------------------
    op.create_table(
        "findings",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage_execution_id", sa.String(36), sa.ForeignKey("stage_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_agent", sa.String(64), nullable=False),
        sa.Column("source_rule_id", sa.String(255), nullable=True),
        sa.Column("prior_version_ref", sa.String(255), nullable=True),
        sa.Column("round_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("clause_uid", sa.String(128), nullable=True),
        sa.Column("clause_text", sa.Text(), nullable=True),
        sa.Column("issue", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("is_disputed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("dispute_reason", sa.Text(), nullable=True),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_findings_run_id", "findings", ["run_id"])
    op.create_index("ix_findings_stage_execution_id", "findings", ["stage_execution_id"])
    op.create_index("ix_findings_clause_uid", "findings", ["clause_uid"])

    # ------------------------------------------------------------------
    # evidence  (run-state-contract, docling-canonical-parser)
    # ------------------------------------------------------------------
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("finding_id", sa.String(36), sa.ForeignKey("findings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clause_uid", sa.String(128), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("bbox_x0", sa.Float(), nullable=True),
        sa.Column("bbox_y0", sa.Float(), nullable=True),
        sa.Column("bbox_x1", sa.Float(), nullable=True),
        sa.Column("bbox_y1", sa.Float(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_evidence_finding_id", "evidence", ["finding_id"])

    # ------------------------------------------------------------------
    # policy_versions  (policy-lineage-and-corpora)
    # Keyed by tenant_id + policy_family_id + version_number
    # ------------------------------------------------------------------
    op.create_table(
        "policy_versions",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("policy_family_id", sa.String(255), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("policy_name", sa.String(512), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("rules_payload", postgresql.JSONB(), nullable=False),
        sa.Column("parent_version_number", sa.Integer(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_policy_versions_lineage",
        "policy_versions",
        ["tenant_id", "policy_family_id", "version_number"],
        unique=True,
    )
    op.create_index("ix_policy_versions_tenant_id", "policy_versions", ["tenant_id"])

    # ------------------------------------------------------------------
    # compliance_corpora  (policy-lineage-and-corpora)
    # Keyed by tenant_id + corpus_type + jurisdiction + regime + effective_date
    # ------------------------------------------------------------------
    op.create_table(
        "compliance_corpora",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("corpus_type", sa.String(64), nullable=False, comment="internal_playbook | external"),
        sa.Column("jurisdiction", sa.String(128), nullable=False),
        sa.Column("regime", sa.String(128), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("corpus_name", sa.String(512), nullable=True),
        sa.Column("rules_payload", postgresql.JSONB(), nullable=False),
        sa.Column("source_url", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_compliance_corpora_lookup",
        "compliance_corpora",
        ["tenant_id", "corpus_type", "jurisdiction", "regime", "effective_from"],
        unique=True,
    )
    op.create_index("ix_compliance_corpora_tenant_id", "compliance_corpora", ["tenant_id"])

    # ------------------------------------------------------------------
    # run_events  (sse-run-events)
    # Append-only; ordered by sequence_number for replay
    # ------------------------------------------------------------------
    op.create_table(
        "run_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "event_type",
            sa.String(64),
            nullable=False,
            comment=(
                "run_created | stage_started | stage_completed | stage_failed | stage_retrying | "
                "consensus_unresolved | awaiting_human_review | human_edited | human_rejected | "
                "human_approved | run_finalized"
            ),
        ),
        sa.Column("sequence_number", sa.BigInteger(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "sequence_number", name="uq_run_event_sequence"),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])
    op.create_index(
        "ix_run_events_replay_order",
        "run_events",
        ["run_id", "sequence_number"],
    )
    op.create_index("ix_run_events_event_type", "run_events", ["event_type"])

    # ------------------------------------------------------------------
    # human_reviews  (human-review-gate)
    # ------------------------------------------------------------------
    op.create_table(
        "human_reviews",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finding_id", sa.String(36), sa.ForeignKey("findings.id", ondelete="CASCADE"), nullable=True),
        sa.Column("reviewer_id", sa.String(255), nullable=False),
        sa.Column("reviewer_role", sa.String(64), nullable=True),
        sa.Column(
            "action",
            sa.String(32),
            nullable=False,
            comment="approve | reject | edit | escalate",
        ),
        sa.Column("original_finding_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("edited_finding_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("edit_justification", sa.Text(), nullable=True),
        sa.Column("is_run_level", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_human_reviews_run_id", "human_reviews", ["run_id"])
    op.create_index("ix_human_reviews_finding_id", "human_reviews", ["finding_id"])
    op.create_index("ix_human_reviews_run_action", "human_reviews", ["run_id", "action"])


def downgrade() -> None:
    op.drop_table("human_reviews")
    op.drop_table("run_events")
    op.drop_table("compliance_corpora")
    op.drop_table("policy_versions")
    op.drop_table("evidence")
    op.drop_table("findings")
    op.drop_table("parsed_clauses")
    op.drop_table("stage_executions")
    op.drop_table("runs")

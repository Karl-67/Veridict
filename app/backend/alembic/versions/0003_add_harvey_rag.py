"""add_harvey_rag

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "rag_source_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True),
        sa.Column("doc_type", sa.String(64), nullable=False),
        sa.Column("policy_family_id", sa.String(255), nullable=True),
        sa.Column("jurisdiction", sa.String(128), nullable=True),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("source_path", sa.String(1024), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_rag_source_documents_tenant_id", "rag_source_documents", ["tenant_id"])
    op.create_index("ix_rag_source_documents_workspace_id", "rag_source_documents", ["workspace_id"])
    op.create_index(
        "ix_rag_source_doc_tenant_scope",
        "rag_source_documents",
        ["tenant_id", "workspace_id", "policy_family_id", "doc_type"],
    )

    op.create_table(
        "rag_document_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("rag_source_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("version_label", sa.String(128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "version", name="uq_rag_doc_version"),
    )
    op.create_index("ix_rag_document_versions_document_id", "rag_document_versions", ["document_id"])

    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("rag_document_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chunk_hash", sa.String(64), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("chunk_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("version_id", "chunk_hash", name="uq_rag_chunk_hash"),
    )
    op.create_index("ix_rag_chunks_version_id", "rag_chunks", ["version_id"])
    op.execute("CREATE INDEX ix_rag_chunks_fts ON rag_chunks USING gin(to_tsvector('english', text))")

    op.create_table(
        "rag_embeddings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chunk_id", sa.String(36), sa.ForeignKey("rag_chunks.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("embedding", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.execute("ALTER TABLE rag_embeddings ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector")
    op.create_index("ix_rag_embeddings_chunk_id", "rag_embeddings", ["chunk_id"])
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rag_embeddings_hnsw ON rag_embeddings "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    op.create_table(
        "rag_ingestion_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column("doc_type", sa.String(64), nullable=False),
        sa.Column("policy_family_id", sa.String(255), nullable=True),
        sa.Column("jurisdiction", sa.String(128), nullable=True),
        sa.Column("version_label", sa.String(128), nullable=True),
        sa.Column("source_document_id", sa.String(36), sa.ForeignKey("rag_source_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("version_id", sa.String(36), sa.ForeignKey("rag_document_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_rag_ingestion_jobs_tenant_id", "rag_ingestion_jobs", ["tenant_id"])
    op.create_index("ix_rag_ingestion_jobs_workspace_id", "rag_ingestion_jobs", ["workspace_id"])
    op.create_index("ix_rag_ingestion_jobs_source_document_id", "rag_ingestion_jobs", ["source_document_id"])
    op.create_index("ix_rag_ingestion_jobs_version_id", "rag_ingestion_jobs", ["version_id"])

    op.create_table(
        "rag_retrieval_traces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clause_id", sa.String(128), nullable=False),
        sa.Column("chunk_ids", postgresql.ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("scores", postgresql.ARRAY(sa.Float()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_rag_retrieval_traces_run_id", "rag_retrieval_traces", ["run_id"])
    op.create_index("ix_rag_retrieval_traces_clause_id", "rag_retrieval_traces", ["clause_id"])
    op.create_index("ix_rag_retrieval_trace_run_clause", "rag_retrieval_traces", ["run_id", "clause_id"])

    op.execute("ALTER TABLE findings ADD COLUMN IF NOT EXISTS contract_evidence JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE findings ADD COLUMN IF NOT EXISTS rag_citations JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE findings ADD COLUMN IF NOT EXISTS consensus_state VARCHAR(32)")
    op.execute("ALTER TABLE findings ADD COLUMN IF NOT EXISTS business_impact TEXT")
    op.execute("ALTER TABLE findings ADD COLUMN IF NOT EXISTS exploitability TEXT")
    op.execute("ALTER TABLE findings ADD COLUMN IF NOT EXISTS unresolved_by_consensus BOOLEAN DEFAULT false NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE findings DROP COLUMN IF EXISTS unresolved_by_consensus")
    op.execute("ALTER TABLE findings DROP COLUMN IF EXISTS exploitability")
    op.execute("ALTER TABLE findings DROP COLUMN IF EXISTS business_impact")
    op.execute("ALTER TABLE findings DROP COLUMN IF EXISTS consensus_state")
    op.execute("ALTER TABLE findings DROP COLUMN IF EXISTS rag_citations")
    op.execute("ALTER TABLE findings DROP COLUMN IF EXISTS contract_evidence")
    op.drop_index("ix_rag_retrieval_trace_run_clause", table_name="rag_retrieval_traces")
    op.drop_index("ix_rag_retrieval_traces_clause_id", table_name="rag_retrieval_traces")
    op.drop_index("ix_rag_retrieval_traces_run_id", table_name="rag_retrieval_traces")
    op.drop_table("rag_retrieval_traces")
    op.drop_index("ix_rag_ingestion_jobs_version_id", table_name="rag_ingestion_jobs")
    op.drop_index("ix_rag_ingestion_jobs_source_document_id", table_name="rag_ingestion_jobs")
    op.drop_index("ix_rag_ingestion_jobs_workspace_id", table_name="rag_ingestion_jobs")
    op.drop_index("ix_rag_ingestion_jobs_tenant_id", table_name="rag_ingestion_jobs")
    op.drop_table("rag_ingestion_jobs")
    op.execute("DROP INDEX IF EXISTS ix_rag_embeddings_hnsw")
    op.drop_index("ix_rag_embeddings_chunk_id", table_name="rag_embeddings")
    op.drop_table("rag_embeddings")
    op.drop_index("ix_rag_chunks_fts", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_version_id", table_name="rag_chunks")
    op.drop_table("rag_chunks")
    op.drop_index("ix_rag_document_versions_document_id", table_name="rag_document_versions")
    op.drop_table("rag_document_versions")
    op.drop_index("ix_rag_source_doc_tenant_scope", table_name="rag_source_documents")
    op.drop_index("ix_rag_source_documents_workspace_id", table_name="rag_source_documents")
    op.drop_index("ix_rag_source_documents_tenant_id", table_name="rag_source_documents")
    op.drop_table("rag_source_documents")

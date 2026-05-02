"""add_contract_edits

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("contract_edits", sa.JSON(), nullable=True))
    op.add_column("findings", sa.Column("recommended_change", sa.Text(), nullable=True))
    op.add_column("findings", sa.Column("dismissed_at", sa.DateTime(), nullable=True))
    op.add_column("findings", sa.Column("accepted_at", sa.DateTime(), nullable=True))

    op.create_table(
        "document_annotations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clause_uid", sa.String(128), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("selected_text", sa.Text(), nullable=True),
        sa.Column("span_start", sa.Integer(), nullable=True),
        sa.Column("span_end", sa.Integer(), nullable=True),
        sa.Column("annotation_type", sa.String(16), nullable=False, server_default="comment"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("suggested_replacement", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("source", sa.String(8), nullable=False, server_default="human"),
        sa.Column("finding_id", sa.String(36), sa.ForeignKey("findings.id", ondelete="SET NULL"), nullable=True),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_document_annotations_run_id", "document_annotations", ["run_id"])
    op.create_index("ix_document_annotations_clause_uid", "document_annotations", ["clause_uid"])
    op.create_index("ix_document_annotations_finding_id", "document_annotations", ["finding_id"])
    op.create_index("ix_document_annotations_author_id", "document_annotations", ["author_id"])
    op.create_index("ix_doc_annotation_run_clause", "document_annotations", ["run_id", "clause_uid"])


def downgrade() -> None:
    op.drop_index("ix_doc_annotation_run_clause", table_name="document_annotations")
    op.drop_index("ix_document_annotations_author_id", table_name="document_annotations")
    op.drop_index("ix_document_annotations_finding_id", table_name="document_annotations")
    op.drop_index("ix_document_annotations_clause_uid", table_name="document_annotations")
    op.drop_index("ix_document_annotations_run_id", table_name="document_annotations")
    op.drop_table("document_annotations")
    op.drop_column("findings", "accepted_at")
    op.drop_column("findings", "dismissed_at")
    op.drop_column("findings", "recommended_change")
    op.drop_column("runs", "contract_edits")

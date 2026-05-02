"""add inline comment anchors

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contract_comments", sa.Column("workspace_id", sa.String(36), nullable=True))
    op.add_column("contract_comments", sa.Column("contract_id", sa.String(36), nullable=True))
    op.add_column("contract_comments", sa.Column("page_number", sa.Integer(), nullable=True))
    op.add_column("contract_comments", sa.Column("selected_text", sa.Text(), nullable=True))
    op.add_column("contract_comments", sa.Column("anchor", sa.JSON(), nullable=True))
    op.create_index("ix_contract_comments_workspace_id", "contract_comments", ["workspace_id"])
    op.create_index("ix_contract_comments_contract_id", "contract_comments", ["contract_id"])


def downgrade() -> None:
    op.drop_index("ix_contract_comments_contract_id", table_name="contract_comments")
    op.drop_index("ix_contract_comments_workspace_id", table_name="contract_comments")
    op.drop_column("contract_comments", "anchor")
    op.drop_column("contract_comments", "selected_text")
    op.drop_column("contract_comments", "page_number")
    op.drop_column("contract_comments", "contract_id")
    op.drop_column("contract_comments", "workspace_id")

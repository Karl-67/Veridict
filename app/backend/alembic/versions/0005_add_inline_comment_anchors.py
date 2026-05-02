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
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE contract_comments ADD COLUMN IF NOT EXISTS workspace_id VARCHAR(36)"))
    conn.execute(sa.text("ALTER TABLE contract_comments ADD COLUMN IF NOT EXISTS contract_id VARCHAR(36)"))
    conn.execute(sa.text("ALTER TABLE contract_comments ADD COLUMN IF NOT EXISTS page_number INTEGER"))
    conn.execute(sa.text("ALTER TABLE contract_comments ADD COLUMN IF NOT EXISTS selected_text TEXT"))
    conn.execute(sa.text("ALTER TABLE contract_comments ADD COLUMN IF NOT EXISTS anchor JSONB"))
    # Create indexes only if they don't exist
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_contract_comments_workspace_id ON contract_comments (workspace_id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_contract_comments_contract_id ON contract_comments (contract_id)"
    ))


def downgrade() -> None:
    op.drop_index("ix_contract_comments_contract_id", table_name="contract_comments")
    op.drop_index("ix_contract_comments_workspace_id", table_name="contract_comments")
    op.drop_column("contract_comments", "anchor")
    op.drop_column("contract_comments", "selected_text")
    op.drop_column("contract_comments", "page_number")
    op.drop_column("contract_comments", "contract_id")
    op.drop_column("contract_comments", "workspace_id")

"""add_org_workspace_to_contracts

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contracts", sa.Column("org_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=True))
    op.add_column("contracts", sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=True))
    op.create_index("ix_contracts_org_id", "contracts", ["org_id"])
    op.create_index("ix_contracts_workspace_id", "contracts", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_contracts_workspace_id", "contracts")
    op.drop_index("ix_contracts_org_id", "contracts")
    op.drop_column("contracts", "workspace_id")
    op.drop_column("contracts", "org_id")

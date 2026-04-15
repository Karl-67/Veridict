"""add_contracts

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contracts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_contracts_tenant_id", "contracts", ["tenant_id"])

    op.create_table(
        "contract_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "contract_id",
            sa.Integer(),
            sa.ForeignKey("contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("runs.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column("main_version", sa.Integer(), nullable=False),
        sa.Column("branch_letter", sa.String(4), nullable=True),
        sa.Column("branch_name", sa.String(255), nullable=True),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_contract_versions_contract_id", "contract_versions", ["contract_id"])


def downgrade() -> None:
    op.drop_index("ix_contract_versions_contract_id", "contract_versions")
    op.drop_table("contract_versions")
    op.drop_index("ix_contracts_tenant_id", "contracts")
    op.drop_table("contracts")

"""add_clause_order_index

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-03
"""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "parsed_clauses",
        sa.Column("order_index", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("parsed_clauses", "order_index")

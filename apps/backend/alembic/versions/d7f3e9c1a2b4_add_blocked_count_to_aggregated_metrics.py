"""add blocked_count to aggregated_metrics

Revision ID: d7f3e9c1a2b4
Revises: c4e1f2a3b5d6
Create Date: 2026-05-25

"""
from alembic import op
import sqlalchemy as sa

revision = "d7f3e9c1a2b4"
down_revision = "c4e1f2a3b5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "aggregated_metrics",
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("aggregated_metrics", "blocked_count")

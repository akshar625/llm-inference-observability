"""add status to messages

Revision ID: c4e1f2a3b5d6
Revises: 833c2d7748cd
Create Date: 2026-05-25

"""
from alembic import op
import sqlalchemy as sa

revision = "c4e1f2a3b5d6"
down_revision = "833c2d7748cd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("status", sa.String(), nullable=False, server_default="completed"),
    )


def downgrade() -> None:
    op.drop_column("messages", "status")

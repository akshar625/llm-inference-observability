"""fix_message_ordering_clock_timestamp

Revision ID: 833c2d7748cd
Revises: 638d5d789d48
Create Date: 2026-05-23 23:25:40.033818

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '833c2d7748cd'
down_revision: Union[str, Sequence[str], None] = '638d5d789d48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "messages",
        "created_at",
        server_default=sa.text("clock_timestamp()"),
    )


def downgrade() -> None:
    op.alter_column(
        "messages",
        "created_at",
        server_default=sa.text("now()"),
    )

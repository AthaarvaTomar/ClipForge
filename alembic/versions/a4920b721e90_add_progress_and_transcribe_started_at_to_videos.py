"""add progress and transcribe_started_at to videos

Revision ID: a4920b721e90
Revises: c3cb4047c9fd
Create Date: 2026-11-17 22:15:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a4920b721e90'
down_revision: str | Sequence[str] | None = 'c3cb4047c9fd'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('videos', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('progress', sa.Integer(), server_default='0', nullable=False)
        )
        batch_op.add_column(
            sa.Column('transcribe_started_at', sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('videos', schema=None) as batch_op:
        batch_op.drop_column('transcribe_started_at')
        batch_op.drop_column('progress')

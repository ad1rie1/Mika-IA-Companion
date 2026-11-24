"""events.remind : « Mika te le rappelle » pour un événement (ADR 0309, lot 3b), gardé dans la base seulement ; vide
pour ce qui était là avant (le choix de son agenda)

Revision ID: c5a8e1f3b207
Revises: 3fbed6e2467d
Create Date: 2026-11-23 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c5a8e1f3b207'
down_revision: str | Sequence[str] | None = '3fbed6e2467d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('remind', sa.String(length=16), server_default='', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_column('remind')

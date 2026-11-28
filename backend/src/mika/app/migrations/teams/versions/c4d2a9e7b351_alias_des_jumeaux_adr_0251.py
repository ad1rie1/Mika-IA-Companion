"""messages.alias : la référence du même message sous son autre identifiant (ADR 0251) — sa version en attente dans
Teams puis celle du service, ou une empreinte de l'extension ; vide pour un message d'avant

Revision ID: c4d2a9e7b351
Revises: 5e315c8f113d
Create Date: 2026-11-20 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c4d2a9e7b351'
down_revision: str | Sequence[str] | None = '5e315c8f113d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('alias', sa.String(length=32), server_default='', nullable=False))
        batch_op.create_index('ix_messages_alias', ['alias'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_index('ix_messages_alias')
        batch_op.drop_column('alias')

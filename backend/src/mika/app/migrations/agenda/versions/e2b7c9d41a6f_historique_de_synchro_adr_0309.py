"""sync_notes : l'historique de la synchro de chaque compte (ADR 0309, lot 5) — une relecture qui a changé quelque
chose, la copie relue après une écriture, une panne et sa reprise ; vide pour ce qui était là avant

Revision ID: e2b7c9d41a6f
Revises: c5a8e1f3b207
Create Date: 2026-11-24 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = 'e2b7c9d41a6f'
down_revision: str | Sequence[str] | None = 'c5a8e1f3b207'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('sync_notes',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('account', sa.String(length=404), nullable=False),
    sa.Column('calendar', sa.String(length=445), nullable=False),
    sa.Column('at', sa.BigInteger(), nullable=False),
    sa.Column('what', sa.String(length=16), nullable=False),
    sa.Column('changed', sa.BigInteger(), nullable=False),
    sa.Column('detail', sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sync_notes')),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_nopad_bin',
    mariadb_engine='InnoDB'
    )
    with op.batch_alter_table('sync_notes', schema=None) as batch_op:
        batch_op.create_index('ix_sync_notes_account_at', ['account', 'at'], unique=False)
        batch_op.create_index('ix_sync_notes_at', ['at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('sync_notes', schema=None) as batch_op:
        batch_op.drop_index('ix_sync_notes_at')
        batch_op.drop_index('ix_sync_notes_account_at')

    op.drop_table('sync_notes')

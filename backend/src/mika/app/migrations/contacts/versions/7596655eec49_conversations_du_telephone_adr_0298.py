"""threads : les conversations du téléphone où elle voit un expéditeur — sa clé, le nom du groupe, combien de
messages, de quand à quand (ADR 0298, lot 5)

Revision ID: 7596655eec49
Revises: a60efd22b77f
Create Date: 2026-11-22 01:40:54.531864
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = '7596655eec49'
down_revision: str | Sequence[str] | None = 'a60efd22b77f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('threads',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('identifier', sa.BigInteger(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('account', sa.String(length=40), nullable=False),
    sa.Column('thread', sa.String(length=64), nullable=False),
    sa.Column('title', sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.Column('grouped', sa.Boolean(), nullable=False),
    sa.Column('count', sa.BigInteger(), nullable=False),
    sa.Column('first', sa.BigInteger(), nullable=False),
    sa.Column('last', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_threads')),
    sa.UniqueConstraint('identifier', 'source', 'account', 'thread', name='uq_threads_place'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_nopad_bin',
    mariadb_engine='InnoDB'
    )
    with op.batch_alter_table('threads', schema=None) as batch_op:
        batch_op.create_index('ix_threads_identifier', ['identifier'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('threads', schema=None) as batch_op:
        batch_op.drop_index('ix_threads_identifier')

    op.drop_table('threads')

"""notes, notes_forgotten, portraits : ce qu'elle sait d'un contact à partir de ce qu'elle lit — ses faits, l'empreinte
de ceux qu'on lui a fait oublier, chaque passage du portrait (ADR 0298, lot 6)

Revision ID: 93842099e883
Revises: 7596655eec49
Create Date: 2026-11-22 10:13:39.013685
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = '93842099e883'
down_revision: str | Sequence[str] | None = '7596655eec49'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('notes',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('contact', sa.BigInteger(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('account', sa.String(length=40), nullable=False),
    sa.Column('text', sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('confidence', sa.BigInteger(), nullable=False),
    sa.Column('ref', sa.String(length=200), nullable=False),
    sa.Column('place', sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.Column('said_at', sa.BigInteger(), nullable=False),
    sa.Column('at', sa.BigInteger(), nullable=False),
    sa.Column('call_id', sa.String(length=200), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notes')),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_nopad_bin',
    mariadb_engine='InnoDB'
    )
    with op.batch_alter_table('notes', schema=None) as batch_op:
        batch_op.create_index('ix_notes_contact', ['contact'], unique=False)
        batch_op.create_index('ix_notes_place', ['source', 'account'], unique=False)

    op.create_table('notes_forgotten',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('contact', sa.BigInteger(), nullable=False),
    sa.Column('prints', sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.Column('at', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notes_forgotten')),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_nopad_bin',
    mariadb_engine='InnoDB'
    )
    with op.batch_alter_table('notes_forgotten', schema=None) as batch_op:
        batch_op.create_index('ix_notes_forgotten_contact', ['contact'], unique=False)

    op.create_table('portraits',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('contact', sa.BigInteger(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('account', sa.String(length=40), nullable=False),
    sa.Column('at', sa.BigInteger(), nullable=False),
    sa.Column('upto', sa.BigInteger(), nullable=False),
    sa.Column('read', sa.BigInteger(), nullable=False),
    sa.Column('ok', sa.Boolean(), nullable=False),
    sa.Column('call_id', sa.String(length=200), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_portraits')),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_nopad_bin',
    mariadb_engine='InnoDB'
    )
    with op.batch_alter_table('portraits', schema=None) as batch_op:
        batch_op.create_index('ix_portraits_at', ['at'], unique=False)
        batch_op.create_index('ix_portraits_place', ['contact', 'source', 'account'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('portraits', schema=None) as batch_op:
        batch_op.drop_index('ix_portraits_place')
        batch_op.drop_index('ix_portraits_at')

    op.drop_table('portraits')
    with op.batch_alter_table('notes_forgotten', schema=None) as batch_op:
        batch_op.drop_index('ix_notes_forgotten_contact')

    op.drop_table('notes_forgotten')
    with op.batch_alter_table('notes', schema=None) as batch_op:
        batch_op.drop_index('ix_notes_place')
        batch_op.drop_index('ix_notes_contact')

    op.drop_table('notes')

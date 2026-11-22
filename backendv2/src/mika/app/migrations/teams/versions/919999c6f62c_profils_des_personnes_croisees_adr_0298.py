"""profiles : le profil des personnes croisées, tel que l'extension l'envoie (ADR 0298) ; counters : le
dernier rang donné à un changement de profil (un rang ne resert jamais)

Revision ID: 919999c6f62c
Revises: d7e3b5a19c62
Create Date: 2026-11-22 00:30:14.592597
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = '919999c6f62c'
down_revision: str | Sequence[str] | None = 'd7e3b5a19c62'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('counters',
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.Column('value', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('name', name=op.f('pk_counters')),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_nopad_bin',
    mariadb_engine='InnoDB'
    )
    op.create_table('profiles',
    sa.Column('account', sa.String(length=40), nullable=False),
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('name', sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.Column('email', sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.Column('title', sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.Column('company', sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.Column('department', sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.Column('tenant', sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.Column('phones', sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.Column('updated', sa.BigInteger(), nullable=False),
    sa.Column('seq', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('account', 'key', name=op.f('pk_profiles')),
    sa.UniqueConstraint('seq', name='uq_profiles_seq'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_nopad_bin',
    mariadb_engine='InnoDB'
    )
    with op.batch_alter_table('profiles', schema=None) as batch_op:
        batch_op.create_index('ix_profiles_key', ['key'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('profiles', schema=None) as batch_op:
        batch_op.drop_index('ix_profiles_key')
    op.drop_table('profiles')
    op.drop_table('counters')

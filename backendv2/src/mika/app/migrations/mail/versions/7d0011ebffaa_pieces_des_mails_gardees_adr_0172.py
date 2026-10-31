"""parts, blobs : les pièces des mails, gardées avec eux (ADR 0172) ; un mail d'avant n'a pas les siennes

Revision ID: 7d0011ebffaa
Revises: dfee9920d3e3
Create Date: 2026-10-31 23:41:52.463924
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = '7d0011ebffaa'
down_revision: str | Sequence[str] | None = 'dfee9920d3e3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('blobs',
    sa.Column('digest', sa.String(length=64), nullable=False),
    sa.Column('chunk', sa.BigInteger(), nullable=False),
    sa.Column('data', sa.LargeBinary().with_variant(mysql.LONGBLOB(), 'mariadb').with_variant(mysql.LONGBLOB(), 'mysql'), nullable=False),
    sa.PrimaryKeyConstraint('digest', 'chunk', name=op.f('pk_blobs')),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_nopad_bin',
    mariadb_engine='InnoDB'
    )
    op.create_table('parts',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('owner', sa.BigInteger(), nullable=False),
    sa.Column('position', sa.BigInteger(), nullable=False),
    sa.Column('content_id', sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.Column('name', sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.Column('mime', sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql'), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('digest', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_parts')),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_nopad_bin',
    mariadb_engine='InnoDB'
    )
    with op.batch_alter_table('parts', schema=None) as batch_op:
        batch_op.create_index('ix_parts_digest', ['digest'], unique=False)
        batch_op.create_index('ix_parts_owner', ['owner'], unique=False)

    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('parts_kept', sa.Boolean(), server_default=sa.text('0'), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('parts_kept')

    with op.batch_alter_table('parts', schema=None) as batch_op:
        batch_op.drop_index('ix_parts_owner')
        batch_op.drop_index('ix_parts_digest')

    op.drop_table('parts')
    op.drop_table('blobs')

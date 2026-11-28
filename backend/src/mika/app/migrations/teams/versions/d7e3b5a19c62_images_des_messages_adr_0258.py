"""images : les images des messages, téléchargées par l'extension, et ce que Mika y a vu (ADR 0258) ;
messages.images_pending : celles qu'un message attend encore (0 pour un message d'avant)

Revision ID: d7e3b5a19c62
Revises: c4d2a9e7b351
Create Date: 2026-11-20 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = 'd7e3b5a19c62'
down_revision: str | Sequence[str] | None = 'c4d2a9e7b351'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LONG = sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql')
BLOB = sa.LargeBinary().with_variant(mysql.LONGBLOB(), 'mariadb').with_variant(mysql.LONGBLOB(), 'mysql')


def upgrade() -> None:
    op.create_table('images',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('ref', sa.String(length=32), nullable=False),
    sa.Column('account', sa.String(length=40), server_default='principal', nullable=False),
    sa.Column('image', sa.String(length=200), nullable=False),
    sa.Column('position', sa.BigInteger(), nullable=False),
    sa.Column('mime', sa.String(length=40), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('data', BLOB, nullable=False),
    sa.Column('at', sa.BigInteger(), nullable=False),
    sa.Column('seen', LONG, nullable=False),
    sa.Column('read', sa.Boolean(), nullable=False),
    sa.Column('sensitive', sa.Boolean(), nullable=False),
    sa.Column('tries', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_images')),
    sa.UniqueConstraint('ref', 'image', name='uq_images_ref_image'),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_nopad_bin',
    mariadb_engine='InnoDB'
    )
    with op.batch_alter_table('images', schema=None) as batch_op:
        batch_op.create_index('ix_images_unread', ['read', 'at'], unique=False)
        batch_op.create_index('ix_images_account_at', ['account', 'at'], unique=False)
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('images_pending', sa.BigInteger(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('images_pending')
    with op.batch_alter_table('images', schema=None) as batch_op:
        batch_op.drop_index('ix_images_account_at')
        batch_op.drop_index('ix_images_unread')
    op.drop_table('images')

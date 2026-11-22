"""messages.reactions : les réactions d'un message (ADR 0300), vides pour ce qui était là avant ; profiles.avatar :
l'empreinte de la photo d'une personne ; photos : la photo de profil des personnes croisées, par compte

Revision ID: 6440869dea44
Revises: 919999c6f62c
Create Date: 2026-11-22 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = '6440869dea44'
down_revision: str | Sequence[str] | None = '919999c6f62c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LONG = sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql')
BLOB = sa.LargeBinary().with_variant(mysql.LONGBLOB(), 'mariadb').with_variant(mysql.LONGBLOB(), 'mysql')


def upgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reactions', LONG, server_default='', nullable=False))
    with op.batch_alter_table('profiles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('avatar', LONG, server_default='', nullable=False))
    op.create_table('photos',
    sa.Column('account', sa.String(length=40), nullable=False),
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('etag', LONG, nullable=False),
    sa.Column('mime', sa.String(length=40), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('data', BLOB, nullable=False),
    sa.Column('updated', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('account', 'key', name=op.f('pk_photos')),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_nopad_bin',
    mariadb_engine='InnoDB'
    )
    with op.batch_alter_table('photos', schema=None) as batch_op:
        batch_op.create_index('ix_photos_key', ['key'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('photos', schema=None) as batch_op:
        batch_op.drop_index('ix_photos_key')
    op.drop_table('photos')
    with op.batch_alter_table('profiles', schema=None) as batch_op:
        batch_op.drop_column('avatar')
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('reactions')

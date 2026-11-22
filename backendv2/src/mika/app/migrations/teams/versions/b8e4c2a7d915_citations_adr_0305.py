"""messages.quote : le message qu'un message cite (ADR 0305), séparé de son texte par l'extension ; vide pour ce qui
était là avant (rechargé, l'historique la reprend)

Revision ID: b8e4c2a7d915
Revises: 6440869dea44
Create Date: 2026-11-22 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = 'b8e4c2a7d915'
down_revision: str | Sequence[str] | None = '6440869dea44'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LONG = sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql')


def upgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('quote', LONG, server_default='', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('quote')

"""contacts.title, contacts.department, sightings.title, sightings.department : le poste et le service qu'un profil
Teams dit d'une personne (ADR 0298, lot 2) ; vides pour ce qui était là avant

Revision ID: a60efd22b77f
Revises: dba5d93227cf
Create Date: 2026-11-22 00:32:02.059495
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = 'a60efd22b77f'
down_revision: str | Sequence[str] | None = 'dba5d93227cf'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LONG = sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql')


def upgrade() -> None:
    for table in ('contacts', 'sightings'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('title', LONG, server_default='', nullable=False))
            batch_op.add_column(sa.Column('department', LONG, server_default='', nullable=False))


def downgrade() -> None:
    for table in ('sightings', 'contacts'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column('department')
            batch_op.drop_column('title')

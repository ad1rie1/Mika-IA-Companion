"""sightings.company : l'entreprise que le profil Teams d'une vue dit de sa personne — ce qui prouve, à qui voit cette
vue, qu'elle est de cette organisation (ADR 0298, relecture) ; vide pour ce qui était là avant

Revision ID: b3f1c0d2e4a5
Revises: 93842099e883
Create Date: 2026-11-22 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = 'b3f1c0d2e4a5'
down_revision: str | Sequence[str] | None = '93842099e883'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LONG = sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql')


def upgrade() -> None:
    with op.batch_alter_table('sightings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('company', LONG, server_default='', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('sightings', schema=None) as batch_op:
        batch_op.drop_column('company')

"""Les rappels du fournisseur et le nom donné dans Mika (ADR 0309, lot 6) : ``events.reminders`` devient une liste de
paires [minutes, méthode] (notification ou e-mail), ``events.reminders_default`` dit qu'un événement suit les rappels
de son agenda (Google), ``calendars.reminders`` les garde, ``calendars.alias`` est le nom qu'un agenda branché porte
dans Mika. Ce qui était gardé avant (des minutes seules, les rappels de l'agenda recopiés dans chaque événement)
s'efface, et la copie de chaque agenda branché se relit en entier à la synchronisation suivante (son curseur vidé) :
rien ne se convertit, le fournisseur redit tout.

Revision ID: f4a1c8e2d93b
Revises: e2b7c9d41a6f
Create Date: 2026-11-24 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = 'f4a1c8e2d93b'
down_revision: str | Sequence[str] | None = 'e2b7c9d41a6f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TEXT = sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql')
#: les colonnes que la mise à jour touche, nommées par SQLAlchemy (``cursor`` est un mot réservé de MariaDB)
_EVENTS = sa.table('events', sa.column('reminders'))
_CALENDARS = sa.table('calendars', sa.column('cursor'), sa.column('account'))


def upgrade() -> None:
    with op.batch_alter_table('calendars', schema=None) as batch_op:
        batch_op.add_column(sa.Column('alias', _TEXT, server_default='', nullable=False))
        batch_op.add_column(sa.Column('reminders', _TEXT, server_default='', nullable=False))
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reminders_default', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.execute(_EVENTS.update().values(reminders=''))
    op.execute(_CALENDARS.update().where(_CALENDARS.c.account.notlike('moi:%')).values(cursor=''))


def downgrade() -> None:
    op.execute(_EVENTS.update().values(reminders=''))
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_column('reminders_default')
    with op.batch_alter_table('calendars', schema=None) as batch_op:
        batch_op.drop_column('reminders')
        batch_op.drop_column('alias')

"""seen_elsewhere : les mails gardés ici, lus dans un autre client, que sa relève ne lui a pas encore dits (ADR 0308 :
le courrier en direct relit les drapeaux même quand elle dort) ; une base d'avant n'en attend aucun

Revision ID: adb86505dc3b
Revises: b8e41f6c2a97
Create Date: 2026-11-23 12:38:08.076214
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'adb86505dc3b'
down_revision: str | Sequence[str] | None = 'b8e41f6c2a97'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('seen_elsewhere',
    sa.Column('account', sa.String(length=40), nullable=False),
    sa.Column('ref', sa.String(length=400), nullable=False),
    sa.PrimaryKeyConstraint('account', 'ref', name=op.f('pk_seen_elsewhere')),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_nopad_bin',
    mariadb_engine='InnoDB'
    )


def downgrade() -> None:
    op.drop_table('seen_elsewhere')

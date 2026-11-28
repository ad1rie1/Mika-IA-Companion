"""folders.floor, folders.complete : jusqu'où une lecture de l'historique d'un dossier est descendue, et s'il est
gardé ici en entier (ADR 0249) ; un dossier d'avant n'a rien lu de son historique. forgotten_people : l'empreinte de
l'adresse d'un correspondant oublié et l'instant de l'oubli ; un oubli d'avant n'a retenu que les mails gardés

Revision ID: b8e41f6c2a97
Revises: 4d1a02f4407d
Create Date: 2026-11-18 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b8e41f6c2a97'
down_revision: str | Sequence[str] | None = '4d1a02f4407d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('forgotten_people',
    sa.Column('digest', sa.String(length=64), nullable=False),
    sa.Column('until', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('digest', name=op.f('pk_forgotten_people')),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_nopad_bin',
    mariadb_engine='InnoDB'
    )
    with op.batch_alter_table('folders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('floor', sa.BigInteger(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('complete', sa.Boolean(), server_default=sa.text('0'), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('folders', schema=None) as batch_op:
        batch_op.drop_column('complete')
        batch_op.drop_column('floor')
    op.drop_table('forgotten_people')

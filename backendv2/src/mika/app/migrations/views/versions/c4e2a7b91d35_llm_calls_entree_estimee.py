"""llm_calls : l'entrée estimée à côté de l'entrée réelle (audit du 2026-10-26, L9)

Revision ID: c4e2a7b91d35
Revises: a5d9d6a6af54
Create Date: 2026-10-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c4e2a7b91d35'
down_revision: str | Sequence[str] | None = 'a5d9d6a6af54'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('llm_calls', schema=None) as batch_op:
        batch_op.add_column(sa.Column('estimated_input_tokens', sa.BigInteger(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('llm_calls', schema=None) as batch_op:
        batch_op.drop_column('estimated_input_tokens')

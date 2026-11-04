"""un Teams par personne (ADR 0186) : chaque ligne porte son compte ; ce qui était là devient le compte « principal »

- ``accounts`` naît (le dernier lot de l'extension d'un compte, l'identifiant et le nom que Teams donne à sa
  personne) ; ce que ``meta`` savait de l'extension (``last_batch``, ``self_id``, ``self_name``) y devient la ligne
  de ``principal``, puis ``meta`` part ;
- ``conversations``, ``messages`` et ``drafts`` reçoivent ``account`` (``principal`` pour chaque ligne déjà là) ; une
  conversation se désigne désormais par son compte et son identifiant (sa clé primaire) ; les index de lecture d'une
  conversation et de la file commencent par le compte.

Les références des messages ne changent pas : celle d'un message du compte ``principal`` se calcule comme avant
(``ports.teams.message_ref``), ce que le journal en garde la retrouve.

Revision ID: a3c71e5d9b20
Revises: f7de680acc8b
Create Date: 2026-11-04 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = 'a3c71e5d9b20'
down_revision: str | Sequence[str] | None = 'f7de680acc8b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: le compte de ce qui était là (``ports.teams.DEFAULT_ACCOUNT`` : écrit ici, une révision ne dépend pas du code)
ACCOUNT = 'principal'
LONG = sa.Text().with_variant(mysql.LONGTEXT(), 'mariadb').with_variant(mysql.LONGTEXT(), 'mysql')


def _account() -> sa.Column:
    return sa.Column('account', sa.String(length=40), server_default=ACCOUNT, nullable=False)


def upgrade() -> None:
    op.create_table('accounts',
    sa.Column('key', sa.String(length=40), nullable=False),
    sa.Column('last_batch', sa.BigInteger(), nullable=False),
    sa.Column('self_id', LONG, nullable=False),
    sa.Column('self_name', LONG, nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_accounts')),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_nopad_bin',
    mariadb_engine='InnoDB'
    )
    # ce que ``meta`` savait de l'extension : la ligne du compte d'avant
    conn = op.get_bind()
    meta = sa.table('meta', sa.column('name', sa.String()), sa.column('value', sa.Text()))
    known = {str(name): str(value or '') for name, value in conn.execute(sa.select(meta.c.name, meta.c.value))}
    if known:
        try:
            last = int(known.get('last_batch') or 0)
        except ValueError:
            last = 0
        accounts = sa.table('accounts', sa.column('key', sa.String()), sa.column('last_batch', sa.BigInteger()),
                            sa.column('self_id', sa.Text()), sa.column('self_name', sa.Text()))
        conn.execute(sa.insert(accounts).values(key=ACCOUNT, last_batch=last, self_id=known.get('self_id', ''),
                                                self_name=known.get('self_name', '')))
    op.drop_table('meta')

    # une conversation : son compte et son identifiant
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(_account())
        batch_op.drop_constraint('pk_conversations', type_='primary')
        batch_op.create_primary_key('pk_conversations', ['account', 'id'])

    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(_account())
        batch_op.drop_index('ix_messages_conversation_at')
        batch_op.create_index('ix_messages_conversation_at', ['account', 'conversation', 'at'], unique=False)

    with op.batch_alter_table('drafts', schema=None) as batch_op:
        batch_op.add_column(_account())
        batch_op.drop_index('ix_drafts_open')
        batch_op.create_index('ix_drafts_open', ['account', 'state', 'conversation'], unique=False)


def downgrade() -> None:
    """Un seul Teams de nouveau : celui de ``principal`` ; les lignes des autres comptes partent."""
    for table in ('drafts', 'messages', 'conversations'):
        op.execute(sa.text(f"DELETE FROM {table} WHERE account <> :account").bindparams(account=ACCOUNT))
    with op.batch_alter_table('drafts', schema=None) as batch_op:
        batch_op.drop_index('ix_drafts_open')
        batch_op.create_index('ix_drafts_open', ['state', 'conversation'], unique=False)
        batch_op.drop_column('account')

    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_index('ix_messages_conversation_at')
        batch_op.create_index('ix_messages_conversation_at', ['conversation', 'at'], unique=False)
        batch_op.drop_column('account')

    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_constraint('pk_conversations', type_='primary')
        batch_op.create_primary_key('pk_conversations', ['id'])
        batch_op.drop_column('account')

    op.create_table('meta',
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.Column('value', LONG, nullable=False),
    sa.PrimaryKeyConstraint('name', name=op.f('pk_meta')),
    mariadb_charset='utf8mb4',
    mariadb_collate='utf8mb4_nopad_bin',
    mariadb_engine='InnoDB'
    )
    conn = op.get_bind()
    accounts = sa.table('accounts', sa.column('key', sa.String()), sa.column('last_batch', sa.BigInteger()),
                        sa.column('self_id', sa.Text()), sa.column('self_name', sa.Text()))
    row = conn.execute(sa.select(accounts.c.last_batch, accounts.c.self_id, accounts.c.self_name)
                       .where(accounts.c.key == ACCOUNT)).first()
    if row is not None:
        meta = sa.table('meta', sa.column('name', sa.String()), sa.column('value', sa.Text()))
        conn.execute(sa.insert(meta), [{'name': 'last_batch', 'value': str(row[0] or 0) if row[0] else ''},
                                       {'name': 'self_id', 'value': row[1] or ''},
                                       {'name': 'self_name', 'value': row[2] or ''}])
    op.drop_table('accounts')

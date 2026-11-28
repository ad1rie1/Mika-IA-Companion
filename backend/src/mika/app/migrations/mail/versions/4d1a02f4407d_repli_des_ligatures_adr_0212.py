"""les textes repliés déplient leurs ligatures (ADR 0212) : « sœur » se cherche aussi par « soeur »

Revision ID: 4d1a02f4407d
Revises: 7d0011ebffaa
Create Date: 2026-11-07 01:00:00.000000
"""

from collections.abc import Sequence

from mika.app.migrations import unfold_ligatures

revision: str = '4d1a02f4407d'
down_revision: str | Sequence[str] | None = '7d0011ebffaa'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    unfold_ligatures('messages', 'fold_subject', 'fold_sender', 'fold_dest', 'fold_body', 'fold_who')
    unfold_ligatures('drafts', 'fold_search')
    unfold_ligatures('sent', 'fold_subject', 'fold_dest', 'fold_body')
    unfold_ligatures('recipients', 'fold_who')


def downgrade() -> None:
    """Une ligature dépliée ne se refait pas : on ne sait plus quel « oe » en était une."""

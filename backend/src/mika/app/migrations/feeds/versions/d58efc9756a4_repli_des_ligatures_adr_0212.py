"""les textes repliés déplient leurs ligatures (ADR 0212) : « sœur » se cherche aussi par « soeur »

Revision ID: d58efc9756a4
Revises: efbc9585b3aa
Create Date: 2026-11-07 01:00:00.000000
"""

from collections.abc import Sequence

from mika.app.migrations import unfold_ligatures

revision: str = 'd58efc9756a4'
down_revision: str | Sequence[str] | None = 'efbc9585b3aa'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    unfold_ligatures('entries', 'feed_fold', 'text_fold')


def downgrade() -> None:
    """Une ligature dépliée ne se refait pas : on ne sait plus quel « oe » en était une."""

"""les textes repliés déplient leurs ligatures (ADR 0212) : « sœur » se cherche aussi par « soeur »

Revision ID: 5e315c8f113d
Revises: a3c71e5d9b20
Create Date: 2026-11-07 01:00:00.000000
"""

from collections.abc import Sequence

from mika.app.migrations import unfold_ligatures

revision: str = '5e315c8f113d'
down_revision: str | Sequence[str] | None = 'a3c71e5d9b20'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    unfold_ligatures('conversations', 'title_fold', 'id_fold')


def downgrade() -> None:
    """Une ligature dépliée ne se refait pas : on ne sait plus quel « oe » en était une."""

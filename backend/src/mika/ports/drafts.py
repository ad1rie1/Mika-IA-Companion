"""Ce qui vaut pour un brouillon, quel que soit son canal (le courrier, Teams) : la marque de ce qu'elle n'a pas su."""

from __future__ import annotations

import re

from mika.kernel.text import fold

#: ce qu'un brouillon ne peut pas contenir au moment de partir (ce qu'elle n'a pas su) ; reconnu sous
#: toutes ses graphies par ``to_fill`` (casse, accents, blancs, « à remplir », « à préciser »)
_TO_FILL = re.compile(r"\[\s*(?:a\s*)?(?:completer|remplir|preciser)\b")


def to_fill(*texts: str) -> bool:
    """Reste-t-il un « [À COMPLÉTER » (sous n'importe quelle graphie : casse, accents
    décomposés, blancs, « à remplir », « à préciser », crochets pleine chasse) ?"""
    return any(_TO_FILL.search(fold(text or "")) for text in texts)

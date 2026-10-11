"""Un au revoir (« bonne nuit », « à demain », « je file ») — pur.

Ce n'est pas une émotion : un acte de la conversation, qu'on reconnaît à sa forme (``others`` le lisait avec le ton,
ADR 0093 l'en sépare). Une personne qui clôt la conversation n'attend rien en retour.
"""

from __future__ import annotations

import re

from mika.vocab.words import fold

#: ce qui clôt une conversation (replié, sans accents) : on se dit au revoir, on va se coucher
_CLOSING = re.compile(
    r"\b(?:bonne\s+(?:nuit|soiree|journee|aprem|fin\s+de\s+(?:soiree|journee))|bon\s+(?:week-?end|weekend|aprem)|"
    r"a\s+(?:demain|plus(?:\s+tard)?|\+|tout\s+a\s+l'heure|bientot|la\s+prochaine|ce\s+soir|lundi|mardi|mercredi|"
    r"jeudi|vendredi|samedi|dimanche)|au\s+revoir|bisous?|bises|ciao|tchao|bye|dodo|je\s+(?:file|me\s+sauve|te\s+laisse|"
    r"me\s+deco|decroche|vais\s+(?:dormir|me\s+coucher|y\s+aller|bosser|travailler))|j'y\s+vais|"
    r"on\s+se\s+(?:parle|dit|voit)\s+(?:demain|plus\s+tard|ce\s+soir))\b|\ba\+(?!\w)")
#: au-delà, un message raconte autre chose qu'un au revoir
_CLOSING_MAX_WORDS = 15


def closing(text: str) -> bool:
    """La personne clôt-elle la conversation (« bonne nuit », « à demain », « je file ») ? Pas un message qui finit
    par une question (« bonne nuit, tu dors ? » attend encore quelque chose), ni un long message qui raconte autre
    chose. Y répondre n'attend rien en retour."""
    stripped = text.strip()
    if not stripped or stripped.endswith("?") or len(stripped.split()) > _CLOSING_MAX_WORDS:
        return False
    return bool(_CLOSING.search(fold(stripped).replace("’", "'")))

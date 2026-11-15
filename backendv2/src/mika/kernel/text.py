"""Une seule façon de traiter un texte, importable par tous : le replier pour le comparer (ADR 0212), le couper
pour le montrer."""

from __future__ import annotations

import unicodedata


def unaccented(text: str) -> str:
    """Le texte sans ses accents (NFKD, puis sans ses marques combinantes) ; sa casse et ses ligatures restent."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def fold(text: str) -> str:
    """Ce qu'on compare d'un texte : ni casse ni accents, les ligatures dépliées (« Sœur » → « soeur », NFKD ne les
    décompose pas). Replier ce qui l'est déjà ne change rien. Un texte qu'on garde replié, dans une base, change
    avec cette fonction : la changer, c'est le réécrire aussi."""
    return unaccented(text).casefold().replace("œ", "oe").replace("æ", "ae")


def clipped(text: str, limit: int) -> str:
    """Ce qu'on montre d'un texte en une ligne : ses blancs repliés en une espace ; au-delà de ``limit`` caractères,
    coupé et fini par « … », sans blanc devant, ellipse comprise dans ``limit``."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

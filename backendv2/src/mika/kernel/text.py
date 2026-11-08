"""Replier un texte pour le comparer : une seule façon de le faire, importable par tous (ADR 0212)."""

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

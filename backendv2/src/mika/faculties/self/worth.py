"""Ce qu'un message dit d'elle — et qui touche son estime. Pur, sans modèle
(il passe sur chaque message).

Un merci, un compliment qui la vise (« t'es géniale », « je t'adore »), une
insulte qui la vise (« t'es nulle », « ta gueule »). Ce qui se dit d'autre
chose (« ce film est nul », « merci de rien ») n'en dit rien ; la négation
(« t'es pas nulle ») non plus. Un indice, pas un verdict : l'estime ne bouge
que de petits coups, et la proximité de qui le dit pèse (``self``).
"""

from __future__ import annotations

import re

from mika.contracts import self_ as c
from mika.vocab.words import fold

_PUNCT = re.compile(r"[^a-z0-9]+")
_YOU = r"(?:t es|tu es|t etais|tu etais|t as ete|tu as ete|vous etes)"
_MORE = r"(?:(?:vraiment|trop|tellement|super|si|grave|carrement|vachement|la plus|le plus|la|le|une|un|qu une|qu un) )*"
_GOOD = (r"(?:geniale?|drole|gentille?|adorable|incroyable|top|cool|marrante?|intelligente?|forte?|meilleure?|"
         r"belle|mignonne|brillante?|parfaite?|amour|ange|chou|pepite|perle|creme|formidable|extra|"
         r"genie|star|reine)")
_BAD = (r"(?:nulle?|conne?|bete|stupide|idiote?|debile|inutile|chiante?|pathetique|moche|merde|connasse|salope|"
        r"abrutie?|cretine?|naze|pourrie?|ridicule|insupportable|lourde?|boulet)")

_INSULT = re.compile(
    rf" (?:{_YOU} {_MORE}{_BAD}|espece d {_MORE}{_BAD}|sale (?:ia|bot|robot|machine|conne|idiote)|ta gueule|"
    r"va te faire|tu sers a rien|je te deteste|je te hais|"
    r"t es qu une? (?:machine|robot|bot|ia)|connasse|salope|grosse merde) ")
_COMPLIMENT = re.compile(
    rf" (?:{_YOU} {_MORE}{_GOOD}|je t adore|je t aime|bien joue|bravo|tu geres|t assures|tu assures|"
    r"chapeau|t es au top|tu es au top|t es la meilleure) ")
_THANKS = re.compile(r" (?:merci+|thanks|thank you|thx|c est gentil|trop gentil) ")
#: « merci de rien », « non merci » : de la politesse qui refuse, pas un merci
_NOT_THANKS = re.compile(r" (?:non merci|merci de rien|merci pour rien|merci mais non|merci bien mais) ")
#: une moquerie qui rit (« t'es nulle mdr ») taquine, elle ne blesse pas
_TEASE = re.compile(r" (?:mdr|lol|ptdr|xd|jk|haha\w*|hihi\w*|hehe\w*|je rigole|je plaisante|je blague) ")
_TEASE_EMOJI = frozenset("😂🤣😜😝😛😉")
#: « je t'aime pas », « je te déteste plus » : la négation qui suit retourne le sens
_DENIED = frozenset({"pas", "plus", "jamais", "point"})


def _plain(text: str) -> str:
    return " " + _PUNCT.sub(" ", fold(text)).strip() + " "


def _said(pattern: re.Pattern[str], low: str) -> bool:
    """Le motif est dit, et pas aussitôt nié (« je t'aime pas »)."""
    return any(not _DENIED & set(low[m.end():].split()[:1]) for m in pattern.finditer(low))


def touched(text: str) -> str | None:
    """``INSULTED``, ``COMPLIMENTED``, ``THANKED`` ou ``None`` (le plus
    souvent). Une insulte l'emporte sur le reste du message."""
    low = _plain(text)
    if _said(_INSULT, low):
        teasing = _TEASE.search(low) or set(text) & _TEASE_EMOJI
        return None if teasing else c.INSULTED
    if _said(_COMPLIMENT, low):
        return c.COMPLIMENTED
    if _THANKS.search(low) and not _NOT_THANKS.search(low):
        return c.THANKED
    return None

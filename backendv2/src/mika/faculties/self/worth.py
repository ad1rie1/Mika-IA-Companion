"""Ce qu'un message dit d'elle — et qui touche son estime. Pur, sans modèle
(il passe sur chaque message).

Un merci, un compliment qui la vise (« t'es géniale », « je t'adore »), une
insulte qui la vise (« t'es nulle », « ta gueule »), des excuses (« pardon,
j'étais à cran, je le pensais pas »). Ce qui se dit d'autre chose (« ce film
est nul », « merci de rien ») n'en dit rien ; la négation (« t'es pas nulle »)
non plus ; une excuse qui rit (« pardon mdr »), une formule de politesse
(« pardon de te déranger », « pardon ? ») ou des condoléances (« désolée pour
ton chat ») ne sont pas des excuses. Un indice, pas un verdict : l'estime ne
bouge que de petits coups, et la proximité de qui le dit pèse (``self``).
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
_HARSH = r"(?:dur|dure|con|conne|mechant|mechante|nul|nulle|lourd|lourde|blessant|blessante|odieux|odieuse|injuste)"
#: des excuses : ce qu'on dit quand on regrette ce qu'on a dit ou fait
_APOLOGY = re.compile(
    r" (?:pardon|desolee?s?|dsl|je m excuse|je vous prie de m excuser|excuse moi|excusez moi|mes excuses|"
    r"toutes mes excuses|je le pensais pas|je ne le pensais pas|je pensais pas ce que j ai dit|"
    r"je retire ce que j ai dit|je suis allee? trop loin|j ai ete " + _MORE + _HARSH + r"|"
    r"c etait (?:pas sympa|mechant|nul de ma part|pas cool)) ")
#: … et ce qui en a la forme sans en être : la politesse (« pardon de te déranger », « excuse-moi, tu sais
#: où… »), les condoléances (« désolée pour ton chat »), « pardon ? » (« quoi ? »)
_NOT_APOLOGY = re.compile(
    r" (?:(?:pardon|desolee?s?|dsl|excuse moi|excusez moi) (?:de te deranger|de vous deranger|de deranger|"
    r"pour toi|pour vous|pour ta|pour ton|pour tes|pour ce qui t arrive|d insister|mais tu sais|"
    r"tu sais|vous savez|je peux)) ")


def _plain(text: str) -> str:
    return " " + _PUNCT.sub(" ", fold(text)).strip() + " "


def _said(pattern: re.Pattern[str], low: str) -> bool:
    """Le motif est dit, et pas aussitôt nié (« je t'aime pas »)."""
    return any(not _DENIED & set(low[m.end():].split()[:1]) for m in pattern.finditer(low))


def _owned(low: str) -> bool:
    """Des excuses dites, ni niées après (« désolé pas désolé ») ni avant (« je suis pas désolée »)."""
    return any(not _DENIED & set(low[m.end():].split()[:1]) and not _DENIED & set(low[:m.start()].split()[-1:])
               for m in _APOLOGY.finditer(low))


def apologized(text: str) -> bool:
    """Des excuses, dans la forme : pas en riant, pas une politesse, pas « pardon ? »."""
    low = _plain(text)
    if not _owned(low) or _NOT_APOLOGY.search(low):
        return False
    if low.strip() in ("pardon", "quoi pardon") and "?" in text:
        return False  # « pardon ? » : « quoi ? »
    return not (_TEASE.search(low) or set(text) & _TEASE_EMOJI)


def touched(text: str) -> str | None:
    """``INSULTED``, ``APOLOGIZED``, ``COMPLIMENTED``, ``THANKED`` ou ``None``
    (le plus souvent). Une insulte l'emporte sur le reste du message ; des
    excuses, sur un merci ou un compliment."""
    low = _plain(text)
    if _said(_INSULT, low):
        teasing = _TEASE.search(low) or set(text) & _TEASE_EMOJI
        return None if teasing else c.INSULTED
    if apologized(text):
        return c.APOLOGIZED
    if _said(_COMPLIMENT, low):
        return c.COMPLIMENTED
    if _THANKS.search(low) and not _NOT_THANKS.search(low):
        return c.THANKED
    return None

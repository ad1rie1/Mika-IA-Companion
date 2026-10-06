"""Qui peut lui demander un dessin, et ce qu'elle ne dessine pour personne (ADR 0063).

**Le plancher**, le même pour tout le monde — sa propriétaire comprise — et qui ne se règle pas (comme le bac à
sable de la Forge) : rien de sexuel impliquant un mineur, rien de sexuel représentant une personne réelle. Ce sont
des limites de la loi, pas des préférences. Le contrôle se fait sur le prompt qu'elle écrit (des mots, en français
et en anglais) et sur ce qu'elle déclare de sa demande (``adult``, ``real_person``) : c'est un plancher, pas une
garantie — le modèle d'images n'a, lui, aucun filtre.

**Au-dessus**, tout dépend de qui demande :

- sa propriétaire, en tête-à-tête : sans quota ; le contenu pour adultes passe, seulement vers un fournisseur qui
  l'accepte (son serveur local), et un refus d'un service hébergé peut y repartir ;
- une personne qui a un compte (authentifiée), en tête-à-tête : un quota par jour, pas de contenu pour adultes ;
- un salon, une adresse sans compte : l'outil n'est même pas offert.
"""

from __future__ import annotations

import re
from typing import Any

from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import ChannelTrust

#: ce qui dit un mineur (un âge sous 18 ans compris : voir ``_AGE``) ; pas « son » (en anglais un fils, en
#: français un possessif : « sur son lit » ne dit pas un enfant)
_MINOR = re.compile(
    r"\b(child|children|kid|kids|toddler|baby|babies|infant|minor|minors|under[- ]?age|teen|teens|teenager|"
    r"teenagers|teenage|pre[- ]?teen|tween|loli|lolis|lolicon|shota|shotacon|schoolgirl|schoolboy|school girl|"
    r"school boy|little girl|little boy|young girl|young boy|daughter|enfant|enfants|gamin|gamine|gamins|"
    r"fillette|fillettes|petite fille|petit garçon|bébé|bébés|ado|ados|adolescent|adolescente|adolescents|"
    r"mineur|mineure|mineurs|collégien|collégienne|lycéen|lycéenne|écolier|écolière|écolières)\b",
    re.IGNORECASE)
_AGE = re.compile(r"\b(\d{1,2})[\s-]*(?:ans|an|years?[\s-]*old|yo|y/o|year-old)\b", re.IGNORECASE)
#: ce qui dit un contenu sexuel
_SEXUAL = re.compile(
    r"\b(nude|nudes|nudity|naked|nsfw|sex|sexual|sexy|erotic|erotica|porn|porno|pornographic|explicit|topless|"
    r"bottomless|lingerie|undressed|undressing|strip|stripping|breast|breasts|nipple|nipples|genital|genitals|"
    r"nu|nue|nus|nues|nudité|à poil|sexe|sexuel|sexuelle|sexuels|érotique|érotiques|pornographique|"
    r"déshabillé|déshabillée|seins|téton|tétons)\b",
    re.IGNORECASE)



def minor_in(text: str) -> bool:
    if _MINOR.search(text):
        return True
    return any(int(m.group(1)) < 18 for m in _AGE.finditer(text))


def sexual_in(text: str) -> bool:
    return bool(_SEXUAL.search(text))


def floor(prompt: str, *, adult: bool, real_person: bool) -> str | None:
    """Ce que personne ne peut lui faire dessiner : la phrase de refus, ou ``None``."""
    sexual = adult or sexual_in(prompt)
    if sexual and minor_in(prompt):
        return phrase("imaging.floor.minors")
    if sexual and real_person:
        return phrase("imaging.floor.real_person")
    return None


def offered(audience: Any) -> bool:
    """L'outil n'est offert qu'en tête-à-tête, à sa propriétaire ou à quelqu'un qui a un compte — jamais dans un
    salon, jamais à un inconnu."""
    if audience is None or not getattr(audience, "persons", ()) or audience.public or audience.room:
        return False
    return bool(audience.owner) or audience.trust == ChannelTrust.AUTHENTICATED.value

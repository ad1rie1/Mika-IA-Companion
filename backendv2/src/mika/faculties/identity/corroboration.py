"""Être convaincue : ce que dit quelqu'un recoupe-t-il ce que seule la
personne qu'il prétend être pourrait savoir ?

Ne comptent que des souvenirs et croyances :

- sur la personne revendiquée, au moins **personnels** (l'anodin, tout le
  monde peut le savoir) ;
- appris **d'elle, en privé** : chaque message source vient d'une de ses
  adresses, hors d'un salon (un fait cité en groupe ne prouve rien) ;
- que Mika **n'a répété à personne d'autre** (sinon d'autres le savent) ;
- pas déjà utilisés comme preuve pour cette revendication.

Le recoupement est lexical (radicaux communs, noms et mots de conversation
exclus) : trois radicaux d'un même souvenir au moins. Fonctions pures ; les
lectures du magasin sont faites par l'appelant.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from mika.vocab.words import stems

MIN_OVERLAP = 3


@dataclass(frozen=True, slots=True)
class Candidate:
    id: int
    text: str


def overlap(message: str, text: str, *, exclude: Iterable[str] = ()) -> set[str]:
    banned = set()
    for name in exclude:
        banned |= stems(name, min_len=2)
    return (stems(message) & stems(text)) - banned


def corroborating(message: str, candidates: Sequence[Candidate], *, names: Iterable[str] = (),
                  minimum: int = MIN_OVERLAP) -> Candidate | None:
    """Le souvenir le mieux recoupé, s'il l'est assez."""
    names = tuple(names)
    best: tuple[int, int] | None = None
    found: Candidate | None = None
    for cand in candidates:
        n = len(overlap(message, cand.text, exclude=names))
        if n >= minimum and (best is None or (n, -cand.id) > best):
            best, found = (n, -cand.id), cand
    return found

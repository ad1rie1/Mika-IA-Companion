"""Ses centres d'intérêt (ADR 0089), partagés entre qui les fait vivre (``self``) et qui les lit (``goals`` pour ce
qu'elle va explorer, ``rss`` pour ce qu'elle remarque dans ses flux) — pur.

Un intérêt est de sa persona (une ligne écrite par l'opératrice : il s'endort, il ne disparaît jamais) ou vécu (né de
ce qu'elle a lu, exploré, de ce dont on lui a parlé : il naît, s'avive, s'endort et s'en va). Sa vivacité dit son
niveau — vif, présent, endormi — et ce qu'il pèse : dans ce qu'elle choisit d'explorer, dans ce qu'elle remarque.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from mika.vocab.words import fold, stems

PERSONA, LIVED = "persona", "lived"
VIVID, PRESENT, ASLEEP = "vivid", "present", "asleep"
#: ce que pèse un intérêt dans ce qu'elle choisit d'explorer, selon son niveau
EXPLORE_WEIGHT = {VIVID: 2.0, PRESENT: 1.0, ASLEEP: 0.25}
#: ce que pèsent ses mots dans ce qu'elle remarque de ses flux, selon son niveau
NOTICE_WEIGHT = {VIVID: 1.0, PRESENT: 1.0, ASLEEP: 0.5}

#: des mots de ses centres d'intérêt qui ne disent pas de quoi il s'agit (sa persona les rédige en phrases)
STOP = frozenset({"surtout", "mais", "sans", "avec", "pour", "dans", "tout", "tous", "toute", "toutes", "elle",
                  "joue", "grosse", "petite", "beaucoup", "assume", "resultats", "variables", "amateur", "etre",
                  "cette", "plus", "moins", "comme", "leur", "leurs", "notre", "votre", "seul", "sujet", "devient",
                  "google", "hardcore", "consommatrice"})
_WORD = re.compile(r"[a-z]{4,}")


@dataclass(frozen=True, slots=True)
class InterestView:
    """Un de ses centres d'intérêt, tel que les autres facultés le lisent (``self.interests``). ``line`` : la ligne
    de sa persona ; un intérêt vécu n'a que ses références (``label_ref``, ``detail_ref`` : son sujet et ce qu'il
    est, dits par elle — l'oubli d'une personne d'où il est né les efface)."""

    key: str
    origin: str
    level: str
    line: str = ""
    label_ref: str = ""
    detail_ref: str = ""
    about: tuple[str, ...] = ()
    born_at: int = 0


def subject_of(interest: str) -> str:
    """Un centre d'intérêt en quelques mots (la persona les rédige en phrases)."""
    head = re.split(r" \(| — | - |, ", interest.strip(), maxsplit=1)[0].strip()
    return head[:80] or interest[:80]


def topic_words(texts: Iterable[str]) -> frozenset[str]:
    """Les mots qui disent de quoi il s'agit (sans les mots vides), repliés."""
    found = {w for text in texts for w in _WORD.findall(fold(text))}
    return frozenset(w for w in found if w not in STOP)


def matches(title: str, summary: str, words: Iterable[str]) -> frozenset[str]:
    """Ceux de ces mots qu'un article contient (son titre et le début de son chapeau)."""
    return frozenset(set(_WORD.findall(fold(f"{title} {summary[:500]}"))) & set(words))


def pertinence(title: str, summary: str, words: Mapping[str, float] | Iterable[str]) -> float:
    """Ce qu'un article lui dit : rien sans un de ses mots, davantage avec plusieurs — chacun de ce qu'il pèse (un
    intérêt endormi la touche moins)."""
    weights = words if isinstance(words, Mapping) else dict.fromkeys(words, 1.0)
    found = matches(title, summary, weights)
    if not found:
        return 0.1
    return round(min(1.0, 0.35 + 0.25 * sum(weights[w] for w in found)), 3)


def same_topic(a: str, b: str) -> bool:
    """Deux sujets parlent-ils de la même chose ? Un mot de sens en commun (à la racine près)."""
    return bool(stems(" ".join(topic_words([a])), min_len=4) & stems(" ".join(topic_words([b])), min_len=4))

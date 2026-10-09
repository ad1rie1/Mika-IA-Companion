"""Une proposition et ses témoignages (ADR 0080) — fonctions pures.

Ce qu'elle croit est une **proposition** (une ligne de ``memory_items``) ; chaque façon dont elle l'a apprise est un
**témoignage** (``memory_testimonies``) : qui le lui a dit (ou elle-même : ``told_by`` vide), qui l'a entendu, à quel
point c'est sensible, si on lui a demandé de le garder pour soi, et ce que ce témoin y croit.

- **La confiance se met en commun** sur des témoins distincts : la meilleure confiance de chacun, puis celle du plus
  sûr, à laquelle s'ajoute une part (``CORROBORATION_WEIGHT``) de ce que chacun des autres apporte, en log-cotes,
  bornée à ``CEILING``. Ce que la même personne redit n'ajoute rien.
- **Un témoignage muet** (``speaks`` faux) vient d'un ancien renforcement (``memory.reinforced``), d'avant les
  témoignages : il compte pour la confiance, il n'ouvre aucune diffusion.
- **Qui a raison** (ADR 0081) ne dépend pas de qui l'a entendu : une correction remplace ce qu'elle croyait quand
  elle vient d'une source au moins aussi sûre (``rank``) — la personne concernée qui parle d'elle-même, ce qu'elle a
  vu, un témoin de première main —, ou du même témoin qui se corrige ; sinon elle **conteste** : les deux restent,
  et elle doute.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

#: ce qu'un témoin de plus apporte, en part de ses log-cotes : deux témoins à 0,8 font ~0,89 (un ancien renfort
#: corroboré ajoutait 0,1)
CORROBORATION_WEIGHT = 0.5
#: aucune croyance n'est jamais tout à fait sûre
CEILING = 0.95


@dataclass(frozen=True, slots=True)
class Testimony:
    seq: int
    told_by: tuple[str, ...]
    heard_by: tuple[str, ...]
    sensitivity: int
    secret: bool
    confidence: float
    informants: tuple[str, ...] = ()
    origin: str = "told"
    at: int = 0
    between_us: bool = False
    #: un témoignage d'avant (un ancien renforcement) : la confiance, jamais la diffusion
    speaks: bool = True
    #: de première main : la personne concernée qui parle d'elle-même, ou un témoin qui l'a vu (ADR 0081)
    first_hand: bool = False

    @property
    def informant(self) -> str:
        """Qui le lui a appris (``""`` : elle-même, ou personne de nommé)."""
        return ",".join(sorted(self.informants or self.told_by))


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def pooled(testimonies: Iterable[Testimony], weight: float = CORROBORATION_WEIGHT,
           ceiling: float = CEILING) -> float | None:
    """La confiance de ces témoignages ensemble : le meilleur de chaque témoin, puis le plus sûr plus une part de
    chacun des autres. ``None`` : aucun témoignage."""
    best: dict[str, float] = {}
    for t in testimonies:
        best[t.informant] = max(best.get(t.informant, 0.0), float(t.confidence))
    if not best:
        return None
    ranked = sorted(best.values(), reverse=True)
    score = _logit(ranked[0]) + weight * sum(max(0.0, _logit(c)) for c in ranked[1:])
    return min(ceiling, 1 / (1 + math.exp(-score)))


#: un jugement de vérité : la nouvelle remplace l'ancienne, ou la conteste (les deux restent)
SUPERSEDE, CONTEST = "supersede", "contest"
#: ce qu'elle a vu, ce que la personne concernée dit d'elle-même, ce qu'un témoin a vu : sûr
FIRST_HAND_RANK = 2


def rank(t: Testimony, *, about_self: bool = False) -> int:
    """La sûreté d'un témoignage : 3, elle-même, ou la personne concernée qui parle d'elle ; 2, ce qu'elle a vu, ou un
    témoin de première main ; 1, rapporté ; 0, une déduction."""
    if about_self or (t.first_hand and t.told_by):
        return 3
    if t.origin == "observed" or t.first_hand:
        return FIRST_HAND_RANK
    if t.origin == "inferred":
        return 0
    return 1


def judge(old: Iterable[Testimony], new: Testimony, *, about_self: bool = False) -> str:
    """Une nouvelle parole contredit ce qu'elle croyait : la remplace-t-elle, ou la conteste-t-elle ? Le même témoin
    qui se corrige remplace ; une source au moins aussi sûre que la plus sûre d'avant, et de première main, remplace ;
    sinon elle conteste — un ragot ne remplace pas ce qu'Alice a dit d'elle-même."""
    said = [t for t in old if t.speaks] or list(old)
    if new.told_by and any(set(t.told_by) == set(new.told_by) for t in said):
        return SUPERSEDE
    best = max((rank(t, about_self=about_self) for t in said), default=0)
    mine = rank(new, about_self=about_self)
    return SUPERSEDE if mine >= FIRST_HAND_RANK and mine >= best else CONTEST

"""Une proposition et ses témoignages (ADR 0080, 0081) : les mettre en commun, dire qui a raison, et les retrouver.

Ce qu'elle croit est une **proposition** (une ligne de ``memory_items``) ; chaque façon dont elle l'a apprise est un
**témoignage** (``memory_testimonies`` ; sa forme lue, ``tables.Testimony``) : qui le lui a dit (ou elle-même :
``told_by`` vide), qui l'a entendu, à quel point c'est sensible, si on lui a demandé de le garder pour soi, et ce que
ce témoin y croit.

Les règles, pures :

- **La confiance se met en commun** (``pooled``) sur des témoins distincts : la meilleure confiance de chacun, puis
  celle du plus sûr, à laquelle s'ajoute une part (``CORROBORATION_WEIGHT``) de ce que chacun des autres apporte, en
  log-cotes, bornée à ``CEILING``. Ce que la même personne redit n'ajoute rien.
- **Un témoignage muet** (``speaks`` faux) vient d'un ancien renforcement (``memory.reinforced``), d'avant les
  témoignages : il compte pour la confiance, il n'ouvre aucune diffusion.
- **Qui a raison** (ADR 0081, ``judge``) ne dépend pas de qui l'a entendu : une correction remplace ce qu'elle
  croyait quand elle vient d'une source au moins aussi sûre (``rank``) — la personne concernée qui parle d'elle-même,
  ce qu'elle a vu, un témoin de première main —, ou du même témoin qui se corrige ; sinon elle **conteste** : les deux
  restent, et elle doute.

Retrouver une croyance et ses témoins — une seule façon de dire qu'un élément est le même, ou ce qu'une correction
désigne :

- ``twin_of`` : le doublon exact d'un élément — un souvenir : le même, confié et entendu par les mêmes ; une
  croyance : la même proposition, quel qu'en soit le témoin (ADR 0080) ;
- ``target_of`` : la croyance qu'une correction désigne, si elle peut l'être (ADR 0081) ;
- ``testimonies_of`` : ses témoignages, dans l'ordre où ils sont venus ;
- ``former_twin`` et ``head_of`` : la croyance qu'elle a cessé de croire, aux mêmes mots, et ce qui l'a remplacée
  jusqu'à ce qu'elle croit maintenant.

Ce que le code garde d'une relecture (``kept.py``) et la relecture de la nuit (``reread.py``) les lisent (ADR 0153) ;
le verdict de ce qui peut se dire ici (``hearing.py``) et la projection (``projections.py``) mettent la confiance en
commun.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select

from mika.contracts import memory as c
from mika.faculties.memory import tables as tb
from mika.faculties.memory.tables import Testimony, fingerprint, keys_json, testimony_columns, testimony_of
from mika.vocab.words import same_words

# ── Les règles, pures : la confiance en commun, qui a raison ───────────────


#: ce qu'un témoin de plus apporte, en part de ses log-cotes : deux témoins à 0,8 font ~0,89 (un ancien renfort
#: corroboré ajoutait 0,1)
CORROBORATION_WEIGHT = 0.5
#: aucune croyance n'est jamais tout à fait sûre
CEILING = 0.95


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
    if t.origin == c.OBSERVED or t.first_hand:
        return FIRST_HAND_RANK
    if t.origin == c.INFERRED:
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


# ── Retrouver une croyance et ses témoins ─────────────────────────────────


def twin_of(store: Any, text: str, kind: str, about: tuple[str, ...], *, told_by: tuple[str, ...] = (),
            heard_by: tuple[str, ...] = (), knowledge_kind: str = "claim", holder: str | None = None,
            about_self: bool = False) -> int | None:
    """Doublon exact indexé, sans dépendre des cinq voisins vectoriels les plus proches. Un souvenir : le même,
    confié et entendu par les mêmes. Une croyance : **la même proposition**, quel qu'en soit le témoin — ce
    qu'un autre lui en dira sera un témoignage de plus (ADR 0080) ; un avis ou une hypothèse restent à qui les
    porte ; la plus ancienne. Les listes se comparent écrites comme la projection les range (``keys_json`` : triées,
    sans doublon ni clé vide)."""
    t = tb.items()
    if kind == c.BELIEF:
        rows = store.query_mind(
            select(t.c.id, t.c.text, t.c.knowledge_kind, t.c.holder)
            .where(t.c.fingerprint == fingerprint(text), t.c.kind == kind, t.c.status == c.ACTIVE_STATUS,
                   t.c.about == keys_json(about),
                   t.c.about_self > 0 if about_self else t.c.about_self <= 0).order_by(t.c.id))
        for k, previous, nature, owner in rows:
            if same_words(previous, text) and nature == knowledge_kind \
                    and (knowledge_kind == "claim" or (owner or None) == (holder or None)):
                return int(k)
        return None
    encoded = tuple(keys_json(keys) for keys in (about, told_by, heard_by))
    rows = store.query_mind(
        select(t.c.id, t.c.text).where(t.c.fingerprint == fingerprint(text), t.c.kind == kind,
                                       t.c.status == c.ACTIVE_STATUS, t.c.about == encoded[0], t.c.told_by == encoded[1],
                                       t.c.heard_by == encoded[2]).order_by(t.c.id))
    for k, previous in rows:
        if same_words(previous, text):
            return int(k)
    return None


def target_of(store: Any, item: int | None, nature: str, holder: str | None, *,
              about_self: bool = False) -> int | None:
    """La croyance qu'une correction désigne, si elle peut l'être (ADR 0081) : vivante, de même sorte (sur elle,
    ou pas). L'audience n'y est pour rien — qui l'a entendue ne décide pas de ce qui est vrai. Un avis ou un goût
    d'un autre porteur ne se corrige pas : deux avis, deux porteurs, aucun n'a tort."""
    if item is None:
        return None
    t = tb.items()
    rows = store.query_mind(select(t.c.knowledge_kind, t.c.holder, t.c.about_self)
                            .where(t.c.id == item, t.c.kind == c.BELIEF, t.c.status == c.ACTIVE_STATUS))
    if not rows:
        return None
    kind, owner, self_item = rows[0]
    if bool(self_item) != about_self:
        return None
    personal = {"opinion", "preference"}
    if not about_self and (kind in personal or nature in personal) and (owner or None) != (holder or None):
        return None
    return item


def testimonies_of(store: Any, item: int | None) -> list[Testimony]:
    if item is None:
        return []
    tt = tb.testimonies()
    return [testimony_of(r) for r in store.query_mind(
        select(*testimony_columns()).where(tt.c.item == item).order_by(tt.c.seq))]


def former_twin(store: Any, text: str, about: tuple[str, ...], nature: str, holder: str | None) -> int | None:
    """Une croyance qu'elle a cessé de croire (remplacée), aux mêmes mots : redite, elle revient."""
    t = tb.items()
    rows = store.query_mind(
        select(t.c.id, t.c.text, t.c.knowledge_kind, t.c.holder)
        .where(t.c.fingerprint == fingerprint(text), t.c.kind == c.BELIEF, t.c.status == c.SUPERSEDED_STATUS,
               t.c.about == keys_json(about), t.c.about_self == 0)
        .order_by(t.c.id.desc()))
    for k, previous, kind, owner in rows:
        if same_words(previous, text) and kind == nature and (nature == "claim" or (owner or None) == (holder or None)):
            return int(k)
    return None


def head_of(store: Any, item: int) -> int | None:
    """Ce qui l'a remplacée, de remplacement en remplacement, jusqu'à ce qu'elle croit maintenant."""
    seen: set[int] = set()
    current: int | None = item
    while current is not None and current not in seen and len(seen) < 16:
        seen.add(current)
        t = tb.items()
        rows = store.query_mind(select(t.c.status, t.c.superseded_by).where(t.c.id == current))
        if not rows:
            return None
        status, after = rows[0]
        if status == c.ACTIVE_STATUS:
            return current if current != item else None
        current = after
    return None

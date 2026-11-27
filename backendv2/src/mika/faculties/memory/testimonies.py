"""Retrouver une croyance et ses témoins : une seule façon de dire qu'un élément est le même, ou ce qu'une
correction désigne.

- ``twin_of`` : le doublon exact d'un élément — un souvenir : le même, confié et entendu par les mêmes ; une
  croyance : la même proposition, quel qu'en soit le témoin (ADR 0080) ;
- ``target_of`` : la croyance qu'une correction désigne, si elle peut l'être (ADR 0081) ;
- ``testimonies_of`` : ses témoignages, dans l'ordre où ils sont venus ;
- ``former_twin`` et ``head_of`` : la croyance qu'elle a cessé de croire, aux mêmes mots, et ce qui l'a remplacée
  jusqu'à ce qu'elle croit maintenant.

Ce que le code garde d'une relecture (``kept.py``) et la relecture de la nuit (``reread.py``) les lisent (ADR 0153).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from mika.contracts import memory as c
from mika.faculties.memory import tables as tb
from mika.faculties.memory.tables import Testimony, fingerprint, keys_json, testimony_columns, testimony_of
from mika.vocab.words import same_words


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

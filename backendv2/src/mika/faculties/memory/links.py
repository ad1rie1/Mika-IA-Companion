"""« Aucun lien connu » (ADR 0091) : avant de raconter sans nom ce qu'elle sait de quelqu'un, s'assurer que qui
l'écoute n'a aucun lien connu avec la personne — sinon, même sans prénom, il la reconnaîtrait.

Un lien qui *ouvre* doit être prouvé, un lien qui *ferme* seulement soupçonné : tout ce qui rapproche les deux
ferme — un lien que le graphe social connaît (dans un sens ou dans l'autre), un salon où ils ont parlé tous les
deux, un élément de sa mémoire qui les nomme ensemble, l'un qui lui a parlé de l'autre (une mention qu'elle présume
désigner l'autre comprise), le nom de l'un dans ce que l'autre lui a écrit (tout l'historique), ce qu'elle a déjà
raconté nommément de la personne à qui l'écoute ; un nom qu'elle ne connaît pas, et toute panne, ferment aussi
(``None``). Au second degré (``depth`` 2, le réglage ``veiled_link_depth``) : quelqu'un que le graphe social relie aux
deux — une relation dans un sens ou dans l'autre, quel qu'en soit l'état — ferme aussi : une amie commune
reconnaîtrait « une amie qui vient de se séparer » (ADR 0092). Le graphe (``contracts.social.RELATIONS_TABLE``) se lit
sans s'écrire.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import literal, or_, select, union

from mika.contracts import identity as identity_c
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.memory.tables import about, handle_key, items, prefixed, told
from mika.kernel.frame import Frame
from mika.ports.paging import fold_text
from mika.ports.sql import alias_of, json_has
from mika.vocab.people import fold

log = logging.getLogger(__name__)


def handles_of(frame: Frame, person: str) -> tuple[str, ...]:
    return tuple(sorted({person, *frame.get(identity_c.HANDLES(person))}))


def _keys(values: tuple[str, ...]) -> list[str]:
    return sorted({handle_key(v) for v in values})


def _named_in(store: Any, writers: tuple[str, ...], name: str) -> bool:
    """Le nom (ou le prénom) de quelqu'un paraît-il dans ce que ces adresses lui ont écrit — sur tout l'historique ?
    La base n'en rend que les messages dont le texte replié (``folded`` : casse et accents ignorés, pareil sur les deux
    moteurs) contient le prénom replié ; le mot entier se vérifie ici (« Léa » n'est pas dans « léard »)."""
    parts = re.findall(r"\w+", fold(name))
    raw = re.findall(r"\w+", name)
    if not parts or len(parts[0]) < 3:
        return False
    t = transcript_c.thread_table()
    rows = store.query_mind(select(t.c.text).where(t.c.role == "user", t.c.person.in_(_keys(writers)),
                                                   t.c.folded.contains(fold_text(raw[0] if raw else parts[0]),
                                                                       autoescape=True)))
    first, full = f" {parts[0]} ", f" {' '.join(parts)} "
    for (text,) in rows:
        said = " " + " ".join(re.findall(r"\w+", fold(text or ""))) + " "
        if first in said or full in said:
            return True
    return False


def written(store: Any, writers: tuple[str, ...], names: tuple[str, ...]) -> bool:
    """L'un de ces prénoms paraît-il dans ce que ces adresses lui ont écrit ? (un détail d'une histoire — « Paul », l'ex
    d'Alice — que l'auditeur connaîtrait)"""
    return any(_named_in(store, writers, name) for name in names)


def _related(store: Any, a: tuple[str, ...], b: tuple[str, ...], depth: int) -> bool:
    """Le graphe social les relie-t-il — directement, ou (``depth`` 2) par quelqu'un qui connaît les deux ? Une
    relation dans un sens ou dans l'autre, quel qu'en soit l'état : un lien qui ferme n'a pas à être prouvé."""
    ka, kb = _keys(a), _keys(b)
    r = social_c.relations_table()
    edges = union(select(r.c.subject.label("x"), r.c.other.label("y")),
                  select(r.c.other.label("x"), r.c.subject.label("y")))
    e = edges.subquery("e")
    if store.query_mind(select(literal(1)).select_from(e).where(e.c.x.in_(ka), e.c.y.in_(kb)).limit(1)):
        return True
    if depth < 2:
        return False
    p, q = edges.subquery("p"), edges.subquery("q")
    return bool(store.query_mind(
        select(literal(1)).select_from(p.join(q, p.c.y == q.c.y))
        .where(p.c.x.in_(ka), q.c.x.in_(kb), p.c.y.not_in(ka), p.c.y.not_in(kb)).limit(1)))


def _rooms(store: Any, handles: tuple[str, ...]) -> set[str]:
    t = transcript_c.thread_table()
    return {str(r) for (r,) in store.query_mind(
        select(t.c.room).distinct().where(t.c.room.is_not(None), t.c.person.in_(_keys(handles))))}


def _told_about(store: Any, tellers: tuple[str, ...], about_: tuple[str, ...]) -> bool:
    """L'un de ces témoins lui a-t-il parlé de l'une de ces clés (un élément qui les concerne, confié par lui) ?"""
    if not tellers:
        return False
    a, i = alias_of(about(), "a"), alias_of(items(), "i")
    return bool(store.query_mind(
        select(literal(1)).select_from(a.join(i, i.c.id == a.c.item))
        .where(a.c.person.in_(_keys(about_)), or_(*(json_has(i.c.told_by, t) for t in sorted(set(tellers)))))
        .limit(1)))


def _named_together(store: Any, a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    x, y = alias_of(about(), "x"), alias_of(about(), "y")
    return bool(store.query_mind(
        select(literal(1)).select_from(x.join(y, x.c.item == y.c.item))
        .where(x.c.person.in_(_keys(a)), y.c.person.in_(_keys(b))).limit(1)))


def _told_named(store: Any, listener: tuple[str, ...], about_: tuple[str, ...]) -> bool:
    """Lui a-t-elle déjà raconté nommément quelque chose de la personne ?"""
    t, a = alias_of(told(), "t"), alias_of(about(), "a")
    return bool(store.query_mind(
        select(literal(1)).select_from(t.join(a, a.c.item == t.c.item))
        .where(t.c.veiled == 0, t.c.handle.in_(_keys(listener)), a.c.person.in_(_keys(about_))).limit(1)))


def _presumed_keys(store: Any, frame: Frame, person: str) -> tuple[str, ...]:
    """Les mentions (``name:…``) qu'elle présume désigner la personne (ADR 0075), dans ce qu'elle sait et dans le
    graphe social."""
    ab, r = about(), social_c.relations_table()
    keys = {str(k) for (k,) in store.query_mind(union(
        select(ab.c.person).where(prefixed(ab.c.person, "name:")),
        select(r.c.subject).where(prefixed(r.c.subject, "name:")),
        select(r.c.other).where(prefixed(r.c.other, "name:"))))}
    return tuple(sorted(k for k in keys if frame.get(identity_c.PRESUMED(k)) == person))


def links_of(frame: Frame, store: Any, listener: str, person: str, memo: dict[tuple[str, str], bool | None], *,
             depth: int = 2) -> bool | None:
    """Un lien connu entre qui l'écoute et la personne : vrai, faux, ou ``None`` (on n'a pas pu le savoir — ferme).
    ``depth`` : 1, les liens directs ; 2, aussi quelqu'un que le graphe social relie aux deux."""
    key = (listener, person)
    if key not in memo:
        try:
            memo[key] = _linked(frame, store, listener, person, depth)
        except Exception as exc:  # noqa: BLE001 — une panne ferme : dans le doute, rien ne se raconte
            log.warning("lien entre deux personnes illisible : %s", type(exc).__name__)
            memo[key] = None
    return memo[key]


def _linked(frame: Frame, store: Any, listener: str, person: str, depth: int) -> bool:
    if listener == person:
        return True
    name, heard = frame.get(identity_c.IDENTITY(person)).name, frame.get(identity_c.IDENTITY(listener)).name
    if not name:
        return True  # un nom qu'elle ne connaît pas : elle ne sait pas qui il ne doit pas reconnaître
    if person in frame.get(social_c.TIES(listener)) or listener in frame.get(social_c.TIES(person)):
        return True
    mine, theirs = handles_of(frame, listener), handles_of(frame, person)
    # une mention qu'elle présume désigner l'un ou l'autre compte pour lui : « Bob, mon collègue », dit par Alice, la
    # relie à Bob — un lien qui ferme n'a pas à être prouvé
    about_me = (*mine, *_presumed_keys(store, frame, listener))
    about_them = (*theirs, *_presumed_keys(store, frame, person))
    if _rooms(store, mine) & _rooms(store, theirs):
        return True
    if _related(store, about_me, about_them, depth):
        return True
    if _named_together(store, about_me, about_them):
        return True
    if _told_about(store, mine, about_them) or _told_about(store, theirs, about_me):
        return True
    if _named_in(store, mine, name) or (heard and _named_in(store, theirs, heard)):
        return True
    return _told_named(store, mine, about_them)

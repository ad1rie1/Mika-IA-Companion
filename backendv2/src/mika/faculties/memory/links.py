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

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.kernel.frame import Frame
from mika.vocab.people import fold

log = logging.getLogger(__name__)


def handles_of(frame: Frame, person: str) -> tuple[str, ...]:
    return tuple(sorted({person, *frame.get(identity_c.HANDLES(person))}))


def _spellings(word: str) -> tuple[str, ...]:
    """Les graphies d'un mot qu'un ``LIKE`` de SQLite ne confond pas d'office (il ne replie la casse que des lettres
    sans accent) : « inès », « Inès », « INÈS », « ines »."""
    low = word.lower()
    return tuple(dict.fromkeys((low, low[:1].upper() + low[1:], low.upper(), fold(low))))


def _like(word: str) -> str:
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _named_in(store: Any, writers: tuple[str, ...], name: str) -> bool:
    """Le nom (ou le prénom) de quelqu'un paraît-il dans ce que ces adresses lui ont écrit — sur tout l'historique ?
    La base n'en rend que les messages qui contiennent le prénom sous une de ses graphies ; le mot entier se vérifie
    ici (« Léa » n'est pas dans « léard »)."""
    parts = re.findall(r"\w+", fold(name))
    raw = re.findall(r"\w+", name)
    if not parts or len(parts[0]) < 3:
        return False
    marks = ",".join("?" * len(writers))
    spellings = _spellings(raw[0] if raw else parts[0])
    likes = " OR ".join("text LIKE ? ESCAPE '\\'" for _ in spellings)
    rows = store.query_mind(f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE role='user' AND person IN ({marks}) "
                            f"AND ({likes})", (*writers, *(_like(w) for w in spellings)))
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
    ma, mb = ",".join("?" * len(a)), ",".join("?" * len(b))
    edges = (f"(SELECT subject AS x, other AS y FROM {social_c.RELATIONS_TABLE} "
             f"UNION SELECT other, subject FROM {social_c.RELATIONS_TABLE})")
    if store.query_mind(f"SELECT 1 FROM {edges} WHERE x IN ({ma}) AND y IN ({mb}) LIMIT 1", (*a, *b)):
        return True
    if depth < 2:
        return False
    return bool(store.query_mind(
        f"SELECT 1 FROM {edges} p JOIN {edges} q ON p.y = q.y WHERE p.x IN ({ma}) AND q.x IN ({mb}) "
        f"AND p.y NOT IN ({ma}) AND p.y NOT IN ({mb}) LIMIT 1", (*a, *b, *a, *b)))


def _rooms(store: Any, handles: tuple[str, ...]) -> set[str]:
    marks = ",".join("?" * len(handles))
    return {str(r) for (r,) in store.query_mind(
        f"SELECT DISTINCT room FROM {transcript_c.THREAD_TABLE} WHERE room IS NOT NULL AND person IN ({marks})",
        handles)}


def _told_about(store: Any, tellers: tuple[str, ...], about: tuple[str, ...]) -> bool:
    """L'un de ces témoins lui a-t-il parlé de l'une de ces clés (un élément qui les concerne, confié par lui) ?"""
    marks = ",".join("?" * len(about))
    rows = store.query_mind(f"SELECT DISTINCT i.told_by FROM {c.ABOUT_TABLE} a JOIN {c.ITEMS_TABLE} i ON i.id = a.item "
                            f"WHERE a.person IN ({marks})", about)
    return any(f'"{t}"' in (told or "") for (told,) in rows for t in tellers)


def _named_together(store: Any, a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    ma, mb = ",".join("?" * len(a)), ",".join("?" * len(b))
    return bool(store.query_mind(
        f"SELECT 1 FROM {c.ABOUT_TABLE} x JOIN {c.ABOUT_TABLE} y ON x.item = y.item "
        f"WHERE x.person IN ({ma}) AND y.person IN ({mb}) LIMIT 1", (*a, *b)))


def _told_named(store: Any, listener: tuple[str, ...], about: tuple[str, ...]) -> bool:
    """Lui a-t-elle déjà raconté nommément quelque chose de la personne ?"""
    ml, ma = ",".join("?" * len(listener)), ",".join("?" * len(about))
    return bool(store.query_mind(
        f"SELECT 1 FROM {c.TOLD_TABLE} t JOIN {c.ABOUT_TABLE} a ON a.item = t.item "
        f"WHERE t.veiled = 0 AND t.handle IN ({ml}) AND a.person IN ({ma}) LIMIT 1", (*listener, *about)))


def _presumed_keys(store: Any, frame: Frame, person: str) -> tuple[str, ...]:
    """Les mentions (``name:…``) qu'elle présume désigner la personne (ADR 0075), dans ce qu'elle sait et dans le
    graphe social."""
    keys = {str(k) for (k,) in store.query_mind(
        f"SELECT person FROM {c.ABOUT_TABLE} WHERE person LIKE 'name:%' "
        f"UNION SELECT subject FROM {social_c.RELATIONS_TABLE} WHERE subject LIKE 'name:%' "
        f"UNION SELECT other FROM {social_c.RELATIONS_TABLE} WHERE other LIKE 'name:%'")}
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

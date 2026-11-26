"""« L'agenda de Mika » (ADR 0309, lot 3b) : ses dates à venir, montrées comme un agenda — sans rien recopier.

Elle a déjà ses dates : ses **promesses datées** (``memory.promises_to``), **les moments de la vie des gens** qu'elle
retient (``memory.life_events`` : à venir, et les dates qui reviennent chaque année à leur prochaine fois) et **ce
qu'elle voit venir** dans le monde (``memory.ahead``). Cette lecture les rend comme des événements — un titre (son
texte, tel que sa mémoire le garde), quand, et d'où ça vient (qui, quand c'est arrivé jusqu'à elle, la conversation,
la référence de l'élément de sa mémoire). On ne l'édite pas : on le lui dit (« c'est reporté », « oublie ça »).

- **Pour une personne** (``person``, l'API par personne) : seulement ce qui la concerne — ce qu'elle lui a promis, et
  les moments de sa vie à elle qu'elle lui a racontés elle-même (``told_by`` : elle seule). Jamais ce qu'une autre a
  confié, rien de secret, et chaque élément passe par le verdict commun de sa mémoire, devant la personne seule
  (``vocab.lineage.admits`` sur ``vocab.privacy.private_to``) : ce que ses sources restreignent reste tu. Ce qu'elle
  voit venir dans le monde n'y est pas.
- **Pour la console** (``person=None``) : tout, chaque date avec les personnes qu'elle concerne (``persons`` : la
  console choisit par personne), et si elle est secrète.

Elle ne lit sa mémoire que par sa porte (``contracts.memory`` : ses faits, et la vue ``KNOWLEDGE`` pour la filiation et
les messages d'où vient chaque élément) ; le message source se relit au journal (quand, par quelle adresse).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.kernel.clock import DAY, HOUR, MINUTE, local
from mika.kernel.frame import Frame
from mika.plugins.agenda.when import midnight
from mika.vocab.circadian import day_fr
from mika.vocab.knowledge import Known, knowns
from mika.vocab.lineage import admits
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import private_to

#: ce qu'elle a promis ; un moment de la vie de quelqu'un ; une date qui revient chaque année ; ce qu'elle voit venir
#: dans le monde
PROMISE, MOMENT, YEARLY, AHEAD = "promesse", "moment", "chaque_annee", "voir_venir"
#: une promesse à une heure se montre un quart d'heure ; un moment à une heure sans fin dite, une heure
PROMISE_SPAN, MOMENT_SPAN = 15 * MINUTE, HOUR
#: sans période demandée : d'aujourd'hui à un an devant
AHEAD_DEFAULT = 366 * DAY
#: ce qui ne se tient plus (un moment annulé, reporté : ce qui le remplace est noté à part)
NOT_HAPPENING = frozenset({memory_c.CANCELLED, memory_c.MOVED})


@dataclass(frozen=True, slots=True)
class HerDate:
    """Une date de son agenda : ``ref`` l'élément de sa mémoire (``memory:<n°>``, ce que Mémoire › Promesses et La vie
    des autres ouvrent) ; ``kind`` ce que c'est (``PROMISE``, ``MOMENT``, ``YEARLY``, ``AHEAD``) ; ``title`` son texte ;
    quand (``start``, ``end`` en µs ; une journée entière : de minuit à minuit, ``day`` sa date) ; ``persons`` qui elle
    concerne (leurs clés) ; d'où ça vient — ``said_at`` (le message d'où il vient, sinon quand elle l'a retenu),
    ``source`` (en mots), ``conversation`` (``chat:<adresse>:<message>``, vide si on ne le sait pas), ``sources`` (les
    messages) ; ``secret`` : à ne redire qu'à qui l'a confié (la console seule le montre)."""

    ref: str
    kind: str
    title: str
    start: int
    end: int
    all_day: bool
    day: str
    persons: tuple[str, ...]
    said_at: int
    source: str
    conversation: str
    sources: tuple[int, ...]
    secret: bool = False


def her_agenda(kernel: Any, *, person: str | None = None, since: int | None = None,
               until: int | None = None) -> list[HerDate]:
    """L'agenda de Mika sur [``since``, ``until``[ (par défaut : de maintenant à un an), le plus proche d'abord —
    pour une personne (sa clé : seulement ce qui la concerne, ce qu'elle lui a confié elle-même), ou pour la console
    (``None`` : tout, et à qui)."""
    frame, store = kernel.mind.frame(), kernel.mind.store
    lo = frame.now if since is None else since
    hi = lo + AHEAD_DEFAULT if until is None else until
    if person is not None:
        dates = [*_promises(frame, [person]), *_moments(frame, [person])]
    else:
        everyone = _everyone(frame, store)
        dates = [*_promises(frame, everyone), *_moments(frame, everyone), *_ahead(frame)]
    if not dates:
        return []
    rows = _rows(store, {d[0] for d in dates})
    out = []
    resolve, presumed = identity_c.resolvers(frame.get)
    seen: set[int] = set()
    for item, kind, start, end, all_day, persons in dates:
        known = rows.get(item)
        if item in seen or known is None or not known.text or end <= lo or start >= hi:
            continue  # oublié, remplacé, démenti : il n'est plus à elle ; hors de la période
        if person is not None and not _for(person, known, resolve, presumed):
            continue
        seen.add(item)
        said_at, conversation = _said(store, known)
        out.append(HerDate(
            ref=f"memory:{item}", kind=kind, title=known.text, start=start, end=end, all_day=all_day,
            day=local(start, frame.env.tz_of(frame.root)).date().isoformat() if all_day else "",
            persons=persons, said_at=said_at,
            source=_source(frame, kind, persons if kind == PROMISE else _canon(frame, known.told_by) or persons,
                           said_at, person),
            conversation=conversation, sources=known.sources, secret=known.secret))
    return sorted(out, key=lambda d: (d.start, d.ref))


def title_of(kernel: Any) -> str:
    """Son nom d'agenda, son nom à elle tiré de sa persona : « L'agenda de Mika »."""
    return phrase("agenda.mine.title", name=self_c.name_of(kernel.mind.frame().get(self_c.PERSONA)))


# ── ce qu'elle a de daté ──────────────────────────────────────────────────

#: (élément, sorte, début, fin, journée entière, personnes)
_Date = tuple[int, str, int, int, bool, tuple[str, ...]]


def _day(frame: Frame, t: int) -> tuple[int, int]:
    """La journée de cet instant, ici : de minuit à minuit."""
    tz = frame.env.tz_of(frame.root)
    d = local(t, tz).date()
    return midnight(d, tz), midnight(d + timedelta(days=1), tz)


def _canon(frame: Frame, keys: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({str(frame.get(identity_c.PERSON(k)) or k) for k in keys if k}))


def _promises(frame: Frame, persons: Sequence[str]) -> list[_Date]:
    """Ses promesses datées envers ces personnes (une échéance dite : pas l'horizon d'une promesse vague)."""
    out: list[_Date] = []
    for person in persons:
        for pr in frame.get(memory_c.PROMISES_TO(person)) or ():
            if pr.due is None or pr.implicit_due:
                continue
            if pr.all_day:
                start, end = _day(frame, pr.due)
                out.append((pr.id, PROMISE, start, end, True, (person,)))
            else:
                out.append((pr.id, PROMISE, pr.due, pr.due + PROMISE_SPAN, False, (person,)))
    return out


def _moment(frame: Frame, ev: memory_c.LifeEvent, kind: str) -> _Date | None:
    """Un moment tel qu'un agenda le montre : daté (pas une situation qui dure), ni fini, ni annulé ni reporté."""
    if ev.ongoing or ev.ended_at or ev.outcome in NOT_HAPPENING:
        return None
    persons = _canon(frame, ev.about)
    if ev.all_day or ev.vague:
        start, end = _day(frame, ev.when)
        if ev.until:
            end = _day(frame, ev.until)[1]
        return ev.id, kind, start, end, True, persons
    return ev.id, kind, ev.when, ev.until or ev.when + MOMENT_SPAN, False, persons


def _moments(frame: Frame, persons: Sequence[str]) -> list[_Date]:
    """Les moments de la vie de ces personnes (une date qui revient chaque année : sa prochaine fois)."""
    out = []
    for person in persons:
        for ev in frame.get(memory_c.LIFE_EVENTS(person)) or ():
            got = _moment(frame, ev, YEARLY if ev.yearly else MOMENT)
            if got is not None:
                out.append(got)
    return out


def _ahead(frame: Frame) -> list[_Date]:
    """Ce qu'elle voit venir dans le monde, et ce qu'elle vivra à travers quelqu'un."""
    out = []
    for ev in frame.get(memory_c.AHEAD) or ():
        got = _moment(frame, ev, AHEAD if ev.scope == memory_c.WORLD else MOMENT)
        if got is not None:
            out.append(got)
    return out


def _everyone(frame: Frame, store: Any) -> list[str]:
    """Les personnes à qui elle a promis quelque chose, ou dont elle retient un moment (par sa porte)."""
    v = memory_c.KNOWLEDGE
    rows = store.query_mind(select(v.c.recipient, v.c.about).where(
        v.c.kind.in_((memory_c.PROMISE, memory_c.EVENT)), v.c.status.in_(("pending", "active"))))
    keys: set[str] = set()
    for recipient, about in rows:
        if recipient:
            keys.add(str(recipient))
        try:
            keys.update(str(k) for k in json.loads(about or "[]"))
        except ValueError:
            continue
    return list(_canon(frame, keys))


def _rows(store: Any, items: Iterable[int]) -> dict[int, Known]:
    """Ces éléments, par la porte de sa mémoire : leur texte, leur filiation, leurs messages."""
    v = memory_c.KNOWLEDGE
    ids = sorted(items)
    out: dict[int, Known] = {}
    for i in range(0, len(ids), 500):
        rows = store.query_mind(memory_c.select_known().where(v.c.id.in_(ids[i:i + 500])))
        out.update({k.id: k for k in knowns(rows, memory_c.KNOWN_COLUMNS)})
    return out


# ── pour qui, et d'où ça vient ────────────────────────────────────────────


def _for(person: str, known: Known, resolve: Any, presumed: Any) -> bool:
    """Ce qu'une personne voit de son agenda : ce qui la concerne, qu'elle lui a confié elle-même (une promesse est à
    elle), jamais un secret, et seulement ce que sa mémoire redirait à elle seule."""
    if known.secret:
        return False
    if known.kind == memory_c.EVENT:
        tellers = {resolve(t) or t for t in known.told_by}
        if tellers != {person} or person not in {resolve(a) or a for a in known.about}:
            return False  # ce qu'une autre lui a confié, ou un moment d'avant sans confident connu
    elif {resolve(a) or a for a in known.about} != {person}:
        return False
    return admits(known.lineage, person, private_to(person), resolve=resolve, presumed=presumed).ok


def _said(store: Any, known: Known) -> tuple[int, str]:
    """Quand c'est arrivé jusqu'à elle et dans quelle conversation : le premier message d'où il vient, sinon quand
    elle l'a retenu."""
    first = min(known.sources) if known.sources else 0
    for e in store.get_events([first]) if first else ():
        if e.type != rt.PERCEPTION_RECEIVED.name:
            continue
        try:
            handle = str(json.loads(e.data).get("handle") or "")
        except ValueError:
            handle = ""
        return e.at, f"chat:{handle}:{e.seq}" if handle else ""
    return known.born_at, ""


def _source(frame: Frame, kind: str, persons: tuple[str, ...], at: int, viewer: str | None) -> str:
    """D'où ça vient, en mots : « Elle te l'a promis mardi 17 novembre », « Léa le lui a raconté dimanche 22
    novembre » — ``persons`` : à qui elle l'a promis, ou qui le lui a raconté."""
    day = day_fr(local(at, frame.env.tz_of(frame.root)).date()) if at else ""
    if kind == AHEAD:
        return phrase("agenda.mine.from.ahead", day=day)
    if viewer is not None:
        if kind == PROMISE:
            return phrase("agenda.mine.from.promised_you", day=day)
        return phrase("agenda.mine.from.told_by_you", day=day)
    who = ", ".join(identity_c.person_name(frame, p) or p for p in persons) or phrase("agenda.words.someone")
    if kind == PROMISE:
        return phrase("agenda.mine.from.promised", who=who, day=day)
    return phrase("agenda.mine.from.told", who=who, day=day)


__all__ = ["AHEAD", "MOMENT", "PROMISE", "YEARLY", "HerDate", "her_agenda", "title_of"]

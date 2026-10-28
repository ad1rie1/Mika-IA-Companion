"""Raconter sans nommer (ADR 0091) : ce que le rappel ne peut pas lui montrer nommément, elle peut parfois le raconter
sans dire de qui il s'agit — à qui n'a aucun lien connu avec la personne (``links``), gradué par ce qu'elle sait de qui
l'écoute (``Audience.veiled_level``), en réponse seulement, jamais à la place de ce qui peut se dire nommé.

Le rappel lui passe ses candidats (ce que la question réveille, ou, quand on lui demande des nouvelles, ce qui est
récent) ; le verdict est ``vocab.retelling`` ; le budget : au plus ``veiled_max_shown`` par réponse, et
``veiled_per_person`` par personne et par auditeur sur ``veiled_keep_days`` — un même élément une fois. Ce qu'elle a
déjà raconté sans nom à quelqu'un lui revient comme tel (« garde-le sans nom »), sous le même verdict (devenu secret,
ou un lien depuis : plus rien). « Raconté » : sa réponse en a repris les mots (``echoed``) — que son prompt le lui
ait montré ne suffit pas (ADR 0092). Le bloc porte les noms qu'il tait : s'ils paraissent ailleurs dans le prompt, le
compositeur le retire (``kernel.prompt.unveiled``).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.memory.faculty import MEMORY, MemoryParams, MemoryState
from mika.faculties.memory.links import handles_of, links_of, written
from mika.faculties.memory.salience import Item
from mika.faculties.memory.tables import about, batches, handle_key, items, told_lines
from mika.kernel.clock import DAY
from mika.kernel.faculty import Zone
from mika.kernel.frame import Audience, Frame
from mika.kernel.prompt import SectionBody
from mika.ports.sql import alias_of
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable, named_label
from mika.vocab.phrasebook import phrase
from mika.vocab.retelling import FRAMING, retellable
from mika.vocab.words import fold, stems

#: « quoi de neuf ? » : on lui demande des nouvelles (replié, sans accents)
_NEWS = re.compile(r"\b(?:quoi de neuf|quoi de beau|des nouvelles|tu racontes quoi|ca dit quoi|raconte[- ]moi|"
                   r"quelles nouvelles|du nouveau)\b")


def asks_news(text: str) -> bool:
    return bool(_NEWS.search(fold(text or "")))


#: deux récits qui partagent au moins cette part de leurs mots disent la même histoire (un souvenir et une croyance
#: tirés du même message) : elle ne la raconte qu'une fois
SAME_STORY = 0.6
#: des radicaux courts : « perdu » ≈ « perdre », « séparée » ≈ « séparation » — une réponse redit rarement mot pour mot
_WIDTH = 4
_FRAMING = frozenset(w[:_WIDTH] for w in FRAMING if len(w) >= 4)


def echoed(spoken: str, told: str, share: float) -> bool:
    """Sa réponse reprend-elle ce récit ? La part des mots qui le portent (hors ce qui le tourne) retrouvée dans ce
    qu'elle a dit, au moins ``share``. Un récit qui ne porte aucun mot à lui ne se départage pas : il compte (ce qui
    ferme le moins mal — gardé sans nom, dans le budget)."""
    words = stems(told, width=_WIDTH) - _FRAMING
    if not words:
        return True
    return len(words & stems(spoken, width=_WIDTH)) / len(words) >= share


@dataclass(frozen=True, slots=True)
class Candidate:
    """Ce que le rappel sait d'un élément qu'il n'a pas pu montrer nommément : qui il concerne, qui l'a confié et
    entendu (résolus), à quel point c'est sensible devant cette audience."""

    item: Item
    persons: tuple[str, ...]
    told_by: tuple[str, ...]
    heard_by: tuple[str, ...]
    sensitivity: int


@dataclass(frozen=True, slots=True)
class Veiled:
    item: int
    person: str
    text: str
    who: str
    sensitivity: int
    names: tuple[str, ...]
    kept: bool = False


def _who(frame: Frame, person: str) -> str:
    """Ce que la personne est pour elle, en mots épicènes — jamais qui, jamais « ma propriétaire »."""
    closeness = frame.get(social_c.CLOSENESS(person))
    if closeness == social_c.CLOSE:
        return phrase("memory.veiled.who.close")
    if closeness == social_c.FRIEND:
        return phrase("memory.veiled.who.friend")
    return phrase("memory.veiled.who.known")


def _names(frame: Frame, person: str) -> tuple[str, ...]:
    """Les formes du nom qu'un bloc sans nom tait : le nom entier, le prénom."""
    name = frame.get(identity_c.IDENTITY(person)).name or ""
    first = name.split()[0] if name.split() else ""
    return tuple(n for n in dict.fromkeys((name, first)) if n)


def _people(frame: Frame, persons: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Qui le récit concerne, et les prénoms qui n'en sont que des détails : une mention que l'identité ne présume
    être personne de connu (« Paul », l'ex d'Alice) est un détail de l'histoire de qui la raconte (ADR 0058) — la
    version sans nom le tait (« son compagnon »). Une mention présumée reste une personne, et ferme (ADR 0092)."""
    keep: list[str] = []
    details: list[str] = []
    for key in persons:
        if key.startswith("name:") and not frame.get(identity_c.PRESUMED(key)):
            details.append(named_label(key))
        else:
            keep.append(key)
    return tuple(keep), tuple(d for d in dict.fromkeys(details) if d)


def _told(store: Any, handles: tuple[str, ...], since: int, share: float) -> dict[int, int]:
    """Ce qu'elle a vraiment raconté sans nom à ces adresses depuis ``since`` (élément → quand) : un énoncé qui le
    lui montrait et dont la réponse le reprend (``echoed``) — le prompt montre, il ne dit pas (ADR 0092)."""
    if not handles:
        return {}
    out: dict[int, int] = {}
    lines, i, t = alias_of(told_lines(), "l"), alias_of(items(), "i"), alias_of(transcript_c.thread_table(), "t")
    for item, at, veiled, spoken in store.query_mind(
            select(lines.c.item, lines.c.at, i.c.veiled, t.c.text)
            .select_from(lines.join(i, i.c.id == lines.c.item).outerjoin(t, t.c.id == lines.c.utterance))
            .where(lines.c.at >= since, lines.c.handle.in_(sorted({handle_key(h) for h in handles})))):
        if veiled and echoed(spoken or "", veiled, share):
            out[int(item)] = max(out.get(int(item), 0), int(at))
    return out


def _told_persons(frame: Frame, store: Any, told: Mapping[int, int]) -> Counter[str]:
    """Combien d'éléments de chaque personne elle a déjà racontés sans nom à cet auditeur (budget par personne)."""
    out: Counter[str] = Counter()
    if not told:
        return out
    ab = about()
    for chunk in batches(sorted(told)):
        for _item, key in store.query_mind(select(ab.c.item, ab.c.person).where(ab.c.item.in_(chunk))):
            out[frame.get(identity_c.PERSON(key)) or key] += 1
    return out


def choose(frame: Frame, store: Any, candidates: Sequence[Candidate], listener: str, aud: Audience,
           p: MemoryParams) -> list[Veiled]:
    """Ce qu'elle peut raconter sans nommer personne à ``listener`` (une personne, résolue), dans l'ordre des
    candidats (le plus pertinent d'abord)."""
    if p.veiled_max_shown <= 0 or aud.public or not is_identifiable(listener) or not candidates:
        return []
    handles = handles_of(frame, listener)
    told = _told(store, handles, frame.now - round(p.veiled_keep_days * DAY), p.veiled_said_share)
    owners = set(frame.get(identity_c.OWNERS))
    links: dict[tuple[str, str], bool | None] = {}

    def linked(person: str) -> bool | None:
        return links_of(frame, store, listener, person, links, depth=p.veiled_link_depth)

    by_person = _told_persons(frame, store, told)
    out: list[Veiled] = []
    fresh = 0
    for cand in candidates:
        it = cand.item
        kept = it.id in told
        if not kept and fresh >= p.veiled_max_shown:
            continue
        persons, details = _people(frame, cand.persons)
        common = dict(admitted=False, veiled=it.veiled, persons=persons, sensitivity=cand.sensitivity,
                      level=aud.veiled_level, listener=listener, told_by=cand.told_by, heard_by=cand.heard_by,
                      secret=it.secret, lie=it.origin == c.LIED, between_us=it.between_us,
                      derived=it.internal_only or bool(it.constraints),
                      claim=it.kind == c.SOUVENIR or it.knowledge_kind == "claim", owners=owners,
                      importance=it.importance)
        if not retellable(**common, linked=False).ok:  # le lien se cherche seulement s'il reste la seule question
            continue
        person = persons[0]
        if details and written(store, handles, details):
            continue  # l'auditeur a lui-même écrit un prénom de l'histoire : il pourrait la reconnaître
        names = (*_names(frame, person), *details)
        if kept:
            # déjà raconté sans nom : il lui revient comme tel, sous le même verdict — devenu secret, ou un lien
            # depuis, il ne revient plus (rien à garder sans nom : elle n'en dit plus rien)
            if retellable(**common, linked=linked(person)).ok:
                out.append(Veiled(it.id, person, it.veiled, _who(frame, person), cand.sensitivity, names, kept=True))
            continue
        if by_person[person] >= p.veiled_per_person:
            continue
        if any(echoed(v.text, it.veiled, SAME_STORY) for v in out):
            continue  # la même histoire, déjà retenue (un souvenir et une croyance du même message)
        if not retellable(**common, linked=linked(person)).ok:
            continue
        by_person[person] += 1
        fresh += 1
        out.append(Veiled(it.id, person, it.veiled, _who(frame, person), cand.sensitivity, names))
    return out


@MEMORY.section("veiled", zone=Zone.VOLATILE, episodes=[Kind.REPLY], trim_rank=28,
                title=phrase("memory.veiled.title"))
def _veiled(s: MemoryState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """« CE QUE TU PEUX RACONTER SANS NOMMER PERSONNE » : ce qu'elle peut raconter, si ça vient, sans dire de qui il
    s'agit — et ce qu'elle a déjà raconté ainsi à cette personne, qui reste sans nom."""
    recall = enrich.get("recall")
    shown: list[Veiled] = list(getattr(recall, "veiled", None) or [])
    if not shown:
        return None
    lines = [phrase("memory.veiled.kept", text=v.text, who=v.who) if v.kept
             else phrase("memory.veiled.line", text=v.text, who=v.who) for v in shown]
    return SectionBody("\n".join([*lines, phrase("memory.veiled.advice")]),
                       level=max(v.sensitivity for v in shown),
                       provenance=tuple(f"{c.VEILED_PROVENANCE}{v.item}" for v in shown),
                       veils=tuple(dict.fromkeys(n for v in shown for n in v.names)))

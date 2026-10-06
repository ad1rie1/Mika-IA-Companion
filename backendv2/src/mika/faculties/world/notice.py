"""Ce qu'elle remarque quand on a changé quelque chose chez elle (ADR 0050 §10).

Une opératrice édite le monde (``world.authored``) : un objet apparaît, un autre n'est plus là, son lit a changé
de place. On remarque qu'on a touché à ses affaires — sans en dresser l'inventaire : ce qui se voit et ce qui est
à elle, jamais qu'une ancre a bougé de trois centimètres (la vérité du monde est discrète : une pièce, un lieu, un
meuble, un contenant ; une place sur la même étagère n'est pas un déplacement).

Des fonctions pures : le réducteur de l'édition range ce qu'elle remarquera dans la tranche, le processus
``world.notice`` le lui fait remarquer quand elle est éveillée (endormie : à son réveil), et chaque remarque est un
signal (``world.noticed``, ``kind="change"``) que l'attention dose et habitue comme les autres sens.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from mika.contracts import world as w
from mika.faculties.world import plan
from mika.kernel.events import Content, Draft
from mika.vocab.affect import Emotion
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity

#: La sorte de ses signaux de changement (l'attention habitue par source et par sorte).
KIND = "change"
APPEARED, GONE, MOVED = "appeared", "gone", "moved"
#: Ce qu'un changement chez elle attire au moins son attention : le seuil d'une pensée (comme un geste raté) —
#: un objet saillant davantage, jusqu'à 1.
CHANGE_PERTINENCE = 0.6
#: Ce qui n'est pas à elle compte moins (ses affaires comptent plus qu'un meuble anonyme).
NOT_MINE = 0.6
#: Une émotion légère : de la curiosité pour ce qui arrive, de la confusion pour ce qui manque, de la surprise
#: pour ce qui a bougé.
CHANGE_EMOTION = {APPEARED: Emotion.CURIOUS, GONE: Emotion.CONFUSED, MOVED: Emotion.SURPRISED}
CHANGE_INTENSITY = 0.15
#: Ce qui attend d'être remarqué, au plus (les plus pertinents) : elle remarque, elle ne fait pas l'inventaire.
KEPT = 6


@dataclass(frozen=True, slots=True)
class Remark:
    """Un changement qu'elle n'a pas encore remarqué : un objet, où il était et où il est (``None`` : il n'y était
    pas, ou plus), tel qu'elle le dit, et l'édition qui l'a fait naître (la dernière, si plusieurs l'ont touché avant
    qu'elle le voie)."""

    object: str
    before: w.Location | None
    after: w.Location | None
    #: son nom, et là où il est, là où il était, en mots
    label: str
    where: str
    was: str
    mine: bool
    salience: float
    given_by: str | None
    seq: int


def _spot(loc: w.Location) -> tuple[str, ...]:
    """Où est un objet, à la finesse où on le remarque : la pièce et le lieu, le meuble, le contenant, la main."""
    if isinstance(loc, w.InRoom):
        return ("room", loc.room, loc.near or "")
    if isinstance(loc, w.Held):
        return ("held", loc.actor)
    return (loc.kind, loc.object)


def change(r: Remark) -> str | None:
    """Ce qu'elle remarquera : apparu, disparu, ou — à elle — déplacé ; ``None`` : rien (apparu puis retiré avant
    qu'elle le voie, revenu à sa place)."""
    if r.before is None:
        return APPEARED if r.after is not None else None
    if r.after is None:
        return GONE
    return MOVED if r.mine and _spot(r.before) != _spot(r.after) else None


def _where(defn: w.WorldDef, loc: w.Location) -> str:
    """Là où est un objet, en mots : « à la fenêtre », « près de ton lit » (le nom d'une assise se dit assise : « sur
    ton lit »), « sur ton bureau »."""
    if isinstance(loc, w.InRoom):
        place = defn.place(loc.near) if loc.near else None
        if place is not None and place.place_kind is not w.PlaceKind.SPOT and place.of_object:
            return phrase("world.notice.near", object=plan.label_of(defn, place.of_object))
        if place is not None:
            return place.label
        room = defn.room(loc.room)
        return phrase("world.notice.in_room", room=room.label) if room is not None else ""
    if isinstance(loc, w.Held):
        return phrase("world.notice.in_hands") if loc.actor == w.MIKA else ""
    if isinstance(loc, w.On):
        return phrase("world.notice.on_top", object=plan.label_of(defn, loc.object))
    return phrase("world.notice.in", object=plan.label_of(defn, loc.object))


def changes(before: w.WorldDef, after: w.WorldDef, was: Mapping[str, w.ObjectState],
            now: Mapping[str, w.ObjectState], seq: int) -> list[Remark]:
    """Ce qu'une édition (``seq``) a changé des objets : ceux qui sont apparus, ceux qui ne sont plus là, ceux qui
    ont changé d'endroit (``was`` et ``now`` : l'état vécu avant et après elle)."""
    out: list[Remark] = []
    for oid in sorted(set(was) | set(now)):
        a, b = was.get(oid), now.get(oid)
        if a is not None and b is not None and _spot(a.location) == _spot(b.location):
            continue
        defn = after if b is not None else before
        o = defn.object(oid)
        out.append(Remark(
            object=oid, before=a.location if a is not None else None, after=b.location if b is not None else None,
            label=plan.label_of(defn, oid), where=_where(after, b.location) if b is not None else "",
            was=_where(before, a.location) if a is not None else "", mine=o is not None and o.owner == w.MIKA,
            salience=plan.salience(defn, oid), given_by=o.given_by if o is not None else None, seq=seq))
    return out


def pertinence(r: Remark) -> float:
    """Ce qu'un changement attire son attention : au moins le seuil d'une pensée, plus l'objet est saillant ; moins
    pour ce qui n'est pas à elle."""
    return round((CHANGE_PERTINENCE + (1 - CHANGE_PERTINENCE) * r.salience) * (1.0 if r.mine else NOT_MINE), 4)


def merge(pending: tuple[Remark, ...], fresh: Iterable[Remark]) -> tuple[Remark, ...]:
    """Ce qui reste à remarquer après une édition de plus : un objet touché deux fois avant qu'elle le voie se
    remarque une fois, entre ce qu'elle a vu et ce qui est (apparu puis retiré : rien). Les plus pertinents
    d'abord, ``KEPT`` au plus."""
    by = {r.object: r for r in pending}
    for r in fresh:
        seen = by.get(r.object)
        if seen is not None:
            r = replace(r, before=seen.before, was=seen.was)
        if change(r) is None:
            by.pop(r.object, None)
        else:
            by[r.object] = r
    return tuple(sorted(by.values(), key=lambda r: (-pertinence(r), r.object))[:KEPT])


def sentence(r: Remark) -> str:
    """Ce qu'elle remarque, comme elle se le dit (vide : rien)."""
    kind = change(r)
    if kind == APPEARED:
        return phrase("world.notice.appeared_where", where=r.where, label=r.label) if r.where else \
            phrase("world.notice.appeared", label=r.label)
    if kind == GONE:
        return phrase("world.notice.gone_from", was=r.was, label=r.label) if r.was else \
            phrase("world.notice.gone", label=r.label)
    if kind == MOVED:
        return phrase("world.notice.moved_to", label=r.label, where=r.where) if r.where else \
            phrase("world.notice.moved", label=r.label)
    return ""


def signal(r: Remark) -> Draft[Any] | None:
    """Ce qu'elle en remarque : un signal, sans section ni consigne. Un objet offert concerne qui l'a offert
    (``about``) : l'oubli de cette personne l'atteint (ADR 0024). Une fois par édition et par objet."""
    kind = change(r)
    if kind is None:
        return None
    about = (r.given_by,) if r.given_by else ()
    level = int(Sensitivity.PERSONAL if about else Sensitivity.NONE)
    factor = 1.0 if r.mine else NOT_MINE
    return w.NOTICED.draft(
        source="world", kind=KIND, summary=Content.of(sentence(r), level=level), pertinence=pertinence(r),
        emotion=CHANGE_EMOTION[kind].value, intensity=round(CHANGE_INTENSITY * factor, 4), about=about,
        sensitivity=level, bundle="world", object=r.object, dedupe_key=f"remarque:{r.seq}:{r.object}")

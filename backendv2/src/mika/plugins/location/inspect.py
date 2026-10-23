"""La console de la localisation (ADR 0119) : où sont les personnes qui le lui ont permis, d'après leur téléphone, et
ce que leurs téléphones lui ont dit — personne par personne (toutes ses adresses réunies), et sur la fiche de chacune
(« Sa position », seulement si elle en a une). Lecture seule ; un lieu oublié se dit « (oublié) »."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import location as c
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Block,
    Cell,
    Column,
    InspectContext,
    Nav,
    NavItem,
    Note,
    Pager,
    Ref,
    Row,
    Table,
    Text,
    When,
)
from mika.plugins.location import LOCATION, Fix, LocationState
from mika.vocab.people import is_internal

#: une page de ce que les téléphones lui ont dit
SHOWN = 50
FORGOTTEN = "(oublié)"
#: la page de la console où vit la localisation (son filtre par personne y mène)
PAGE = "/inspecteur/sens/positions"
#: le paramètre qui ne garde qu'une personne
WHO = "personne"


def _name(frame: Frame, person: str) -> str:
    return frame.get(identity_c.IDENTITY(person)).name or person


def _who(frame: Frame, handle: str) -> Cell:
    if not handle or is_internal(handle):
        return Text("personne", "muted")
    person = frame.get(identity_c.PERSON(handle))
    name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(handle)).name
    return Ref.subject("person", person, f"{name} ({handle})" if name else handle)


def _person(frame: Frame, person: str) -> Cell:
    if not person or is_internal(person):
        return Text("personne", "muted")
    return Ref.subject("person", person, _name(frame, person))


def _accuracy(m: int) -> str:
    return f"à {m} m près" if m else "inconnue"


def _text(content: Any) -> str:
    if content is None:
        return ""
    return content.text if content.text is not None else FORGOTTEN


def _sent(e: Any, frame: Frame) -> Row:
    d = e.data
    if e.type.name == c.CLEARED.name:
        return Row((When(e.at), _who(frame, d.handle), Text("partage coupé : position effacée", "muted"), "", "",
                    Ref("event", str(e.seq), f"#{e.seq}")), tone="muted")
    return Row((When(e.at), _who(frame, d.handle), Text(_text(d.label) or "—", clamp=200), _text(d.coords),
                _accuracy(int(d.accuracy_m)), Ref("event", str(e.seq), f"#{e.seq}")))


def by_person(s: LocationState) -> dict[str, list[Fix]]:
    """Les dernières positions, par personne (une adresse que personne ne réclame compte pour elle-même), la plus
    récente d'abord."""
    out: dict[str, list[Fix]] = {}
    for f in sorted(s.fixes.values(), key=lambda f: -f.fixed_at):
        out.setdefault(f.person or f.handle, []).append(f)
    return out


def _known(frame: Frame, texts: Mapping[str, Any], people: Mapping[str, Sequence[Fix]], *, title: str) -> Table:
    """Une ligne par personne : sa position la plus récente ; ses autres téléphones (ses autres adresses), dépliés."""
    def place(f: Fix) -> Text:
        return Text(texts.get(f.label_ref, FORGOTTEN) if f.label_ref else "—", clamp=200)

    rows = []
    for person, fixes in people.items():
        last = fixes[0]
        others = tuple(Row((_who(frame, f.handle), place(f), texts.get(f.coords_ref, FORGOTTEN), When(f.fixed_at)))
                       for f in fixes[1:])
        detail = (Table(("moyen de communication", "lieu", "coordonnées", Column("mesurée", "fit")), others,
                        title="Ses autres téléphones"),) if others else ()
        rows.append(Row((_person(frame, person), place(last), texts.get(last.coords_ref, FORGOTTEN),
                         _accuracy(last.accuracy_m), When(last.fixed_at),
                         f"{len(fixes)} téléphones" if len(fixes) > 1 else "un téléphone",
                         Ref("event", str(last.seq), f"#{last.seq}")), detail=detail))
    return Table((Column("personne", role="title"), "lieu", "coordonnées", Column("précision", "fit"),
                  Column("mesurée", "fit"), Column("d'où", "fit"), Column("journal", "fit")),
                 tuple(rows), title=title, empty="aucune")


def _journal(ctx: InspectContext, frame: Frame, person: str = "") -> Table:
    before = ctx.int_param("avant", 0) or None
    sent = ctx.events([c.LOCATED, c.CLEARED], SHOWN, before=before, where=("person", person) if person else None)
    older = (("avant", str(sent[-1].seq)),) if len(sent) == SHOWN else ()
    return Table(
        (Column("quand", "fit"), "moyen de communication", "lieu", "coordonnées", Column("précision", "fit"),
         Column("journal", "fit")),
        tuple(_sent(e, frame) for e in sent), title="Ce que son téléphone lui a dit" if person else
        "Ce que les téléphones lui ont dit" + (" — plus anciens" if before else ""), empty="rien pour l'instant",
        pager=Pager(param="avant", size=SHOWN, older=older) if older or before else None)


def _texts(ctx: InspectContext, fixes: Sequence[Fix]) -> Mapping[str, Any]:
    refs = [r for f in fixes for r in (f.coords_ref, f.label_ref) if r]
    return ctx.store.content(refs) if refs else {}


@LOCATION.inspect("positions", title="Localisation", section="sens", order=45,
                  description="Où sont les personnes qui le lui ont permis, d'après leur téléphone (l'application "
                              "ouverte seulement) : une ligne par personne, tous ses téléphones réunis. Elle ne le "
                              "regarde qu'en tête-à-tête, pour la personne elle-même, et chaque regard se voit dans "
                              "le fil.")
def _inspect(s: LocationState, frame: Frame, ctx: InspectContext) -> list[Block]:
    if not s.fixes:
        return [Note("Aucun téléphone ne lui a dit où il était. Dans l'application Android : Paramètres › « Lui "
                     "dire où je suis ».", tone="muted")]
    people = by_person(s)
    chosen = ctx.param(WHO)
    if chosen not in people:
        chosen = ""
    blocks: list[Block] = []
    if len(people) > 1:
        blocks.append(Nav((NavItem("Tout le monde", Ref("local", PAGE, "Tout le monde"), len(people), not chosen),
                           *(NavItem(_name(frame, p), Ref("local", PAGE, _name(frame, p), ((WHO, p),)), None,
                                     p == chosen) for p in people)), title="Personne"))
    shown = {chosen: people[chosen]} if chosen else people
    blocks += [_known(frame, _texts(ctx, [f for fs in shown.values() for f in fs]), shown,
                      title="Dernière position connue"), _journal(ctx, frame, chosen)]
    return blocks


def _has_position(s: LocationState, person: str) -> bool:
    return any(f.person == person for f in s.fixes.values())


@LOCATION.inspect("position", title="Sa position", subject="person", order=66, shown=_has_position,
                  description="Où se trouve cette personne d'après son téléphone (l'application ouverte, si le "
                              "partage est permis), et ce qu'il en a dit. Elle ne la regarde qu'en tête-à-tête avec "
                              "cette personne.")
def _person_tab(s: LocationState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = ctx.subject
    fixes = [f for f in sorted(s.fixes.values(), key=lambda f: -f.fixed_at) if f.person == person]
    if not fixes:
        return [Note("Son téléphone ne dit pas où se trouve cette personne.", tone="muted")]
    texts = _texts(ctx, fixes)
    rows = tuple(Row((_who(frame, f.handle), Text(texts.get(f.label_ref, FORGOTTEN) if f.label_ref else "—",
                                                  clamp=200),
                      texts.get(f.coords_ref, FORGOTTEN), _accuracy(f.accuracy_m), When(f.fixed_at),
                      Ref("event", str(f.seq), f"#{f.seq}"))) for f in fixes)
    return [Table((Column("moyen de communication", role="title"), "lieu", "coordonnées",
                   Column("précision", "fit"),
                   Column("mesurée", "fit"), Column("journal", "fit")), rows,
                  title="Sa dernière position", empty="aucune"),
            _journal(ctx, frame, person)]

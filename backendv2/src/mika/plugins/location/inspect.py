"""La console de la localisation (ADR 0119) : où sont les personnes qui le lui ont permis, d'après leur téléphone, et
ce que leurs téléphones lui ont dit. Lecture seule ; un lieu oublié se dit « (oublié) »."""

from __future__ import annotations

from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import location as c
from mika.kernel.frame import Frame
from mika.kernel.inspect import Block, Cell, Column, InspectContext, Note, Pager, Ref, Row, Table, Text, When
from mika.plugins.location import LOCATION, LocationState
from mika.vocab.people import is_internal

#: une page de ce que les téléphones lui ont dit
SHOWN = 50
FORGOTTEN = "(oublié)"


def _who(frame: Frame, handle: str) -> Cell:
    if not handle or is_internal(handle):
        return Text("personne", "muted")
    person = frame.get(identity_c.PERSON(handle))
    name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(handle)).name
    return Ref.subject("person", person, f"{name} ({handle})" if name else handle)


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


@LOCATION.inspect("positions", title="Localisation", section="sens", order=45,
                  description="Où sont les personnes qui le lui ont permis, d'après leur téléphone (l'application "
                              "ouverte seulement). Elle ne le regarde qu'en tête-à-tête, pour la personne elle-même, "
                              "et chaque regard se voit dans le fil.")
def _inspect(s: LocationState, frame: Frame, ctx: InspectContext) -> list[Block]:
    if not s.fixes:
        return [Note("Aucun téléphone ne lui a dit où il était. Dans l'application Android : Paramètres › « Lui "
                     "dire où je suis ».", tone="muted")]
    refs = [r for f in s.fixes.values() for r in (f.coords_ref, f.label_ref) if r]
    texts = ctx.store.content(refs) if refs else {}
    fixes = sorted(s.fixes.values(), key=lambda f: -f.fixed_at)
    known = Table(
        ("personne", "lieu", "coordonnées", Column("précision", "fit"), Column("mesurée", "fit"),
         Column("journal", "fit")),
        tuple(Row((_who(frame, f.handle), Text(texts.get(f.label_ref, FORGOTTEN) if f.label_ref else "—", clamp=200),
                   texts.get(f.coords_ref, FORGOTTEN), _accuracy(f.accuracy_m), When(f.fixed_at),
                   Ref("event", str(f.seq), f"#{f.seq}"))) for f in fixes),
        title="Dernière position connue", empty="aucune")
    before = ctx.int_param("avant", 0) or None
    sent = ctx.events([c.LOCATED, c.CLEARED], SHOWN, before=before)
    older = (("avant", str(sent[-1].seq)),) if len(sent) == SHOWN else ()
    journal = Table(
        (Column("quand", "fit"), "personne", "lieu", "coordonnées", Column("précision", "fit"),
         Column("journal", "fit")),
        tuple(_sent(e, frame) for e in sent), title="Ce que les téléphones lui ont dit" + (
            " — plus anciens" if before else ""), empty="rien pour l'instant",
        pager=Pager(param="avant", size=SHOWN, older=older) if older or before else None)
    return [known, journal]

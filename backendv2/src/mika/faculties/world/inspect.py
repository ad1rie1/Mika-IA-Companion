"""La console du monde : où elle est, ce qu'elle fait, ce qui est en route, où sont les choses (ADR 0050)."""

from __future__ import annotations

from typing import Any

from mika.contracts import world as w
from mika.faculties.world import WORLD, WorldState, plan
from mika.kernel.frame import Frame
from mika.kernel.inspect import Block, Column, InspectContext, Note, Stat, Stats, Table, Text, When

_OUTCOME_FR = {w.Source.MIKA: "elle", w.Source.REFLEX: "un réflexe", w.Source.PLAYER: "une personne",
               w.Source.HOST: "le moteur", w.Source.CREATOR: "une opératrice", w.Source.KERNEL: "le noyau"}


def _location(s: WorldState, loc: w.Location) -> str:
    defn = s.definition
    if isinstance(loc, w.InRoom):
        room = defn.room(loc.room)
        near = defn.place(loc.near) if loc.near else None
        return (room.label if room else loc.room) + (f", {near.label}" if near else "")
    if isinstance(loc, w.Held):
        return f"dans les mains de {'Mika' if loc.actor == w.MIKA else loc.actor}"
    what = plan.label_of(defn, loc.object)
    return f"sur {what} (place {loc.slot + 1})" if isinstance(loc, w.On) else f"dans {what}"


def _steps(i: w.Intent) -> str:
    out = []
    for st in i.steps:
        if st.kind == "walk":
            out.append(f"marcher → {st.to_place or st.to_room}")
        elif st.kind == "posture" and st.posture:
            out.append(plan.POSTURE_FR[st.posture])
        elif st.kind == "act":
            out.append(f"{st.action} {st.object}")
    return " · ".join(out)


@WORLD.inspect("monde", title="Son monde", section="vie", order=45,
               description="Où elle est, ce qu'elle fait, ce qu'elle tient, ce qui est en route et où sont les choses.")
def _world_view(s: WorldState, frame: Frame, ctx: InspectContext) -> list[Block]:
    defn = s.definition
    me = s.actors[w.MIKA]
    now = frame.now
    busy = me.activity is not None and (me.activity.until is None or me.activity.until > now)
    rows_intents: list[tuple[Any, ...]] = [
        (i.actor, _OUTCOME_FR.get(i.cause.source, i.cause.source.value), _steps(i), When(i.eta), When(i.deadline))
        for i in sorted(s.intents.values(), key=lambda i: i.started)]
    rows_objects: list[tuple[Any, ...]] = [
        (plan.label_of(defn, oid), Text(oid, kind="mono"), _location(s, o.location),
         plan.state_label(defn, oid, o.state) or Text("—", kind="muted"))
        for oid, o in sorted(s.objects.items())]
    return [
        Stats((
            Stat("où", plan.POSTURE_FR[me.posture] + " " + (defn.place(me.place).label if me.place and defn.place(
                me.place) else "dans la pièce"), sub=(f"en chemin vers {me.moving.to_place}" if me.moving else "")),
            Stat("ce qu'elle fait", plan.affordance_label(defn, me.activity) if busy and me.activity else "rien de "
                 "particulier"),
            Stat("ce qu'elle tient", ", ".join(plan.label_of(defn, o) for o in me.holding) or "rien"),
            Stat("le monde", f"{defn.label} · révision {defn.rev}",
                 sub=f"{len(defn.rooms)} pièce(s), {len(defn.places)} lieux, {len(defn.objects)} objets"),
        ), title="Son corps"),
        Table((Column("acteur"), Column("décidé par"), Column("les pas"), Column("fin prévue", "fit"),
               Column("échéance", "fit", hint="sans moteur pour la jouer, l'action se termine là, comme prévue")),
              tuple(rows_intents), title="Ce qui est en route", empty="rien en route"),
        Table((Column("objet"), Column("identifiant", "fit"), Column("où"), Column("état", "fit")),
              tuple(rows_objects), title="Les choses"),
        Note("Ce qu'elle lit de tout ça dans son prompt est la section « AUTOUR DE TOI ».", tone="muted"),
    ]

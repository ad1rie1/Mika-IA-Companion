"""La console du monde : où elle est, ce qu'elle fait, ce qui est en route, où sont les choses, ce qu'une opératrice
y a changé et ce qu'elle en a remarqué (ADR 0050)."""

from __future__ import annotations

from typing import Any

from mika.contracts import body as body_c
from mika.contracts import world as w
from mika.faculties.world import WORLD, WorldState, notice, plan
from mika.kernel.frame import Frame
from mika.kernel.inspect import Block, Column, InspectContext, Note, Stat, Stats, Table, Text, When, num_fr

_OUTCOME_FR = {w.Source.MIKA: "elle", w.Source.REFLEX: "un réflexe", w.Source.PLAYER: "une personne",
               w.Source.HOST: "le moteur", w.Source.CREATOR: "une opératrice", w.Source.KERNEL: "le noyau"}


def _location(s: WorldState, loc: w.Location) -> str:
    defn = s.definition
    if isinstance(loc, w.InRoom):
        room = defn.room(loc.room)
        near = defn.place(loc.near) if loc.near else None
        return (room.label if room else loc.room) + (f", {near.label}" if near else "")
    if isinstance(loc, w.Held):
        return "dans ses mains" if loc.actor == w.MIKA else f"dans les mains de {loc.actor}"
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


#: Les dernières éditions montrées, ce qu'elle en a remarqué, et combien de changements d'un lot sont nommés.
EDITS_SHOWN = 8
NOTICED_SHOWN = 12
CHANGES_NAMED = 6


def _edits(ctx: InspectContext) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for e in ctx.events([w.AUTHORED], EDITS_SHOWN):
        d = e.data
        named = [f"+ {ch.item.kind} {ch.item.id}" if isinstance(ch, w.DefPut) else f"− {ch.of.value} {ch.id}"
                 for ch in d.changes[:CHANGES_NAMED]]
        more = f" … et {len(d.changes) - CHANGES_NAMED} de plus" if len(d.changes) > CHANGES_NAMED else ""
        rows.append((When(e.at), Text(d.by, kind="mono"), f"{d.base_rev} → {d.base_rev + 1}",
                     Text(", ".join(named) + more, kind="mono")))
    return rows


def _remarks(s: WorldState, frame: Frame, ctx: InspectContext) -> list[tuple[Any, ...]]:
    """Ce qu'elle va remarquer (endormie : à son réveil), puis ce qu'elle a remarqué, du plus récent."""
    awake = frame.get(body_c.SLEEP) is body_c.SleepPhase.AWAKE
    rows: list[tuple[Any, ...]] = [
        (Text("—", kind="muted"), notice.sentence(r), num_fr(notice.pertinence(r), 2),
         Text("tout de suite" if awake else "à son réveil", kind="muted")) for r in s.unnoticed]
    for e in ctx.events([w.NOTICED], NOTICED_SHOWN, where=("kind", notice.KIND)):
        text = e.data.summary.text
        rows.append((When(e.at), text if text is not None else Text("(oublié)", kind="muted"),
                     num_fr(e.data.pertinence, 2), "remarqué"))
    return rows


@WORLD.inspect("monde", title="Son monde", section="vie", order=45,
               description="Où elle est, ce qu'elle fait, ce qu'elle tient, ce qui est en route, où sont les choses, "
                           "et ce qu'elle a remarqué des éditions de son monde.")
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
        Table((Column("quand", "fit"), Column("par", "fit"), Column("révision", "fit"), Column("les changements")),
              tuple(_edits(ctx)), title="Les dernières éditions", empty="personne n'a encore édité son monde"),
        Table((Column("quand", "fit"), Column("ce qu'elle remarque"),
               Column("pertinence", "num", hint="ce qu'elle en retient : une pensée dès le seuil de l'attention ; ses "
                                                "affaires comptent plus qu'un meuble anonyme"),
               Column("état", "fit")),
              tuple(_remarks(s, frame, ctx)), title="Ce qu'elle en a remarqué",
              empty="rien de changé chez elle, ou rien qui se voie"),
        Note("Ce qu'elle lit de tout ça dans son prompt est la section « AUTOUR DE TOI » ; ce qu'elle remarque d'une "
             "édition est un signal, que l'attention dose comme les autres sens.", tone="muted"),
    ]

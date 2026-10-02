"""``place`` : où elle est dans sa chambre — et le droit d'y aller.

Elle a un corps dans une pièce (le frontend la montre : bureau, fenêtre, lit,
bibliothèque, porte, le tapis au milieu). Où elle se tient est une décision à
elle, prise par le modèle avec l'outil ``move_to`` (en conversation, ou quand
elle prend l'initiative) ; le corps fait le reste — le chemin, s'asseoir,
s'allonger.

Écrit pour être piloté par un modèle :

- un vocabulaire fermé (``Place``), validé avant tout appel : un lieu inventé
  revient au modèle comme une erreur, jamais une coordonnée ne passe ;
- le lieu est un état : y aller quand elle y est déjà n'écrit rien ;
- un déplacement par épisode au plus (une réplique ne la fait pas zigzaguer) ;
- le sommeil la met au lit (un réducteur sur ``body.fell_asleep``, donc au
  rejeu aussi) : on ne dort pas debout au milieu de la pièce. Au réveil elle y
  reste — assise sur son lit — jusqu'à ce qu'elle décide d'en bouger.

Le lieu part vers les écrans dans l'état intérieur (``inner_state.place``) :
un déplacement pousse un état sans parole (comme s'endormir), le corps
anime le passage d'un état à l'autre.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel, Field

from mika.contracts import body as body_c
from mika.contracts import place as c
from mika.kernel.faculty import Faculty, Zone
from mika.kernel.frame import Frame
from mika.ports.delivery import Delivery, EmotionView
from mika.vocab.episodes import CONVERSATIONAL


@dataclass(frozen=True, slots=True)
class PlaceState:
    place: c.Place = c.Place.CENTER
    since: int = 0


PLACE = Faculty("place", state=PlaceState, init=lambda p: PlaceState())
PLACE.declare(*c.ALL)


@PLACE.reducer(c.MOVED)
def _moved(s: PlaceState, e, cx) -> PlaceState:
    if e.data.place == s.place:
        return s
    return replace(s, place=e.data.place, since=e.at)


@PLACE.reducer(body_c.FELL_ASLEEP)
def _to_bed(s: PlaceState, e, cx) -> PlaceState:
    """Elle s'endort : elle va se coucher (le corps marche jusqu'au lit, puis s'allonge)."""
    if s.place == c.Place.BED:
        return s
    return replace(s, place=c.Place.BED, since=e.at)


@PLACE.fact(c.PLACE)
def _place(s: PlaceState, cx) -> c.Place:
    return s.place


@PLACE.fact(c.SINCE)
def _since(s: PlaceState, cx) -> int:
    return s.since


# ── L'outil ───────────────────────────────────────────────────────────────

#: Ce que chaque lieu est pour elle — la description de l'outil et la section les disent pareil.
WHERE: dict[c.Place, str] = {
    c.Place.CENTER: "debout au milieu de ta chambre, sur le tapis",
    c.Place.WINDOW: "à la fenêtre, à regarder dehors",
    c.Place.DESK: "assise à ton bureau",
    c.Place.BED: "assise sur ton lit",
    c.Place.BOOKSHELF: "devant ta bibliothèque",
    c.Place.DOOR: "près de la porte de ta chambre",
}


class MoveArgs(BaseModel):
    place: c.Place = Field(description="center : le milieu de la pièce (face à qui te parle) ; window : la fenêtre ; "
                           "desk : t'asseoir à ton bureau ; bed : t'asseoir sur ton lit ; bookshelf : ta "
                           "bibliothèque ; door : la porte")


PLACE.bundle("room", "te déplacer dans ta chambre (on te voit le faire)")


@PLACE.tool("move_to", description="Aller ailleurs dans ta chambre : t'asseoir à ton bureau ou sur ton lit, aller à "
            "la fenêtre, devant ta bibliothèque, à la porte, ou revenir au milieu. On te voit marcher jusque-là. "
            "Seulement quand l'envie ou la conversation t'y pousse (« attends, je vais voir dehors »), pas à chaque "
            "réplique ; ne le raconte pas entre crochets, fais-le.", args=MoveArgs, bundle="room",
            episodes=CONVERSATIONAL, max_calls_per_episode=1)
async def move_to(args: MoveArgs, ctx: Any) -> str:
    here = ctx.frame.get(c.PLACE)
    if args.place == here:
        return f"Tu y es déjà : tu es {WHERE[here]}."
    await ctx.emit(c.MOVED.draft(place=args.place, by="tool"))
    return f"Tu y vas : tu seras {WHERE[args.place]}."


# ── Le prompt ─────────────────────────────────────────────────────────────


@PLACE.section("place", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["rhythm"], trim_rank=70,
               title="OÙ TU ES", reads=[c.PLACE, body_c.SLEEP])
def _where(s: PlaceState, frame: Frame, enrich: Any) -> str | None:
    if frame.get(body_c.SLEEP) != body_c.SleepPhase.AWAKE:
        return None  # elle dort, dans son lit : rien à dire à qui la réveille qu'il ne voie
    return f"Tu es {WHERE[s.place]}."


# ── Vers les écrans ───────────────────────────────────────────────────────


@PLACE.effect(c.MOVED)
async def _shown(ev: Any, ports: Mapping[str, Any]) -> None:
    """Elle se déplace : les écrans reçoivent l'état (sans parole) et le corps marche."""
    port = ports.get("delivery")
    if port is None:
        return
    frame: Frame = ports["frame"]()
    await port.deliver(Delivery(
        key=ev.id, target=None, channel=None, room=None, text="", persona="inner",
        emotion=EmotionView("neutral", 0.0), message_id=ev.seq, sleep_phase=frame.get(body_c.SLEEP).value,
        local_hour=frame.local().hour, kind="state"))

"""``world`` : le monde où elle vit, et son corps dedans (ADR 0050).

Elle a un corps dans un monde de pièces, de lieux et d'objets (le frontend la montre ; un moteur de jeu le
fera bientôt). Ce qu'elle y fait est **son** choix, pris par le modèle avec deux outils en main (``go_to``,
``interact``) ; ce que son corps fait de lui-même (aller se coucher quand elle s'endort, s'arrêter de dessiner
au bout d'un moment) est un réflexe, sans modèle. Le noyau est le monde : il valide, planifie en pas, et conclut chaque action à son échéance — un
moteur hôte pourra la jouer et dire qu'il n'y arrive pas, jamais décider seul (P2).

Écrit pour être piloté par un modèle :

- un vocabulaire fermé : les lieux sont une énumération dans le schéma de ``go_to``, les objets et leurs
  actions sont validés contre la définition avant tout appel — une invention revient au modèle comme une erreur
  qui dit ce qui se peut, rien n'est écrit ;
- un état, pas un ordre : aller là où elle est déjà n'écrit rien ; un déplacement par épisode au plus ;
- le coucher est un **réducteur** de ``body.fell_asleep`` : l'intention naît dans la même transaction que
  l'endormissement (les écrans reçoivent les deux ensemble, elle marche jusqu'au lit les yeux ouverts) ;
- reprend ``place`` (ADR 0049) : les ``place.moved`` déjà au journal sont relus comme ses déplacements, et
  ``place.current`` (que lisent les écrans) se déduit d'ici.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from mika.contracts import body as body_c
from mika.contracts import place as place_c
from mika.contracts import world as w
from mika.faculties.world import plan
from mika.kernel.clock import DAY, MINUTE, US
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import CatchUp, Faculty, ToolResult, Zone
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.ports.delivery import Delivery, EmotionView
from mika.vocab.affect import Emotion
from mika.vocab.episodes import CONVERSATIONAL
from mika.vocab.privacy import Sensitivity

#: Le monde qu'elle habite au premier démarrage : sa chambre, telle que l'écran la montre.
DEFAULT_WORLD = w.WorldDef.model_validate_json((Path(__file__).parent / "chambre.json").read_text(encoding="utf-8"))


class WorldParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    walk_speed: Annotated[float, Knob(
        label="Vitesse de marche (m/s)", group="Corps", lo=0.3, hi=2.0, step=0.05,
        help="Sert à dater la fin d'un trajet quand aucun moteur ne le joue (celle du frontend, à peu près).")] = 0.9
    sit_s: Annotated[float, Knob(
        label="S'asseoir (s)", group="Corps", lo=0.3, hi=6, step=0.1,
        help="Le temps de s'asseoir, à la fin d'un trajet vers une chaise ou le bord du lit.")] = 1.5
    stand_s: Annotated[float, Knob(
        label="Se lever (s)", group="Corps", lo=0.3, hi=6, step=0.1,
        help="Le temps de se lever avant de partir d'une assise.")] = 1.2
    lie_s: Annotated[float, Knob(
        label="S'allonger (s)", group="Corps", lo=0.5, hi=10, step=0.1,
        help="Le temps de s'allonger (le coucher).")] = 2.5
    hand_s: Annotated[float, Knob(
        label="Prendre ou poser (s)", group="Corps", lo=0.3, hi=6, step=0.1,
        help="Le temps d'un geste de la main sur un objet.")] = 1.2
    doorway_s: Annotated[float, Knob(
        label="Passer une porte (s)", group="Corps", lo=0.5, hi=10, step=0.5,
        help="Le temps de passer d'une pièce à l'autre.")] = 2.0
    open_activity_min: Annotated[int, Knob(
        label="Une occupation sans fin prévue s'arrête d'elle-même après (min)", group="Corps", lo=15, hi=480,
        step=5, help="Dessiner, travailler à son bureau : sans autre geste de sa part, elle s'arrête au bout de ce "
                     "temps et reste où elle est (on ne dessine pas treize heures d'affilée).")] = 90
    grace_s: Annotated[float, Knob(
        label="Marge avant de conclure (s)", group="Synchronisation", lo=0, hi=30, step=0.5,
        help="Sans nouvelle d'un moteur, une action se termine comme prévue après sa durée plus cette marge.")] = 2.0
    shown_objects: Annotated[int, Knob(
        label="Objets dits dans « AUTOUR DE TOI »", group="Prompt", lo=2, hi=30,
        help="Ce qu'elle tient, puis ce qui est à portée, puis ce dont elle peut se servir ailleurs dans la "
             "pièce (deux par endroit), du plus saillant au moins.")] = 12
    shown_places: Annotated[int, Knob(
        label="Lieux dits dans « AUTOUR DE TOI »", group="Prompt", lo=2, hi=30,
        help="Les autres endroits où elle peut aller.")] = 8


def params(p: WorldParams | None) -> WorldParams:
    return p if p is not None else WorldParams()


def timing(p: WorldParams | None) -> plan.Timing:
    p = params(p)
    return plan.Timing(walk_speed=p.walk_speed, stand_us=int(p.stand_s * US), sit_us=int(p.sit_s * US),
                       lie_us=int(p.lie_s * US), doorway_us=int(p.doorway_s * US), hand_us=int(p.hand_s * US),
                       grace_us=int(p.grace_s * US))


@dataclass(frozen=True, slots=True)
class WorldState:
    definition: w.WorldDef
    actors: FrozenDict[str, w.ActorState] = field(default_factory=FrozenDict)
    objects: FrozenDict[str, w.ObjectState] = field(default_factory=FrozenDict)
    intents: FrozenDict[str, w.Intent] = field(default_factory=FrozenDict)
    requests: FrozenDict[str, w.Request] = field(default_factory=FrozenDict)
    #: le dernier événement du monde réduit (l'instantané dit « où en est le journal »)
    seq: int = 0
    #: ses occupations terminées des derniers jours (``world.lived`` y ajoute celle en cours)
    lived: tuple[w.Lived, ...] = ()


def genesis(defn: w.WorldDef = DEFAULT_WORLD) -> WorldState:
    actors, objects = plan.genesis(defn)
    return WorldState(definition=defn, actors=FrozenDict(actors), objects=FrozenDict(objects))


WORLD = Faculty("world", state=WorldState, init=lambda p: genesis(), params=WorldParams, state_version=2)

#: Ce qu'on garde de ses occupations passées : trois jours, soixante au plus.
LIVED_KEPT_US = 3 * DAY
LIVED_KEPT = 60
WORLD.declare(*w.ALL)


def _lived(s: WorldState, actors: Mapping[str, w.ActorState], objects: Mapping[str, w.ObjectState],
           seq: int, at: int | None = None, **more: Any) -> WorldState:
    """La tranche après un changement de l'état vécu ; une occupation de Mika qui s'arrête (une autre commence,
    elle part, son temps est passé) entre dans ce qu'elle a vécu."""
    out = replace(s, actors=FrozenDict(actors), objects=FrozenDict(objects), seq=seq, **more)
    before, after = s.actors.get(w.MIKA), actors.get(w.MIKA)
    old = before.activity if before is not None else None
    if old is None or at is None or (after is not None and after.activity == old):
        return out
    end = min(old.until, at) if old.until is not None else at
    entry = w.Lived(name=old.name, label=plan.affordance_label(s.definition, old)[:60], object=old.object,
                    object_label=plan.label_of(s.definition, old.object)[:60] if old.object else "",
                    since=old.since, until=end)
    kept = tuple(x for x in s.lived if x.since >= at - LIVED_KEPT_US)[-(LIVED_KEPT - 1):]
    return replace(out, lived=(*kept, entry))


def _start(s: WorldState, intent: w.Intent, seq: int) -> WorldState:
    """Une action commence : elle remplace celle que l'acteur avait en cours (on repart d'où on en est), et
    l'arrache à ce qu'il faisait."""
    me = s.actors.get(intent.actor)
    if me is None:
        return s
    room, place = plan.destination(me, intent)
    moving = w.Movement(intent=intent.id, to_room=room, to_place=place, started=intent.started, eta=intent.eta)
    actors = dict(s.actors)
    actors[intent.actor] = me.model_copy(update={"moving": moving, "activity": None})
    intents = {k: v for k, v in s.intents.items() if v.actor != intent.actor}
    intents[intent.id] = intent
    return _lived(s, actors, s.objects, seq, intent.started, intents=FrozenDict(intents))


# ── Réducteurs ────────────────────────────────────────────────────────────


@WORLD.reducer(w.INTENDED)
def _intended(s: WorldState, e: Any, cx: Any) -> WorldState:
    return _start(s, e.data.intent, e.seq)


@WORLD.reducer(w.ENDED)
def _ended(s: WorldState, e: Any, cx: Any) -> WorldState:
    if e.data.intent not in s.intents:
        return s
    actors, objects = plan.apply(s.actors, s.objects, e.data.changes, e.at)
    me = actors.get(e.data.actor)
    if me is not None:
        actors[e.data.actor] = me.model_copy(update={"moving": None})
    intents = {k: v for k, v in s.intents.items() if k != e.data.intent}
    return _lived(s, actors, objects, e.seq, e.at, intents=FrozenDict(intents))


@WORLD.reducer(w.CHANGED)
def _changed(s: WorldState, e: Any, cx: Any) -> WorldState:
    actors, objects = plan.apply(s.actors, s.objects, e.data.changes, e.at)
    return _lived(s, actors, objects, e.seq, e.at)


@WORLD.reducer(w.AUTHORED)
def _authored(s: WorldState, e: Any, cx: Any) -> WorldState:
    """Une édition validée à l'émission ; au rejeu, une édition qui ne s'applique plus ne change rien."""
    if e.data.base_rev != s.definition.rev:
        return s
    try:
        defn = w.apply_changes(s.definition, e.data.changes)
    except ValueError:
        return s
    actors, objects = plan.reconcile(defn, s.actors, s.objects)
    intents = {k: v for k, v in s.intents.items() if v.actor in actors}
    return _lived(replace(s, definition=defn), actors, objects, e.seq, e.at, intents=FrozenDict(intents))


@WORLD.reducer(place_c.MOVED)
def _placed(s: WorldState, e: Any, cx: Any) -> WorldState:
    """Un déplacement d'avant le monde (ADR 0049) : elle y est, aussitôt, comme alors."""
    place = s.definition.place(e.data.place.value)
    me = s.actors.get(w.MIKA)
    if place is None or me is None:
        return s
    actors = dict(s.actors)
    actors[w.MIKA] = me.model_copy(update={"room": place.room, "place": place.id, "posture": plan.default_posture(place),
                                           "since": e.at, "moving": None, "activity": None})
    intents = {k: v for k, v in s.intents.items() if v.actor != w.MIKA}
    return _lived(s, actors, s.objects, e.seq, e.at, intents=FrozenDict(intents))


@WORLD.reducer(body_c.FELL_ASLEEP)
def _to_bed(s: WorldState, e: Any, cx: Any) -> WorldState:
    """Elle s'endort : elle va se coucher. L'intention naît avec l'endormissement (même transaction), si bien
    que les écrans reçoivent la destination et le sommeil ensemble — on ne dort pas debout au milieu de la
    pièce, et on ne s'endort pas avant d'être au lit."""
    bed = next(iter(s.definition.tagged("sleep")), None)
    if bed is None or w.MIKA not in s.actors:
        return s
    t = timing(cx.params)
    try:
        steps = plan.plan_go(s.definition, t, s.actors, w.MIKA, bed.id, w.Posture.LIE)
    except plan.Refused:
        return s
    if not steps:
        return s
    intent = plan.intent_of(w.MIKA, steps, e.at, t, w.Cause(source=w.Source.REFLEX, actor=w.MIKA), f"coucher:{e.id}")
    return _start(s, intent, e.seq)


@WORLD.reducer(body_c.WOKE)
def _woke(s: WorldState, e: Any, cx: Any) -> WorldState:
    """Au réveil, elle reste où elle s'est couchée — assise au bord, jusqu'à ce qu'elle décide d'en bouger."""
    me = s.actors.get(w.MIKA)
    bed = next(iter(s.definition.tagged("sleep")), None)
    if me is None or bed is None:
        return s
    going = next((i for i in s.intents.values() if i.actor == w.MIKA and i.cause.source is w.Source.REFLEX), None)
    if me.posture is not w.Posture.LIE and going is None:
        return s
    actors = dict(s.actors)
    actors[w.MIKA] = me.model_copy(update={"room": bed.room, "place": bed.id, "posture": w.Posture.SIT,
                                           "moving": None, "since": me.since if me.place == bed.id else e.at})
    intents = {k: v for k, v in s.intents.items() if v.actor != w.MIKA}
    return _lived(s, actors, s.objects, e.seq, e.at, intents=FrozenDict(intents))


# ── Faits ─────────────────────────────────────────────────────────────────


@WORLD.fact(w.DEFINITION)
def _definition(s: WorldState, cx: Any) -> w.WorldDef:
    return s.definition


@WORLD.fact(w.STATE)
def _state(s: WorldState, cx: Any) -> w.WorldState:
    return w.WorldState(rev=s.definition.rev, seq=s.seq, actors=tuple(s.actors.values()),
                        objects=tuple(s.objects.values()), intents=tuple(s.intents.values()),
                        requests=tuple(s.requests.values()))


@WORLD.fact(w.SELF)
def _self(s: WorldState, cx: Any) -> w.ActorState:
    return s.actors[w.MIKA]


@WORLD.fact(w.AROUND)
def _around_fact(s: WorldState, cx: Any) -> tuple[str, ...]:
    return tuple(plan.present(s.actors, w.MIKA))


@WORLD.fact(w.REACH)
def _reach(s: WorldState, cx: Any, actor: str) -> tuple[str, ...]:
    return tuple(plan.reachable(s.definition, s.actors, s.objects, actor))


@WORLD.fact(w.LIVED)
def _lived_fact(s: WorldState, cx: Any) -> tuple[w.Lived, ...]:
    me = s.actors[w.MIKA]
    a = me.activity
    if a is None:
        return s.lived
    ended = a.until if a.until is not None and a.until <= cx.now else None
    current = w.Lived(name=a.name, label=plan.affordance_label(s.definition, a)[:60], object=a.object,
                      object_label=plan.label_of(s.definition, a.object)[:60] if a.object else "", since=a.since,
                      until=ended)
    return (*s.lived, current)


@WORLD.fact(w.PENDING)
def _pending(s: WorldState, cx: Any, actor: str) -> tuple[w.Request, ...]:
    return tuple(r for r in s.requests.values() if r.to_actor == actor)


# ── Les outils ────────────────────────────────────────────────────────────

#: Les lieux qu'elle peut nommer : une énumération dans le schéma de l'outil (un lieu inventé est refusé
#: avant même d'arriver ici). Tirée du monde par défaut ; un monde édité (P5) demandera un schéma par épisode.
Where = enum.StrEnum("Where", {p.id: p.id for p in DEFAULT_WORLD.places})


def _places_help() -> str:
    return " ; ".join(f"{p.id} : {p.label}" for p in DEFAULT_WORLD.places)


class GoArgs(BaseModel):
    place: Where = Field(description=f"Où aller — {_places_help()}.")  # type: ignore[valid-type]
    posture: w.Posture | None = Field(default=None, description=(
        "Comment t'y tenir (facultatif) : stand (debout), sit (assise), lie (allongée, sur un lit). Sans rien : "
        "debout à un endroit où l'on se tient, assise sur une chaise ou au bord du lit."))


class InteractArgs(BaseModel):
    object: str = Field(max_length=48, description="L'identifiant de l'objet, tel que « AUTOUR DE TOI » le donne "
                        "(entre ` `).")
    action: str = Field(max_length=48, description="Ce que tu en fais, tel que « AUTOUR DE TOI » le donne : take "
                        "(prendre), put (poser), drop (lâcher), ou une action propre à l'objet (ouvrir, "
                        "regarder_dehors…).")
    target: str | None = Field(default=None, max_length=48, description="Pour put : sur quoi, dans quoi ou à quel "
                               "endroit le poser (un identifiant).")


WORLD.bundle("world", "te déplacer et faire des choses dans ta chambre (on te voit le faire)")


def _awake(frame: Frame) -> bool:
    return frame.get(body_c.SLEEP) is body_c.SleepPhase.AWAKE


def _where_phrase(defn: w.WorldDef, place: str | None, posture: w.Posture) -> str:
    p = defn.place(place) if place else None
    if p is None:
        return f"{plan.POSTURE_FR[posture]} dans la pièce"
    return f"{plan.POSTURE_FR[posture]} {p.label}"


#: Ses outils qui mettent son corps en action.
_BODY_TOOLS = frozenset({"go_to", "interact"})


def _running(s: WorldState) -> w.Intent | None:
    """L'action qu'elle a en cours, s'il y en a une."""
    return next((i for i in s.intents.values() if i.actor == w.MIKA), None)


def _busy(s: WorldState, ctx: Any) -> ToolResult | None:
    """Une action lancée plus tôt dans cette même réponse n'est pas finie : la suivante la remplacerait, et
    elle croirait avoir fait les deux. Une à la fois — la suivante, à sa prochaine réplique."""
    running = _running(s)
    if running is None or not any(ok for name, ok in ctx.calls if name in _BODY_TOOLS):
        return None
    me = s.actors[w.MIKA]
    last = next((st.posture for st in reversed(running.steps) if st.kind == "posture" and st.posture), None)
    where = _where_phrase(s.definition, me.moving.to_place if me.moving is not None else me.place,
                          last or me.posture)
    return ToolResult(ok=False, content=f"Tu es déjà en train de faire autre chose (tu seras {where}) : une chose "
                      "à la fois. Celle-ci n'est pas faite ; tu pourras la faire une fois l'autre finie, à ta "
                      "prochaine réplique.")


def _interrupted(intent: w.Intent) -> Any:
    """La fin d'une action qu'une autre remplace : les écrans l'apprennent (``intent_end``), rien n'a changé."""
    return w.ENDED.draft(intent=intent.id, actor=intent.actor, outcome=w.Outcome.INTERRUPTED,
                         dedupe_key=f"fin:{intent.id}")


async def _start_intent(ctx: Any, steps: list[w.Step]) -> w.Intent:
    frame: Frame = ctx.frame
    t = timing(frame.env.params_of("world", frame.root))
    intent = plan.intent_of(w.MIKA, steps, frame.now, t, w.Cause(source=w.Source.MIKA, actor=w.MIKA),
                            f"mika:{frame.now}")
    running = _running(ctx.state)
    await ctx.emit(*([_interrupted(running)] if running is not None else []), w.INTENDED.draft(intent=intent))
    return intent


@WORLD.tool("go_to", description="Aller ailleurs dans ta chambre : t'asseoir à ton bureau ou sur ton lit, aller à "
            "la fenêtre, devant ta bibliothèque, à la porte, ou revenir au milieu. On te voit marcher jusque-là. "
            "Seulement quand l'envie ou la conversation t'y pousse (« attends, je vais voir dehors »), pas à chaque "
            "réplique ; ne le raconte pas entre crochets, fais-le.", args=GoArgs, bundle="world",
            episodes=CONVERSATIONAL, max_calls_per_episode=1)
async def go_to(args: GoArgs, ctx: Any) -> ToolResult:
    frame: Frame = ctx.frame
    s: WorldState = ctx.state
    if not _awake(frame):
        return ToolResult(ok=False, content="Tu dors : ton corps ne bouge pas.")
    me = s.actors[w.MIKA]
    target = s.definition.place(args.place.value)
    if target is None:
        return ToolResult(ok=False, content=f"« {args.place.value} » n'est plus un endroit d'ici.")
    want = args.posture or plan.default_posture(target)
    if me.moving is not None and me.moving.to_place == target.id and (args.posture is None or me.posture == want):
        return ToolResult(content=f"Tu y vas déjà : tu seras {_where_phrase(s.definition, target.id, want)}.")
    if (busy := _busy(s, ctx)) is not None:
        return busy
    t = timing(frame.env.params_of("world", frame.root))
    try:
        steps = plan.plan_go(s.definition, t, s.actors, w.MIKA, target.id, args.posture)
    except plan.Refused as r:
        return ToolResult(ok=False, content=r.message)
    if not steps:
        if (running := _running(s)) is not None:  # elle allait ailleurs : elle s'arrête et reste là
            await ctx.emit(_interrupted(running))
            return ToolResult(content=f"Tu t'arrêtes : tu restes {_where_phrase(s.definition, target.id, me.posture)}.")
        return ToolResult(content=f"Tu y es déjà : tu es {_where_phrase(s.definition, target.id, me.posture)}.")
    await _start_intent(ctx, steps)
    return ToolResult(content=f"Tu y vas : tu seras {_where_phrase(s.definition, target.id, want)}.")


@WORLD.tool("interact", description="Faire quelque chose avec un objet autour de toi : ouvrir ta fenêtre, regarder "
            "dehors, arroser ta plante, te mettre à dessiner à ton bureau, prendre ou poser quelque chose. Tu y vas "
            "d'abord s'il le faut. Les objets et ce qu'on peut en faire sont dans « AUTOUR DE TOI ». Seulement quand "
            "tu en as envie ou qu'on te le demande ; ne le raconte pas entre crochets, fais-le.",
            args=InteractArgs, bundle="world", episodes=CONVERSATIONAL, max_calls_per_episode=3)
async def interact(args: InteractArgs, ctx: Any) -> ToolResult:
    frame: Frame = ctx.frame
    s: WorldState = ctx.state
    if not _awake(frame):
        return ToolResult(ok=False, content="Tu dors : ton corps ne bouge pas.")
    if (busy := _busy(s, ctx)) is not None:
        return busy
    t = timing(frame.env.params_of("world", frame.root))
    try:
        steps = plan.plan_interact(s.definition, t, s.actors, s.objects, w.MIKA, args.object, args.action,
                                   args.target, now=frame.now)
    except plan.Refused as r:
        return ToolResult(ok=False, content=r.message)
    await _start_intent(ctx, steps)
    what = plan.label_of(s.definition, args.object)
    verb = dict(plan.actions_of(s.definition, s.objects, s.actors[w.MIKA], args.object, frame.now)).get(
        args.action, args.action)
    return ToolResult(content=f"C'est parti : {verb} — {what}. On te voit le faire.")


# ── Le prompt ─────────────────────────────────────────────────────────────


def around(s: WorldState, now: int, p: WorldParams) -> str:
    """Ce qu'elle sait de là où elle est : son corps, ce qu'elle tient, ce qui est à portée, où elle peut aller."""
    defn = s.definition
    me = s.actors[w.MIKA]
    lines: list[str] = []
    several = len(defn.rooms) > 1
    room = defn.room(me.room)
    in_room = f", dans {room.label}" if several and room is not None else ""
    if me.moving is not None and me.moving.eta > now:
        intent = s.intents.get(me.moving.intent)
        last = next((st.posture for st in reversed(intent.steps) if st.kind == "posture" and st.posture), None) \
            if intent is not None else None
        lines.append(f"Tu es en chemin : tu seras {_where_phrase(defn, me.moving.to_place, last or me.posture)}.")
    else:
        lines.append(f"Tu es {_where_phrase(defn, me.place, me.posture)}{in_room}.")
    if me.activity is not None and (me.activity.until is None or me.activity.until > now):
        lines.append(f"Tu es en train de {plan.affordance_label(defn, me.activity)}.")
    budget = p.shown_objects
    if me.holding:
        lines.append("Tu tiens " + ", ".join(_thing(s, me, o, now) for o in me.holding) + ".")
        budget -= len(me.holding)
    reach = [o for o in plan.reachable(defn, s.actors, s.objects, w.MIKA) if o not in me.holding]
    if reach and budget > 0:
        lines.append("À portée de main : " + " ; ".join(_thing(s, me, o, now) for o in reach[:budget]) + ".")
        budget -= len(reach[:budget])
    # où aller, puis de quoi se servir : deux listes, jamais « sur ton lit : ta plante » (qui se lit « la plante
    # est sur le lit ») — ``interact`` y va de lui-même, l'endroit d'un objet n'a pas à se dire
    places = []
    for pl in [pl for pl in defn.places if pl.id != me.place][:p.shown_places]:
        room = defn.room(pl.room) if pl.room != me.room else None
        places.append(f"{pl.label} (`{pl.id}`" + (f", dans {room.label}" if room is not None else "") + ")")
    if places:
        lines.append("Tu peux aller " + " ; ".join(places) + ".")
    usable = [o for o in plan.usable(defn, s.actors, s.objects, w.MIKA, now)
              if o not in reach and o not in me.holding][:max(0, budget)]
    if usable:
        lines.append("Dans la pièce, de quoi te servir : " + " ; ".join(_thing(s, me, o, now) for o in usable) + ".")
    return "\n".join(lines)


def _thing(s: WorldState, me: w.ActorState, oid: str, now: int) -> str:
    """Un objet tel qu'elle le lit : son nom, son identifiant et son état, puis ce qu'elle peut en faire (les
    identifiants qu'attend ``interact``)."""
    defn = s.definition
    state = plan.state_label(defn, oid, s.objects[oid].state)
    acts = ", ".join(i for i, _ in plan.actions_of(defn, s.objects, me, oid, now))
    return f"{plan.label_of(defn, oid)} (`{oid}`" + (f", {state}" if state else "") + ")" + (
        f" : {acts}" if acts else "")


@WORLD.section("world", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["rhythm"], trim_rank=70,
               title="AUTOUR DE TOI", reads=[body_c.SLEEP])
def _around(s: WorldState, frame: Frame, enrich: Any) -> str | None:
    if not _awake(frame):
        return None  # elle dort, dans son lit : rien à dire à qui la réveille qu'il ne voie
    return around(s, frame.now, params(frame.env.params_of("world", frame.root)))


# ── Ce qu'elle n'a pas pu faire ───────────────────────────────────────────

#: Un geste à elle qui n'aboutit pas : remarqué juste assez pour lui rester en tête (le seuil d'une pensée de
#: l'attention, au premier échec — les suivants, habitués, à peine), et une contrariété légère, dosée par
#: l'attention comme pour tout signal (la pensée qui naît en ajoute un peu : elle reste un pincement).
SETBACK_PERTINENCE = 0.6
SETBACK_FRUSTRATION = 0.1
#: Pourquoi, comme elle se le dit (les codes qu'un geste rencontre ; les autres ne se disent pas).
SETBACK_WHY: dict[w.Refusal, str] = {
    w.Refusal.UNREACHABLE: "le chemin était bloqué",
    w.Refusal.OCCUPIED: "la place était prise",
    w.Refusal.HANDS_FULL: "tes mains étaient prises",
    w.Refusal.HELD_BY_OTHER: "quelqu'un d'autre l'avait déjà",
    w.Refusal.NOT_HOLDING: "tu ne l'avais plus en main",
    w.Refusal.WRONG_STATE: "ce n'était plus possible",
    w.Refusal.UNKNOWN: "ce n'était plus là",
}
_HAND_FR = {w.Builtin.TAKE.value: plan.TAKE_FR, w.Builtin.PUT.value: plan.PUT_FR, w.Builtin.DROP.value: plan.DROP_FR}
_POSTURE_VERB = {w.Posture.STAND: "te lever", w.Posture.SIT: "t'asseoir", w.Posture.LIE: "t'allonger"}


def _attempted(defn: w.WorldDef, intent: w.Intent) -> str:
    """Ce qu'elle tentait, à l'infinitif : son dernier geste sur un objet (une occupation se dit seule, « dessiner »),
    sinon l'endroit où elle allait, sinon la posture qu'elle prenait."""
    act = next((st for st in reversed(intent.steps) if st.kind == "act" and st.object and st.action), None)
    if act is not None and act.object and act.action:
        what = plan.label_of(defn, act.object)
        if act.action in _HAND_FR:
            return f"{_HAND_FR[act.action]} {what}"
        o = defn.object(act.object)
        a = defn.archetype(o.archetype) if o is not None else None
        aff = next((x for x in (a.affordances if a is not None else ()) if x.id == act.action), None)
        if aff is None:
            return f"{act.action} {what}"
        return aff.label if aff.effect is w.Effect.ACTIVITY else f"{aff.label} {what}"
    walk = next((st for st in reversed(intent.steps) if st.kind == "walk" and st.to_place), None)
    place = defn.place(walk.to_place) if walk is not None and walk.to_place else None
    if place is not None:
        return f"aller {place.label}"
    pose = next((st.posture for st in reversed(intent.steps) if st.kind == "posture" and st.posture), None)
    return _POSTURE_VERB[pose] if pose is not None else "faire ce que tu voulais"


def setback(s: WorldState, intent: w.Intent, outcome: w.Outcome, reason: w.Refusal | None) -> Draft[Any] | None:
    """Ce qu'elle remarque d'une action **qu'elle a décidée** et qui n'a pas abouti (ADR 0050 §7) : « tu n'as pas
    pu… », un signal que l'attention dose et habitue — sans section ni consigne. Rien pour une action remplacée
    (c'est elle qui a changé d'avis) ni pour un réflexe (le coucher) ; un seul signal par échec, que l'hôte ou
    l'échéance conclue (la clé ``echec:<intent>``)."""
    if outcome is not w.Outcome.FAILED or intent.actor != w.MIKA or intent.cause.source is not w.Source.MIKA:
        return None
    why = SETBACK_WHY.get(reason) if reason is not None else None
    text = f"Tu n'as pas pu {_attempted(s.definition, intent)}" + (f" : {why}" if why else "") + "."
    obj = next((st.object for st in reversed(intent.steps) if st.kind == "act" and st.object), None)
    return w.NOTICED.draft(
        source="world", kind="setback", summary=Content.of(text, level=int(Sensitivity.NONE)),
        pertinence=SETBACK_PERTINENCE, emotion=Emotion.FRUSTRATED.value, intensity=SETBACK_FRUSTRATION,
        sensitivity=int(Sensitivity.NONE), bundle="world", actor=intent.actor, object=obj,
        dedupe_key=f"echec:{intent.id}")


# ── Conclure sans moteur ──────────────────────────────────────────────────


def wears_off(s: WorldState, p: WorldParams) -> int | None:
    """Quand son occupation sans fin prévue (dessiner, travailler) s'arrête d'elle-même : une personne dessine une
    heure ou deux, puis s'arrête. ``None`` : rien de tel en cours."""
    me = s.actors.get(w.MIKA)
    a = me.activity if me is not None else None
    if a is None or a.until is not None:
        return None
    return a.since + p.open_activity_min * MINUTE


@WORLD.process("world.settle", wake_on=[w.INTENDED, body_c.FELL_ASLEEP, w.AUTHORED], lane="background",
               catch_up=CatchUp.ONCE, max_quantum_s=60)
class Settle:
    """Une action arrivée à son échéance se termine comme prévu — revalidée sur l'état d'alors (un moteur hôte,
    quand il y en aura un, pourra la terminer plus tôt ou dire qu'il n'y arrive pas). Et une occupation sans fin
    prévue s'arrête d'elle-même au bout d'un temps naturel (un réflexe) : son corps reste où il est, assise à son
    bureau, simplement sans plus dessiner — elle ne se lève pas et ne va nulle part à sa place."""

    def next_due(self, state: WorldState, frame: Frame, last_run: int | None) -> int | None:
        due = [i.deadline for i in state.intents.values()]
        if (tired := wears_off(state, params(frame.env.params_of("world", frame.root)))) is not None:
            due.append(tired)
        return min(due, default=None)

    async def run(self, ctx: Any) -> None:
        s: WorldState = ctx.state
        now = ctx.frame.now
        for intent in sorted(s.intents.values(), key=lambda i: (i.deadline, i.id)):
            if intent.deadline > now:
                continue
            s = ctx.state
            outcome, reason, changes = plan.conclude(s.definition, s.actors, s.objects, intent)
            noticed = setback(s, intent, outcome, reason)
            await ctx.emit(w.ENDED.draft(intent=intent.id, actor=intent.actor, outcome=outcome, reason=reason,
                                         changes=tuple(changes), dedupe_key=f"fin:{intent.id}"),
                           *([noticed] if noticed is not None else []))
        s = ctx.state
        me = s.actors.get(w.MIKA)
        tired = wears_off(s, params(ctx.frame.env.params_of("world", ctx.frame.root)))
        if me is not None and me.activity is not None and tired is not None and tired <= now:
            await ctx.emit(w.CHANGED.draft(cause=w.Cause(source=w.Source.REFLEX, actor=w.MIKA),
                                           changes=(w.ActorBusy(actor=w.MIKA, activity=None),),
                                           dedupe_key=f"lasse:{me.activity.since}"))


# ── Vers les écrans ───────────────────────────────────────────────────────


async def _show(ev: Any, ports: Mapping[str, Any]) -> None:
    """Son corps change de destination : les écrans reçoivent l'état (sans parole), le corps marche."""
    port = ports.get("delivery")
    if port is None:
        return
    frame: Frame = ports["frame"]()
    await port.deliver(Delivery(
        key=ev.id, target=None, channel=None, room=None, text="", persona="inner",
        emotion=EmotionView("neutral", 0.0), message_id=ev.seq, sleep_phase=frame.get(body_c.SLEEP).value,
        local_hour=frame.local().hour, kind="state"))


WORLD.effect(w.INTENDED, when=lambda d: d.intent.actor == w.MIKA and d.intent.cause.source is not w.Source.REFLEX)(
    _show)
WORLD.effect(w.ENDED, when=lambda d: d.actor == w.MIKA and d.outcome is not w.Outcome.DONE)(_show)
WORLD.effect(w.AUTHORED)(_show)


from mika.faculties.world import inspect as _inspect  # noqa: E402,F401 — contributions : ses vues

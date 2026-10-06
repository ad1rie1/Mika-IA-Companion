"""Ce qu'une action devient : valider, planifier, conclure — sans rien lire d'autre que le monde (ADR 0050).

Pur : la définition, l'état vécu, des durées et un instant entrent ; des pas, des changements ou un refus
sortent. Le même code sert à ses outils (planifier ce qu'elle décide), aux réflexes (le coucher, le bureau, dans
un réducteur) et à la fin d'une action (le processus qui conclut sans moteur, et revalide au moment de conclure :
ce qui était vrai au départ ne l'est peut-être plus).
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from mika.contracts import world as w
from mika.kernel.clock import US
from mika.vocab.phrasebook import family, phrase

Actors = Mapping[str, w.ActorState]
Objects = Mapping[str, w.ObjectState]



def posture_words(posture: w.Posture) -> str:
    """Sa posture en mots : « debout », « assise », « allongée » (``world.posture``)."""
    return family("world.posture")[posture.value]


#: sa posture en mots, pour qui la lit d'ici (la console)
POSTURE_FR = {p: posture_words(p) for p in w.Posture}
#: les actions de base qu'on fait avec les mains, sur un objet (s'asseoir ou s'allonger passe par un lieu)
HAND_ACTIONS = frozenset({w.Builtin.TAKE, w.Builtin.PUT, w.Builtin.DROP, w.Builtin.GIVE})
#: au-delà, un trajet est trop long pour une seule action
MAX_STEPS = 8
#: le tag d'un lieu où l'on travaille, et le nom de l'occupation qu'on y a (ADR 0050 §6)
WORK = "work"


class Refused(Exception):
    """Une action que les règles du monde n'admettent pas : un code, et ce que ça veut dire pour elle."""

    def __init__(self, code: w.Refusal, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class Timing:
    """Les durées nominales d'un corps (celles du moteur, à peu près) : sans moteur, une action dure ça."""

    walk_speed: float = 0.9  # m/s
    stand_us: int = int(1.2 * US)
    sit_us: int = int(1.5 * US)
    lie_us: int = int(2.5 * US)
    doorway_us: int = 2 * US
    hand_us: int = int(1.2 * US)
    settle_us: int = 1 * US
    grace_us: int = 2 * US

    def posture_us(self, posture: w.Posture) -> int:
        return {w.Posture.STAND: self.stand_us, w.Posture.SIT: self.sit_us, w.Posture.LIE: self.lie_us}[posture]


# ── L'état vécu ───────────────────────────────────────────────────────────


def default_posture(place: w.PlaceDef) -> w.Posture:
    """Ce qu'on fait à un lieu quand on n'en dit pas plus : debout à la fenêtre, assise au bureau et sur le lit
    (s'y allonger est le coucher, ou une demande explicite)."""
    return w.Posture.STAND if place.place_kind is w.PlaceKind.SPOT else w.Posture.SIT


def label_of(defn: w.WorldDef, obj: str) -> str:
    o = defn.object(obj)
    if o is None:
        return obj
    if o.label:
        return o.label
    a = defn.archetype(o.archetype)
    return a.label if a is not None else obj


def state_label(defn: w.WorldDef, obj: str, state: str | None) -> str:
    o = defn.object(obj)
    a = defn.archetype(o.archetype) if o is not None else None
    if state is None:
        return ""
    return a.state_labels.get(state, state) if a is not None else state


def _actor_at_home(defn: w.WorldDef, a: w.ActorDef) -> w.ActorState:
    place = defn.place(a.home)
    assert place is not None  # une définition est cohérente
    return w.ActorState(id=a.id, room=place.room, place=place.id, posture=default_posture(place))


def _object_at_home(defn: w.WorldDef, o: w.ObjectDef) -> w.ObjectState:
    a = defn.archetype(o.archetype)
    state = o.state if o.state is not None else (a.initial_state if a is not None else None)
    return w.ObjectState(id=o.id, location=o.home, state=state, given_by=o.given_by)


def genesis(defn: w.WorldDef) -> tuple[dict[str, w.ActorState], dict[str, w.ObjectState]]:
    """Le monde au moment où il est créé : chacun à son lieu, chaque chose à sa place."""
    actors = {a.id: _actor_at_home(defn, a) for a in defn.actors}
    objects = {o.id: _object_at_home(defn, o) for o in defn.objects}
    return actors, _with_holding(actors, objects)[1]


def _location_valid(defn: w.WorldDef, loc: w.Location, actors: Actors) -> bool:
    if isinstance(loc, w.InRoom):
        place = defn.place(loc.near) if loc.near else None
        return defn.room(loc.room) is not None and (loc.near is None or (place is not None and place.room == loc.room))
    if isinstance(loc, w.Held):
        return loc.actor in actors
    support = defn.object(loc.object)
    a = defn.archetype(support.archetype) if support is not None else None
    if a is None:
        return False
    return loc.slot < a.surface_slots if isinstance(loc, w.On) else a.container_slots > 0


def rehome(before: w.WorldDef, after: w.WorldDef, objects: Objects, now: int) -> dict[str, w.ObjectState]:
    """Une édition qui change le foyer d'un objet resté à sa place le déplace : il était chez lui, et c'est chez lui
    qui a bougé (un meuble que l'opératrice a poussé). Un objet qu'on a mis ailleurs reste où on l'a mis."""
    out = dict(objects)
    for o in after.objects:
        old, cur = before.object(o.id), objects.get(o.id)
        if old is not None and cur is not None and old.home != o.home and cur.location == old.home:
            out[o.id] = cur.model_copy(update={"location": o.home, "since": now})
    return out


def reconcile(defn: w.WorldDef, actors: Actors, objects: Objects) -> tuple[dict[str, w.ActorState],
                                                                           dict[str, w.ObjectState]]:
    """Après une édition : ce qui a encore un sens reste où il est, le reste rentre chez soi (un objet retiré
    disparaît, des mains comprises)."""
    out_actors: dict[str, w.ActorState] = {}
    for a in defn.actors:
        cur = actors.get(a.id)
        place = defn.place(cur.place) if cur is not None and cur.place else None
        ok = cur is not None and defn.room(cur.room) is not None and (cur.place is None or (
            place is not None and place.room == cur.room))
        out_actors[a.id] = cur if ok and cur is not None else _actor_at_home(defn, a)
    for aid, cur in actors.items():
        if aid.startswith(w.PLAYER_PREFIX) and defn.room(cur.room) is not None:
            place = defn.place(cur.place) if cur.place else None
            out_actors[aid] = cur if cur.place is None or (place and place.room == cur.room) else cur.model_copy(
                update={"place": None})
    out_objects: dict[str, w.ObjectState] = {}
    taken: set[tuple[str, int]] = set()
    for o in defn.objects:
        cur = objects.get(o.id)
        a = defn.archetype(o.archetype)
        if cur is None or not _location_valid(defn, cur.location, out_actors):
            cur = _object_at_home(defn, o)
        if a is not None and cur.state not in (a.states or (None,)):
            cur = cur.model_copy(update={"state": a.initial_state})
        if isinstance(cur.location, w.On):
            key = (cur.location.object, cur.location.slot)
            if key in taken:
                cur = _object_at_home(defn, o)
            taken.add(key)
        out_objects[o.id] = cur
    return _with_holding(out_actors, out_objects)


def _with_holding(actors: Actors, objects: Objects) -> tuple[dict[str, w.ActorState], dict[str, w.ObjectState]]:
    """Ce que chacun tient se lit dans les objets (une seule vérité : la place de l'objet)."""
    held: dict[str, list[str]] = {}
    for oid, o in sorted(objects.items()):
        if isinstance(o.location, w.Held):
            held.setdefault(o.location.actor, []).append(oid)
    out = {aid: a if a.holding == tuple(held.get(aid, ())) else a.model_copy(update={"holding": tuple(held.get(aid, ()))})
           for aid, a in actors.items()}
    return out, dict(objects)


def apply(actors: Actors, objects: Objects, changes: Iterable[w.ActorMoved | w.ActorBusy | w.ObjectMoved | w.ObjectSet
                                                                | w.ObjectGone],
          now: int) -> tuple[dict[str, w.ActorState], dict[str, w.ObjectState]]:
    """L'état vécu après des changements (ceux d'un constat, d'une action conclue). Total : un changement qui ne
    s'applique plus (un objet disparu entre-temps) est ignoré."""
    acts = dict(actors)
    objs = dict(objects)
    for ch in changes:
        if isinstance(ch, w.ActorMoved):
            cur = acts.get(ch.actor)
            if cur is None:
                continue
            moved = cur.place != ch.place or cur.room != ch.room
            acts[ch.actor] = cur.model_copy(update={"room": ch.room, "place": ch.place, "posture": ch.posture,
                                                    "since": now if moved else cur.since})
        elif isinstance(ch, w.ActorBusy):
            cur = acts.get(ch.actor)
            if cur is not None:
                acts[ch.actor] = cur.model_copy(update={"activity": ch.activity})
        elif isinstance(ch, w.ObjectMoved):
            cur_o = objs.get(ch.object)
            if cur_o is not None:
                objs[ch.object] = cur_o.model_copy(update={"location": ch.to, "since": now})
        elif isinstance(ch, w.ObjectSet):
            cur_o = objs.get(ch.object)
            if cur_o is not None:
                objs[ch.object] = cur_o.model_copy(update={"state": ch.state})
        else:
            objs.pop(ch.object, None)
    return _with_holding(acts, objs)


# ── Où sont les choses ────────────────────────────────────────────────────


def anchor_of(defn: w.WorldDef, actors: Actors, objects: Objects, obj: str) -> tuple[str, str | None] | None:
    """La pièce et le lieu d'où l'on atteint un objet : là où il est posé, de surface en surface ; dans une main,
    là où se tient qui le tient. ``None`` : introuvable."""
    seen: set[str] = set()
    cur = objects.get(obj)
    while cur is not None:
        loc = cur.location
        if isinstance(loc, w.InRoom):
            return loc.room, loc.near
        if isinstance(loc, w.Held):
            holder = actors.get(loc.actor)
            return (holder.room, holder.place) if holder is not None else None
        if loc.object in seen:
            return None
        seen.add(loc.object)
        cur = objects.get(loc.object)
    return None


def reachable(defn: w.WorldDef, actors: Actors, objects: Objects, actor: str) -> list[str]:
    """Ce qu'un acteur a à portée, du plus saillant au moins : ce qu'il tient, puis ce qui est à son lieu (posé
    là, sur un meuble de là, dans un contenant de là), puis ce qui est dans la pièce sans lieu."""
    me = actors.get(actor)
    if me is None:
        return []
    out: list[tuple[float, str]] = []
    for oid in sorted(objects):
        anchor = anchor_of(defn, actors, objects, oid)
        if anchor is None:
            continue
        room, near = anchor
        held = oid in me.holding
        if held or (room == me.room and (near is None or near == me.place)):
            out.append((2.0 if held else salience(defn, oid), oid))
    return [oid for _, oid in sorted(out, key=lambda x: (-x[0], x[1]))]


def salience(defn: w.WorldDef, obj: str) -> float:
    o = defn.object(obj)
    if o is None:
        return 0.0
    if o.salience is not None:
        return o.salience
    a = defn.archetype(o.archetype)
    return a.salience if a is not None else 0.5


def usable(defn: w.WorldDef, actors: Actors, objects: Objects, actor: str, now: int | None = None) -> list[str]:
    """Ce dont un acteur peut se servir dans sa pièce (au moins une action possible), du plus saillant au moins."""
    me = actors.get(actor)
    if me is None:
        return []
    out = []
    for oid in objects:
        anchor = anchor_of(defn, actors, objects, oid)
        if anchor is not None and anchor[0] == me.room and actions_of(defn, objects, me, oid, now):
            out.append(oid)
    return sorted(out, key=lambda o: (-salience(defn, o), o))


def present(actors: Actors, actor: str) -> list[str]:
    """Les autres acteurs dans la même pièce."""
    me = actors.get(actor)
    return [] if me is None else [a for a in sorted(actors) if a != actor and actors[a].room == me.room]


# ── Planifier ─────────────────────────────────────────────────────────────


def _pos(defn: w.WorldDef, place: str | None) -> w.Pos:
    p = defn.place(place) if place else None
    return p.pos if p is not None else w.Pos(x=0.0, z=0.0)


def _walk(defn: w.WorldDef, t: Timing, room: str, a: str | None, b: str) -> w.Step:
    pa, pb = _pos(defn, a), _pos(defn, b)
    d = math.hypot(pa.x - pb.x, pa.z - pb.z)
    return w.Step(kind="walk", to_room=room, to_place=b, duration_us=int(d / t.walk_speed * US))


def route(defn: w.WorldDef, t: Timing, room: str, place: str | None, to: w.PlaceDef) -> list[w.Step]:
    """Les pas pour marcher jusqu'à un lieu : droit dans la même pièce, sinon de passage en passage."""
    if room == to.room:
        return [] if place == to.id else [_walk(defn, t, room, place, to.id)]
    prev: dict[str, tuple[str, w.Exit] | None] = {room: None}
    queue = deque([room])
    while queue:
        r = queue.popleft()
        here = defn.room(r)
        for x in here.exits if here is not None else ():
            if x.to not in prev:
                prev[x.to] = (r, x)
                queue.append(x.to)
    if to.room not in prev:
        raise Refused(w.Refusal.UNREACHABLE, phrase("world.refusals.no_path", place=to.label))
    hops: list[w.Exit] = []
    r = to.room
    while (link := prev[r]) is not None:
        r, x = link
        hops.append(x)
    steps: list[w.Step] = []
    cur_room, cur_place = room, place
    for x in reversed(hops):
        if cur_place != x.via:
            steps.append(_walk(defn, t, cur_room, cur_place, x.via))
        steps.append(w.Step(kind="walk", to_room=x.to, to_place=x.arrives, duration_us=t.doorway_us))
        cur_room, cur_place = x.to, x.arrives
    if cur_place != to.id:
        steps.append(_walk(defn, t, cur_room, cur_place, to.id))
    return steps


def _occupants(actors: Actors, place: str, but: str) -> int:
    return sum(1 for a in actors.values() if a.id != but and (a.place == place or (
        a.moving is not None and a.moving.to_place == place)))


def plan_go(defn: w.WorldDef, t: Timing, actors: Actors, actor: str, place_id: str,
            posture: w.Posture | None = None) -> list[w.Step]:
    """Aller à un lieu, et s'y tenir comme il se doit. Une liste vide : elle y est déjà, comme ça."""
    me = actors[actor]
    place = defn.place(place_id)
    if place is None:
        raise Refused(w.Refusal.UNKNOWN, phrase("world.refusals.not_a_place", place=place_id))
    want = posture or default_posture(place)
    if want not in w.POSTURES[place.place_kind]:
        raise Refused(w.Refusal.WRONG_POSTURE, phrase("world.refusals.wrong_posture", posture=posture_words(want),
                                                      place=place.label))
    here = me.place == place.id and me.room == place.room
    if here and me.posture == want:
        return []
    if not here and _occupants(actors, place.id, actor) >= place.capacity:
        raise Refused(w.Refusal.OCCUPIED, phrase("world.refusals.no_room_at", place=place.label))
    steps: list[w.Step] = []
    if not here:
        if me.posture is not w.Posture.STAND:
            steps.append(w.Step(kind="posture", posture=w.Posture.STAND, duration_us=t.stand_us))
        steps += route(defn, t, me.room, me.place, place)
    if want is not w.Posture.STAND or (here and me.posture is not w.Posture.STAND):
        steps.append(w.Step(kind="posture", posture=want, duration_us=t.posture_us(want)))
    if len(steps) > MAX_STEPS:
        raise Refused(w.Refusal.UNREACHABLE, phrase("world.refusals.too_far_go", place=place.label))
    return steps


def _hands_free(defn: w.WorldDef, objects: Objects, me: w.ActorState) -> int:
    used = 0
    for oid in me.holding:
        o = defn.object(oid)
        a = defn.archetype(o.archetype) if o is not None else None
        used += 2 if a is not None and a.size is w.Size.ARMS else 1
    return max(0, 2 - used)


def _hand_for(defn: w.WorldDef, objects: Objects, me: w.ActorState, size: w.Size) -> w.Hand:
    if size is w.Size.ARMS:
        return w.Hand.BOTH
    used = {objects[o].location.hand for o in me.holding if o in objects and isinstance(objects[o].location, w.Held)}
    return w.Hand.LEFT if w.Hand.RIGHT in used else w.Hand.RIGHT


def _doing(me: w.ActorState, activity: str | None, obj: str, now: int | None) -> bool:
    """Elle est en train de faire cette occupation avec cet objet : une occupation échue ne compte plus (la règle
    d'``around``). Sans heure (``now`` vide), toute occupation inscrite compte."""
    cur = me.activity
    return cur is not None and cur.name == activity and cur.object == obj and (
        now is None or cur.until is None or cur.until > now)


def actions_of(defn: w.WorldDef, objects: Objects, me: w.ActorState, obj: str,
               now: int | None = None) -> list[tuple[str, str]]:
    """Ce qu'elle peut faire de cet objet, maintenant : ``(identifiant, nom)``."""
    o = defn.object(obj)
    cur = objects.get(obj)
    a = defn.archetype(o.archetype) if o is not None else None
    if o is None or a is None or cur is None:
        return []
    out: list[tuple[str, str]] = []
    held_by_me = isinstance(cur.location, w.Held) and cur.location.actor == me.id
    if a.size is not w.Size.FIXED:
        if held_by_me:
            out += [(w.Builtin.PUT.value, phrase("world.hands.put")), (w.Builtin.DROP.value, phrase("world.hands.drop"))]
        elif not isinstance(cur.location, w.Held):
            out.append((w.Builtin.TAKE.value, phrase("world.hands.take")))
    for aff in a.affordances:
        if aff.requires_state and cur.state not in aff.requires_state:
            continue
        if _doing(me, aff.activity, obj, now):
            continue
        out.append((aff.id, aff.label))
    return out


def _target_location(defn: w.WorldDef, actors: Actors, objects: Objects, obj: str,
                     target: str | None) -> tuple[w.Location, tuple[str, str | None]]:
    """Où poser ce qu'on tient : sur une surface (la première place libre), dans un contenant, ou au sol d'un
    lieu. Rend l'emplacement et d'où on l'atteint."""
    what = label_of(defn, obj)
    if not target:
        raise Refused(w.Refusal.UNKNOWN, phrase("world.refusals.put_where", what=what))
    place = defn.place(target)
    if place is not None:
        return w.InRoom(room=place.room, near=place.id), (place.room, place.id)
    support = defn.object(target)
    a = defn.archetype(support.archetype) if support is not None else None
    if support is None or a is None or target == obj:
        raise Refused(w.Refusal.UNKNOWN, phrase("world.refusals.not_a_support", target=target))
    anchor = anchor_of(defn, actors, objects, target)
    if anchor is None:
        raise Refused(w.Refusal.UNKNOWN, phrase("world.refusals.lost", what=label_of(defn, target)))
    if a.surface_slots:
        used = {o.location.slot for o in objects.values() if isinstance(o.location, w.On) and o.location.object == target}
        free = next((i for i in range(a.surface_slots) if i not in used), None)
        if free is None:
            raise Refused(w.Refusal.OCCUPIED, phrase("world.refusals.no_room_on", what=label_of(defn, target)))
        return w.On(object=target, slot=free), anchor
    if a.container_slots:
        inside = sum(1 for o in objects.values() if isinstance(o.location, w.In) and o.location.object == target)
        if inside >= a.container_slots:
            raise Refused(w.Refusal.OCCUPIED, phrase("world.refusals.full", what=label_of(defn, target)))
        return w.In(object=target), anchor
    raise Refused(w.Refusal.WRONG_STATE, phrase("world.refusals.not_a_surface", what=label_of(defn, target)))


def _approach(defn: w.WorldDef, t: Timing, actors: Actors, actor: str, anchor: tuple[str, str | None],
              activity: bool) -> list[w.Step]:
    """Les pas pour avoir quelque chose à portée : aller au lieu d'où on l'atteint (assise si c'est une
    occupation à un lieu où l'on s'assied), ou seulement entrer dans sa pièce s'il n'a pas de lieu."""
    me = actors[actor]
    room, near = anchor
    if near is None:
        if room == me.room:
            return []
        entry = next((p for p in defn.tagged("spawn") if p.room == room), None) or next(
            (p for p in defn.places if p.room == room), None)
        if entry is None:
            raise Refused(w.Refusal.UNREACHABLE, phrase("world.refusals.nowhere_to_stand"))
        return plan_go(defn, t, actors, actor, entry.id, w.Posture.STAND)
    place = defn.place(near)
    assert place is not None
    if me.place == near and me.room == room:
        return []
    posture = default_posture(place) if activity else w.Posture.STAND
    return plan_go(defn, t, actors, actor, near, posture)


def plan_interact(defn: w.WorldDef, t: Timing, actors: Actors, objects: Objects, actor: str, obj: str, action: str,
                  target: str | None = None, now: int | None = None) -> list[w.Step]:
    """Agir sur un objet : y aller s'il le faut, le prendre d'abord s'il faut le tenir, puis agir."""
    me = actors[actor]
    o = defn.object(obj)
    cur = objects.get(obj)
    a = defn.archetype(o.archetype) if o is not None else None
    if o is None or a is None or cur is None:
        raise Refused(w.Refusal.UNKNOWN, phrase("world.refusals.not_a_thing", object=obj))
    what = label_of(defn, obj)
    held_by_me = isinstance(cur.location, w.Held) and cur.location.actor == actor
    anchor = anchor_of(defn, actors, objects, obj)
    if anchor is None:
        raise Refused(w.Refusal.UNKNOWN, phrase("world.refusals.lost", what=what))
    if action in {b.value for b in w.Builtin} and action not in HAND_ACTIONS:
        raise Refused(w.Refusal.UNKNOWN, phrase("world.refusals.posture_is_a_place"))
    if action == w.Builtin.GIVE:
        raise Refused(w.Refusal.UNKNOWN, phrase("world.refusals.nobody_to_give", what=what))
    if action == w.Builtin.TAKE:
        _check_take(defn, objects, me, obj, a)
        return [*_approach(defn, t, actors, actor, anchor, False),
                w.Step(kind="act", object=obj, action=action, duration_us=t.hand_us)]
    if action in (w.Builtin.PUT, w.Builtin.DROP):
        if not held_by_me:
            raise Refused(w.Refusal.NOT_HOLDING, phrase("world.refusals.not_holding", what=what))
        if action == w.Builtin.DROP:
            return [w.Step(kind="act", object=obj, action=action,
                           target=w.InRoom(room=me.room, near=me.place), duration_us=t.hand_us)]
        loc, reach = _target_location(defn, actors, objects, obj, target)
        return [*_approach(defn, t, actors, actor, reach, False),
                w.Step(kind="act", object=obj, action=action, target=loc, duration_us=t.hand_us)]
    aff = next((x for x in a.affordances if x.id == action), None)
    if aff is None:
        can = ", ".join(f"« {i} » ({label})" for i, label in actions_of(defn, objects, me, obj, now)) or \
            phrase("world.refusals.nothing_possible")
        raise Refused(w.Refusal.UNKNOWN, phrase("world.refusals.cannot_do", what=what, can=can, action=action))
    if aff.requires_state and cur.state not in aff.requires_state:
        raise Refused(w.Refusal.WRONG_STATE, phrase("world.refusals.in_state", what=what,
                                                    state=state_label(defn, obj, cur.state)))
    if aff.effect is w.Effect.ACTIVITY and _doing(me, aff.activity, obj, now):
        raise Refused(w.Refusal.WRONG_STATE, phrase("world.refusals.already_doing", activity=aff.label))
    steps: list[w.Step] = []
    lasting = aff.effect is w.Effect.ACTIVITY
    if aff.held and not held_by_me:
        _check_take(defn, objects, me, obj, a)
        steps += _approach(defn, t, actors, actor, anchor, False)
        steps.append(w.Step(kind="act", object=obj, action=w.Builtin.TAKE.value, duration_us=t.hand_us))
        # une occupation à un endroit où l'on s'assied (dessiner au bureau) : prendre debout, puis s'asseoir
        place = defn.place(anchor[1]) if anchor[1] else None
        posture = next((s.posture for s in reversed(steps) if s.kind == "posture" and s.posture), None) or (
            me.posture if me.place == anchor[1] else w.Posture.STAND)
        if lasting and place is not None and default_posture(place) is not w.Posture.STAND and posture is not \
                default_posture(place):
            steps.append(w.Step(kind="posture", posture=default_posture(place),
                                duration_us=t.posture_us(default_posture(place))))
    elif not held_by_me:
        steps += _approach(defn, t, actors, actor, anchor, lasting)
    duration = t.settle_us if lasting else int((aff.duration_s or 0.0) * US)
    steps.append(w.Step(kind="act", object=obj, action=aff.id, duration_us=duration))
    if len(steps) > MAX_STEPS:
        raise Refused(w.Refusal.UNREACHABLE, phrase("world.refusals.too_far_act", action=aff.label, what=what))
    return steps


def work_desk(defn: w.WorldDef, actors: Actors, objects: Objects) -> tuple[str, str] | None:
    """Où elle se met au travail : le premier objet posé à un lieu ``work`` qui offre de quoi travailler (une
    occupation ``work``), et l'action qui l'y met. ``None`` : ce monde n'en a pas."""
    for place in defn.tagged(WORK):
        for o in defn.objects:
            anchor = anchor_of(defn, actors, objects, o.id)
            a = defn.archetype(o.archetype)
            if anchor is None or anchor[1] != place.id or a is None:
                continue
            aff = next((x for x in a.affordances if x.effect is w.Effect.ACTIVITY and x.activity == WORK), None)
            if aff is not None:
                return o.id, aff.id
    return None


def _check_take(defn: w.WorldDef, objects: Objects, me: w.ActorState, obj: str, a: w.ArchetypeDef) -> None:
    what = label_of(defn, obj)
    cur = objects[obj]
    if a.size is w.Size.FIXED:
        raise Refused(w.Refusal.NOT_PORTABLE, phrase("world.refusals.not_portable", what=what))
    if isinstance(cur.location, w.Held):
        if cur.location.actor == me.id:
            raise Refused(w.Refusal.WRONG_STATE, phrase("world.refusals.already_holding", what=what))
        raise Refused(w.Refusal.HELD_BY_OTHER, phrase("world.refusals.held_by_other", what=what))
    if _hands_free(defn, objects, me) < (2 if a.size is w.Size.ARMS else 1):
        raise Refused(w.Refusal.HANDS_FULL, phrase("world.refusals.hands_full"))


def intent_of(actor: str, steps: list[w.Step], started: int, t: Timing, cause: w.Cause, ident: str) -> w.Intent:
    eta = started + sum(s.duration_us for s in steps)
    return w.Intent(id=ident, actor=actor, steps=tuple(steps), started=started, eta=eta, deadline=eta + t.grace_us,
                    cause=cause)


def destination(me: w.ActorState, intent: w.Intent) -> tuple[str, str | None]:
    """Où une action mène son acteur (sa pièce, son lieu)."""
    room, place = me.room, me.place
    for s in intent.steps:
        if s.kind == "walk" and s.to_room:
            room, place = s.to_room, s.to_place
    return room, place


# ── Conclure ──────────────────────────────────────────────────────────────


def conclude(defn: w.WorldDef, actors: Actors, objects: Objects, intent: w.Intent
             ) -> tuple[w.Outcome, w.Refusal | None, list[w.StateChange]]:
    """L'issue d'une action jouée jusqu'au bout : chaque geste revalidé sur l'état d'alors (le monde a pu
    changer depuis le départ). Un geste devenu impossible arrête l'action là où elle en est : elle a marché,
    mais la tasse n'est plus là."""
    me = actors.get(intent.actor)
    if me is None:
        return w.Outcome.FAILED, w.Refusal.UNKNOWN, []
    acts, objs = dict(actors), dict(objects)
    room, place, posture = me.room, me.place, me.posture
    at = intent.started
    changes: list[w.StateChange] = []
    for step in intent.steps:
        at += step.duration_us
        if step.kind == "walk" and step.to_room:
            room, place = step.to_room, step.to_place
        elif step.kind == "posture" and step.posture is not None:
            posture = step.posture
        elif step.kind == "act" and step.object and step.action:
            body = w.ActorMoved(actor=intent.actor, room=room, place=place, posture=posture)
            acts, objs = apply(acts, objs, [body], at)
            try:
                done = _act(defn, acts, objs, intent.actor, step, at)
            except Refused as r:
                return w.Outcome.FAILED, r.code, [body]
            acts, objs = apply(acts, objs, done, at)
            changes += done
    return w.Outcome.DONE, None, [w.ActorMoved(actor=intent.actor, room=room, place=place, posture=posture), *changes]


def _act(defn: w.WorldDef, actors: Actors, objects: Objects, actor: str, step: w.Step, at: int
         ) -> list[w.StateChange]:
    obj, action = step.object or "", step.action or ""
    me = actors[actor]
    o = defn.object(obj)
    cur = objects.get(obj)
    a = defn.archetype(o.archetype) if o is not None else None
    if o is None or a is None or cur is None:
        raise Refused(w.Refusal.UNKNOWN, phrase("world.refusals.gone", object=obj))
    held_by_me = isinstance(cur.location, w.Held) and cur.location.actor == actor
    anchor = anchor_of(defn, actors, objects, obj)
    within = held_by_me or (anchor is not None and anchor[0] == me.room and anchor[1] in (None, me.place))
    if action == w.Builtin.TAKE:
        _check_take(defn, objects, me, obj, a)
        if not within:
            raise Refused(w.Refusal.UNREACHABLE, phrase("world.refusals.out_of_reach", what=label_of(defn, obj)))
        return [w.ObjectMoved(object=obj, to=w.Held(actor=actor, hand=_hand_for(defn, objects, me, a.size)))]
    if action in (w.Builtin.PUT, w.Builtin.DROP):
        if not held_by_me or step.target is None:
            raise Refused(w.Refusal.NOT_HOLDING, phrase("world.refusals.no_longer_holding", what=label_of(defn, obj)))
        if isinstance(step.target, w.On) and any(
                isinstance(x.location, w.On) and x.location.object == step.target.object
                and x.location.slot == step.target.slot for x in objects.values()):
            raise Refused(w.Refusal.OCCUPIED, phrase("world.refusals.taken_meanwhile"))
        return [w.ObjectMoved(object=obj, to=step.target)]
    aff = next((x for x in a.affordances if x.id == action), None)
    if aff is None:
        raise Refused(w.Refusal.UNKNOWN, phrase("world.refusals.cannot", what=label_of(defn, obj), action=action))
    if not within:
        raise Refused(w.Refusal.UNREACHABLE, phrase("world.refusals.out_of_reach", what=label_of(defn, obj)))
    if aff.held and not held_by_me:
        raise Refused(w.Refusal.NOT_HOLDING, phrase("world.refusals.must_hold", what=label_of(defn, obj)))
    if aff.requires_state and cur.state not in aff.requires_state:
        raise Refused(w.Refusal.WRONG_STATE, phrase("world.refusals.in_state", what=label_of(defn, obj),
                                                    state=state_label(defn, obj, cur.state)))
    out: list[w.StateChange] = []
    if aff.to_state is not None:
        out.append(w.ObjectSet(object=obj, state=aff.to_state))
    if aff.effect is w.Effect.ACTIVITY and aff.activity is not None:
        until = None if aff.duration_s is None else at + int(aff.duration_s * US)
        out.append(w.ActorBusy(actor=actor, activity=w.Activity(name=aff.activity, object=obj, since=at, until=until,
                                                                nourishes=aff.nourishes)))
    if aff.effect is w.Effect.CONSUME:
        out.append(w.ObjectGone(object=obj))
    return out


def affordance_label(defn: w.WorldDef, activity: w.Activity) -> str:
    """Comment elle dit ce qu'elle est en train de faire (le nom de l'action qui l'a commencé)."""
    o = defn.object(activity.object) if activity.object else None
    a = defn.archetype(o.archetype) if o is not None else None
    aff = next((x for x in (a.affordances if a is not None else ()) if x.activity == activity.name), None)
    return aff.label if aff is not None else activity.name

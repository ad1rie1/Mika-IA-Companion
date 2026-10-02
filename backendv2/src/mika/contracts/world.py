"""Contrat de ``world`` : le monde en 3D où elle vit, et ce qu'on y fait (ADR 0050).

Le monde a deux couches, et le journal tient les deux :

- la **définition**, écrite par le créateur (une opératrice) : les pièces, les
  lieux où l'on peut se tenir, s'asseoir ou s'allonger, les sortes d'objets
  (archétypes) et ce qu'on peut en faire (affordances), les objets eux-mêmes,
  les personnages. Une définition **incohérente ne se construit pas**
  (``WorldDef`` refuse à la validation) ; on la modifie par lots de
  changements (``world.authored``), chacun sur la révision qu'il a lue ;
- l'**état vécu** : où est chaque personnage et chaque objet maintenant, dans
  quel état, qui tient quoi, qui fait quoi, ce qui est en route. Il change par
  les outils de Mika, les gestes des joueuses, les réflexes (le sommeil la met
  au lit), et ce que le moteur de jeu constate (une tasse tombée).

La vérité est **discrète** : un lieu, une surface et sa place, l'intérieur
d'un contenant, une main — jamais des coordonnées (seule la définition porte
une position grossière par lieu, pour les distances). La physique du moteur
n'est jamais la source de vérité : il peut **constater** une issue (que le
noyau valide) et **refuser** une action qu'il n'arrive pas à jouer, jamais
décider seul.

Un même vocabulaire pour tout le monde : Mika, une joueuse et un personnage
du moteur agissent par les mêmes actions, validées par les mêmes règles.
Tous les instants sont en microsecondes (l'horloge du noyau).
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from mika.contracts.attention import Signal
from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey

OWNER = "world"
FORMAT = "mika.world/1"

# ── Identifiants et textes ────────────────────────────────────────────────

#: L'identifiant d'une pièce, d'un lieu, d'un objet, d'un archétype : une seule famille de noms pour les
#: pièces, les lieux et les objets (``go_to("desk")`` ne peut pas être ambigu).
Ident = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,47}$")]
#: ``mika``, ``npc:<ident>`` (un personnage du monde) ou ``player:<adresse>`` (une personne dans le monde).
ActorId = Annotated[str, StringConstraints(pattern=r"^(mika|npc:[a-z][a-z0-9_]{0,47}|player:[^\s]{1,96})$")]
#: La clé d'une ressource du moteur (un prefab, un modèle) ou d'une ancre de sa scène : le noyau ne la lit pas.
AssetKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_./-]{1,120}$")]
#: Un nom qu'elle lira dans son prompt : court, sans retour à la ligne ni caractère de contrôle (un nom ne
#: peut pas imiter un titre de section).
Label = Annotated[str, StringConstraints(pattern=r"^[^\x00-\x1f\x7f]{1,60}$", strip_whitespace=True)]

MIKA = "mika"
PLAYER_PREFIX = "player:"
NPC_PREFIX = "npc:"


def player(handle: str) -> str:
    """L'acteur d'une personne dans le monde : son adresse (``player:web_1a2b``)."""
    return f"{PLAYER_PREFIX}{handle}"


def handle_of(actor: str) -> str | None:
    """L'adresse d'une personne derrière un acteur, ``None`` pour Mika et les personnages du moteur."""
    return actor[len(PLAYER_PREFIX):] if actor.startswith(PLAYER_PREFIX) else None


class Posture(enum.StrEnum):
    STAND = "stand"
    SIT = "sit"
    LIE = "lie"


class PlaceKind(enum.StrEnum):
    #: on s'y tient debout (la fenêtre, le milieu de la pièce, une porte)
    SPOT = "spot"
    #: on s'y assied (une chaise, un canapé, le bord du lit)
    SEAT = "seat"
    #: on peut s'y asseoir ou s'y allonger
    BED = "bed"


#: Les postures qu'un lieu permet.
POSTURES: dict[PlaceKind, frozenset[Posture]] = {
    PlaceKind.SPOT: frozenset({Posture.STAND}),
    PlaceKind.SEAT: frozenset({Posture.STAND, Posture.SIT}),
    PlaceKind.BED: frozenset({Posture.STAND, Posture.SIT, Posture.LIE}),
}


class Size(enum.StrEnum):
    #: se prend d'une main (une tasse, un livre)
    HAND = "hand"
    #: se porte à deux mains (un carton, une guitare)
    ARMS = "arms"
    #: ne se porte pas (un lit, une lampe sur pied vissée, une fenêtre)
    FIXED = "fixed"


class Hand(enum.StrEnum):
    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"


class Access(enum.StrEnum):
    """Qui, en dehors d'elle, peut se servir d'un objet ou le déplacer — gradué comme le reste (une amie peut
    feuilleter son carnet de croquis, une inconnue non). Elle-même peut toujours."""

    ANYONE = "anyone"
    FRIENDS = "friends"
    OWNERS = "owners"
    MIKA = "mika"


class Effect(enum.StrEnum):
    """Ce qu'une affordance fait : une liste fermée, les noms d'actions sont libres (``allumer``,
    ``arroser``), leurs effets non."""

    #: l'objet passe dans un autre état (allumée, ouverte)
    STATE = "state"
    #: l'acteur s'occupe avec l'objet un moment (lire, jouer de la guitare, regarder dehors)
    ACTIVITY = "activity"
    #: l'objet disparaît (manger un biscuit)
    CONSUME = "consume"


class Builtin(enum.StrEnum):
    """Les actions que tout objet ou tout lieu permet sans qu'on les déclare."""

    TAKE = "take"  # un objet qui se porte, à portée
    PUT = "put"  # ce qu'on tient, sur une surface, dans un contenant, ou au sol
    GIVE = "give"  # ce qu'on tient, à quelqu'un (qui accepte)
    DROP = "drop"  # ce qu'on tient, au sol, là où on est
    SIT = "sit"  # sur un lieu SEAT ou BED
    LIE = "lie"  # sur un lieu BED
    STAND = "stand"  # se relever


class Gesture(enum.StrEnum):
    """Un geste vers quelqu'un ou quelque chose : unilatéral, il se fait sans accord — et se ressent selon qui
    le fait (une tape sur la tête d'une proche ou d'une inconnue n'est pas la même chose)."""

    WAVE = "wave"
    POINT = "point"
    NOD = "nod"
    SHAKE_HEAD = "shake_head"
    BOW = "bow"
    CLAP = "clap"
    POKE = "poke"
    PAT_HEAD = "pat_head"


class RequestKind(enum.StrEnum):
    """Ce qui demande l'accord de l'autre : on ne prend pas ce qu'elle tient, on ne la serre pas dans ses bras
    sans qu'elle le veuille — et elle non plus."""

    OFFER = "offer"  # tendre un objet qu'on tient
    ASK = "ask"  # demander un objet qu'elle tient
    HUG = "hug"
    HIGH_FIVE = "high_five"
    HOLD_HAND = "hold_hand"
    INVITE = "invite"  # « viens t'asseoir » : à un lieu


class Answer(enum.StrEnum):
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class Outcome(enum.StrEnum):
    DONE = "done"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class Refusal(enum.StrEnum):
    """Pourquoi une action, un constat ou une édition est refusé — le même code pour tous ; le texte en
    français qui l'accompagne est celui qu'elle lit dans le résultat d'un outil."""

    UNKNOWN = "unknown"  # cet identifiant n'existe pas (ou plus)
    UNREACHABLE = "unreachable"  # pas de chemin (une autre pièce sans passage)
    HANDS_FULL = "hands_full"
    NOT_HOLDING = "not_holding"
    NOT_PORTABLE = "not_portable"
    OCCUPIED = "occupied"  # le lieu est plein, la place sur l'étagère prise
    HELD_BY_OTHER = "held_by_other"  # quelqu'un d'autre le tient : on demande, on ne prend pas
    FORBIDDEN = "forbidden"  # l'accès de l'objet ne le permet pas à cet acteur
    WRONG_STATE = "wrong_state"  # déjà allumée, pas ouverte
    WRONG_POSTURE = "wrong_posture"
    ASLEEP = "asleep"
    STALE = "stale"  # écrit sur une révision ou un état qui a changé depuis
    INCOHERENT = "incoherent"  # une édition qui rendrait la définition incohérente
    IMPLAUSIBLE = "implausible"  # un constat du moteur que les règles du monde n'admettent pas
    NOT_HOST = "not_host"
    NOT_CREATOR = "not_creator"
    RATE_LIMITED = "rate_limited"
    #: ce noyau ne sait pas encore traiter cette commande (une version du protocole plus récente que lui)
    UNSUPPORTED = "unsupported"


class Source(enum.StrEnum):
    """D'où vient un changement de l'état vécu."""

    MIKA = "mika"  # ses outils
    REFLEX = "reflex"  # une règle du noyau (elle s'endort : elle va au lit)
    PLAYER = "player"  # une personne, dans le monde
    HOST = "host"  # le moteur hôte constate (physique, personnage du moteur)
    CREATOR = "creator"  # une opératrice qui édite le monde
    KERNEL = "kernel"  # l'issue d'une action sans moteur pour la jouer


# ── La définition ─────────────────────────────────────────────────────────


class Pos(Payload):
    """Une position dans le plan d'une pièce : mètres, ``x`` et ``z`` de l'espace de la pièce (Y vers le
    haut, celui du modèle de la pièce). Pour les distances et les durées de marche, jamais pour le rendu (le
    moteur a ses ancres)."""

    x: float = Field(ge=-1000, le=1000)
    z: float = Field(ge=-1000, le=1000)


class Exit(Payload):
    """Un passage : depuis le lieu ``via`` de cette pièce on arrive au lieu ``arrives`` de ``to``.
    Un passage dans les deux sens se déclare des deux côtés."""

    via: Ident
    to: Ident
    arrives: Ident


class RoomDef(Payload):
    kind: Literal["room"] = "room"
    id: Ident
    label: Label
    exits: tuple[Exit, ...] = ()
    tags: tuple[Ident, ...] = ()


class PlaceDef(Payload):
    """Un endroit où un acteur peut se tenir : le milieu de la pièce, la fenêtre, le bureau, le lit.

    ``label`` se lit après « tu es » (« à ton bureau », « sur ton lit », « devant ta bibliothèque ») : la posture
    le précède (« assise à ton bureau ») ;
    ``pos`` : le point d'approche, là où l'on arrive debout (pour s'asseoir, on y arrive avant de s'asseoir) ;
    ``facing`` : l'orientation une fois là, un lacet en radians dont l'avant est ``(sin φ, cos φ)`` sur
    ``(x, z)`` — 0 regarde vers +Z ; ``of_object`` : le meuble qui le porte (un lieu SEAT ou BED est presque
    toujours le lieu d'un meuble) ;
    ``anchor`` : l'ancre de la scène du moteur ; ``tags`` : ce qu'il est pour les réflexes (``sleep`` : où
    elle dort, ``work`` : où elle travaille, ``spawn`` : où arrive une personne)."""

    kind: Literal["place"] = "place"
    id: Ident
    room: Ident
    label: Label
    place_kind: PlaceKind = PlaceKind.SPOT
    capacity: int = Field(default=1, ge=1, le=16)
    pos: Pos
    facing: float | None = Field(default=None, ge=-7.0, le=7.0)
    anchor: AssetKey | None = None
    of_object: Ident | None = None
    tags: tuple[Ident, ...] = ()


class Affordance(Payload):
    """Une action qu'un archétype permet, au-delà des actions de base (``Builtin``).

    ``id`` : le nom de l'action (``allumer``, ``arroser``, ``lire``) ; ``label`` : ce qu'elle lit ;
    ``requires_state`` : les états de l'objet où elle a un sens ; ``to_state`` : l'état qu'elle donne ;
    ``held`` : il faut tenir l'objet (lire un livre) ; ``duration_s`` : la durée nominale (``None`` pour une
    occupation sans fin prévue) ; ``noise`` : jusqu'où ça s'entend (0 : la pièce, 1 : les pièces voisines) ;
    ``animation`` : la clé d'animation du moteur."""

    id: Ident
    label: Label
    effect: Effect
    to_state: Ident | None = None
    requires_state: tuple[Ident, ...] = ()
    activity: Ident | None = None
    held: bool = False
    duration_s: float | None = Field(default=2.0, ge=0, le=86_400)
    access: Access | None = None
    noise: float = Field(default=0.0, ge=0, le=1)
    animation: AssetKey | None = None

    @model_validator(mode="after")
    def _effect_fields(self) -> Affordance:
        if self.id in {b.value for b in Builtin}:
            raise ValueError(f"« {self.id} » est une action de base : une affordance ne la redéclare pas")
        if self.effect is Effect.STATE and self.to_state is None:
            raise ValueError(f"l'affordance « {self.id} » change l'état : il lui faut to_state")
        if self.effect is Effect.ACTIVITY and self.activity is None:
            raise ValueError(f"l'affordance « {self.id} » est une occupation : il lui faut activity")
        return self


class ArchetypeDef(Payload):
    """Une sorte d'objet : une tasse, une lampe, une étagère.

    ``states`` / ``initial_state`` : ses états (vide : il n'en a pas) ; ``state_labels`` : comment elle les dit
    (``{"off": "éteinte"}``) ; ``surface_slots`` : combien d'objets
    se posent dessus ; ``container_slots`` : combien il en contient ; ``salience`` : ce qu'il attire
    l'attention (ce qui compte dans son prompt quand la pièce est pleine)."""

    kind: Literal["archetype"] = "archetype"
    id: Ident
    label: Label
    asset: AssetKey
    size: Size = Size.HAND
    states: tuple[Ident, ...] = ()
    initial_state: Ident | None = None
    state_labels: dict[str, Label] = Field(default_factory=dict)
    affordances: tuple[Affordance, ...] = ()
    surface_slots: int = Field(default=0, ge=0, le=64)
    container_slots: int = Field(default=0, ge=0, le=256)
    salience: float = Field(default=0.5, ge=0, le=1)
    tags: tuple[Ident, ...] = ()

    @model_validator(mode="after")
    def _states(self) -> ArchetypeDef:
        known = set(self.states)
        if len(known) != len(self.states):
            raise ValueError(f"l'archétype « {self.id} » déclare deux fois un même état")
        if self.initial_state is not None and self.initial_state not in known:
            raise ValueError(f"l'archétype « {self.id} » part d'un état qu'il ne déclare pas")
        if self.states and self.initial_state is None:
            raise ValueError(f"l'archétype « {self.id} » a des états : il lui faut initial_state")
        if unknown := sorted(set(self.state_labels) - known):
            raise ValueError(f"l'archétype « {self.id} » nomme des états qu'il ne déclare pas : {', '.join(unknown)}")
        ids = [a.id for a in self.affordances]
        if len(set(ids)) != len(ids):
            raise ValueError(f"l'archétype « {self.id} » déclare deux fois une même action")
        for a in self.affordances:
            for s in (*a.requires_state, *([a.to_state] if a.to_state else [])):
                if s not in known:
                    raise ValueError(f"l'action « {a.id} » de « {self.id} » parle d'un état inconnu : {s}")
            if a.held and self.size is Size.FIXED:
                raise ValueError(f"« {a.id} » demande de tenir « {self.id} », qui ne se porte pas")
        return self


class InRoom(Payload):
    """Posé dans une pièce : au sol, ou un meuble à sa place. ``near`` : le lieu le plus proche."""

    kind: Literal["room"] = "room"
    room: Ident
    near: Ident | None = None


class On(Payload):
    """Sur la surface d'un autre objet, à une place numérotée."""

    kind: Literal["on"] = "on"
    object: Ident
    slot: int = Field(ge=0, le=63)


class In(Payload):
    """Dans un contenant."""

    kind: Literal["in"] = "in"
    object: Ident


class Held(Payload):
    kind: Literal["held"] = "held"
    actor: ActorId
    hand: Hand = Hand.RIGHT


Location = Annotated[InRoom | On | In | Held, Field(discriminator="kind")]


class ObjectDef(Payload):
    """Un objet du monde. ``home`` : où il est quand le monde est créé (jamais dans une main) ; ``owner`` :
    à qui il est (``mika``, ou l'adresse d'une personne) ; ``given_by`` : qui le lui a offert."""

    kind: Literal["object"] = "object"
    id: Ident
    archetype: Ident
    label: Label | None = None
    home: Location
    state: Ident | None = None
    owner: str | None = Field(default=None, max_length=96)
    given_by: str | None = Field(default=None, max_length=96)
    access: Access = Access.ANYONE
    salience: float | None = Field(default=None, ge=0, le=1)
    tags: tuple[Ident, ...] = ()


class Controller(enum.StrEnum):
    #: le noyau le fait vivre (Mika) : il décide, le moteur joue
    KERNEL = "kernel"
    #: le moteur hôte le fait vivre (un chat qui se promène) : il constate, le noyau valide
    HOST = "host"


class ActorDef(Payload):
    """Un personnage déclaré : Mika, ou un personnage du monde (``npc:…``). Les personnes n'y sont pas :
    elles entrent quand elles se connectent (``world.joined``)."""

    kind: Literal["actor"] = "actor"
    id: ActorId
    label: Label
    asset: AssetKey
    home: Ident
    controller: Controller = Controller.HOST
    tags: tuple[Ident, ...] = ()

    @model_validator(mode="after")
    def _who(self) -> ActorDef:
        if self.id.startswith(PLAYER_PREFIX):
            raise ValueError("une personne ne se déclare pas : elle entre dans le monde en s'y connectant")
        if (self.id == MIKA) != (self.controller is Controller.KERNEL):
            raise ValueError("c'est le noyau qui fait vivre Mika, et elle seule")
        return self


DefItem = Annotated[RoomDef | PlaceDef | ArchetypeDef | ObjectDef | ActorDef, Field(discriminator="kind")]


class WorldDef(Payload):
    """Un monde entier, tel que le créateur l'a écrit. Une instance est toujours cohérente : tout ce qu'elle
    nomme existe, chaque objet est à un seul endroit possible, chaque état est déclaré."""

    format: Literal["mika.world/1"] = FORMAT
    id: Ident
    label: Label
    rev: int = Field(default=0, ge=0)
    rooms: tuple[RoomDef, ...]
    places: tuple[PlaceDef, ...]
    archetypes: tuple[ArchetypeDef, ...] = ()
    objects: tuple[ObjectDef, ...] = ()
    actors: tuple[ActorDef, ...]

    @model_validator(mode="after")
    def _coherent(self) -> WorldDef:
        problems = list(_incoherences(self))
        if problems:
            raise ValueError(" ; ".join(problems))
        return self

    def room(self, ident: str) -> RoomDef | None:
        return next((r for r in self.rooms if r.id == ident), None)

    def place(self, ident: str) -> PlaceDef | None:
        return next((p for p in self.places if p.id == ident), None)

    def archetype(self, ident: str) -> ArchetypeDef | None:
        return next((a for a in self.archetypes if a.id == ident), None)

    def object(self, ident: str) -> ObjectDef | None:
        return next((o for o in self.objects if o.id == ident), None)

    def actor(self, ident: str) -> ActorDef | None:
        return next((a for a in self.actors if a.id == ident), None)

    def tagged(self, tag: str) -> tuple[PlaceDef, ...]:
        """Les lieux qui portent ce tag (``sleep`` : où elle dort)."""
        return tuple(p for p in self.places if tag in p.tags)


def _incoherences(w: WorldDef) -> Iterable[str]:
    """Tout ce qui empêche un monde d'exister — une liste, pour tout dire au créateur d'un coup."""
    rooms = {r.id for r in w.rooms}
    places = {p.id: p for p in w.places}
    archetypes = {a.id: a for a in w.archetypes}
    objects = {o.id: o for o in w.objects}
    named = [r.id for r in w.rooms] + [p.id for p in w.places] + [o.id for o in w.objects]
    doubles = sorted({n for n in named if named.count(n) > 1})
    if doubles:
        yield f"identifiants en double (pièces, lieux et objets partagent leurs noms) : {', '.join(doubles)}"
    if len(archetypes) != len(w.archetypes):
        yield "un archétype est déclaré deux fois"
    actors = [a.id for a in w.actors]
    if len(set(actors)) != len(actors):
        yield "un personnage est déclaré deux fois"
    if MIKA not in actors:
        yield "le monde n'a pas de Mika"
    for r in w.rooms:
        for x in r.exits:
            via, arrives = places.get(x.via), places.get(x.arrives)
            if x.to not in rooms:
                yield f"le passage de « {r.id} » mène à une pièce inconnue : {x.to}"
            if via is None or via.room != r.id:
                yield f"le passage de « {r.id} » part d'un lieu qui n'est pas dans la pièce : {x.via}"
            if arrives is None or arrives.room != x.to:
                yield f"le passage vers « {x.to} » arrive à un lieu qui n'y est pas : {x.arrives}"
    for p in w.places:
        if p.room not in rooms:
            yield f"le lieu « {p.id} » est dans une pièce inconnue : {p.room}"
        if p.of_object is not None:
            furniture = objects.get(p.of_object)
            if furniture is None:
                yield f"le lieu « {p.id} » appartient à un objet inconnu : {p.of_object}"
            elif (a := archetypes.get(furniture.archetype)) is not None and a.size is not Size.FIXED:
                yield f"le lieu « {p.id} » est porté par « {furniture.id} », qui se déplace : un lieu ne bouge pas"
    for a in w.actors:
        if a.home not in places:
            yield f"« {a.id} » commence à un lieu inconnu : {a.home}"
    slots: dict[tuple[str, int], str] = {}
    filled: dict[str, int] = {}
    for o in w.objects:
        a = archetypes.get(o.archetype)
        if a is None:
            yield f"l'objet « {o.id} » est d'un archétype inconnu : {o.archetype}"
        elif o.state is not None and o.state not in a.states:
            yield f"l'objet « {o.id} » est dans un état que « {a.id} » ne connaît pas : {o.state}"
        home = o.home
        if isinstance(home, Held):
            yield f"l'objet « {o.id} » ne peut pas commencer dans une main"
        elif isinstance(home, InRoom):
            if home.room not in rooms:
                yield f"l'objet « {o.id} » est dans une pièce inconnue : {home.room}"
            if home.near is not None and (places.get(home.near) is None or places[home.near].room != home.room):
                yield f"l'objet « {o.id} » est près d'un lieu qui n'est pas dans sa pièce : {home.near}"
        else:
            support = objects.get(home.object)
            sa = archetypes.get(support.archetype) if support is not None else None
            if support is None or sa is None:
                yield f"l'objet « {o.id} » est posé sur ou dans un objet inconnu : {home.object}"
            elif isinstance(home, On):
                if home.slot >= sa.surface_slots:
                    yield f"« {support.id} » n'a pas de place n° {home.slot} pour « {o.id} »"
                elif (taken := slots.get((support.id, home.slot))) is not None:
                    yield f"« {o.id} » et « {taken} » sont à la même place sur « {support.id} »"
                else:
                    slots[(support.id, home.slot)] = o.id
            else:
                filled[support.id] = filled.get(support.id, 0) + 1
                if filled[support.id] > sa.container_slots:
                    yield f"« {support.id} » ne peut pas contenir autant d'objets"
    for o in w.objects:
        seen = {o.id}
        cur = o.home
        while isinstance(cur, On | In):
            if cur.object in seen:
                yield f"« {o.id} » est posé sur lui-même, d'objet en objet"
                break
            seen.add(cur.object)
            nxt = objects.get(cur.object)
            if nxt is None:
                break
            cur = nxt.home


# ── Éditer la définition ──────────────────────────────────────────────────


class DefKind(enum.StrEnum):
    ROOM = "room"
    PLACE = "place"
    ARCHETYPE = "archetype"
    OBJECT = "object"
    ACTOR = "actor"


class DefPut(Payload):
    """Ajouter ou remplacer un élément (l'identifiant le désigne)."""

    op: Literal["put"] = "put"
    item: DefItem


class DefRemove(Payload):
    op: Literal["remove"] = "remove"
    of: DefKind
    id: str = Field(max_length=120)


DefChange = Annotated[DefPut | DefRemove, Field(discriminator="op")]

_FIELDS: dict[str, str] = {"room": "rooms", "place": "places", "archetype": "archetypes", "object": "objects",
                           "actor": "actors"}


def apply_changes(w: WorldDef, changes: Iterable[DefPut | DefRemove]) -> WorldDef:
    """La définition après ces changements, à la révision suivante ; lève ``ValueError`` (en français) si
    le résultat serait incohérent — un lot passe en entier ou pas du tout."""
    lists: dict[str, list[Payload]] = {f: list(getattr(w, f)) for f in _FIELDS.values()}
    for ch in changes:
        if isinstance(ch, DefPut):
            items = lists[_FIELDS[ch.item.kind]]
            at = next((i for i, x in enumerate(items) if x.id == ch.item.id), None)  # type: ignore[attr-defined]
            if at is None:
                items.append(ch.item)
            else:
                items[at] = ch.item
        else:
            items = lists[_FIELDS[ch.of.value]]
            kept = [x for x in items if x.id != ch.id]  # type: ignore[attr-defined]
            if len(kept) == len(items):
                raise ValueError(f"rien à retirer : {ch.of.value} « {ch.id} » n'existe pas")
            lists[_FIELDS[ch.of.value]] = kept
    return WorldDef(id=w.id, label=w.label, rev=w.rev + 1, **{f: tuple(v) for f, v in lists.items()})


# ── L'état vécu ───────────────────────────────────────────────────────────


class Activity(Payload):
    """Ce qu'un acteur est en train de faire (lire, regarder dehors, travailler) ; ``until`` : la fin prévue,
    ``None`` pour une occupation qu'on interrompra."""

    name: Ident
    object: Ident | None = None
    since: int
    until: int | None = None


class Movement(Payload):
    """Un acteur en chemin : un écran qui s'ouvre en route le place sur le trajet d'après ``started``/``eta``."""

    intent: str = Field(max_length=64)
    to_room: Ident
    to_place: Ident | None = None
    started: int
    eta: int


class ActorState(Payload):
    id: ActorId
    room: Ident
    place: Ident | None = None
    posture: Posture = Posture.STAND
    #: depuis quand il est là (0 : depuis la création du monde)
    since: int = 0
    holding: tuple[Ident, ...] = ()
    activity: Activity | None = None
    moving: Movement | None = None


class ObjectState(Payload):
    id: Ident
    location: Location
    state: Ident | None = None
    given_by: str | None = Field(default=None, max_length=96)
    #: depuis quand il est là (un objet déplacé par quelqu'un d'autre, elle peut le remarquer)
    since: int = 0


class Step(Payload):
    """Un pas d'une action, tel que le noyau l'a planifié : marcher jusqu'à un lieu, changer de posture,
    agir sur un objet, attendre. ``duration_us`` : la durée nominale (sans moteur, l'action dure ça)."""

    kind: Literal["walk", "posture", "act", "wait"]
    to_room: Ident | None = None
    to_place: Ident | None = None
    posture: Posture | None = None
    object: Ident | None = None
    action: Ident | None = None  # une action de base (``Builtin``) ou une affordance de l'objet
    target_actor: ActorId | None = None  # donner à quelqu'un
    target: Location | None = None  # poser sur, dans, au sol
    duration_us: int = Field(ge=0)


class Cause(Payload):
    """Qui est à l'origine d'un changement : la source, l'acteur, la personne responsable (son adresse),
    l'action et l'épisode s'il y en a un."""

    source: Source
    actor: ActorId | None = None
    handle: str | None = Field(default=None, max_length=96)
    intent: str | None = Field(default=None, max_length=64)
    episode: int | None = None


class Intent(Payload):
    """Une action en cours : planifiée et validée par le noyau, jouée par le moteur hôte s'il y en a un,
    terminée par le noyau à ``deadline`` sinon."""

    id: str = Field(max_length=64)
    actor: ActorId
    steps: tuple[Step, ...] = Field(min_length=1, max_length=8)
    started: int
    eta: int
    #: au-delà, sans nouvelle du moteur, le noyau la termine comme prévu
    deadline: int
    cause: Cause


class Request(Payload):
    id: str = Field(max_length=64)
    kind: RequestKind
    from_actor: ActorId
    to_actor: ActorId
    object: Ident | None = None
    place: Ident | None = None
    expires: int


class ActorMoved(Payload):
    kind: Literal["actor_moved"] = "actor_moved"
    actor: ActorId
    room: Ident
    place: Ident | None = None
    posture: Posture = Posture.STAND


class ActorBusy(Payload):
    kind: Literal["actor_activity"] = "actor_activity"
    actor: ActorId
    activity: Activity | None = None


class ObjectMoved(Payload):
    kind: Literal["object_moved"] = "object_moved"
    object: Ident
    to: Location


class ObjectSet(Payload):
    kind: Literal["object_state"] = "object_state"
    object: Ident
    state: Ident


class ObjectGone(Payload):
    kind: Literal["object_gone"] = "object_gone"
    object: Ident


StateChange = Annotated[ActorMoved | ActorBusy | ObjectMoved | ObjectSet | ObjectGone, Field(discriminator="kind")]


class WorldState(Payload):
    """L'état vécu tout entier, au ``seq`` du journal où il a été lu."""

    rev: int = Field(ge=0)
    seq: int = Field(ge=0)
    actors: tuple[ActorState, ...]
    objects: tuple[ObjectState, ...]
    intents: tuple[Intent, ...] = ()
    requests: tuple[Request, ...] = ()


# ── Les commandes : ce qu'un client du monde propose ──────────────────────

#: L'identifiant d'une commande, choisi par le client (unique pour sa session).
CmdId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class Act(Payload):
    """La personne fait quelque chose avec son corps : une action de base (``take``, ``put``, ``give``,
    ``drop``, ``sit``, ``lie``, ``stand``) ou une affordance d'un objet (``allumer``). ``place`` : le lieu
    où s'asseoir ; ``target`` : où poser ; ``to_actor`` : à qui donner — donner, c'est tendre : ``give``
    ouvre une demande ``offer`` que l'autre accepte ou non. ``expect`` : le ``seq`` sur lequel elle a décidé
    (un état qui a changé depuis sur ce qu'elle touche : ``stale``)."""

    type: Literal["act"] = "act"
    cmd: CmdId
    action: Ident
    object: Ident | None = None
    place: Ident | None = None
    target: Location | None = None
    to_actor: ActorId | None = None
    expect: int | None = Field(default=None, ge=0)


class Moved(Payload):
    """Le corps de la personne est arrivé quelque part (grossièrement : une pièce, le lieu le plus proche).
    Son client la déplace librement ; le noyau ne retient que ces arrivées. S'asseoir ou s'allonger occupe une
    place : c'est une action (``act`` ``sit``), pas un déplacement."""

    type: Literal["moved"] = "moved"
    cmd: CmdId
    room: Ident
    near: Ident | None = None


class Address(Payload):
    """Un geste vers quelqu'un (``gesture``), ou une demande qui attend son accord (``request``)."""

    type: Literal["address"] = "address"
    cmd: CmdId
    to: ActorId = MIKA
    gesture: Gesture | None = None
    request: RequestKind | None = None
    object: Ident | None = None
    place: Ident | None = None


class Reply(Payload):
    """La personne répond à une demande (Mika lui tend une tasse, l'invite à s'asseoir)."""

    type: Literal["answer"] = "answer"
    cmd: CmdId
    request: str = Field(max_length=64)
    accept: bool


class Progress(Payload):
    """L'hôte a commencé à jouer un pas d'une action (pour les autres écrans : rien à décider)."""

    kind: Literal["progress"] = "progress"
    intent: str = Field(max_length=64)
    step: int = Field(ge=0, le=7)


class Finished(Payload):
    """L'hôte a fini de jouer une action, ou n'y arrive pas (``failed`` + ``reason``). ``at`` : où l'acteur
    est vraiment, si ce n'est pas là où l'action devait le mener."""

    kind: Literal["finished"] = "finished"
    intent: str = Field(max_length=64)
    outcome: Outcome
    reason: Refusal | None = None
    at: ActorMoved | None = None


class Settled(Payload):
    """Un objet s'est posé ailleurs (il est tombé, un personnage du moteur l'a poussé)."""

    kind: Literal["settled"] = "settled"
    object: Ident
    to: Location


class NpcUpdate(Payload):
    """Un personnage du moteur (``controller: host``) est arrivé quelque part, ou fait autre chose."""

    kind: Literal["npc"] = "npc"
    actor: ActorId
    room: Ident
    near: Ident | None = None
    posture: Posture = Posture.STAND
    activity: Ident | None = None


class Sound(Payload):
    """Un bruit du monde (la pluie se met à tomber, un fracas) : ``kind`` est une clé connue du monde,
    ``loudness`` dit jusqu'où il porte."""

    kind: Literal["sound"] = "sound"
    sound: Ident
    room: Ident
    loudness: float = Field(ge=0, le=1)


class Loaded(Payload):
    """L'hôte a chargé la définition ``rev`` ; ce qui lui manque (ressources, ancres) se lit dans la console."""

    kind: Literal["loaded"] = "loaded"
    rev: int = Field(ge=0)
    missing_assets: tuple[str, ...] = Field(default=(), max_length=200)
    missing_anchors: tuple[str, ...] = Field(default=(), max_length=200)


ReportBody = Annotated[Progress | Finished | Settled | NpcUpdate | Sound | Loaded, Field(discriminator="kind")]


class Report(Payload):
    """Ce que constate l'hôte (le rôle ``host`` seulement). Un constat est validé comme une action : ce que
    les règles du monde n'admettent pas est refusé (``implausible``)."""

    type: Literal["report"] = "report"
    cmd: CmdId
    report: ReportBody


class Edit(Payload):
    """Un lot d'édition de la définition, écrit sur la révision ``base`` (rôle ``creator``)."""

    type: Literal["edit"] = "edit"
    cmd: CmdId
    base: int = Field(ge=0)
    changes: tuple[DefChange, ...] = Field(min_length=1, max_length=500)


class Describe(Payload):
    """Ce qu'un élément est pour elle, en prose (rôle ``creator``) ; ``about`` : les personnes qu'il nomme."""

    type: Literal["describe"] = "describe"
    cmd: CmdId
    of: DefKind
    id: str = Field(max_length=120)
    text: str = Field(max_length=500)
    about: tuple[str, ...] = Field(default=(), max_length=8)


#: Ce qu'un client propose au noyau (``adapters/world/protocol.py`` les porte telles quelles sur le fil).
Command = Annotated[Act | Moved | Address | Reply | Report | Edit | Describe, Field(discriminator="type")]


class CommandStatus(enum.StrEnum):
    ACCEPTED = "accepted"
    REFUSED = "refused"
    DUPLICATE = "duplicate"


class CommandResult(Payload):
    """Ce qu'est devenue une commande : acceptée (et le ``seq`` qui l'a journalisée, s'il y en a un), refusée (un
    code, et ce que ça veut dire en français), ou déjà reçue."""

    status: CommandStatus
    code: Refusal | None = None
    message: str = Field(default="", max_length=300)
    seq: int | None = None


# ── Les événements ────────────────────────────────────────────────────────


class Authored(Payload):
    """Un lot d'édition de la définition, écrit sur la révision ``base_rev`` (une opératrice)."""

    base_rev: int = Field(ge=0)
    changes: tuple[DefChange, ...] = Field(min_length=1, max_length=500)
    by: str = Field(max_length=96)


class Described(Payload):
    """Ce qu'un élément est pour elle, en prose (« la plante qu'Adrien t'a offerte ») : un texte gardé, qui
    dit qui il concerne — l'oubli l'atteint."""

    of: DefKind
    id: str = Field(max_length=120)
    text: Content
    about: tuple[str, ...] = ()


class Intended(Payload):
    intent: Intent
    by: str | None = None  # la personne responsable, pour l'oubli et la console


class Ended(Payload):
    intent: str = Field(max_length=64)
    actor: ActorId
    outcome: Outcome
    reason: Refusal | None = None
    #: ce que l'action a changé (rien pour un échec : l'état reste celui d'avant, corrigé par ``Changed``
    #: si le moteur a constaté autre chose)
    changes: tuple[StateChange, ...] = ()
    by: str | None = None


class Changed(Payload):
    """Un changement de l'état vécu hors d'une action planifiée : un geste instantané d'une personne, un
    constat du moteur, un objet déplacé par une opératrice, un réflexe."""

    cause: Cause
    changes: tuple[StateChange, ...] = Field(min_length=1, max_length=64)
    by: str | None = None


class Requested(Payload):
    request: Request
    by: str | None = None


class Answered(Payload):
    request: str = Field(max_length=64)
    answer: Answer
    changes: tuple[StateChange, ...] = ()
    by: str | None = None


class Gestured(Payload):
    actor: ActorId
    gesture: Gesture
    to_actor: ActorId | None = None
    object: Ident | None = None
    by: str | None = None


class Joined(Payload):
    """Une personne entre dans le monde (son client s'y connecte) : elle y a un corps, à un lieu."""

    actor: ActorId
    handle: str = Field(max_length=96)
    room: Ident
    place: Ident | None = None
    asset: AssetKey | None = None


class Left(Payload):
    actor: ActorId
    handle: str = Field(max_length=96)


class Noticed(Signal):
    """Ce qu'elle remarque du monde (quelqu'un entre, un objet tombe, sa plante a changé de place) : un signal
    comme les autres sens, dosé et habitué par l'attention (ADR 0022)."""

    actor: ActorId | None = None
    object: Ident | None = None


AUTHORED = event_type("world.authored", OWNER, Authored, public=True, subjects=("by",))
DESCRIBED = event_type("world.described", OWNER, Described, public=True, content=("text",), subjects=("about",))
INTENDED = event_type("world.intended", OWNER, Intended, public=True, subjects=("by",))
ENDED = event_type("world.ended", OWNER, Ended, public=True, subjects=("by",))
CHANGED = event_type("world.changed", OWNER, Changed, public=True, subjects=("by",))
REQUESTED = event_type("world.requested", OWNER, Requested, public=True, subjects=("by",))
ANSWERED = event_type("world.answered", OWNER, Answered, public=True, subjects=("by",))
GESTURED = event_type("world.gestured", OWNER, Gestured, public=True, subjects=("by",))
JOINED = event_type("world.joined", OWNER, Joined, public=True, subjects=("handle",))
LEFT = event_type("world.left", OWNER, Left, public=True, subjects=("handle",))
NOTICED = event_type("world.noticed", OWNER, Noticed, public=True, content=("summary",), subjects=("about",))
ALL = (AUTHORED, DESCRIBED, INTENDED, ENDED, CHANGED, REQUESTED, ANSWERED, GESTURED, JOINED, LEFT, NOTICED)

# ── Les faits ─────────────────────────────────────────────────────────────

#: La définition en vigueur.
DEFINITION = FactKey("world.definition", type=WorldDef, doc="le monde tel que le créateur l'a écrit")
#: L'état vécu tout entier (pour les écrans : un instantané).
STATE = FactKey("world.state", type=WorldState, doc="où est chaque chose, qui fait quoi")
#: Où elle est, sa posture, ce qu'elle tient, ce qu'elle fait.
SELF = FactKey("world.self", type=ActorState, doc="son corps dans le monde")
#: Les acteurs dans la même pièce qu'elle (hors elle).
AROUND = FactKey("world.around", type=tuple, doc="qui est dans la pièce avec elle")
#: Les objets à portée d'un acteur (son lieu, ce qu'il tient, ce qui est posé là), du plus saillant au moins.
REACH = FactFamily("world.reach", arg=str, type=tuple, doc="ce qu'un acteur a à portée")
#: Les demandes qui attendent la réponse de cet acteur.
PENDING = FactFamily("world.pending", arg=str, type=tuple, doc="ce qu'on lui demande et qui attend")

"""Le protocole ``mika.world/1`` : les trames échangées avec un client du monde (ADR 0050).

Un client du monde est un moteur de jeu (Unity, le client web en Three.js…) connecté en WebSocket sur
``/ws/world``. Il y tient un ou plusieurs **rôles** :

- ``viewer`` : il montre le monde et y fait vivre le corps de la personne connectée (ses gestes, ses
  déplacements grossiers, ses réponses aux demandes de Mika) ;
- ``host`` : en plus, il **joue** les actions que le noyau a décidées et **constate** ce que sa physique et
  ses personnages font — un seul hôte à la fois, par bail ;
- ``creator`` : une opératrice qui édite la définition.

Le noyau est la seule autorité : un client propose (``act``, ``moved``, ``report``, ``edit``…), le noyau
valide, journalise, puis diffuse (``delta``, ``intent``, ``intent_end``…) à tous — y compris à qui a proposé :
un client n'applique jamais un changement du monde avant de l'avoir reçu. Seule exception, déclarée : la
pose continue d'un avatar (``pose``), relayée aux autres clients sans passer par le journal, et que Mika ne
voit jamais.

Chaque commande d'un client porte ``cmd`` (son identifiant, pour l'accusé ``result`` et le dédoublonnage).
Chaque trame diffusée par le noyau porte le ``seq`` du journal : un client qui voit un trou demande la suite
(``sync``) ; un écart trop grand lui vaut un instantané. Les instants sont en microsecondes depuis l'epoch,
sur l'horloge du noyau (``welcome.now``).

Ce module ne fait que décrire : les modèles valident une trame reçue (``client_frame``), sérialisent une
trame émise, et produisent le schéma JSON que consomme un moteur (``json_schema``).
"""

from __future__ import annotations

import enum
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

from mika.contracts import world as w

PROTOCOL = "mika.world/1"
PATH = "/ws/world"

#: L'identifiant d'une commande, choisi par le client (unique pour sa session).
CmdId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class Role(enum.StrEnum):
    VIEWER = "viewer"
    HOST = "host"
    CREATOR = "creator"


class Status(enum.StrEnum):
    ACCEPTED = "accepted"
    REFUSED = "refused"
    DUPLICATE = "duplicate"


class Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Vec3(Wire):
    x: float
    y: float
    z: float


# ── Client → noyau ────────────────────────────────────────────────────────


class ClientInfo(Wire):
    name: str = Field(max_length=60)
    version: str = Field(max_length=30)
    engine: str = Field(max_length=30)


class Hello(Wire):
    """La première trame. ``roles`` : ce que le client demande (le noyau n'accorde que ce que le compte
    permet) ; ``rev`` / ``after`` : ce qu'il a déjà (définition en cache, dernier ``seq`` appliqué) ;
    ``token`` : un client natif s'authentifie par un jeton porteur (un navigateur, par sa session)."""

    type: Literal["hello"] = "hello"
    protocol: Literal["mika.world/1"] = PROTOCOL
    roles: tuple[Role, ...] = Field(min_length=1, max_length=3)
    client: ClientInfo
    rev: int | None = Field(default=None, ge=0)
    after: int | None = Field(default=None, ge=0)
    token: str | None = Field(default=None, max_length=200)
    #: l'apparence que la personne a choisie (un prefab du moteur)
    avatar: w.AssetKey | None = None


class Act(Wire):
    """La personne fait quelque chose avec son corps : une action de base (``take``, ``put``, ``give``,
    ``drop``, ``sit``, ``lie``, ``stand``) ou une affordance d'un objet (``allumer``). ``place`` : le lieu
    où s'asseoir ; ``target`` : où poser ; ``to_actor`` : à qui donner — donner, c'est tendre : ``give``
    ouvre une demande ``offer`` que l'autre accepte ou non. ``expect`` : le ``seq`` sur lequel elle a décidé
    (un état qui a changé depuis sur ce qu'elle touche : ``stale``)."""

    type: Literal["act"] = "act"
    cmd: CmdId
    action: w.Ident
    object: w.Ident | None = None
    place: w.Ident | None = None
    target: w.Location | None = None
    to_actor: w.ActorId | None = None
    expect: int | None = Field(default=None, ge=0)


class Moved(Wire):
    """Le corps de la personne est arrivé quelque part (grossièrement : une pièce, le lieu le plus proche).
    Son client la déplace librement ; le noyau ne retient que ces arrivées. S'asseoir ou s'allonger occupe une
    place : c'est une action (``act`` ``sit``), pas un déplacement."""

    type: Literal["moved"] = "moved"
    cmd: CmdId
    room: w.Ident
    near: w.Ident | None = None


class Address(Wire):
    """Un geste vers quelqu'un (``gesture``), ou une demande qui attend son accord (``request``)."""

    type: Literal["address"] = "address"
    cmd: CmdId
    to: w.ActorId = w.MIKA
    gesture: w.Gesture | None = None
    request: w.RequestKind | None = None
    object: w.Ident | None = None
    place: w.Ident | None = None


class Reply(Wire):
    """La personne répond à une demande (Mika lui tend une tasse, l'invite à s'asseoir)."""

    type: Literal["answer"] = "answer"
    cmd: CmdId
    request: str = Field(max_length=64)
    accept: bool


class Progress(Wire):
    """L'hôte a commencé à jouer un pas d'une action (pour les autres écrans : rien à décider)."""

    kind: Literal["progress"] = "progress"
    intent: str = Field(max_length=64)
    step: int = Field(ge=0, le=7)


class Finished(Wire):
    """L'hôte a fini de jouer une action, ou n'y arrive pas (``failed`` + ``reason``). ``at`` : où l'acteur
    est vraiment, si ce n'est pas là où l'action devait le mener."""

    kind: Literal["finished"] = "finished"
    intent: str = Field(max_length=64)
    outcome: w.Outcome
    reason: w.Refusal | None = None
    at: w.ActorMoved | None = None


class Settled(Wire):
    """Un objet s'est posé ailleurs (il est tombé, un personnage du moteur l'a poussé)."""

    kind: Literal["settled"] = "settled"
    object: w.Ident
    to: w.Location


class NpcUpdate(Wire):
    """Un personnage du moteur (``controller: host``) est arrivé quelque part, ou fait autre chose."""

    kind: Literal["npc"] = "npc"
    actor: w.ActorId
    room: w.Ident
    near: w.Ident | None = None
    posture: w.Posture = w.Posture.STAND
    activity: w.Ident | None = None


class Sound(Wire):
    """Un bruit du monde (la pluie se met à tomber, un fracas) : ``kind`` est une clé connue du monde,
    ``loudness`` dit jusqu'où il porte."""

    kind: Literal["sound"] = "sound"
    sound: w.Ident
    room: w.Ident
    loudness: float = Field(ge=0, le=1)


class Loaded(Wire):
    """L'hôte a chargé la définition ``rev`` ; ce qui lui manque (ressources, ancres) se lit dans la console."""

    kind: Literal["loaded"] = "loaded"
    rev: int = Field(ge=0)
    missing_assets: tuple[str, ...] = Field(default=(), max_length=200)
    missing_anchors: tuple[str, ...] = Field(default=(), max_length=200)


ReportBody = Annotated[Progress | Finished | Settled | NpcUpdate | Sound | Loaded, Field(discriminator="kind")]


class Report(Wire):
    """Ce que constate l'hôte (le rôle ``host`` seulement). Un constat est validé comme une action : ce que
    les règles du monde n'admettent pas est refusé (``implausible``)."""

    type: Literal["report"] = "report"
    cmd: CmdId
    report: ReportBody


class Edit(Wire):
    """Un lot d'édition de la définition, écrit sur la révision ``base`` (rôle ``creator``)."""

    type: Literal["edit"] = "edit"
    cmd: CmdId
    base: int = Field(ge=0)
    changes: tuple[w.DefChange, ...] = Field(min_length=1, max_length=500)


class Describe(Wire):
    """Ce qu'un élément est pour elle, en prose (rôle ``creator``) ; ``about`` : les personnes qu'il nomme."""

    type: Literal["describe"] = "describe"
    cmd: CmdId
    of: w.DefKind
    id: str = Field(max_length=120)
    text: str = Field(max_length=500)
    about: tuple[str, ...] = Field(default=(), max_length=8)


class PoseIn(Wire):
    """La pose continue de l'avatar de la personne (au plus 20 par seconde) : relayée aux autres clients,
    jamais journalisée, jamais montrée à Mika."""

    type: Literal["pose"] = "pose"
    t: int
    pos: Vec3
    yaw: float
    anim: str | None = Field(default=None, max_length=60)


class Sync(Wire):
    type: Literal["sync"] = "sync"
    after: int = Field(ge=0)


class Ping(Wire):
    type: Literal["ping"] = "ping"
    t: int


ClientFrame = Annotated[
    Hello | Act | Moved | Address | Reply | Report | Edit | Describe | PoseIn | Sync | Ping,
    Field(discriminator="type"),
]

# ── Noyau → client ────────────────────────────────────────────────────────


class Welcome(Wire):
    """La réponse à ``hello`` : les rôles accordés (``host`` seulement si ce client a le bail), le monde
    (``world``, ``rev``), où en est le journal (``seq``) et l'heure du noyau (``now``)."""

    type: Literal["welcome"] = "welcome"
    protocol: Literal["mika.world/1"] = PROTOCOL
    session: str = Field(max_length=64)
    granted: tuple[Role, ...]
    actor: w.ActorId | None = None
    world: w.Ident
    rev: int = Field(ge=0)
    seq: int = Field(ge=0)
    now: int


class Definition(Wire):
    """La définition entière (le client n'avait pas cette révision)."""

    type: Literal["definition"] = "definition"
    world: w.WorldDef


class DefinitionDelta(Wire):
    """La définition a changé : ``base`` → ``rev`` (un client à une autre révision redemande l'entière)."""

    type: Literal["definition_delta"] = "definition_delta"
    seq: int = Field(ge=0)
    base: int = Field(ge=0)
    rev: int = Field(ge=0)
    changes: tuple[w.DefChange, ...]


class Snapshot(Wire):
    """L'état vécu entier, avec les actions et les demandes en cours."""

    type: Literal["snapshot"] = "snapshot"
    state: w.WorldState


class Delta(Wire):
    type: Literal["delta"] = "delta"
    seq: int = Field(ge=0)
    at: int
    cause: w.Cause
    changes: tuple[w.StateChange, ...]


class IntentStart(Wire):
    """Une action commence : l'hôte la joue, les autres écrans l'animent (même plan, mêmes durées)."""

    type: Literal["intent"] = "intent"
    seq: int = Field(ge=0)
    intent: w.Intent


class IntentEnd(Wire):
    type: Literal["intent_end"] = "intent_end"
    seq: int = Field(ge=0)
    intent: str = Field(max_length=64)
    actor: w.ActorId
    outcome: w.Outcome
    reason: w.Refusal | None = None
    changes: tuple[w.StateChange, ...] = ()


class RequestOpen(Wire):
    type: Literal["request"] = "request"
    seq: int = Field(ge=0)
    request: w.Request


class RequestClose(Wire):
    type: Literal["request_end"] = "request_end"
    seq: int = Field(ge=0)
    request: str = Field(max_length=64)
    answer: w.Answer
    changes: tuple[w.StateChange, ...] = ()


class GestureOut(Wire):
    type: Literal["gesture"] = "gesture"
    seq: int = Field(ge=0)
    actor: w.ActorId
    gesture: w.Gesture
    to_actor: w.ActorId | None = None
    object: w.Ident | None = None


class Presence(Wire):
    """Une personne entre dans le monde ou en sort."""

    type: Literal["presence"] = "presence"
    seq: int = Field(ge=0)
    actor: w.ActorId
    joined: bool
    room: w.Ident | None = None
    place: w.Ident | None = None
    asset: w.AssetKey | None = None
    label: str = Field(default="", max_length=60)


class Result(Wire):
    """L'accusé d'une commande : ``accepted`` (et le ``seq`` qui l'a journalisée, s'il y en a un),
    ``refused`` (un code, et ce que ça veut dire en français), ``duplicate`` (déjà reçue)."""

    type: Literal["result"] = "result"
    cmd: CmdId
    status: Status
    code: w.Refusal | None = None
    message: str = Field(default="", max_length=300)
    seq: int | None = None


class HostLease(Wire):
    """Le bail d'hôte accordé ou retiré ; l'hôte le renouvelle par ``ping`` avant ``ttl_ms``."""

    type: Literal["host"] = "host"
    granted: bool
    ttl_ms: int = Field(ge=0)


class PoseOut(Wire):
    type: Literal["pose"] = "pose"
    actor: w.ActorId
    t: int
    pos: Vec3
    yaw: float
    anim: str | None = Field(default=None, max_length=60)


class Pong(Wire):
    type: Literal["pong"] = "pong"
    t: int


class Failure(Wire):
    """Une erreur de protocole (trame illisible, rôle manquant) ; ``fatal`` : la connexion va se fermer."""

    type: Literal["error"] = "error"
    code: str = Field(max_length=40)
    message: str = Field(default="", max_length=300)
    fatal: bool = False


ServerFrame = Annotated[
    Welcome | Definition | DefinitionDelta | Snapshot | Delta | IntentStart | IntentEnd | RequestOpen
    | RequestClose | GestureOut | Presence | Result | HostLease | PoseOut | Pong | Failure,
    Field(discriminator="type"),
]

CLIENT: TypeAdapter[Any] = TypeAdapter(ClientFrame)
SERVER: TypeAdapter[Any] = TypeAdapter(ServerFrame)

#: Les rôles que chaque commande exige (au moins un) ; ``hello``, ``sync`` et ``ping`` n'en exigent aucun.
REQUIRES: dict[str, frozenset[Role]] = {
    "act": frozenset({Role.VIEWER, Role.HOST}),
    "moved": frozenset({Role.VIEWER, Role.HOST}),
    "address": frozenset({Role.VIEWER, Role.HOST}),
    "answer": frozenset({Role.VIEWER, Role.HOST}),
    "pose": frozenset({Role.VIEWER, Role.HOST}),
    "report": frozenset({Role.HOST}),
    "edit": frozenset({Role.CREATOR}),
    "describe": frozenset({Role.CREATOR}),
}

#: Les plafonds par connexion (trames par seconde) ; au-delà : ``result`` ``rate_limited`` (une pose en
#: trop est jetée sans réponse).
RATES: dict[str, float] = {"act": 4, "moved": 4, "address": 2, "answer": 4, "report": 30, "edit": 1,
                           "describe": 1, "pose": 20, "sync": 1, "ping": 1}


def client_frame(raw: str | bytes) -> Any:
    """Une trame reçue, validée (``pydantic.ValidationError`` sinon)."""
    return CLIENT.validate_json(raw)


def server_frame(raw: str | bytes) -> Any:
    return SERVER.validate_json(raw)


def dump(frame: Wire) -> str:
    """Une trame à émettre, en JSON compact. Les ``null`` restent : pour certains champs ils veulent dire
    quelque chose (une occupation sans fin prévue, ``duration_s: null``, n'est pas la durée par défaut)."""
    return json.dumps(frame.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))


def json_schema() -> dict[str, Any]:
    """Le schéma JSON du protocole, pour générer les types côté moteur (C#, GDScript, TypeScript)."""
    return {
        "$id": PROTOCOL,
        "title": "Protocole du monde de Mika",
        "client": CLIENT.json_schema(),
        "server": SERVER.json_schema(),
        "world": w.WorldDef.model_json_schema(),
    }

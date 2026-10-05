"""L'adaptateur du monde : la route WebSocket ``/ws/world`` du protocole ``mika.world/1`` (ADR 0050, 0051).

Il fait le bord, et seulement le bord :

- **qui parle** : un navigateur par sa session et son ``Origin`` (comme ``/ws``) ; un client natif — un moteur
  de jeu, qui n'a ni cookie ni ``Origin`` — par un jeton de son compte (``hello.token`` ou l'en-tête
  ``Authorization: Bearer mw_…``), sous l'adresse du compte : l'identité reste authentifiée ;
- **ce qu'il peut** : ``viewer`` à tout compte qui peut lui parler, ``creator`` aux opérateurs, ``host`` à un
  seul opérateur à la fois, par bail (renouvelé par ``ping``, perdu au silence, passé au suivant qui attend) ;
- **combien** : les débits par connexion (``protocol.RATES``), le dédoublonnage des commandes par ``cmd`` ;
- **ce qu'on lui dit** : le journal traduit en trames (``translate``), chacune avec le ``seq`` de l'événement
  qui la porte ; un instantané quand le retard est trop grand ou que l'état a changé sans action à rejouer ;
- **qui est là** : une personne entre dans le monde quand un ``viewer`` de son compte est accueilli, et en sort
  quand le dernier se déconnecte ou se tait (``PRESENCE_SILENCE_S``) — elle revient à sa trame suivante ; au
  démarrage, qui était resté dans le monde sans connexion en sort (``MindPort.world_presence``).

Il ne valide **rien** du monde : chaque commande passe au port d'entrée (``MindPort.world_command``), qui la
donne à la faculté ``world`` ; ce qu'il diffuse, il le lit dans le journal (``Mind.subscribe`` en direct,
``MindPort.world_events`` pour un rattrapage). La pose d'un avatar est la seule chose qu'il relaie sans le
noyau : continue, jamais journalisée, jamais montrée à Mika.

Une connexion lente ne retient personne : chaque connexion a sa file d'envoi, bornée ; au-delà, elle est fermée
(1013) et revient par ``hello.after``. Une commande en cours retient les diffusions **de sa propre connexion**
jusqu'à son accusé : le client lit ``result`` puis la trame qui l'applique, jamais l'inverse.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import re
import secrets
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from mika.adapters.web.accounts import TOKEN_KEY, Account, Accounts
from mika.adapters.web.app import SESSION_COOKIE, bearer
from mika.adapters.web.protocol import RateLimiter
from mika.adapters.world import protocol as p
from mika.contracts import world as w
from mika.contracts.entry import MindPort
from mika.kernel.events import Event
from mika.vocab.people import clean_display_name

log = logging.getLogger("mika.world")

#: la durée du bail d'hôte (ms) ; chaque ``ping`` de l'hôte le renouvelle
HOST_TTL_MS = 15_000
#: au-delà de ce retard (en événements qui changent le monde), un rattrapage devient un instantané
CATCH_UP_MAX = 500
#: les trames en attente d'envoi sur une connexion ; au-delà, elle est fermée (elle revient par ``hello.after``)
QUEUE_MAX = 1024
#: au-delà de cette file, les poses (continues, remplaçables) ne sont plus relayées à cette connexion
POSE_QUEUE_MAX = QUEUE_MAX // 2
#: les commandes en attente de traitement sur une connexion
COMMANDS_MAX = 128
#: les accusés gardés par connexion, pour reconnaître une commande déjà reçue
RESULTS_KEPT = 512
#: le délai pour la première trame (``hello``)
HELLO_TIMEOUT_S = 10.0
#: l'entretien : bail d'hôte, et identifiants revérifiés (un jeton révoqué par la ligne de commande, un compte
#: désactivé par un autre processus)
TICK_S = 1.0
CREDENTIAL_CHECK_S = 10.0
#: les erreurs de protocole dites par seconde ; au-delà, une trame illisible est jetée sans réponse
ERRORS_PER_S = 5
#: les constats ``loaded`` gardés pour la console (le dernier de chaque connexion hôte)
LOADED_KEPT = 8
#: le temps laissé à une connexion pour recevoir sa trame de fermeture
DRAIN_S = 2.0
#: une connexion qui ne dit plus rien (pas même un ``ping``) depuis ce temps ne fait plus être sa personne dans le
#: monde ; elle y revient à sa trame suivante
PRESENCE_SILENCE_S = 60.0

CLOSE_GOING_AWAY = 1001
CLOSE_UNSUPPORTED = 1003  # ce n'est pas du JSON texte
CLOSE_POLICY = 1008  # origine inconnue, pas de ``hello``
CLOSE_TRY_LATER = 1013  # trop lente : qu'elle revienne par ``hello.after``
CLOSE_UNAUTHORIZED = 4401  # comme ``/ws`` : le client ne réessaie pas sans nouvel identifiant

_CMD = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_COMMANDS = frozenset({"act", "moved", "address", "answer", "report", "edit", "describe"})
_ROLE_ORDER = (p.Role.VIEWER, p.Role.HOST, p.Role.CREATOR)


# ── Le journal en trames ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Translation:
    """Les trames d'une suite d'événements. ``reset`` : l'état a changé sans action à rejouer (elle s'est
    réveillée au bord du lit, une édition a déplacé ce qui n'avait plus sa place) — un instantané suit en
    direct, et remplace un rattrapage ; ``redefined`` : la définition a changé en route."""

    frames: tuple[p.Wire, ...] = ()
    reset: bool = False
    redefined: bool = False


def _intended(e: Event[Any], labels: Mapping[str, str]) -> p.Wire:
    return p.IntentStart(seq=e.seq, intent=e.data.intent)


def _ended(e: Event[Any], labels: Mapping[str, str]) -> p.Wire:
    d = e.data
    return p.IntentEnd(seq=e.seq, intent=d.intent, actor=d.actor, outcome=d.outcome, reason=d.reason,
                       changes=d.changes)


def _changed(e: Event[Any], labels: Mapping[str, str]) -> p.Wire:
    return p.Delta(seq=e.seq, at=e.at, cause=e.data.cause, changes=e.data.changes)


def _authored(e: Event[Any], labels: Mapping[str, str]) -> p.Wire:
    d = e.data
    return p.DefinitionDelta(seq=e.seq, base=d.base_rev, rev=d.base_rev + 1, changes=d.changes)


def _requested(e: Event[Any], labels: Mapping[str, str]) -> p.Wire:
    return p.RequestOpen(seq=e.seq, request=e.data.request)


def _answered(e: Event[Any], labels: Mapping[str, str]) -> p.Wire:
    d = e.data
    return p.RequestClose(seq=e.seq, request=d.request, answer=d.answer, changes=d.changes)


def _gestured(e: Event[Any], labels: Mapping[str, str]) -> p.Wire:
    d = e.data
    return p.GestureOut(seq=e.seq, actor=d.actor, gesture=d.gesture, to_actor=d.to_actor, object=d.object)


def _joined(e: Event[Any], labels: Mapping[str, str]) -> p.Wire:
    d = e.data
    return p.Presence(seq=e.seq, actor=d.actor, joined=True, room=d.room, place=d.place, asset=d.asset,
                      label=labels.get(d.handle, "")[:60])


def _left(e: Event[Any], labels: Mapping[str, str]) -> p.Wire:
    return p.Presence(seq=e.seq, actor=e.data.actor, joined=False)


#: chaque événement du monde que les écrans reçoivent, et sa trame (``world.noticed`` et ``world.described`` ne
#: regardent qu'elle : ils n'en ont pas)
FRAMES: dict[str, Callable[[Event[Any], Mapping[str, str]], p.Wire]] = {
    w.INTENDED.name: _intended, w.ENDED.name: _ended, w.CHANGED.name: _changed, w.AUTHORED.name: _authored,
    w.REQUESTED.name: _requested, w.ANSWERED.name: _answered, w.GESTURED.name: _gestured, w.JOINED.name: _joined,
    w.LEFT.name: _left,
}


def translate(events: Iterable[Event[Any]], state: w.WorldState, labels: Mapping[str, str] | None = None
              ) -> Translation:
    """Les trames d'événements du journal, dans leur ordre, chacune avec le ``seq`` de son événement.

    ``state`` est le monde **après** ces événements. Un événement d'une autre faculté que le monde réduit (elle
    s'endort, elle se réveille) n'a pas de trame à lui : s'il a fait naître un réflexe, c'est l'``intent`` de ce
    réflexe qui part, avec **son** ``seq`` (le coucher et l'endormissement arrivent ensemble, ADR 0050) ; s'il a
    changé le monde autrement, ``reset`` le dit (un instantané) ; s'il ne l'a pas changé (``state.seq`` est
    plus ancien que lui), rien."""
    labels = labels or {}
    frames: list[p.Wire] = []
    announced: set[str] = set()
    reset = redefined = False
    for e in events:
        if e.type.owner != w.OWNER:
            reflexes = [i for i in state.intents if i.cause.source is w.Source.REFLEX and i.started == e.at
                        and i.id not in announced]
            for intent in reflexes:
                announced.add(intent.id)
                frames.append(p.IntentStart(seq=e.seq, intent=intent))
            if not reflexes and state.seq >= e.seq:
                reset = True
            continue
        make = FRAMES.get(e.type.name)
        if make is None:
            continue
        frames.append(make(e, labels))
        if e.type.name == w.AUTHORED.name:
            reset = redefined = True  # ce que l'édition a réconcilié (un objet sans meuble) ne se rejoue pas
    return Translation(tuple(frames), reset, redefined)


def explain(exc: ValidationError, raw: Mapping[str, Any]) -> str:
    """Pourquoi une trame ne se lit pas, en une phrase (la première erreur), avec son ``cmd`` s'il y en a un :
    un client qui attend l'accusé de cette commande sait laquelle est perdue."""
    errors = exc.errors()
    err = errors[0] if errors else {}
    kind = err.get("type", "")
    loc = [str(x) for x in err.get("loc", ())]
    if loc and loc[0] == raw.get("type"):
        loc = loc[1:]  # le nom de la variante (``act``) n'est pas un champ
    where = ".".join(loc) or "?"
    if kind == "union_tag_invalid":
        why = f"type de trame inconnu « {str(raw.get('type'))[:40]} »"
    elif kind == "union_tag_not_found":
        why = "trame sans « type »"
    elif kind == "extra_forbidden":
        why = f"champ inconnu « {loc[-1] if loc else '?'} »"
    elif kind == "missing":
        why = f"champ manquant « {where} »"
    else:
        why = f"champ « {where} » : {err.get('msg', 'invalide')}"
    cmd = raw.get("cmd")
    tag = f" ({cmd})" if isinstance(cmd, str) and _CMD.match(cmd) else ""
    return f"trame illisible{tag} : {why}"[:300]


# ── Une connexion ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LoadedReport:
    """Ce qu'un moteur hôte a dit en chargeant une révision : ce qui lui manque (pour la console)."""

    session: str
    client: str
    actor: str
    at: int
    rev: int
    missing_assets: tuple[str, ...]
    missing_anchors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Close:
    code: int


@dataclass(frozen=True, slots=True)
class _Who:
    account: Account | None
    #: ce que la connexion revérifie (sa session web, ``token:<id>``) ; ``None`` : anonyme
    credential: str | None


class WorldSession:
    """Une connexion accueillie : qui elle est, ce qu'elle peut, ce qu'on lui envoie (une file, un seul
    écrivain), ce qu'elle a déjà demandé."""

    def __init__(self, ws: WebSocket, sid: str, who: _Who, client: p.ClientInfo, *,
                 monotonic: Callable[[], float]) -> None:
        self.ws = ws
        self.id = sid
        self.account = who.account
        self.credential = who.credential
        self.handle = who.account.handle if who.account is not None else f"anon_{secrets.token_hex(6)}"
        self.actor = w.player(self.handle)
        self.operator = bool(who.account and who.account.operator)
        self.label = clean_display_name(who.account.display_name) if who.account is not None else ""
        self.client = client
        self.roles: set[p.Role] = set()
        #: un opérateur qui a demandé le rôle d'hôte (il l'obtient dès que le bail est libre)
        self.wants_host = False
        #: l'apparence que la personne a choisie (``hello.avatar``)
        self.avatar: str | None = None
        #: cette connexion fait être sa personne dans le monde (un ``viewer`` accueilli, qui ne s'est pas tu)
        self.inside = False
        #: la dernière trame reçue, sur l'horloge du concentrateur
        self.heard = monotonic()
        self.closing = False
        self.commands: asyncio.Queue[Any] = asyncio.Queue()
        self.results: OrderedDict[str, p.Result] = OrderedDict()
        self.gates = {kind: RateLimiter(max(1, int(n)), 1.0) for kind, n in p.RATES.items()}
        self.errors = RateLimiter(ERRORS_PER_S, 1.0)
        self._monotonic = monotonic
        self._out: deque[str | _Close] = deque()
        self._held: list[str] | None = None
        self._wake = asyncio.Event()
        self._sender: asyncio.Task[None] | None = None
        self._worker: asyncio.Task[None] | None = None
        #: rappelée quand la file déborde (le concentrateur ferme la connexion)
        self.on_overflow: Callable[[WorldSession], None] | None = None

    # ── l'envoi ──
    def pending(self) -> int:
        return len(self._out) + len(self._held or ())

    def push(self, text: str, *, urgent: bool = False) -> None:
        """Met une trame en file (``urgent`` : devant les diffusions retenues — l'accusé d'une commande)."""
        if self.closing:
            return
        if self._held is not None and not urgent:
            self._held.append(text)
        else:
            self._out.append(text)
        self._wake.set()
        if self.pending() > QUEUE_MAX and self.on_overflow is not None:
            self.on_overflow(self)

    def push_frame(self, frame: p.Wire, *, urgent: bool = False) -> None:
        self.push(p.dump(frame), urgent=urgent)

    def push_pose(self, text: str) -> None:
        """Une pose ne vaut que la suivante : en retard, on la jette plutôt que d'allonger la file."""
        if self.pending() < POSE_QUEUE_MAX:
            self.push(text)

    def hold(self) -> None:
        """Une commande part : ce qui est diffusé attend son accusé."""
        self._held = []

    def release(self) -> None:
        held, self._held = self._held, None
        if held and not self.closing:
            self._out.extend(held)
            self._wake.set()

    def close(self, code: int, error: p.Failure | None = None) -> None:
        """Ferme la connexion : ce qui attendait est abandonné, l'erreur part, puis la fermeture."""
        if self.closing:
            return
        self.closing = True
        self._out.clear()
        self._held = None
        if error is not None:
            self._out.append(p.dump(error))
        self._out.append(_Close(code))
        self._wake.set()

    async def _send_loop(self) -> None:
        try:
            while True:
                while not self._out:
                    self._wake.clear()
                    await self._wake.wait()
                item = self._out.popleft()
                if isinstance(item, _Close):
                    await self.ws.close(code=item.code)
                    return
                await self.ws.send_text(item)
        except (WebSocketDisconnect, RuntimeError, OSError) as exc:  # partie en route : la lecture le verra
            log.debug("envoi impossible sur %s : %r", self.id, exc)

    def start(self, work: Callable[[WorldSession], Any]) -> None:
        self._sender = asyncio.ensure_future(self._send_loop())
        self._worker = asyncio.ensure_future(work(self))

    async def drained(self) -> None:
        """Laisse partir la fermeture (bornée : une connexion morte ne retient pas l'arrêt)."""
        if self._sender is not None and not self._sender.done():
            with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(self._sender), DRAIN_S)

    async def stop(self) -> None:
        for task in (self._worker, self._sender):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(t for t in (self._worker, self._sender) if t is not None), return_exceptions=True)


# ── Le concentrateur ──────────────────────────────────────────────────────


class WorldHub:
    """Les connexions du monde, le bail d'hôte, et la diffusion du journal (``publish``, appelée en direct par
    l'écouteur du ``Mind`` : elle ne fait que mettre en file)."""

    def __init__(self, port: MindPort, accounts: Accounts, *, origins: Sequence[str], auth_required: bool = True,
                 monotonic: Callable[[], float] = time.monotonic, ttl_ms: int = HOST_TTL_MS) -> None:
        self.port = port
        self.accounts = accounts
        self.origins = tuple(origins)
        self.auth_required = auth_required
        #: l'horloge du bail et des débits (remplaçable : les tests avancent le temps sans attendre)
        self.monotonic = monotonic
        self.ttl_ms = ttl_ms
        #: les connexions accueillies (après ``hello``) : elles reçoivent ce qui est diffusé
        self.sessions: dict[str, WorldSession] = {}
        self._lease: str | None = None
        self._lease_until = 0.0
        #: les opérateurs qui attendent le bail, dans l'ordre de leur demande
        self._candidates: list[str] = []
        #: le dernier ``loaded`` de chaque connexion hôte (le plus récent en dernier)
        self.loaded: OrderedDict[str, LoadedReport] = OrderedDict()
        self._counter = itertools.count(1)
        self._task: asyncio.Task[None] | None = None
        self._checked_at = 0.0
        self._stopping = False
        #: une entrée ou une sortie à la fois par personne (deux de ses connexions qui se croisent ne laissent pas
        #: un corps sans connexion)
        self._presence: dict[str, asyncio.Lock] = {}
        #: ceux qui étaient restés dans le monde au démarrage en sont sortis
        self._evicted = False
        accounts.on_revoke.append(lambda account_id: self.revoke(account=account_id))
        accounts.on_token_revoke.append(lambda token_id: self.revoke(token=token_id))

    # ── l'extérieur ──
    @property
    def listening(self) -> bool:
        """Quelqu'un écoute-t-il ? (sinon l'écouteur du journal n'a rien à calculer)"""
        return bool(self.sessions)

    @property
    def host(self) -> str | None:
        """La connexion qui tient le bail d'hôte."""
        self._expire()
        return self._lease

    def route(self) -> WebSocketRoute:
        return WebSocketRoute(p.PATH, self.endpoint)

    def overview(self) -> dict[str, Any]:
        """Ce qu'un opérateur voudrait savoir : qui est connecté, qui joue (et qui attend le bail), la révision
        en vigueur (``rev``), ce qui manque au moteur."""
        definition, _ = self.port.world_view()
        return {"sessions": [{"session": s.id, "actor": s.actor, "handle": s.handle, "client": _client_name(s.client),
                              "roles": [r.value for r in _ROLE_ORDER if r in s.roles],
                              "waiting_host": s.id in self._candidates}
                             for s in self.sessions.values()],
                "host": self.host,
                "rev": definition.rev,
                "loaded": [{"session": r.session, "client": r.client, "rev": r.rev, "at": r.at,
                            "missing_assets": list(r.missing_assets), "missing_anchors": list(r.missing_anchors)}
                           for r in reversed(self.loaded.values())]}

    def publish(self, events: Sequence[Event[Any]], definition: w.WorldDef, state: w.WorldState) -> None:
        """Un lot commité : ses trames, à chaque connexion, dans l'ordre du journal (synchrone : appelée par
        l'écouteur du ``Mind``, elle ne fait que mettre en file)."""
        if not self.sessions:
            return
        t = translate(events, state, self._labels())
        frames = list(t.frames) + ([p.Snapshot(state=state)] if t.reset else [])
        texts = [p.dump(f) for f in frames]
        for s in list(self.sessions.values()):
            for text in texts:
                s.push(text)

    async def revoke(self, *, account: int | None = None, token: int | None = None) -> int:
        """Ferme (4401) les connexions d'un compte dont les droits ont changé, ou d'un jeton révoqué."""
        key = f"{TOKEN_KEY}{token}" if token is not None else None
        doomed = [s for s in list(self.sessions.values())
                  if (account is not None and s.account is not None and s.account.id == account)
                  or (key is not None and s.credential == key)]
        for s in doomed:
            self._unauthorized(s, "Accès révoqué : reconnecte-toi avec un identifiant valide.")
        return len(doomed)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._tick_loop(), name="world-hub")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        sessions = list(self.sessions.values())
        for s in sessions:
            s.close(CLOSE_GOING_AWAY, p.Failure(code="shutdown", message="Le noyau s'arrête.", fatal=True))
            self._forget(s)
        await asyncio.gather(*(s.drained() for s in sessions), return_exceptions=True)
        await asyncio.gather(*(s.stop() for s in sessions), return_exceptions=True)

    # ── une connexion, de bout en bout ──
    async def endpoint(self, websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if (origin is not None and origin not in self.origins) or self._stopping:
            await websocket.close(code=CLOSE_POLICY)
            return
        await websocket.accept()
        hello = await self._hello(websocket)
        if hello is None:
            return
        who = await self._authenticate(websocket, origin, hello)
        if who is None:
            await _refuse(websocket, CLOSE_UNAUTHORIZED, "unauthorized",
                          "Authentification requise : la session d'un navigateur (avec son Origin), ou le jeton "
                          "d'un compte pour un client natif (sans Origin).")
            return
        session = WorldSession(websocket, f"s-{next(self._counter)}-{secrets.token_hex(4)}", who, hello.client,
                               monotonic=self.monotonic)
        session.on_overflow = self._overflow
        session.start(self._work)
        try:
            self._welcome(session, hello)
            if session.inside:
                await self._settle(session.handle, session.actor, session.avatar)  # puis sa ``presence``, à tous
            await self._serve(session)
        finally:
            self._forget(session)
            await session.stop()
            if p.Role.VIEWER in session.roles:
                await self._settle(session.handle, session.actor)  # sa dernière connexion partie : elle sort

    async def _hello(self, websocket: WebSocket) -> p.Hello | None:
        """La première trame, ``hello`` — sinon une erreur fatale, et la connexion se ferme."""
        try:
            message = await asyncio.wait_for(websocket.receive(), HELLO_TIMEOUT_S)
        except TimeoutError:
            await _refuse(websocket, CLOSE_POLICY, "hello_expected",
                          f"La première trame est « hello », attendue dans les {HELLO_TIMEOUT_S:.0f} secondes.")
            return None
        if message["type"] == "websocket.disconnect":
            return None
        text = message.get("text")
        raw = _object(text)
        if raw is None:
            await _refuse(websocket, CLOSE_UNSUPPORTED, "bad_frame", "Une trame est un objet JSON, en texte.")
            return None
        try:
            frame = p.client_frame(text)  # type: ignore[arg-type]
        except ValidationError as exc:
            await _refuse(websocket, CLOSE_POLICY, "bad_frame", explain(exc, raw))
            return None
        if not isinstance(frame, p.Hello):
            await _refuse(websocket, CLOSE_POLICY, "hello_expected", "La première trame est « hello ».")
            return None
        return frame

    async def _authenticate(self, websocket: WebSocket, origin: str | None, hello: p.Hello) -> _Who | None:
        header = bearer(websocket.headers.get("authorization"))
        if origin is not None:
            # un navigateur : sa session (son Origin est déjà vérifiée) ; il ne peut pas poser d'en-tête, et un
            # jeton n'a rien à faire dans une page — on le refuse plutôt que de l'accepter en silence
            if hello.token or header:
                return None
            key = websocket.cookies.get(SESSION_COOKIE)
            account = self.accounts.session(key)
            if account is not None:
                return _Who(account, key)
            return None if self.auth_required else _Who(None, None)
        token = hello.token or header
        found = await self.accounts.use_token(token) if token else None
        if found is None:
            return None
        return _Who(found[0], f"{TOKEN_KEY}{found[1]}")

    def _welcome(self, s: WorldSession, hello: p.Hello) -> None:
        """L'accueil, d'un seul tenant (sans attente : aucun commit ne s'intercale entre ce qu'on lit et le
        moment où la connexion se met à recevoir les diffusions) — ``welcome``, puis ``definition`` si sa
        révision n'est pas la bonne, puis l'instantané ou le rattrapage, puis ``host`` s'il l'a demandé. Un
        ``viewer`` fait entrer sa personne dans le monde : sa ``presence`` suit, diffusée à tous."""
        self._expire()
        definition, state = self.port.world_view()
        asked = set(hello.roles)
        s.avatar = hello.avatar
        if p.Role.VIEWER in asked:
            s.roles.add(p.Role.VIEWER)
            s.inside = True
        if p.Role.CREATOR in asked and s.operator:
            s.roles.add(p.Role.CREATOR)
        host: p.HostLease | None = None
        if p.Role.HOST in asked:
            if s.operator:
                s.wants_host = True
                if self._lease is None:
                    self._take(s)
                else:
                    self._candidates.append(s.id)
            granted = p.Role.HOST in s.roles
            host = p.HostLease(granted=granted, ttl_ms=self.ttl_ms if granted else 0)
        frames: list[p.Wire] = [p.Welcome(
            session=s.id, granted=tuple(r for r in _ROLE_ORDER if r in s.roles), actor=s.actor, world=definition.id,
            rev=definition.rev, seq=state.seq, now=self.port.frame().now)]
        fresh = hello.rev != definition.rev
        if fresh:
            frames.append(p.Definition(world=definition))
        if hello.after is None or fresh:
            frames.append(p.Snapshot(state=state))
        else:
            frames.extend(self._catch_up(hello.after, definition, state))
        if host is not None:
            frames.append(host)
        for frame in frames:
            s.push_frame(frame)
        self.sessions[s.id] = s

    def _catch_up(self, after: int, definition: w.WorldDef, state: w.WorldState) -> list[p.Wire]:
        """Ce qui a changé depuis ``after`` : les trames manquées, ou un instantané (trop de retard ; un état
        qui a changé sans action à rejouer ; un ``after`` que ce journal ne connaît pas — une sauvegarde
        restaurée, un autre monde)."""
        if after == state.seq:
            return []
        if after > state.seq:
            return [p.Snapshot(state=state)]
        events = self.port.world_events(after, limit=CATCH_UP_MAX)
        if events is None:
            return [p.Snapshot(state=state)]
        t = translate(events, state, self._labels())
        if t.reset:
            return ([p.Definition(world=definition)] if t.redefined else []) + [p.Snapshot(state=state)]
        return list(t.frames)

    async def _serve(self, s: WorldSession) -> None:
        while not s.closing:
            message = await s.ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            text = message.get("text")
            if text is None:
                s.close(CLOSE_UNSUPPORTED, p.Failure(code="bad_frame", message="Une trame est un objet JSON, en "
                                                                               "texte.", fatal=True))
                break
            await self._dispatch(s, text)
        await s.drained()

    async def _dispatch(self, s: WorldSession, text: str) -> None:
        self._expire()
        s.heard = self.monotonic()
        if not s.inside and p.Role.VIEWER in s.roles and not s.closing:
            s.inside = True  # elle s'était tue, elle se manifeste : elle revient dans le monde
            await self._settle(s.handle, s.actor, s.avatar)
        raw = _object(text)
        if raw is None:
            s.close(CLOSE_UNSUPPORTED, p.Failure(code="bad_frame", message="Une trame est un objet JSON, en texte.",
                                                 fatal=True))
            return
        kind = raw.get("type")
        gate = s.gates.get(kind) if isinstance(kind, str) else None
        if gate is not None and not gate.allow(self.monotonic()):
            self._limited(s, kind, raw)
            return
        try:
            frame = p.client_frame(text)
        except ValidationError as exc:
            self._error(s, "bad_frame", explain(exc, raw))
            return
        if isinstance(frame, p.Hello):
            self._error(s, "bad_frame", "« hello » ne s'envoie qu'une fois, au début.")
        elif isinstance(frame, p.Ping):
            self._ping(s, frame)
        elif isinstance(frame, p.Sync):
            definition, state = self.port.world_view()
            for f in self._catch_up(frame.after, definition, state):
                s.push_frame(f)
        elif isinstance(frame, p.PoseIn):
            self._pose(s, frame)
        elif s.commands.qsize() >= COMMANDS_MAX:
            s.push_frame(p.Result(cmd=frame.cmd, status=p.Status.REFUSED, code=w.Refusal.RATE_LIMITED,
                                  message="Trop de commandes en attente : patiente un peu."))
        else:
            s.commands.put_nowait(frame)

    def _limited(self, s: WorldSession, kind: str, raw: Mapping[str, Any]) -> None:
        if kind == "pose":
            return  # une pose en trop est jetée sans réponse : la suivante la remplace
        cmd = raw.get("cmd")
        message = f"Trop de « {kind} » : au plus {p.RATES[kind]:g} par seconde."
        if kind in _COMMANDS and isinstance(cmd, str) and _CMD.match(cmd):
            s.push_frame(p.Result(cmd=cmd, status=p.Status.REFUSED, code=w.Refusal.RATE_LIMITED, message=message))
        else:
            self._error(s, "rate_limited", message)

    def _error(self, s: WorldSession, code: str, message: str) -> None:
        if s.errors.allow(self.monotonic()):
            s.push_frame(p.Failure(code=code, message=message[:300], fatal=False))

    def _ping(self, s: WorldSession, frame: p.Ping) -> None:
        if self._lease == s.id:
            self._lease_until = self.monotonic() + self.ttl_ms / 1000
        elif s.wants_host and self._lease is None:
            self._take(s)  # un hôte qui reparle après avoir perdu le bail le reprend, s'il est libre
            s.push_frame(p.HostLease(granted=True, ttl_ms=self.ttl_ms))
        elif s.wants_host and s.id not in self._candidates:
            self._candidates.append(s.id)
        s.push_frame(p.Pong(t=frame.t))

    def _pose(self, s: WorldSession, frame: p.PoseIn) -> None:
        if not s.roles & p.REQUIRES["pose"]:
            self._error(s, "forbidden", "Une pose est celle du corps d'une personne : il faut le rôle « viewer ».")
            return
        text = p.dump(p.PoseOut(actor=s.actor, t=frame.t, pos=frame.pos, yaw=frame.yaw, anim=frame.anim))
        for other in list(self.sessions.values()):
            if other is not s:
                other.push_pose(text)

    # ── les commandes, une à la fois par connexion ──
    async def _work(self, s: WorldSession) -> None:
        while True:
            command = await s.commands.get()
            try:
                await self._execute(s, command)
            except Exception as exc:  # une commande qui lève ne tue pas la connexion
                log.warning("commande %s de %s : %r", getattr(command, "cmd", "?"), s.id, exc)

    async def _execute(self, s: WorldSession, command: Any) -> None:
        cmd = command.cmd
        done = s.results.get(cmd)
        if done is not None:
            s.push_frame(done.model_copy(update={"status": p.Status.DUPLICATE}))
            return
        refusal = _role_refusal(s, command.type)
        if refusal is not None:
            result = p.Result(cmd=cmd, status=p.Status.REFUSED, code=refusal[0], message=refusal[1])
            s.push_frame(result)
        else:
            if not self._still_valid(s):
                return
            s.hold()
            try:
                result = await self._submit(s, command)
                s.push_frame(result, urgent=True)
            finally:
                s.release()
            if result.status is p.Status.ACCEPTED and isinstance(command, w.Report) \
                    and isinstance(command.report, w.Loaded):
                self._note_loaded(s, command.report)
        s.results[cmd] = result
        while len(s.results) > RESULTS_KEPT:
            s.results.popitem(last=False)

    async def _submit(self, s: WorldSession, command: Any) -> p.Result:
        try:
            got = await self.port.world_command(command, actor=s.actor, handle=s.handle, operator=s.operator,
                                                session=s.id)
        except Exception as exc:  # le noyau a levé : la commande est perdue, la connexion non
            log.warning("le noyau n'a pas traité %s de %s : %r", command.cmd, s.id, exc)
            return p.Result(cmd=command.cmd, status=p.Status.REFUSED,
                            message="Le noyau n'a pas pu traiter cette commande.")
        return p.Result(cmd=command.cmd, status=p.Status(got.status.value), code=got.code, message=got.message[:300],
                        seq=got.seq)

    def _note_loaded(self, s: WorldSession, report: w.Loaded) -> None:
        self.loaded.pop(s.id, None)
        self.loaded[s.id] = LoadedReport(
            session=s.id, client=_client_name(s.client), actor=s.actor, at=self.port.frame().now, rev=report.rev,
            missing_assets=tuple(report.missing_assets), missing_anchors=tuple(report.missing_anchors))
        while len(self.loaded) > LOADED_KEPT:
            self.loaded.popitem(last=False)

    # ── le bail d'hôte ──
    def _take(self, s: WorldSession) -> None:
        self._lease = s.id
        self._lease_until = self.monotonic() + self.ttl_ms / 1000
        s.roles.add(p.Role.HOST)
        if s.id in self._candidates:
            self._candidates.remove(s.id)

    def _expire(self) -> None:
        """Un hôte qui se tait perd le bail ; le premier qui l'attend l'obtient."""
        if self._lease is None or self.monotonic() < self._lease_until:
            return
        holder = self.sessions.get(self._lease)
        self._lease = None
        if holder is not None:
            holder.roles.discard(p.Role.HOST)
            holder.push_frame(p.HostLease(granted=False, ttl_ms=0))
        self._promote(exclude=holder.id if holder is not None else None)

    def _promote(self, *, exclude: str | None = None) -> None:
        while self._lease is None and self._candidates:
            sid = self._candidates.pop(0)
            nxt = self.sessions.get(sid)
            if nxt is None or nxt.closing or sid == exclude:
                continue
            self._take(nxt)
            nxt.push_frame(p.HostLease(granted=True, ttl_ms=self.ttl_ms))

    # ── la fin d'une connexion ──
    def _forget(self, s: WorldSession) -> None:
        """Elle ne reçoit plus rien ; si elle tenait le bail, il passe au suivant."""
        self.sessions.pop(s.id, None)
        if s.id in self._candidates:
            self._candidates.remove(s.id)
        if self._lease == s.id:
            self._lease = None
            self._promote()

    def _overflow(self, s: WorldSession) -> None:
        log.info("connexion du monde trop lente (%s) : fermée, elle reviendra par hello.after", s.id)
        s.close(CLOSE_TRY_LATER, p.Failure(code="too_slow", message="Trop de retard : reconnecte-toi avec "
                                                                    "« hello.after ».", fatal=True))
        self._forget(s)

    def _unauthorized(self, s: WorldSession, message: str) -> None:
        s.close(CLOSE_UNAUTHORIZED, p.Failure(code="unauthorized", message=message, fatal=True))
        self._forget(s)

    def _still_valid(self, s: WorldSession) -> bool:
        """Revérifie l'identifiant de la connexion (un jeton révoqué ailleurs, un compte désactivé ou dont les
        droits ont changé) ; ferme si besoin."""
        if s.credential is None:
            return True
        try:
            account = self.accounts.credential(s.credential)
        except Exception as exc:  # une lecture impossible ne ferme personne : on revérifiera
            log.debug("identifiant de %s illisible : %r", s.id, exc)
            return True
        if account is None or account.operator != s.operator:
            self._unauthorized(s, "Accès révoqué, ou tes droits ont changé : reconnecte-toi.")
            return False
        return True

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(TICK_S)
            try:
                if not self._evicted:
                    self._evicted = True
                    await self._evict()
                self._expire()
                now = self.monotonic()
                if now - self._checked_at >= CREDENTIAL_CHECK_S:
                    self._checked_at = now
                    for s in list(self.sessions.values()):
                        self._still_valid(s)
                for s in list(self.sessions.values()):
                    if s.inside and now - s.heard > PRESENCE_SILENCE_S:
                        s.inside = False  # elle ne se manifeste plus : elle sort, et reviendra à sa trame suivante
                        await self._settle(s.handle, s.actor)
            except Exception as exc:  # l'entretien ne tombe jamais
                log.warning("entretien du monde : %r", exc)

    # ── qui est dans le monde ──
    async def _settle(self, handle: str, actor: str, asset: str | None = None) -> None:
        """Le corps d'une personne dans le monde tel que ses connexions le veulent : dedans tant que l'une d'elles y
        est, dehors sinon — redit au noyau, qui n'écrit que ce qui change. Une personne à la fois."""
        lock = self._presence.setdefault(handle, asyncio.Lock())
        async with lock:
            inside = any(o.inside for o in self.sessions.values() if o.handle == handle)
            try:
                got = await self.port.world_presence(actor, handle, inside, asset=asset)
            except Exception as exc:  # le noyau a levé : la connexion n'en meurt pas
                log.warning("le noyau n'a pas fait %s %s du monde : %r", "entrer" if inside else "sortir", handle,
                            exc)
                return
            if got.status is w.CommandStatus.REFUSED:
                log.info("%s n'entre pas dans le monde : %s", handle, got.message)

    async def _evict(self) -> None:
        """Au démarrage : qui était resté dans le monde (le noyau s'est arrêté sans le voir partir) en sort, sauf si
        une connexion l'y a déjà fait entrer — au rejeu, une personne entrée hier n'est plus dans la pièce."""
        _, state = self.port.world_view()
        for a in state.actors:
            handle = w.handle_of(a.id)
            if handle is not None:
                await self._settle(handle, a.id)

    def _labels(self) -> dict[str, str]:
        return {s.handle: s.label for s in self.sessions.values() if s.label}


def _role_refusal(s: WorldSession, kind: str) -> tuple[w.Refusal, str] | None:
    need = p.REQUIRES.get(kind)
    if need is None or need & s.roles:
        return None
    if need == {p.Role.HOST}:
        return w.Refusal.NOT_HOST, "Constater est l'affaire du moteur hôte : il faut tenir le bail (rôle « host »)."
    if need == {p.Role.CREATOR}:
        return w.Refusal.NOT_CREATOR, "Éditer le monde demande le rôle « creator » (un compte opérateur)."
    return w.Refusal.FORBIDDEN, "Agir dans le monde demande le rôle « viewer »."


def _client_name(c: p.ClientInfo) -> str:
    return f"{c.name} {c.version} ({c.engine})"


def _object(text: Any) -> dict[str, Any] | None:
    if not isinstance(text, str):
        return None
    try:
        raw = json.loads(text)
    except ValueError:
        return None
    return raw if isinstance(raw, dict) else None


async def _refuse(websocket: WebSocket, code: int, error: str, message: str) -> None:
    """Avant l'accueil : l'erreur (fatale), puis la fermeture."""
    with contextlib.suppress(WebSocketDisconnect, RuntimeError, OSError):
        await websocket.send_text(p.dump(p.Failure(code=error, message=message[:300], fatal=True)))
        await websocket.close(code=code)

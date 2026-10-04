"""Le concentrateur des connexions WebSocket, et la livraison vers elles.

Une connexion appartient à une adresse ; une adresse peut avoir plusieurs
onglets. Ce qu'elle dit à quelqu'un ne part qu'aux connexions de cette
adresse — une personne absente rattrape par l'historique, jamais par une
diffusion à tout le monde.

- **Une pensée à voix haute** (le murmure, persona ``inner``) ne part qu'aux
  écrans de la personne à qui elle s'apprête à parler (``Delivery.target``) ;
  sans cible, seulement aux écrans des opératrices. Jamais à tout le monde : un
  inconnu dont l'onglet est ouvert n'entend pas ce qu'elle pense d'une autre.
- **Une seule connexion parle** : celle qui a posé la question, sinon la plus
  récemment active ; les autres onglets de la même personne affichent sans voix.
- **Chaque écran reçoit son propre panneau** : un état intérieur poussé à tous
  (elle s'endort, une action attend un accord) est rebâti pour chaque adresse
  — une trame sans panneau vidait rêve, journal, récit, projets.
- **Le visage ne contredit pas ce qu'elle vient de dire** : pendant
  ``REPLY_HOLD_S`` après une réplique, la synchronisation ne pousse pas une
  autre émotion que celle déclarée (elle lit ``FACE``, qui porte la balise de
  la dernière réplique tant qu'elle décroît).
- **Le sort d'une question se dit** : abstention (trame sans texte), réponse
  impossible (second ``ack`` ``no_reply`` : la bulle reste envoyée, une note
  dit que la réponse ne viendra pas ; la cause en clair et où la réparer, aux
  seules connexions opératrices) — une seule fois par question, qu'on
  l'apprenne par l'attente de la connexion ou par la file de sortie.
- Une session révoquée (déconnexion, compte désactivé, mot de passe changé,
  droits retirés) ferme ses WebSockets en 4401.
- **Une connexion n'est pas une présence** (ADR 0062) : l'application du
  téléphone garde sa connexion en arrière-plan pour recevoir, sans que personne
  regarde l'écran (``Conn.here`` faux). Elle reçoit ce qui lui est adressé (sans
  voix), jamais une pensée à voix haute, ni visage ni panneau (la batterie) ; la
  voix se choisit parmi les écrans regardés.
- **Un tour posé d'un autre appareil** : les autres connexions de la personne
  reçoivent aussi la ligne de la question avant la réponse (sinon leur curseur la
  dépasse et elles ne la verraient jamais).
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import secrets
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from mika.adapters.web import protocol
from mika.contracts import affect as affect_c
from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as runtime_c
from mika.contracts.entry import MindPort, SharedMeta
from mika.ports import delivery as delivery_p
from mika.ports.delivery import Delivery
from mika.vocab import voice
from mika.vocab.people import is_internal

log = logging.getLogger("mika.web")

Send = Callable[[dict[str, Any]], Awaitable[None]]
Close = Callable[[int], Awaitable[None]]
SYNC_INTERVAL_S = 3.0
MIN_INTENSITY_DELTA = 0.04
#: après une réplique, la synchronisation ne pousse pas une émotion qui la contredit (secondes)
REPLY_HOLD_S = 90.0
#: les clés livrées, et les questions dont le sort est déjà dit, gardées en mémoire
REMEMBERED = 2048
WS_UNAUTHORIZED = 4401


@dataclass(slots=True)
class Conn:
    id: str
    send: Send
    handle: str
    authenticated: bool = False
    account: int | None = None
    operator: bool = False
    display_name: str = ""
    announced: bool = False
    #: la session qui l'a ouverte (révoquée : la connexion se ferme)
    session: str | None = None
    close: Close | None = None
    #: dernier message envoyé (horloge monotone) : l'onglet actif est celui qui parle
    active_at: float = 0.0
    #: quelqu'un regarde cet écran (faux : l'application du téléphone en arrière-plan, qui ne fait que recevoir)
    here: bool = True
    #: le canal de cette connexion : l'écran (``web``) ou l'application du téléphone (``mobile``, une messagerie)
    channel: str = "web"
    chat: protocol.RateLimiter = field(default_factory=lambda: protocol.RateLimiter(*protocol.CHAT_RATE))
    control: protocol.RateLimiter = field(default_factory=lambda: protocol.RateLimiter(*protocol.CONTROL_RATE))
    #: ce qui s'écrit au journal quand on va et vient (``presence``) : borné, une bascule rapide n'y paraît pas
    presence: protocol.RateLimiter = field(default_factory=lambda: protocol.RateLimiter(*protocol.PRESENCE_RATE))


class Hub:
    def __init__(self, port: MindPort, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self.port = port
        self.conns: dict[str, Conn] = {}
        self._counter = itertools.count(1)
        self._sent_face: dict[str, tuple[str, float, tuple[str, ...]]] = {}
        #: adresse → (émotion déclarée, jusqu'à quand) : la réplique qu'on vient de livrer
        self._held: dict[str, tuple[str, float]] = {}
        self._sent_phase = "awake"
        self._sent_pending: tuple[int, ...] | None = None
        self._sync_task: asyncio.Task[None] | None = None
        self._monotonic = monotonic
        #: (adresse, client_msg_id) → la connexion qui l'a envoyé (elle parlera la réponse)
        self._asked: OrderedDict[tuple[str, str], str] = OrderedDict()
        #: les questions dont le sort (abstention, échec) a déjà été dit
        self._settled: OrderedDict[tuple[str, int | str], None] = OrderedDict()
        self.delivered: deque[str] = deque(maxlen=REMEMBERED)

    # ── connexions ──
    def attach(self, send: Send, *, handle: str | None = None, **kw: Any) -> Conn:
        cid = f"ws{next(self._counter)}-{secrets.token_hex(4)}"
        conn = Conn(cid, send, handle or f"anon_{secrets.token_hex(6)}", **kw)
        conn.active_at = self._monotonic()  # l'onglet qu'on vient d'ouvrir est celui qu'on regarde
        self.conns[cid] = conn
        return conn

    def detach(self, conn: Conn) -> None:
        self.conns.pop(conn.id, None)
        if not self.of(conn.handle):
            self._sent_face.pop(conn.handle, None)
            self._held.pop(conn.handle, None)

    def of(self, handle: str) -> list[Conn]:
        return [c for c in self.conns.values() if c.handle == handle]

    def watching(self, handle: str) -> list[Conn]:
        """Les connexions de cette adresse dont quelqu'un regarde l'écran."""
        return [c for c in self.of(handle) if c.here]

    def operators(self) -> list[Conn]:
        return [c for c in self.conns.values() if c.operator and c.authenticated]

    def note_asked(self, conn: Conn, client_msg_id: str) -> None:
        """Cette connexion vient d'envoyer ce message : c'est elle qui parlera la réponse."""
        conn.active_at = self._monotonic()
        if client_msg_id:
            key = (conn.handle, client_msg_id)
            self._asked[key] = conn.id
            self._asked.move_to_end(key)
            while len(self._asked) > REMEMBERED:
                self._asked.popitem(last=False)

    def speaker(self, conns: list[Conn], d: Delivery | None = None) -> Conn | None:
        """La connexion qui donne la voix : celle qui a posé la question si elle est là,
        sinon la plus récemment active (à égalité, la plus récente)."""
        if not conns:
            return None
        if d is not None and d.client_msg_id and d.target:
            asked = self._asked.get((d.target, d.client_msg_id))
            for c in conns:
                if c.id == asked:
                    return c
        return max(conns, key=lambda c: (c.active_at, int(c.id[2:].split("-", 1)[0] or 0)))

    async def _send(self, conns: list[Conn], frame: dict[str, Any]) -> int:
        sent = 0
        for c in conns:
            try:
                await c.send(frame)
                sent += 1
            except Exception as exc:  # une connexion morte ne bloque pas les autres
                log.debug("envoi impossible sur %s : %r", c.id, exc)
        return sent

    async def send_to(self, handle: str, frame: dict[str, Any]) -> int:
        return await self._send(self.of(handle), frame)

    async def revoke(self, *, account: int | None = None, session: str | None = None) -> int:
        """Ferme en 4401 les connexions d'un compte, ou d'une session : le client sait
        lire ce code (« session expirée — reconnecte-toi ») et ne réessaie pas en boucle."""
        doomed = [c for c in list(self.conns.values())
                  if (account is not None and c.account == account) or (session is not None and c.session == session)]
        for c in doomed:
            self.conns.pop(c.id, None)
            if c.close is not None:
                try:
                    await c.close(WS_UNAUTHORIZED)
                except Exception as exc:  # déjà fermée : rien à faire
                    log.debug("fermeture de %s : %r", c.id, exc)
        return len(doomed)

    # ── livraison (port) ──
    async def deliver(self, d: Delivery) -> bool:
        if d.kind == delivery_p.STATE:
            # son état a changé (elle s'endort, s'éveille) : sans parole, chacun avec son panneau
            await self.refresh_panels()
            return True
        if d.kind in delivery_p.REPLY_OUTCOMES:
            if d.target:
                outcome = "failed" if d.kind == delivery_p.REPLY_FAILED else protocol.ABSTAINED_OUTCOME
                await self.settle_reply(d.target, d.reply_to, d.client_msg_id, outcome, d.text)
            return True
        inner = d.persona == voice.INNER
        target = None if d.target is None or is_internal(d.target) else d.target
        if inner:
            # une pensée à voix haute ne s'entend que devant un écran regardé : jamais une notification
            targets = [c for c in (self.of(target) if target else self.operators()) if c.here]
        else:
            targets = self.of(target) if target else []
        if not targets:
            return True  # personne de connecté : rattrapage par l'historique (une pensée, elle, passe)
        handles = sorted({c.handle for c in targets})
        if not inner and target:
            await self._bind_turn(target, d)
        voices = set()  # une voix par personne : l'onglet regardé qui a demandé, sinon le plus récemment actif
        for h in handles:
            chosen = self.speaker([c for c in targets if c.handle == h and c.here], d)
            if chosen is not None:
                voices.add(chosen.id)
        files = self.shared(d.attachments) if not inner else []
        for c in targets:
            await self._send([c], protocol.speech(d, present=c.here, voiced=c.id in voices, attachments=files))
        self.delivered.append(d.key)
        if not inner and target and d.emotion.declared:
            self._hold(target, d)
        await self.refresh_panels(handles)
        return True

    async def _bind_turn(self, handle: str, d: Delivery) -> None:
        """Une réponse qui règle une rafale (« salut », « t'as vu le match ? », « allo ? ») ne lie par sa trame
        ``speech`` que son dernier message (``user_message_id``, ``client_msg_id``). Les bulles d'avant restaient
        sans identifiant : le curseur passait au-delà, aucun ``sync`` ne les renvoyait, et sorties de la fenêtre
        initiale elles finissaient épinglées sous tout le fil. Juste avant la trame ``speech``, une trame
        ``history`` (``catchup``) porte leurs lignes : le client les adopte par leur texte (contrat inchangé)."""
        earlier = {a for a in d.answers if a != d.reply_to}
        # les autres appareils de la personne (le téléphone quand elle écrit du navigateur) n'ont pas la question
        # elle-même : sans sa ligne, leur curseur la dépasserait avec la réponse, et ils ne la verraient jamais
        asked = self._asked.get((handle, d.client_msg_id)) if d.client_msg_id else None
        conns = self.of(handle)
        asker = [c for c in conns if c.id == asked]
        others = [c for c in conns if c.id != asked]
        whole = earlier | ({d.reply_to} if d.reply_to is not None and others else set())
        if not whole:
            return
        try:
            rows, _ = self.port.after(handle, min(whole) - 1, protocol.HISTORY_MAX)
        except Exception as exc:  # un fil illisible ne retient pas la réponse : un rattrapage les adoptera
            log.warning("bulles d'une rafale non rattachées (%s) : %r", handle, exc)
            return
        rows = [r for r in rows if r.id in whole and r.role == "user"]
        for group, wanted in ((asker, earlier), (others, whole)):
            mine = [r for r in rows if r.id in wanted]
            if group and mine:
                await self._send(group, self.history("catchup", mine, after_id=min(wanted) - 1))

    def shared(self, ids: Any) -> list[SharedMeta]:
        """Ce qu'on peut montrer des fichiers qu'elle envoie (ADR 0062) ; un port qui ne sait pas le dire, ou qui
        échoue, n'empêche jamais une livraison : le message part sans eux."""
        getter = getattr(self.port, "shared", None)
        wanted = tuple(i for i in (ids or ()) if isinstance(i, str))
        if getter is None or not wanted:
            return []
        try:
            return list(getter(wanted))
        except Exception as exc:  # le message part quand même : le fichier se retrouvera par le fil
            log.warning("fichiers envoyés illisibles (%s) : %r", ", ".join(wanted), exc)
            return []

    def history(self, mode: str, rows: Any, *, life: str | None = None, **kw: Any) -> dict[str, Any]:
        """Une trame ``history`` : l'empreinte de sa vie, et ce qu'on peut montrer des fichiers qu'elle a envoyés
        avec ses messages de ce morceau du fil."""
        ids = [i for r in rows if r.role == "assistant" for i in protocol.sent_ids(r.attachments)]
        shared = {m.id: m for m in self.shared(ids)}
        return protocol.history(mode, rows, life=self.life() if life is None else life, shared=shared, **kw)

    def life(self) -> str:
        """L'empreinte de sa vie, jointe à chaque trame ``history`` (vide si le port ne la connaît pas)."""
        try:
            return self.port.life()
        except Exception as exc:  # une empreinte illisible ne retient pas le fil : le client ne videra rien
            log.debug("empreinte de la vie illisible : %r", exc)
            return ""

    def _hold(self, handle: str, d: Delivery) -> None:
        """La réplique livrée devient la référence du visage pour ce qui suit."""
        blend = tuple(name for name, _w in d.emotion.blend)
        self._sent_face[handle] = (d.emotion.emotion, round(float(d.emotion.intensity), 2), blend)
        self._held[handle] = (d.emotion.emotion, self._monotonic() + REPLY_HOLD_S)

    async def settle_reply(self, handle: str, reply_to: int | None, client_msg_id: str | None, outcome: str,
                           detail: str = "") -> int:
        """Dit à l'écran ce qu'est devenue une question restée sans réponse — une fois
        par question, d'où que vienne la nouvelle (l'attente de la connexion, ou
        l'effet « réponse impossible » de la file de sortie)."""
        key: tuple[str, int | str] = (handle, reply_to if reply_to is not None else (client_msg_id or ""))
        if key in self._settled or not self.of(handle):
            return 0
        self._settled[key] = None
        while len(self._settled) > REMEMBERED:
            self._settled.popitem(last=False)
        face = self.face(handle)
        if outcome == protocol.ABSTAINED_OUTCOME:
            return await self.send_to(handle, protocol.silence(handle, face, user_message_id=reply_to,
                                                               client_msg_id=client_msg_id))
        if outcome not in protocol.FAILED_OUTCOMES:
            return 0
        sent = 0
        for c in self.of(handle):
            # la cause en clair et où la réparer : à une opératrice seulement (G-5) — les autres lisent « Mika n'a
            # pas pu répondre », jamais une consigne d'administration
            frames = protocol.reply_failed_frames(handle, outcome, detail, face, user_message_id=reply_to,
                                                  client_msg_id=client_msg_id,
                                                  operator=c.operator and c.authenticated)
            for frame in frames:
                sent += await self._send([c], frame)
        return sent

    async def refresh_panels(self, handles: list[str] | None = None) -> int:
        """Un état intérieur frais pour chaque connexion (avec son panneau)."""
        frame = self.port.frame()
        sent = 0
        wanted = sorted({c.handle for c in self.conns.values()}) if handles is None else handles
        for handle in wanted:
            conns = self.watching(handle)  # un écran que personne ne regarde n'a pas besoin du panneau
            if conns:
                sent += await self._send(conns, protocol.inner_state_update(frame, handle, self.panel(handle)))
        return sent

    def panel(self, handle: str) -> dict[str, Any] | None:
        getter = getattr(self.port, "person_panel", None)
        if getter is None:
            return None
        try:
            return getter(handle)
        except Exception as exc:  # le panneau ne doit jamais empêcher une livraison
            log.debug("panneau de %s : %r", handle, exc)
            return None

    # ── émotion entre deux tours ──
    def face(self, handle: str) -> affect_c.Face:
        frame = self.port.frame()
        return frame.get(affect_c.FACE(frame.get(identity_c.PERSON(handle))))

    async def push_face(self, handle: str, *, force: bool = False) -> bool:
        if not self.watching(handle):
            return False  # personne ne regarde : le visage partira quand un écran revient (``force``)
        face = self.face(handle)
        sig = protocol.face_signature(face)
        prev = self._sent_face.get(handle)
        if not force and prev is not None:
            moved = (sig[0] != prev[0] or sig[2] != prev[2] or abs(sig[1] - prev[1]) >= MIN_INTENSITY_DELTA)
            if not moved:
                return False
            held = self._held.get(handle)
            if held is not None:
                if self._monotonic() >= held[1]:
                    self._held.pop(handle, None)
                elif sig[0] != held[0]:
                    return False  # elle vient de dire « triste » : le visage ne passe pas à autre chose
        self._sent_face[handle] = sig
        await self._send(self.watching(handle), protocol.emotion_update(handle, face))
        return True

    def _pending_signature(self, frame: Any) -> tuple[int, ...]:
        try:
            return tuple(sorted(int(e.proposal) for e in frame.get(runtime_c.PENDING_EFFECTS)))
        except Exception as exc:  # un fait illisible ne fait pas tomber la synchro
            log.debug("actions en attente illisibles : %r", exc)
            return ()

    async def sync_once(self) -> int:
        pushed = 0
        for handle in sorted({c.handle for c in self.conns.values()}):
            if await self.push_face(handle):
                pushed += 1
        # la phase de sommeil change sans événement (les cycles de la nuit) ; une action peut se
        # mettre en attente d'accord n'importe quand : le panneau suit, chacun avec le sien
        frame = self.port.frame()
        phase = frame.get(body_c.SLEEP).value
        pending = self._pending_signature(frame)
        changed = phase != self._sent_phase or (self._sent_pending is not None and pending != self._sent_pending)
        self._sent_phase, self._sent_pending = phase, pending
        if self.conns and changed:
            await self.refresh_panels()
        return pushed

    async def run_sync(self, interval_s: float = SYNC_INTERVAL_S) -> None:
        while True:
            await asyncio.sleep(interval_s)
            try:
                await self.sync_once()
            except Exception as exc:  # la synchro ne doit jamais tomber
                log.warning("synchro d'émotion : %r", exc)

    def start(self) -> None:
        if self._sync_task is None:
            self._sync_task = asyncio.create_task(self.run_sync(), name="emotion-sync")

    async def stop(self) -> None:
        if self._sync_task is not None:
            self._sync_task.cancel()
            await asyncio.gather(self._sync_task, return_exceptions=True)
            self._sync_task = None

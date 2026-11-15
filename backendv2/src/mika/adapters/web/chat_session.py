"""Le dialogue de ``/ws`` : une connexion WebSocket du chat, de son ouverture à sa fermeture (``ChatSession``).

``create_app`` (``adapters/web/app.py``) l'accepte (une origine déclarée et sa session, ou le jeton d'un client natif
sans ``Origin``) puis la lui confie. Ses trames sont dans ``adapters/web/protocol.py``, qui reçoit quoi dans
``adapters/web/hub.py`` ; le protocole est décrit dans ``docs/protocole-chat.md``.

Une connexion WebSocket lit ses trames sans jamais attendre un message en
cours de traitement : le chat (et le prétraitement de ses pièces jointes)
avance dans une tâche à part, un message après l'autre ; pings, accusés et
rattrapages restent libres.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from mika.adapters.web import protocol
from mika.adapters.web.accounts import Account, Accounts
from mika.adapters.web.hub import Conn, Hub
from mika.contracts.entry import MindPort
from mika.contracts.presence import Connected
from mika.contracts.runtime import AttachmentMeta, PerceptionReceived
from mika.kernel.events import Content
from mika.ports.preprocess import Perceived, Preprocessor, Upload, render
from mika.vocab import privacy
from mika.vocab.people import clean_display_name, client_claim_allowed

log = logging.getLogger("mika.web")

#: au-delà, des messages attendent déjà leur tour sur cette connexion : refusé (« saturée »)
MAX_QUEUED_CHATS = 8


class ChatSession:
    """Une connexion WebSocket : son adresse, ses limites, son dialogue."""

    def __init__(self, websocket: WebSocket, port: MindPort, hub: Hub, account: Account | None,
                 preprocess: Preprocessor | None = None, *, accounts: Accounts | None = None,
                 session_key: str | None = None, channel: str = privacy.WEB, here: bool = True) -> None:
        self.ws = websocket
        self.port = port
        self.preprocess = preprocess
        self.hub = hub
        self.account = account
        self.accounts = accounts
        self.session_key = session_key
        self._lock = asyncio.Lock()
        #: un message à la fois, dans l'ordre (asyncio.Lock réveille dans l'ordre d'arrivée)
        self._chat_lock = asyncio.Lock()
        self._chats: set[asyncio.Future[Any]] = set()
        self._watchers: set[asyncio.Future[Any]] = set()
        self._closed = False
        #: le prochain rapprochement de la présence (aller : tout de suite ; partir : après la grâce)
        self._presence_task: asyncio.Future[Any] | None = None
        #: la prochaine écriture de ce qu'elle a lu, quand la fenêtre de ``PRESENCE_RATE`` est pleine
        self._read_task: asyncio.Future[Any] | None = None
        #: la prochaine écriture de la saisie, quand la fenêtre de ``COMPOSING_RATE`` est pleine ; et son plafond
        self._composing_task: asyncio.Future[Any] | None = None
        self._composing_cap: asyncio.Future[Any] | None = None
        kw: dict[str, Any] = {"session": session_key, "close": self.close, "valid": self._session_valid,
                              "channel": channel, "here": here}
        if account is not None:
            kw |= {"handle": account.handle, "authenticated": True, "account": account.id,
                   "operator": account.operator, "display_name": account.display_name}
        self.conn: Conn = hub.attach(self.send, **kw)

    async def send(self, frame: dict[str, Any]) -> None:
        async with self._lock:
            await self.ws.send_json(frame)

    async def close(self, code: int) -> None:
        """Fermée par le serveur (session révoquée) : le client lit 4401 et ne réessaie pas."""
        self._closed = True
        async with self._lock:
            await self.ws.close(code=code)

    async def _arrive(self) -> None:
        """Quelqu'un est là, devant cet écran : c'est ce que sa présence (et le journal) en savent."""
        c = self.conn
        await self.port.connected(Connected(
            handle=c.handle, channel=c.channel, connection=c.id, authenticated=c.authenticated, account=c.account,
            operator=c.operator, display_name=c.display_name,
        ))
        c.announced = True

    async def _depart(self) -> None:
        c = self.conn
        c.announced = False
        # partie, elle n'écrit plus : la déconnexion clôt aussi sa saisie au journal (``presence``)
        c.composing = c.composing_said = False
        self._uncap_composing()
        await self.port.disconnected(c.handle, c.id)

    async def _refresh(self) -> None:
        # l'état intérieur tout de suite (sommeil, énergie, et où elle est dans sa chambre) : sans lui, un
        # écran qui s'ouvre la montrait au milieu de la pièce jusqu'au prochain changement d'état
        await self.hub.push_face(self.conn.handle, force=True)
        await self.hub.refresh_panels([self.conn.handle])
        await self.hub.push_approvals([self.conn.handle], if_any=True)

    async def announce(self) -> None:
        """Un écran qui s'ouvre : la présence, le fil initial, le visage, le panneau."""
        c = self.conn
        await self._arrive()
        await self.send(self.hub.history("initial", self.port.recent(c.handle, protocol.HISTORY_INITIAL),
                                         verdicts=self._judges()))
        await self._refresh()
        if self._judges():
            # ses fils de travail (ADR 0164), après le visage et le panneau : l'ouverture garde son ordre
            await self.send(protocol.strands(self.port.strands(c.handle)))

    async def run(self) -> None:
        try:
            if self.account is not None and self.conn.here:
                await self.announce()
            # ouverte en arrière-plan (ADR 0062) : rien de non sollicité, le client demande ce qu'il a manqué (sync)
            while not self._closed:
                raw = await self.ws.receive_text()
                await self.dispatch(raw)
        except (WebSocketDisconnect, RuntimeError):
            pass  # RuntimeError : la socket fermée par le serveur (révocation) pendant une lecture
        finally:
            if self._presence_task is not None:
                self._presence_task.cancel()
            if self._read_task is not None:
                self._read_task.cancel()  # le client redit ce qu'il a lu à sa prochaine connexion
            self._uncap_composing()  # la déconnexion clôt la saisie au journal
            if self._composing_task is not None:
                self._composing_task.cancel()
            self.hub.detach(self.conn)
            if self.conn.announced:
                await self.port.disconnected(self.conn.handle, self.conn.id)

    # ── aller et venir (ADR 0062) ──
    async def presence(self, frame: dict[str, Any]) -> None:
        """``{"type": "presence", "here": bool}`` : l'application passe au premier plan, ou le quitte. Revenir vaut
        tout de suite ; partir, après ``AWAY_GRACE_S`` (une photo prise et l'on revient : rien au journal)."""
        here = frame.get("here")
        if not isinstance(here, bool) or self.account is None:
            return
        c = self.conn
        was = c.here
        c.here = here
        if here:
            if self._presence_task is not None:
                self._presence_task.cancel()
                self._presence_task = None
            await self._reconcile()
            if not was:
                await self._refresh()  # l'écran revient : un visage et un panneau frais
        else:
            self._reconcile_after(protocol.AWAY_GRACE_S)

    def _reconcile_after(self, delay: float) -> None:
        if self._presence_task is not None:
            self._presence_task.cancel()
        self._presence_task = asyncio.ensure_future(self._reconcile_later(delay))

    async def _reconcile_later(self, delay: float) -> None:
        await asyncio.sleep(delay)
        self._presence_task = None
        try:
            await self._reconcile()
        except (WebSocketDisconnect, RuntimeError, OSError) as exc:
            log.debug("présence non rapprochée (%s) : %r", self.conn.id, exc)

    async def _reconcile(self) -> None:
        """Le journal suit ce que veut la connexion (``here``), au plus ``PRESENCE_RATE`` fois : au-delà, l'état
        voulu s'applique quand la fenêtre le permet — jamais perdu, jamais une rafale."""
        c = self.conn
        if self._closed or c.here == c.announced:
            return
        if not c.presence.allow(self.hub._monotonic()):
            n, window = protocol.PRESENCE_RATE
            self._reconcile_after(window / n)
            return
        if c.here:
            await self._arrive()
        else:
            await self._depart()

    # ── ce qu'elle a lu (« Lui dire quand j'ai lu ») ──
    async def read(self, frame: dict[str, Any]) -> None:
        """``{"type": "read", "up_to": n}`` : la personne a lu son fil jusqu'au message ``n`` (son application le
        dit, si elle l'a permis). Une connexion authentifiée seulement ; un numéro qui n'est pas dans son fil, ou
        qui n'avance pas ce qu'on sait déjà de cette adresse, est ignoré. Seule la dernière valeur compte."""
        up_to = frame.get("up_to")
        c = self.conn
        if self.account is None or not c.authenticated or isinstance(up_to, bool) or not isinstance(up_to, int):
            return
        if up_to <= max(c.read_up_to, self.hub.read_up_to.get(c.handle, 0)):
            return
        head = self.port.recent(c.handle, 1)
        if not head or up_to > head[-1].id:
            return  # pas un message de son fil (un curseur d'une autre vie, un numéro inventé)
        c.read_up_to = up_to
        await self._write_read()

    def _write_read_after(self, delay: float) -> None:
        if self._read_task is not None:
            self._read_task.cancel()
        self._read_task = asyncio.ensure_future(self._write_read_later(delay))

    async def _write_read_later(self, delay: float) -> None:
        await asyncio.sleep(delay)
        self._read_task = None
        try:
            await self._write_read()
        except (WebSocketDisconnect, RuntimeError, OSError) as exc:
            log.debug("lecture non écrite (%s) : %r", self.conn.id, exc)

    async def _write_read(self) -> None:
        """Au journal, au plus ``PRESENCE_RATE`` fois : au-delà, la dernière valeur voulue s'écrit quand la
        fenêtre le permet — jamais une rafale."""
        c = self.conn
        if self._closed or c.read_up_to <= self.hub.read_up_to.get(c.handle, 0):
            return
        if not c.reads.allow(self.hub._monotonic()):
            n, window = protocol.PRESENCE_RATE
            self._write_read_after(window / n)
            return
        self.hub.read_up_to[c.handle] = c.read_up_to
        await self.port.read(c.handle, c.read_up_to)

    # ── où elle est (« Lui dire où je suis », ADR 0119) ──
    async def where(self, frame: dict[str, Any]) -> None:
        """``{"type": "where", "lat", "lon", "accuracy", "label", "age_ms"}`` : où est la personne, d'après son
        téléphone (l'application ouverte, si elle l'a permis) ; ``{"type": "where", "off": true}`` : elle ne le
        permet plus, sa dernière position s'efface. Une connexion authentifiée seulement ; une position invalide est
        ignorée, une position qui n'a pas bougé (même lieu, moins de ``WHERE_STILL_M``) ne se réécrit qu'au bout de
        ``WHERE_REFRESH_S`` ; au plus ``WHERE_RATE`` écritures (au-delà, la suivante passera)."""
        c = self.conn
        if self.account is None or not c.authenticated or not self._session_valid():
            return
        if frame.get("off") is True:
            self.hub.located.pop(c.handle, None)
            await self.port.unlocate(c.handle)
            return
        fix = protocol.where_fix(frame)
        if fix is None:
            return
        now = self.hub._monotonic()
        last = self.hub.located.get(c.handle)
        if last is not None and last[0].label == fix.label and now - last[1] < protocol.WHERE_REFRESH_S \
                and protocol.where_moved(last[0], fix) < protocol.WHERE_STILL_M:
            return
        if not c.places.allow(now):
            return
        self.hub.located[c.handle] = (fix, now)
        await self.port.locate(c.handle, lat=fix.lat, lon=fix.lon, accuracy_m=fix.accuracy_m, label=fix.label,
                               age_ms=fix.age_ms)

    # ── en train d'écrire ──
    async def composing(self, frame: dict[str, Any]) -> None:
        """``{"type": "composing", "on": bool}`` : la personne commence à écrire un message sur cet écran, ou cesse
        (tout effacé, quelques secondes sans frappe — l'envoi, lui, la clôt de lui-même). Une connexion authentifiée
        et présente seulement. Tant qu'elle écrit, la réponse à son message d'avant attend la suite. Au journal, le
        début et la fin, au plus ``COMPOSING_RATE`` fois ; et jamais au-delà de ``COMPOSING_MAX_S`` de saisie
        continue : l'adaptateur en écrit lui-même la fin."""
        on = frame.get("on")
        c = self.conn
        if not isinstance(on, bool) or self.account is None or not c.announced:
            return
        if on and not c.composing:
            self._uncap_composing()
            self._composing_cap = asyncio.ensure_future(self._composing_capped(protocol.COMPOSING_MAX_S))
        elif not on:
            self._uncap_composing()
        c.composing = on
        await self._write_composing()

    def _uncap_composing(self) -> None:
        if self._composing_cap is not None:
            self._composing_cap.cancel()
            self._composing_cap = None

    async def _composing_capped(self, delay: float) -> None:
        """Le plafond d'une saisie continue : elle n'attend plus la suite."""
        await asyncio.sleep(delay)
        self._composing_cap = None
        self.conn.composing = False
        await self._settle_composing()

    def _write_composing_after(self, delay: float) -> None:
        if self._composing_task is not None:
            self._composing_task.cancel()
        self._composing_task = asyncio.ensure_future(self._write_composing_later(delay))

    async def _write_composing_later(self, delay: float) -> None:
        await asyncio.sleep(delay)
        self._composing_task = None
        await self._settle_composing()

    async def _settle_composing(self) -> None:
        try:
            await self._write_composing()
        except (WebSocketDisconnect, RuntimeError, OSError) as exc:
            log.debug("saisie non écrite (%s) : %r", self.conn.id, exc)

    async def _write_composing(self) -> None:
        """Le journal suit ce que dit la connexion (``composing``), au plus ``COMPOSING_RATE`` fois : au-delà, l'état
        voulu s'écrit quand la fenêtre le permet — jamais une rafale."""
        c = self.conn
        if self._closed or not c.announced or c.composing == c.composing_said:
            return
        if not c.typing.allow(self.hub._monotonic()):
            n, window = protocol.COMPOSING_RATE
            self._write_composing_after(window / n)
            return
        c.composing_said = c.composing
        await self.port.composing(c.handle, c.id, c.composing)

    async def dispatch(self, raw: str) -> None:
        self.conn.seen_at = self.hub._monotonic()  # n'importe quelle trame prouve la vie, même illisible
        try:
            frame = json.loads(raw)
        except ValueError:
            return
        if not isinstance(frame, dict):
            return
        kind = frame.get("type")
        if kind == "ping":
            await self.send({"type": "pong", "t": frame.get("t")})
        elif kind == "identify":
            if self.conn.control.allow():
                await self.identify(frame)
        elif kind == "sync":
            if self.conn.control.allow():
                await self.sync(frame)
        elif kind == "presence":
            await self.presence(frame)
        elif kind == "composing":
            await self.composing(frame)
        elif kind == "read":
            if self.conn.control.allow():
                await self.read(frame)
        elif kind == "where":
            if self.conn.control.allow():
                await self.where(frame)
        elif kind == "approval":
            if self.conn.control.allow():
                await self.approval(frame)
        elif kind == "verdict":
            if self.conn.control.allow():
                await self.verdict(frame)
        elif kind == "strand":
            if self.conn.control.allow():
                await self.set_strand(frame)
        elif kind == "strand_history":
            if self.conn.control.allow():
                await self.strand_history(frame)
        elif kind == "chat":
            self.enqueue_chat(frame)

    async def approval(self, frame: dict[str, Any]) -> None:
        """Une carte d'accord décidée (ADR 0064) : par la personne à qui elle est adressée, connectée et
        authentifiée, telle qu'elle était montrée (``digest``). La réponse dit le sort ; la liste suit."""
        try:
            proposal = int(frame.get("id"))
        except (TypeError, ValueError):
            return
        decision = frame.get("decision")
        if decision not in ("accept", "refuse"):
            return
        if not self.conn.authenticated or self.account is None or not self._session_valid():
            await self.send({"type": "approval_result", "id": proposal, "status": "forbidden"})
            return
        status = await self.port.decide_card(self.conn.handle, proposal, decision == "accept",
                                             str(frame.get("digest") or "")[:128])
        await self.send({"type": "approval_result", "id": proposal, "status": status})
        await self.hub.push_approvals([self.conn.handle])
        await self.hub.refresh_panels()

    async def set_strand(self, frame: dict[str, Any]) -> None:
        """Un fil de travail réglé depuis le chat (ADR 0164) : son titre, sa petite description, archivé ou non — le
        réglage entier. Par une opératrice connectée et authentifiée, pour ses propres fils. La réponse dit le sort ;
        la liste suit, à tous ses écrans."""
        strand = protocol.strand_id(frame.get("id"))
        if strand is None:
            return
        reply = {"type": "strand_result", "id": strand}
        if not self._judges() or self.account is None or not self._session_valid():
            await self.send(reply | {"status": "forbidden"})
            return
        title, description = frame.get("title"), frame.get("description")
        status = await self.port.set_strand(self.conn.handle, strand, title=title if isinstance(title, str) else "",
                                            description=description if isinstance(description, str) else "",
                                            archived=frame.get("archived") is True)
        await self.send(reply | {"status": status})
        if status == "ok":
            await self.hub.push_strands(self.conn.handle)

    async def strand_history(self, frame: dict[str, Any]) -> None:
        """Les messages d'un fil, pour un écran qui les relit : les plus récents avant ``before`` (tous s'il est
        absent). ``id`` vide : le fil avec elle, sa propre conversation, pour toute connexion authentifiée (ADR 0215) ;
        sinon un de ses fils de travail (ADR 0164), pour une opératrice authentifiée seulement. Toujours celui de
        cette connexion : le compte vient de la session, jamais de la trame."""
        raw = frame.get("id")
        main = raw == ""
        strand = "" if main else protocol.strand_id(raw)
        allowed = self.conn.authenticated and self.account is not None if main else self._judges()
        if strand is None or not allowed or not self._session_valid():
            return
        try:
            before = int(frame["before"]) if frame.get("before") is not None else None
        except (TypeError, ValueError):
            before = None
        rows, more = self.port.strand_history(self.conn.handle, strand, before, protocol.HISTORY_MAX)
        await self.send(self.hub.history("strand", rows, life=self.hub.life(), verdicts=self._judges())
                        | {"strand": strand, "more": more})

    def _judges(self) -> bool:
        """Une connexion d'opératrice, authentifiée : elle voit et donne son avis sur ses réponses (ADR 0113)."""
        return bool(self.conn.operator and self.conn.authenticated)

    async def verdict(self, frame: dict[str, Any]) -> None:
        """Une de ses réponses jugée depuis le chat (ADR 0113) : par une opératrice connectée et authentifiée
        seulement — ``verdict`` ``ok``, ``ko``, ou vide pour retirer l'avis ; ``comment`` : ce qu'elle aurait dû
        dire, ou pourquoi. La réponse dit le sort (``ok``, ``forbidden``, ``invalid``, ``failed``)."""
        try:
            seq = int(frame.get("message_id"))
        except (TypeError, ValueError):
            return
        verdict = frame.get("verdict") or ""
        if verdict not in ("ok", "ko", ""):
            return
        comment = str(frame.get("comment") or "")[:2000]
        reply = {"type": "verdict_result", "message_id": seq, "verdict": verdict}
        if not self._judges() or self.account is None or not self._session_valid():
            await self.send({**reply, "status": "forbidden"})
            return
        status = await self.port.judge(self.conn.handle, seq, verdict, comment)
        await self.send({**reply, "status": status, "comment": comment if status == "ok" else ""})

    def enqueue_chat(self, frame: dict[str, Any]) -> None:
        """Le chat avance dans sa propre tâche : la lecture des trames continue pendant
        qu'une pièce jointe se décrit (le client, sans pong, se reconnecterait). Ce qui attend
        devant lui se compte ici, à la réception : une rafale lue d'un trait crée toutes ses
        tâches avant qu'aucune ne démarre, et chacune, comptée à son premier pas, voyait la
        rafale entière — tous refusés, pas seulement les derniers."""
        # le message envoyé clôt la saisie : sa perception la clôt au journal, sans rien écrire de plus
        self.conn.composing = False
        self._uncap_composing()
        ahead = len(self._chats)
        task = asyncio.ensure_future(self._chat_in_turn(frame, ahead))
        self._chats.add(task)
        task.add_done_callback(self._chats.discard)

    async def _chat_in_turn(self, frame: dict[str, Any], ahead: int) -> None:
        cid = str(frame.get("client_msg_id") or "")[: protocol.MAX_CLIENT_MSG_ID]
        if ahead >= MAX_QUEUED_CHATS:
            await self._safe_send(protocol.ack(cid, "overloaded"))
            await self._settle_composing()  # refusé : la fin de sa saisie s'écrit
            return
        async with self._chat_lock:
            try:
                await self.chat(frame)
            except (WebSocketDisconnect, RuntimeError, OSError) as exc:  # la connexion est partie en route
                log.debug("message non accusé (%s) : %r", self.conn.id, exc)
        # refusé, la fin de sa saisie s'écrit ; reçu pendant qu'elle écrivait déjà la suite, son début
        await self._settle_composing()

    async def _safe_send(self, frame: dict[str, Any]) -> None:
        try:
            await self.send(frame)
        except (WebSocketDisconnect, RuntimeError, OSError) as exc:
            log.debug("envoi impossible sur %s : %r", self.conn.id, exc)

    async def identify(self, frame: dict[str, Any]) -> None:
        c = self.conn
        if c.authenticated:
            return  # la session fait foi : l'indice du client est ignoré
        wanted = frame.get("person_id")
        name = clean_display_name(frame.get("display_name"))
        if not isinstance(wanted, str) or not client_claim_allowed(wanted):
            if not c.announced:
                await self.announce()
            return
        if wanted != c.handle or not c.announced or name != c.display_name:
            # une autre adresse, ou un nouveau nom (le client renvoie identify quand on le change)
            if c.announced:
                await self.port.disconnected(c.handle, c.id)
                c.announced = False
            c.handle = wanted
            c.display_name = name
            await self.announce()

    async def sync(self, frame: dict[str, Any]) -> None:
        c = self.conn
        if not self._session_valid():  # avant tout historique : un identifiant qui ne vaut plus ne relit pas le fil
            await self.hub.revoke(session=self.session_key)
            return
        if not c.announced and c.here and self.account is None:
            await self.announce()
        try:
            after_id = max(0, int(frame.get("after_id") or 0))
        except (TypeError, ValueError):
            after_id = 0
        life = self.hub.life()
        if after_id:
            head = self.port.recent(c.handle, 1)
            if after_id > (head[-1].id if head else 0):
                # un curseur venu d'ailleurs (une vie restaurée plus ancienne, un fil oublié) : un
                # « rattrapage » vide le laisserait cacher tout ce qui est plus petit que lui — le fil initial
                # remplace ce que l'écran montre
                rows = self.port.recent(c.handle, protocol.HISTORY_INITIAL)
                await self.send(self.hub.history("initial", rows, life=life, reset=True, verdicts=self._judges()))
                return
            rows, truncated = self.port.after(c.handle, after_id, protocol.HISTORY_MAX)
        else:
            rows, truncated = self.port.recent(c.handle, protocol.HISTORY_INITIAL), False
        await self.send(self.hub.history("catchup", rows, after_id=after_id, truncated=truncated, life=life,
                                         verdicts=self._judges()))

    def _session_valid(self) -> bool:
        """Revérifiée à chaque message, avant chaque rattrapage, et par le concentrateur à chaque
        ``CREDENTIAL_CHECK_S`` : une session effacée ailleurs (un autre processus, une expiration), un
        jeton révoqué (``mika token revoke``) ou des droits changés ne parlent plus, ne relisent plus le
        fil, ne reçoivent plus rien — la règle de ``/ws/world`` (``Accounts.still_valid``)."""
        if self.session_key is None or self.accounts is None:
            return True
        return self.accounts.still_valid(self.session_key, operator=self.conn.operator)

    async def chat(self, frame: dict[str, Any]) -> None:
        c = self.conn
        cid = str(frame.get("client_msg_id") or "")[: protocol.MAX_CLIENT_MSG_ID]
        if not self._session_valid():
            await self.hub.revoke(session=self.session_key)
            return
        if not c.chat.allow():
            await self.send(protocol.ack(cid, "rate_limited"))
            return
        if not c.announced and c.here and self.account is None:
            await self.announce()
        message = frame.get("message")
        text = message.strip() if isinstance(message, str) else ""
        kept, rejected = protocol.validate_attachments(frame.get("attachments"))
        if len(text) > protocol.MAX_MESSAGE_CHARS:
            await self.send(protocol.ack(cid, "too_long"))
            return
        if not text and not kept:
            await self.send(protocol.ack(cid, "attachments_rejected" if rejected else "empty", rejected))
            return
        self.hub.note_asked(c, cid)
        seen = await self._perceive(kept)
        # ses octets gardés avant que le message n'entre dans sa vie : il les désigne (ADR 0106)
        files = await self.port.keep_attachments(c.handle, [a.data for a in kept]) if kept else []
        body = "\n".join(x for x in [text, render(seen)] if x).strip()
        mode = protocol.chat_mode(frame.get("mode")) if self._judges() else ""
        perception = PerceptionReceived(
            handle=c.handle, channel=c.channel, text=Content.of(body), authenticated=c.authenticated,
            client_msg_id=cid or None, display_name=c.display_name,
            # le mode pro (ADR 0116) : demandé par une opératrice seulement ; ailleurs, la conversation ordinaire
            mode=mode,
            # son fil de travail (ADR 0164) : seulement en mode pro
            strand=protocol.strand_id(frame.get("strand")) if mode else None,
            # ce qu'elle a tapé est le début du texte ; la suite, ce que ses pièces jointes ont donné à percevoir
            # (pour le prompt) — le fil relu ne montre que le premier, et les fichiers par leur nom (G-6)
            typed_chars=len(text) if seen else None,
            attachments=tuple(AttachmentMeta(name=a.name, kind=a.kind, mime=a.mime, extracted=p.extracted,
                                             error=p.error, file=f)
                              for a, p, f in zip(kept, seen, files, strict=True)),
        )
        admission = await self.port.perceive(perception, dedupe_key=f"{c.handle}:{cid}" if cid else None)
        if admission.status == "accepted" and not admission.duplicate:
            c.composing_said = False  # sa perception a clos la saisie au journal (``presence``)
        await self.send(protocol.ack(cid, admission.status, rejected))
        if perception.strand is not None and admission.status == "accepted" and not admission.duplicate:
            await self.hub.push_strands(c.handle)  # un fil ouvert, ou qui avance (ADR 0164)
        if admission.held:
            # elle dort : la réponse attend son réveil — « Mika écrit… » ne tourne pas pendant sa nuit
            await self.send(protocol.silence(c.handle, self.hub.face(c.handle), user_message_id=admission.seq,
                                             client_msg_id=cid or None, reason=protocol.ASLEEP))
        if admission.reply is not None:
            task = asyncio.ensure_future(self._watch(admission, cid or None))
            self._watchers.add(task)
            task.add_done_callback(self._watchers.discard)

    async def _perceive(self, kept: list[Any]) -> list[Perceived]:
        """Ce qu'elle perçoit des pièces jointes, au bord (avant d'entrer dans sa vie)."""
        if not kept:
            return []
        if self.preprocess is None:
            return [Perceived(a.name, a.kind, "reçu, mais je ne peux pas encore le lire", False) for a in kept]
        return await self.preprocess.perceive([Upload(a.name, a.mime, a.data) for a in kept])

    async def _watch(self, admission: Any, cid: str | None) -> None:
        """Si la réponse échoue ou qu'elle choisit de se taire, la personne l'apprend
        (sinon « Mika écrit… » tourne pour rien)."""
        try:
            report = await admission.reply
        except Exception as exc:  # l'épisode a levé : même effet qu'un échec
            report = None
            detail = repr(exc)
        else:
            detail = str(getattr(report, "detail", ""))
        outcome = str(getattr(report, "outcome", "failed")) if report is not None else "failed"
        if outcome in protocol.FAILED_OUTCOMES or outcome == protocol.ABSTAINED_OUTCOME:
            await self.hub.settle_reply(self.conn.handle, admission.seq, cid, outcome, detail)

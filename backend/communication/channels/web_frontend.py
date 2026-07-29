"""WebSocket channel — direct browser/frontend connection.

Builds `Perception`s and routes them through `pipeline.router.perceive()`.
No longer calls `process_message` directly.

Identity (owned consumer): a backend-authenticated Django user is trusted and
yields ``user_{pk}`` — the client CANNOT override it. An unauthenticated
connection gets a connection-scoped ``anon_*`` id and may declare a persistent
id via the ``identify`` handshake (sanitized, never a reserved server-side
prefix). Set ``CONSUMER_REQUIRE_AUTH`` to refuse unauthenticated connections.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid

from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

from communication import history
from communication.presence import person_group, presence_registry
from pipeline.media import validate_attachments
from pipeline.perception import Intent, Perception
from pipeline.turns import turn_queue

logger = logging.getLogger(__name__)

BROADCAST_GROUP = "vtuber_broadcast"
MAX_MESSAGE_LENGTH = 2000
MAX_PERSON_ID_LENGTH = 64
MAX_CLIENT_MSG_ID_LENGTH = 64

# person_id prefixes owned by trusted server-side channels — a browser client
# must not be able to impersonate them (they index per-person mood + memory).
# "user_" is reserved for backend-authenticated identities.
RESERVED_PERSON_PREFIXES = ("tg_", "module_", "conscience", "user_")
_PERSON_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Simple per-connection rate limit (sliding window).
RATE_LIMIT_MAX_MESSAGES = 20
RATE_LIMIT_WINDOW_SECONDS = 10.0

# Control frames are cheap to send and not free to serve: a `sync` runs a
# query over a table six background loops write to, and an `identify`
# re-persists the handle. They were unlimited because only `chat` was
# rate-limited, which reads as "the expensive frames are the ones with
# words in them" — not true here.
RATE_LIMIT_MAX_CONTROL = 12

# How long a person stays "already greeted". `_greeted` is per *connection*,
# so every reconnect — a laptop waking, a proxy reaping an idle socket, the
# client's own liveness watchdog — used to spend a full LLM turn on another
# hello, persist it, and hold the single turn worker while a real question
# waited behind it. Greeting is a property of the person and the moment, not
# of the socket that happens to be carrying them.
GREETING_COOLDOWN_SECONDS = 3600.0

# person_id -> monotonic time of the last greeting scheduled for them.
# Process-local and deliberately not persisted: after a restart Mika has
# genuinely just come back, and saying hello is the right move.
_last_greeted: dict[str, float] = {}

# Above this many tracked persons, drop the entries the cooldown no longer
# protects. One `web_*` id per browser means a public install accumulates
# them for the life of the process, and an entry older than the cooldown
# answers nothing — the next greeting is allowed either way.
_GREETED_MAX_TRACKED = 500


def _prune_greeted(now: float) -> None:
    if len(_last_greeted) <= _GREETED_MAX_TRACKED:
        return
    cutoff = now - GREETING_COOLDOWN_SECONDS
    for person_id in [p for p, t in _last_greeted.items() if t < cutoff]:
        _last_greeted.pop(person_id, None)


def _sanitize_person_id(raw, fallback: str) -> str:
    """Validate a client-supplied person_id, falling back when untrusted.

    Rejects bad types, over-long ids, non-alphanumeric content, and any
    attempt to claim a reserved server-side prefix.
    """
    if not isinstance(raw, str):
        return fallback
    raw = raw.strip()
    if not raw or len(raw) > MAX_PERSON_ID_LENGTH:
        return fallback
    if not _PERSON_ID_RE.match(raw):
        return fallback
    if raw.startswith(RESERVED_PERSON_PREFIXES):
        logger.warning("Rejected client attempt to use reserved person_id %r", raw)
        return fallback
    return raw


def _sanitize_client_msg_id(raw) -> str | None:
    """Bound a client-generated correlation id.

    It is never stored, never indexed and never trusted — only echoed back
    to the browser that minted it — so the only requirement is that it
    cannot be used to inflate a frame.
    """
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None
    return raw[:MAX_CLIENT_MSG_ID_LENGTH]


class WebSocketConsumer(AsyncWebsocketConsumer):
    """WebSocket channel — handles browser/frontend connections to the VTuber."""

    # Safe defaults so the consumer stays coherent even if a frame is handled
    # before connect() finished initializing the instance.
    authenticated = False
    display_name: str | None = None
    _greeted = False
    # Immutable default: _is_rate_limited() rebinds it to a fresh instance list.
    _msg_timestamps: tuple[float, ...] | list[float] = ()
    _control_timestamps: tuple[float, ...] | list[float] = ()
    _group: str = ""
    _state_sent = False

    async def connect(self):
        # Identity: a backend-authenticated user is trusted and CANNOT be
        # overridden by the client. Otherwise fall back to a connection-scoped
        # anonymous id (never client-chosen).
        self.authenticated = False
        self.display_name: str | None = None
        self._greeted = False
        self._msg_timestamps: list[float] = []
        self._control_timestamps: list[float] = []
        self._state_sent = False

        auth_id = self._authenticated_person_id()
        if auth_id:
            self.person_id = auth_id
            self.authenticated = True
            self.display_name = self._auth_display_name() or None
        elif getattr(settings, "CONSUMER_REQUIRE_AUTH", False):
            # Owned client must authenticate when the policy demands it.
            await self.close(code=4401)
            return
        else:
            self.person_id = "anon_" + uuid.uuid4().hex[:8]

        self._group = person_group(self.person_id)

        # Join the legacy broadcast group (proactive messages with no resolved
        # recipient) AND this person's own group (targeted delivery).
        await self.channel_layer.group_add(BROADCAST_GROUP, self.channel_name)
        await self.channel_layer.group_add(self._group, self.channel_name)
        await self.accept()

        await self._register_presence()

        # Hand over the conversation before anything slow runs. A client
        # opens with an empty thread (or a stale localStorage one) and has
        # no other way to learn what it missed while it was away.
        #
        # Deferred for a not-yet-identified anonymous socket: `anon_*` is a
        # fresh uuid minted seconds ago, so it *cannot* have a history, and
        # reading its mood would create a PAD oscillator for an id that the
        # identify handshake is about to throw away. `_handle_identify`
        # sends it for real once we know who this is.
        if not self.person_id.startswith("anon_"):
            await self._send_initial_state()

        # An authenticated user has a stable identity already; greet now.
        # Anonymous clients defer the greeting to the identify handshake or the
        # first chat turn, so the greeting uses their persistent id.
        #
        # The memory Entity is created by _register_presence() above, through
        # bind_authenticated() — a proven session is exactly the case where
        # Mika may know who this is without being convinced first.
        if self.authenticated:
            self._schedule_greeting()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(BROADCAST_GROUP, self.channel_name)
        group = getattr(self, "_group", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)
        person_id = getattr(self, "person_id", None)
        if person_id:
            # Scoped to *this* socket. The registry is keyed per person, so
            # an unconditional removal took the presence of every other tab
            # with it — and worse, a reconnect's replacement socket had
            # usually already registered by the time this ran, so the dying
            # one erased its successor and the person went silently
            # undeliverable on a perfectly live connection.
            presence_registry.unregister(
                person_id, "web", connection_id=self.channel_name,
            )
            # Drop the "already told them this" memo so a reconnecting client
            # is resynced on the next tick instead of waiting for a mood that
            # may already be exactly where it was. The sync loop prunes on
            # its own cadence; doing it here makes it deterministic rather
            # than dependent on which happens first.
            #
            # Only when nobody is left: forgetting while another tab is still
            # connected would push it a redundant frame on the next tick.
            if presence_registry.resolve_on(person_id, "web") is None:
                try:
                    from emotion.sync import emotion_sync

                    emotion_sync.forget(person_id)
                except Exception:
                    logger.debug("emotion sync forget failed", exc_info=True)

    # --- Identity helpers ---

    def _authenticated_person_id(self) -> str | None:
        """Derive a trusted person_id from the authenticated Django user."""
        user = self.scope.get("user")
        if user is not None and getattr(user, "is_authenticated", False):
            return f"user_{user.pk}"
        return None

    def _auth_display_name(self) -> str:
        user = self.scope.get("user")
        if user is not None and getattr(user, "is_authenticated", False):
            return getattr(user, "username", "") or ""
        return ""

    async def _register_presence(self) -> None:
        """Register runtime presence + persist the handle so this person is
        reachable (targeted delivery) and known across sessions.

        Anonymous per-connection ids are marked ephemeral: they represent a
        socket, not a person, and every reconnect mints a new one. Without
        the flag they accumulated forever — an install with zero messages
        had already collected 68 of them.
        """
        from identity.resolver import identity_resolver
        from identity.trust import ChannelTrust

        presence_registry.register(
            person_id=self.person_id,
            channel="web",
            kind="consumer",
            delivery_ref=self._group,
            display_name=self.display_name or "",
            connection_id=self.channel_name,
        )
        ephemeral = self.person_id.startswith("anon_")
        await identity_resolver.link_handle(
            person_id=self.person_id,
            channel="web",
            kind="consumer",
            delivery_ref=self._group,
            display_name=self.display_name or "",
            trust=(
                ChannelTrust.AUTHENTICATED if self.authenticated
                else ChannelTrust.PUBLIC
            ),
            ephemeral=ephemeral,
        )
        # An authenticated session *proves* who this is. Bind the handle to a
        # memory Entity right away so the theory-of-mind layer (profile,
        # commitments, shared history) resolves from the first turn instead
        # of waiting for a name to be claimed and believed.
        if self.authenticated:
            await identity_resolver.bind_authenticated(
                person_id=self.person_id,
                channel="web",
                entity_name=self.display_name or self.person_id,
            )

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data)
        except (json.JSONDecodeError, TypeError):
            return

        msg_type = data.get("type")

        if msg_type == "identify":
            # Handshake: an anonymous client declares its persistent identity.
            # Authenticated users keep their trusted id and ignore the claim.
            if self._is_control_flooding():
                return
            await self._handle_identify(data)
            return

        if msg_type == "ping":
            # Application-level keepalive. The browser cannot send or observe
            # protocol-level ping/pong frames, so a socket that died without
            # a FIN — the laptop that slept, the proxy that reaped an idle
            # connection — stays `readyState === OPEN` on the client and
            # silently swallows everything sent through it. Answering here is
            # what lets the client notice and reconnect.
            await self._send_frame({"type": "pong", "t": data.get("t")})
            return

        if msg_type == "sync":
            if self._is_control_flooding():
                return
            await self._handle_sync(data)
            return

        if msg_type != "chat":
            return

        client_msg_id = _sanitize_client_msg_id(data.get("client_msg_id"))

        if self._is_rate_limited():
            logger.warning("Rate limit hit for connection %s", self.person_id)
            # Said out loud rather than dropped. A silently discarded message
            # leaves the sender's bubble on screen looking delivered, with a
            # typing indicator that resolves only on a timeout — the exact
            # failure mode this protocol exists to remove.
            await self._send_ack(client_msg_id, "rate_limited")
            return

        # Defensive: if the client never sent identify, still produce the
        # greeting once on the first chat turn. Detached — an answer to what
        # was just typed must not queue behind a greeting's LLM call.
        if not self._greeted:
            self._schedule_greeting()

        message = data.get("message", "")
        raw_attachments = data.get("attachments", [])

        if not isinstance(message, str):
            message = ""
        has_attachments = (
            isinstance(raw_attachments, list) and len(raw_attachments) > 0
        )
        clean_message = message.strip()
        if not clean_message and not has_attachments:
            await self._send_ack(client_msg_id, "empty")
            return

        # Refused, not silently cut. Truncating left the browser showing the
        # full text it painted itself while the server held a shortened
        # version — two different sentences, one marked delivered, diverging
        # forever. Saying no lets the sender edit what they actually wrote.
        if len(clean_message) > MAX_MESSAGE_LENGTH:
            await self._send_ack(client_msg_id, "too_long")
            return

        # The connection's bound person_id is authoritative: authenticated ids
        # are trusted, anonymous ids were sanitized at connect/identify time.
        person_id = self.person_id

        # Validated *before* the ack. The empty-message guard above tests the
        # raw list, so three oversized files with no caption used to pass it,
        # come back as zero valid attachments, and send an empty perception
        # into the pipeline: the model was handed "User: " and answered
        # nothing, while the sender had been told "accepted" and never
        # learned their files had been dropped.
        attachments = (
            validate_attachments(raw_attachments) if has_attachments else None
        )
        if has_attachments and not attachments and not clean_message:
            await self._send_ack(client_msg_id, "attachments_rejected")
            return

        # The identity layer needs to know this turn arrived on a verified
        # session — that is what makes the web the one channel where Mika is
        # certain who she is talking to.
        meta = {"authenticated": self.authenticated, "channel": "web"}
        if client_msg_id:
            # Echoed back on the `speech` frame so the client can bind the
            # bubble it painted optimistically to the row that now exists,
            # instead of rendering it twice after the next history merge.
            meta["client_msg_id"] = client_msg_id

        if attachments:
            perception = Perception.from_mixed(
                text=clean_message,
                attachments=attachments,
                source="frontend",
                person_id=person_id,
                intent=Intent.REQUEST_RESPONSE,
                metadata=meta,
            )
        else:
            perception = Perception.from_text(
                clean_message,
                source="frontend",
                person_id=person_id,
                intent=Intent.REQUEST_RESPONSE,
                metadata=meta,
            )

        # Handed to the turn pool rather than awaited. Channels dispatches a
        # consumer's frames one at a time, so awaiting the pipeline here made
        # the connection deaf for the whole turn — no pong, no catch-up, no
        # next message — which is exactly when a client's liveness watchdog
        # decides the socket is dead and reconnects. The reply finds its way
        # back on its own: it is sent to the person's group, not to this
        # socket, and is recoverable by cursor if nobody is listening.
        #
        # Submitted before the ack, not after: acking first meant a refused
        # turn got "accepted" immediately followed by "overloaded" for the
        # same id. The client ended in the right state, but the first answer
        # was a claim we had not yet earned.
        accepted = turn_queue.submit(perception)
        await self._send_ack(
            client_msg_id, "accepted" if accepted else "overloaded",
        )

    async def _handle_identify(self, data: dict) -> None:
        """Bind an anonymous consumer to the client's persistent identity + greet."""
        claimed_id = data.get("person_id")
        display = data.get("display_name")

        # Authenticated users are already trusted — ignore identity claims, but
        # still accept a display_name hint for the greeting.
        rebound = False
        if not self.authenticated:
            new_id = _sanitize_person_id(claimed_id, fallback=self.person_id)
            if new_id != self.person_id:
                await self._rebind_person(new_id)
                rebound = True
        if isinstance(display, str) and display.strip():
            self.display_name = display.strip()[:80]

        # No Entity is created here any more. A memory person-Entity means "a
        # person Mika knows"; minting one per connection filled the table with
        # handles (web_6f3e22ccb0ae) that no souvenir would ever reference,
        # while the consolidator created the *real* entity under the person's
        # actual name — two rows for one person, joined by nothing. The entity
        # is now created exactly when an identity is established: on
        # authentication, or when Mika accepts a claim.
        await self._refresh_handle()

        logger.info(
            "WS identify: person_id=%s display=%s channel=%s",
            self.person_id, self.display_name, self.channel_name,
        )

        if rebound or not self._state_sent:
            # Either the client just told us who it really is — the thread it
            # is owed is a different set of rows — or connect deferred the
            # handover because the socket was still anonymous. The second
            # case covers a claim we *refused* (a reserved prefix, a
            # malformed id): the connection stays anonymous, and it would
            # otherwise never be handed anything at all.
            await self._send_initial_state()

        if not self._greeted:
            self._schedule_greeting()

    async def _rebind_person(self, new_id: str) -> None:
        """Move the connection to a new (sanitized) person_id: swap the
        per-person group + presence handle so targeted delivery follows."""
        old_group = self._group
        old_id = self.person_id
        self.person_id = new_id
        self._group = person_group(new_id)
        if self._group != old_group:
            if old_group:
                await self.channel_layer.group_discard(old_group, self.channel_name)
            await self.channel_layer.group_add(self._group, self.channel_name)
        presence_registry.unregister(
            old_id, "web", connection_id=self.channel_name,
        )
        await self._register_presence()

    # --- Synchronisation protocol ---

    async def _send_frame(self, payload: dict) -> None:
        """Send one JSON frame, tolerating a socket that just went away.

        Every writer below goes through here. A client disconnecting between
        a read and its answer is ordinary, not exceptional, and it must not
        surface as a traceback from a background task nobody supervises.
        """
        try:
            await self.send(text_data=json.dumps(payload, ensure_ascii=False))
        except Exception:
            logger.debug(
                "WS send failed for %s (socket closed?)",
                getattr(self, "person_id", "?"), exc_info=True,
            )

    async def _send_ack(self, client_msg_id: str | None, status: str) -> None:
        """Tell the client what became of the frame it just sent.

        Skipped entirely when the client did not label its message: an ack
        with nothing to match it against is noise on the wire.
        """
        if not client_msg_id:
            return
        await self._send_frame({
            "type": "ack",
            "client_msg_id": client_msg_id,
            "status": status,
        })

    async def _send_initial_state(self) -> None:
        """Hand over the thread and the current mood, once per connection.

        A client opens with an empty thread (or a stale localStorage one)
        and has no other way to learn what it missed while it was away.
        ``_state_sent`` exists so the anonymous deferral above can never
        end in a connection that was handed nothing.
        """
        self._state_sent = True
        await self._send_history(mode="initial")
        await self._push_emotion_now()

    async def _send_history(self, *, mode: str, after_id: int | None = None) -> None:
        """Ship the conversation, or the part of it the client is missing.

        ``after_id`` is the client's cursor — the highest ``Message.pk`` it
        has actually rendered. ``None`` (or 0) means "I have nothing
        trustworthy", which is the honest answer after a cache clear or a
        first visit, and gets the recent window instead of a diff.
        """
        person_id = getattr(self, "person_id", "")
        try:
            if after_id:
                messages, truncated = await history.after_for(person_id, after_id)
            else:
                messages = await history.recent_for(person_id)
                # A first load is a window by construction, not a gap: the
                # client asked for "the tail", and got exactly that.
                truncated = False
        except Exception:
            # History is a convenience, never a precondition for talking.
            # A client that cannot be caught up should still be able to
            # start a new turn.
            logger.exception("History read failed for %s", person_id)
            return

        await self._send_frame({
            "type": "history",
            "mode": mode,
            "messages": messages,
            "last_id": messages[-1]["id"] if messages else (after_id or 0),
            "truncated": truncated,
        })

    async def _handle_sync(self, data: dict) -> None:
        """Answer a client's catch-up request."""
        raw = data.get("after_id")
        try:
            after_id = int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            after_id = 0
        await self._send_history(mode="catchup", after_id=max(0, after_id))

    async def _push_emotion_now(self) -> None:
        """Send the current mood immediately, without waiting for the loop.

        ``emotion.sync`` only emits when the state *moved*, so a client that
        reconnects into a calm moment could sit on a stale face for minutes.
        The mood is part of the state being synchronised, exactly like the
        messages.
        """
        try:
            from emotion.sync import emotion_sync
            from pipeline.broadcast import broadcast_emotion_update

            await broadcast_emotion_update(self.person_id, group=self._group)
            # Tell the loop what we just sent, or it counts this person as
            # never-synced and repeats the identical state within one tick.
            emotion_sync.note_pushed(self.person_id)
        except Exception:
            logger.debug("initial emotion push failed", exc_info=True)

    def _schedule_greeting(self) -> None:
        """Queue the greeting turn instead of awaiting it.

        Channels serialises a consumer's handlers: awaiting the greeting
        inside ``connect()`` meant the whole LLM call — up to
        ``ai.call_timeout_seconds`` — ran before the first inbound frame
        could even be read. On a slow local model that is a browser that
        connects, shows nothing, and swallows the first thing you type
        until the greeting finally times out.

        It goes through the same queue as a chat turn rather than its own
        task, so a greeting and the first message the person types are
        answered in order and never become two concurrent LLM calls.

        Rate-limited per *person*, not per socket. ``_greeted`` only knows
        about this connection, and connections are cheap: a laptop waking,
        a proxy reaping an idle socket, the client's own watchdog. Each one
        used to buy a full LLM turn, a persisted greeting, and the single
        turn worker held while a real question queued behind it — so coming
        back to a tab meant being greeted again.
        """
        if self._greeted:
            return
        now = time.monotonic()
        last = _last_greeted.get(self.person_id)
        if last is not None and now - last < GREETING_COOLDOWN_SECONDS:
            # Already said hello recently. Mark this connection as done so
            # the first chat turn does not try again either.
            self._greeted = True
            return
        # Flag set only once the pool has actually taken it: a refusal here
        # (backlog full) must not cost the person their greeting for the
        # rest of the connection.
        if turn_queue.submit(self._greeting_perception()):
            self._greeted = True
            _last_greeted[self.person_id] = now
            _prune_greeted(now)

    def _greeting_perception(self) -> Perception:
        """The initial greeting, as an INTERNAL_TRIGGER Perception."""
        from config.personality import personality

        recognized = (
            f" Tu reconnais cette personne: {self.display_name}."
            if self.display_name
            else ""
        )
        return Perception.from_internal_trigger(
            prompt=(
                f"Un visiteur vient de se connecter.{recognized} "
                f"Accueille-le avec ta phrase habituelle: {personality.greeting}"
            ),
            source="web_connect",
            person_id=self.person_id,
            metadata={
                "channel": self.channel_name,
                "display_name": self.display_name,
            },
        )

    async def _refresh_handle(self) -> None:
        """Re-persist the handle after identify, picking up the display name.

        Cheap and idempotent: ``link_handle`` upserts on (channel, person_id).
        Separate from ``_register_presence`` only because identify can arrive
        long after connect.
        """
        try:
            await self._register_presence()
        except Exception:
            logger.debug(
                "handle refresh failed for %s", self.person_id, exc_info=True,
            )

    def _is_rate_limited(self) -> bool:
        """Sliding-window rate limit: cap messages per connection."""
        now = time.monotonic()
        window_start = now - RATE_LIMIT_WINDOW_SECONDS
        self._msg_timestamps = [t for t in self._msg_timestamps if t >= window_start]
        if len(self._msg_timestamps) >= RATE_LIMIT_MAX_MESSAGES:
            return True
        self._msg_timestamps.append(now)
        return False

    def _is_control_flooding(self) -> bool:
        """Same window, applied to `sync` / `identify`.

        Neither is free: a catch-up queries a table six background loops
        write to, and an identify re-persists the handle. Only `chat` was
        capped, which amounted to charging for the frames that contain
        words. Dropped silently rather than acked — a control frame carries
        no ``client_msg_id``, so there is nothing to answer, and a client
        sending twelve syncs in ten seconds is not waiting on the twelfth.
        """
        now = time.monotonic()
        window_start = now - RATE_LIMIT_WINDOW_SECONDS
        self._control_timestamps = [
            t for t in self._control_timestamps if t >= window_start
        ]
        if len(self._control_timestamps) >= RATE_LIMIT_MAX_CONTROL:
            logger.warning(
                "Control-frame flood from %s — dropping", self.person_id,
            )
            return True
        self._control_timestamps.append(now)
        return False

    # --- Group message handler ---

    async def communication_broadcast(self, event):
        """Called when the broadcast group sends a message."""
        await self.send(text_data=json.dumps(event["data"], ensure_ascii=False))

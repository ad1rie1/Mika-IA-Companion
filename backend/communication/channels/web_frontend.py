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

from communication.presence import person_group, presence_registry
from pipeline.media import validate_attachments
from pipeline.perception import Intent, Perception
from pipeline.router import perceive

logger = logging.getLogger(__name__)

BROADCAST_GROUP = "vtuber_broadcast"
MAX_MESSAGE_LENGTH = 2000
MAX_PERSON_ID_LENGTH = 64

# person_id prefixes owned by trusted server-side channels — a browser client
# must not be able to impersonate them (they index per-person mood + memory).
# "user_" is reserved for backend-authenticated identities.
RESERVED_PERSON_PREFIXES = ("tg_", "module_", "conscience", "user_")
_PERSON_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Simple per-connection rate limit (sliding window).
RATE_LIMIT_MAX_MESSAGES = 20
RATE_LIMIT_WINDOW_SECONDS = 10.0


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


class WebSocketConsumer(AsyncWebsocketConsumer):
    """WebSocket channel — handles browser/frontend connections to the VTuber."""

    # Safe defaults so the consumer stays coherent even if a frame is handled
    # before connect() finished initializing the instance.
    authenticated = False
    display_name: str | None = None
    _greeted = False
    # Immutable default: _is_rate_limited() rebinds it to a fresh instance list.
    _msg_timestamps: tuple[float, ...] | list[float] = ()
    _group: str = ""

    async def connect(self):
        # Identity: a backend-authenticated user is trusted and CANNOT be
        # overridden by the client. Otherwise fall back to a connection-scoped
        # anonymous id (never client-chosen).
        self.authenticated = False
        self.display_name: str | None = None
        self._greeted = False
        self._msg_timestamps: list[float] = []

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

        # An authenticated user has a stable identity already; greet now.
        # Anonymous clients defer the greeting to the identify handshake or the
        # first chat turn, so the greeting uses their persistent id.
        if self.authenticated:
            await self._ensure_entity(self.person_id)
            await self._send_greeting()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(BROADCAST_GROUP, self.channel_name)
        group = getattr(self, "_group", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)
        person_id = getattr(self, "person_id", None)
        if person_id:
            presence_registry.unregister(person_id, "web")

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
            await self._handle_identify(data)
            return

        if msg_type != "chat":
            return

        if self._is_rate_limited():
            logger.warning("Rate limit hit for connection %s", self.person_id)
            return

        # Defensive: if the client never sent identify, still produce the
        # greeting once on the first chat turn.
        if not self._greeted:
            await self._send_greeting()

        message = data.get("message", "")
        raw_attachments = data.get("attachments", [])

        if not isinstance(message, str):
            message = ""
        has_attachments = (
            isinstance(raw_attachments, list) and len(raw_attachments) > 0
        )
        if not message.strip() and not has_attachments:
            return

        # The connection's bound person_id is authoritative: authenticated ids
        # are trusted, anonymous ids were sanitized at connect/identify time.
        person_id = self.person_id

        attachments = (
            validate_attachments(raw_attachments) if has_attachments else None
        )

        clean_message = message.strip()[:MAX_MESSAGE_LENGTH]

        # The identity layer needs to know this turn arrived on a verified
        # session — that is what makes the web the one channel where Mika is
        # certain who she is talking to.
        meta = {"authenticated": self.authenticated, "channel": "web"}

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

        await perceive(perception)

    async def _handle_identify(self, data: dict) -> None:
        """Bind an anonymous consumer to the client's persistent identity + greet."""
        claimed_id = data.get("person_id")
        display = data.get("display_name")

        # Authenticated users are already trusted — ignore identity claims, but
        # still accept a display_name hint for the greeting.
        if not self.authenticated:
            new_id = _sanitize_person_id(claimed_id, fallback=self.person_id)
            if new_id != self.person_id:
                await self._rebind_person(new_id)
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

        if not self._greeted:
            await self._send_greeting()

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
        presence_registry.unregister(old_id, "web")
        await self._register_presence()

    async def _send_greeting(self) -> None:
        """Produce the initial greeting as an INTERNAL_TRIGGER Perception."""
        from config.personality import personality

        self._greeted = True

        recognized = (
            f" Tu reconnais cette personne: {self.display_name}."
            if self.display_name
            else ""
        )
        greeting_perception = Perception.from_internal_trigger(
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
        await perceive(greeting_perception)

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

    # --- Group message handler ---

    async def communication_broadcast(self, event):
        """Called when the broadcast group sends a message."""
        await self.send(text_data=json.dumps(event["data"], ensure_ascii=False))

"""Teams (ADR 0069), côté application : la clé de l'extension et la porte de ``/api/teams/…``.

- *La clé* : générée ici (``mtk_…``), montrée une seule fois ; seule son empreinte est gardée (``Settings``). Une
  clé neuve rend l'ancienne inutile ; la retirer ferme la porte.
- *La porte* : ce que le transport web appelle. Elle vérifie la clé (en temps constant : une clé absente et une
  mauvaise clé se répondent pareil), l'état de Teams, la forme et les tailles du lot, ses plafonds — **avant** que
  rien ne soit rangé ni journalisé. Un lot admis est rangé par l'adaptateur (hors du journal) ; le journal n'en garde
  que ``teams.received`` (combien de messages neufs, où la personne a écrit) et, pour chaque réponse que les messages
  de la personne ont réglée, ``teams.settled``.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
import time
from collections import deque
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mika.kernel.events import Origin
from mika.plugins.teams import RECEIVED, SETTLED
from mika.ports.teams import (
    ACCEPTED,
    BUSY,
    CONFLICT,
    CONVERSATION_ID,
    DISABLED,
    INVALID,
    KEY_PREFIX,
    MISSING,
    RESULTS,
    UNKNOWN,
    GateResult,
    InboxBatch,
    InboxConversation,
    InboxMessage,
    KeyState,
)

#: l'empreinte qu'on compare quand il n'y a rien à comparer (aucune clé) : le même temps de calcul
_NOTHING = hashlib.sha256(b"").hexdigest()
#: requêtes par minute, au plus (l'extension pousse quand Teams reçoit, relève toutes les 30 s)
PER_MINUTE = 240
KINDS = frozenset({"dm", "group", "channel", "meeting", "other", "system"})
#: un identifiant de message tel que Teams les écrit (des chiffres, ou une empreinte) ; on l'assainit quand même
_MESSAGE_ID = re.compile(r"^[\w.:@=+/-]{1,200}$")
#: une date plausible (ms) : ni avant 2015, ni plus d'un jour dans le futur
_EPOCH_2015_MS = 1_420_070_400_000
_DAY_MS = 86_400_000


class _InMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1, max_length=200)
    conv: str = Field(min_length=3, max_length=320)
    author: str = Field(default="", max_length=200)
    author_id: str = Field(default="", max_length=200)
    time: int
    text: str = Field(min_length=1, max_length=4000)
    own: bool = False
    mentions_me: bool = False


class _InConversation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=3, max_length=320)
    title: str = Field(default="", max_length=200)
    kind: str = Field(default="other", max_length=20)


class _InSelf(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default="", max_length=200)
    name: str = Field(default="", max_length=200)


class _Inbox(BaseModel):
    model_config = ConfigDict(extra="ignore")
    self: _InSelf = Field(default_factory=_InSelf)
    conversations: list[_InConversation] = Field(default_factory=list, max_length=200)
    messages: list[_InMessage] = Field(default_factory=list, max_length=200)


def digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def _flat(text: str, limit: int) -> str:
    """Un nom ou un titre sur une ligne, sans caractères de contrôle."""
    return " ".join("".join(ch for ch in text if ch.isprintable() or ch == " ").split())[:limit]


def batch_of(data: dict[str, Any], now_ms: int) -> InboxBatch:
    """Le lot, validé : formes, tailles, identifiants de conversation, dates plausibles. Lève ``ValueError``."""
    try:
        got = _Inbox.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", ()))
        raise ValueError(f"lot illisible ({where or 'forme'})") from None
    conversations = []
    for c in got.conversations:
        if not CONVERSATION_ID.fullmatch(c.id):
            raise ValueError("identifiant de conversation illisible")
        conversations.append(InboxConversation(c.id, _flat(c.title, 120), c.kind if c.kind in KINDS else "other"))
    messages = []
    for m in got.messages:
        if not CONVERSATION_ID.fullmatch(m.conv) or not _MESSAGE_ID.fullmatch(m.id):
            raise ValueError("identifiant de message ou de conversation illisible")
        if not _EPOCH_2015_MS <= m.time <= now_ms + _DAY_MS:
            raise ValueError("date de message invraisemblable")
        messages.append(InboxMessage(m.id, m.conv, _flat(m.author, 120), _flat(m.author_id, 200), m.time,
                                     m.text.replace("\x00", ""), m.own, m.mentions_me))
    return InboxBatch(_flat(got.self.id, 200), _flat(got.self.name, 120), tuple(conversations), tuple(messages))


class TeamsDesk:
    """La clé de l'extension et la porte de ``/api/teams/…``. ``port`` (le ``KernelPort``) est relié après la
    construction du noyau ; ``store`` est l'adaptateur (le port ``teams``)."""

    def __init__(self, settings: Any, clock: Any, store: Any) -> None:
        self.settings = settings
        self.clock = clock
        self.store = store
        self.port: Any = None
        self._minute: deque[float] = deque()
        #: un lot se range et se journalise d'un tenant : deux lots simultanés ne s'entremêlent pas
        self._lock = asyncio.Lock()

    # ── la clé ──
    def key_state(self) -> KeyState | None:
        k = self.settings.teams_key()
        return KeyState(str(k.get("hint") or ""), int(k.get("created_at") or 0), str(k.get("by") or "")) \
            if k.get("digest") else None

    async def new_key(self, by: str) -> str:
        key = new_key()
        await self.settings.save_teams_key(digest(key), key[:len(KEY_PREFIX) + 4], self.clock(), by)
        return key

    async def revoke_key(self, by: str) -> bool:
        return await self.settings.revoke_teams_key()

    # ── la porte ──
    def _admit(self, key: str) -> GateResult | None:
        """La clé, l'état, la cadence : un refus, ou rien (admis)."""
        stored = str(self.settings.teams_key().get("digest") or "")
        given = digest(key) if key.startswith(KEY_PREFIX) and len(key) <= 200 else _NOTHING
        # toujours une comparaison, du même coût
        if not hmac.compare_digest(given, stored or _NOTHING) or not stored:
            return GateResult(UNKNOWN, "Clé refusée.")
        if not self.settings.teams().enabled:
            return GateResult(DISABLED, "Teams est désactivé dans ses réglages.")
        now = time.monotonic()
        while self._minute and now - self._minute[0] >= 60:
            self._minute.popleft()
        if len(self._minute) >= PER_MINUTE:
            return GateResult(BUSY, "Trop de requêtes.", retry_after=max(1, int(60 - (now - self._minute[0]))))
        self._minute.append(now)
        return None

    async def inbox(self, key: str, data: Any) -> GateResult:
        refused = self._admit(key)
        if refused is not None:
            return refused
        if self.port is None:
            return GateResult(BUSY, "Elle n'est pas prête.", retry_after=10)
        now = self.clock()
        try:
            batch = batch_of(data if isinstance(data, dict) else {}, now // 1000)
        except ValueError as exc:
            return GateResult(INVALID, str(exc))
        async with self._lock:
            stored = self.store.store_batch(batch, now)
            drafts = [SETTLED.draft(draft=s.draft, state=s.state, edited=s.edited, reason=s.reason,
                                    dedupe_key=f"teams-regle:{s.draft}:{s.state}") for s in stored.settled]
            if stored.new or stored.replied:
                drafts.insert(0, RECEIVED.draft(new=stored.new, replied=stored.replied))
            if drafts:
                await self.port.kernel.mind.append(drafts, emitter="teams", correlation="teams:inbox",
                                                   origin=Origin.EXTERNAL)
        return GateResult(ACCEPTED, "Reçu.", data={"accepted": stored.new, "known": stored.known})

    async def outbox(self, key: str) -> GateResult:
        refused = self._admit(key)
        if refused is not None:
            return refused
        items = self.store.outbox(self.clock())
        return GateResult(ACCEPTED, "", data={"items": [
            {"id": i.id, "conversation": i.conversation, "title": i.title, "kind": i.kind, "mode": i.mode,
             "status": i.status, "text": i.text, "created_at": i.created_at, "expires_at": i.expires_at}
            for i in items]})

    async def ack(self, key: str, item: str, data: Any) -> GateResult:
        refused = self._admit(key)
        if refused is not None:
            return refused
        if self.port is None:
            return GateResult(BUSY, "Elle n'est pas prête.", retry_after=10)
        data = data if isinstance(data, dict) else {}
        result = str(data.get("result") or "")
        if result not in RESULTS or not re.fullmatch(r"t[0-9a-f]{12}", item or ""):
            return GateResult(INVALID, "Un accusé : « placed », « sent » ou « failed », sur un élément de la file.")
        text = str(data.get("text") or "")[:4000].replace("\x00", "")
        reason = _flat(str(data.get("reason") or ""), 200)
        async with self._lock:
            outcome, done = self.store.settle(item, result, now=self.clock(), text=text, reason=reason)
            if done is not None:
                await self.port.kernel.mind.append(
                    [SETTLED.draft(draft=done.draft, state=done.state, edited=done.edited, reason=done.reason,
                                   dedupe_key=f"teams-regle:{done.draft}:{done.state}")],
                    emitter="teams", correlation="teams:outbox", origin=Origin.EXTERNAL)
        if outcome == MISSING:
            return GateResult(MISSING, "Élément inconnu.")
        if outcome == CONFLICT:
            return GateResult(CONFLICT, "Cet accusé ne va pas avec l'état de cet élément.")
        found = self.store.draft(item)
        return GateResult(ACCEPTED, "", data={"status": found.state if found is not None else ""})

"""Teams (ADR 0069, 0186), côté application : les clés de l'extension, une par compte, et la porte de
``/api/teams/…``.

- *Une clé par compte* : générée ici (``mtk_…``), montrée une seule fois ; seule son empreinte est gardée
  (``Settings.teams_keys``). Une clé neuve rend l'ancienne de ce compte inutile ; la retirer ferme la porte à ce
  compte. Ce guichet est aussi le port ``teams_keys`` (la console crée et retire une clé, compte par compte).
- *La porte* : ce que le transport web appelle. Elle reconnaît le compte à sa clé (chaque clé comparée en temps
  constant, toutes à chaque requête : une clé absente et une mauvaise clé se répondent pareil, et rien ne dit
  combien de comptes il y a), vérifie l'état de Teams, la forme et les tailles du lot, les plafonds du compte —
  **avant** que rien ne soit rangé ni journalisé. Ce que l'extension pousse, relève ou accuse ne concerne que ce
  compte. Un lot admis est rangé par l'adaptateur (hors du journal) ; le journal n'en garde que ``teams.received``
  (son compte, combien de messages neufs, où la personne a écrit) et, pour chaque réponse que les messages de la
  personne ont réglée, ``teams.settled``.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mika.adapters.web.gate import (
    SlidingWindow,
    clean_fields,
    clean_text,
    matches,
    new_key,
    one_line,
    plausible_ms,
    presented,
)
from mika.adapters.web.gate import token_digest as digest
from mika.kernel.events import Origin
from mika.plugins.teams import IMAGES, RECEIVED, SETTLED
from mika.ports.gate import (
    ACCEPTED,
    BUSY,
    CONFLICT,
    DISABLED,
    INVALID,
    MISSING,
    UNKNOWN,
    GateResult,
    KeyState,
)
from mika.ports.teams import (
    CONVERSATION_ID,
    IMAGE_KEPT,
    IMAGE_MAX_BYTES,
    IMAGE_NO_MESSAGE,
    KEY_PREFIX,
    RESULTS,
    ImageIn,
    InboxBatch,
    InboxConversation,
    InboxMessage,
)

#: requêtes par minute, au plus (l'extension pousse quand Teams reçoit, relève toutes les 30 s)
PER_MINUTE = 240
#: une connexion en direct revérifie sa clé et l'état de Teams au plus tant de secondes après (ADR 0251)
LIVE_RECHECK_S = 10.0
#: les images (ADR 0258) : les types admis et ce par quoi leurs octets commencent ; leur taille, au plus
IMAGE_TYPES: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",), "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"), "image/webp": (b"RIFF",),
}
IMAGE_B64_MAX = (IMAGE_MAX_BYTES * 4) // 3 + 8
#: au journal, ce que devient une réponse que l'extension n'a pas pu faire partir (son détail reste dans le cache)
FAILED_BY_EXTENSION = "l'extension n'a pas pu la faire partir"
KINDS = frozenset({"dm", "group", "channel", "meeting", "other", "system"})
#: un identifiant de message tel que Teams les écrit (des chiffres, ou une empreinte) ; on l'assainit quand même
_MESSAGE_ID = re.compile(r"^[\w.:@=+/-]{1,200}$")


class _InMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1, max_length=200)
    conv: str = Field(min_length=3, max_length=320)
    author: str = Field(default="", max_length=200)
    author_id: str = Field(default="", max_length=200)
    time: int
    text: str = Field(default="", max_length=4000)
    own: bool = False
    mentions_me: bool = False
    deleted: bool = False
    #: ses images, envoyées à part (ADR 0258) : il attend qu'elles soient lues
    images: int = Field(default=0, ge=0, le=8)


class _InImage(BaseModel):
    """Une image d'un message (ADR 0258) : son message, son identifiant, son rang, son type, ses octets en base64."""

    model_config = ConfigDict(extra="ignore")
    conv: str = Field(min_length=3, max_length=320)
    id: str = Field(min_length=1, max_length=200)
    image: str = Field(min_length=1, max_length=200)
    position: int = Field(default=0, ge=0, le=7)
    type: str = Field(max_length=40)
    data: str = Field(min_length=8, max_length=IMAGE_B64_MAX)


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
    """L'enveloppe d'un lot ; chaque message et chaque conversation sont lus un à un (un seul illisible n'emporte
    pas le lot)."""

    model_config = ConfigDict(extra="ignore")
    self: _InSelf = Field(default_factory=_InSelf)
    conversations: list[Any] = Field(default_factory=list, max_length=200)
    messages: list[Any] = Field(default_factory=list, max_length=200)
    #: l'historique chargé à la mise en service (ADR 0251) : rangé déjà lu, rien n'est journalisé
    history: bool = False


def _message(raw: Any, now_ms: int) -> InboxMessage | None:
    try:
        m = _InMessage.model_validate(clean_fields(raw))
    except ValidationError:
        return None
    if not CONVERSATION_ID.fullmatch(m.conv) or not _MESSAGE_ID.fullmatch(m.id):
        return None
    if not plausible_ms(m.time, now_ms):
        return None  # une date invraisemblable
    text = clean_text(m.text)
    if not text.strip() and not m.deleted:
        return None
    return InboxMessage(m.id, m.conv, one_line(m.author, 120), one_line(m.author_id, 200), m.time, text, m.own,
                        m.mentions_me, m.deleted, images=m.images)


def image_of(data: dict[str, Any]) -> ImageIn:
    """Une image envoyée, validée : son message (des identifiants tels que Teams les écrit), un type d'image admis,
    des octets lisibles, sous la borne, qui commencent comme ce type le veut. Lève ``ValueError`` sinon."""
    try:
        got = _InImage.model_validate(clean_fields(data))
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        raise ValueError(f"image illisible ({'.'.join(str(x) for x in first.get('loc', ())) or 'forme'})") from None
    if not CONVERSATION_ID.fullmatch(got.conv) or not _MESSAGE_ID.fullmatch(got.id) \
            or not _MESSAGE_ID.fullmatch(got.image):
        raise ValueError("image illisible (identifiants)")
    magics = IMAGE_TYPES.get(got.type.lower())
    if magics is None:
        raise ValueError("un type d'image admis : " + ", ".join(sorted(IMAGE_TYPES)))
    try:
        raw = base64.b64decode(got.data, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("image illisible (base64)") from None
    if not raw or len(raw) > IMAGE_MAX_BYTES:
        raise ValueError(f"une image de {IMAGE_MAX_BYTES // (1024 * 1024)} Mo au plus")
    if not any(raw.startswith(m) for m in magics) or (got.type.lower() == "image/webp" and raw[8:12] != b"WEBP"):
        raise ValueError("ces octets ne sont pas une image de ce type")
    return ImageIn(got.conv, got.id, got.image, got.position, got.type.lower(), raw)


def batch_of(data: dict[str, Any], now_ms: int) -> tuple[InboxBatch, int]:
    """Le lot, validé — formes, tailles, identifiants, dates plausibles — et combien de ses éléments ont été écartés
    (un message illisible est laissé de côté, le reste passe). Lève ``ValueError`` si l'enveloppe est illisible."""
    try:
        got = _Inbox.model_validate({**data, "self": clean_fields(data.get("self") or {})})
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", ()))
        raise ValueError(f"lot illisible ({where or 'forme'})") from None
    dropped = 0
    conversations = []
    for raw in got.conversations:
        try:
            c = _InConversation.model_validate(clean_fields(raw))
        except ValidationError:
            dropped += 1
            continue
        if not CONVERSATION_ID.fullmatch(c.id):
            dropped += 1
            continue
        conversations.append(InboxConversation(c.id, one_line(c.title, 120), c.kind if c.kind in KINDS else "other"))
    messages = []
    for raw in got.messages:
        m = _message(raw, now_ms)
        if m is None:
            dropped += 1
            continue
        messages.append(m)
    return (InboxBatch(one_line(got.self.id, 200), one_line(got.self.name, 120), tuple(conversations),
                       tuple(messages), history=got.history), dropped)


class TeamsDesk:
    """Les clés de l'extension (une par compte, le port ``teams_keys``) et la porte de ``/api/teams/…``. ``port``
    (le ``KernelPort``) est relié après la construction du noyau ; ``store`` est l'adaptateur (le port ``teams``)."""

    def __init__(self, settings: Any, clock: Any, store: Any) -> None:
        self.settings = settings
        self.clock = clock
        self.store = store
        self.port: Any = None
        #: les requêtes de la minute, par compte (une extension bavarde ne prive pas les autres)
        self._minute = SlidingWindow(PER_MINUTE, 60.0)
        #: un lot se range et se journalise d'un tenant : deux lots simultanés ne s'entremêlent pas
        self._lock = asyncio.Lock()
        #: les connexions en direct (ADR 0251) : la clé reconnue, son compte, et quand on l'a vérifiée
        self._live_checked: dict[str, tuple[str, float]] = {}

    # ── les clés ──
    def key_state(self, account: str) -> KeyState | None:
        k = self.settings.teams_keys().get(account) or {}
        return KeyState(str(k.get("hint") or ""), int(k.get("created_at") or 0), str(k.get("by") or "")) \
            if k.get("digest") else None

    async def new_key(self, account: str, by: str) -> str:
        if self.settings.teams().account(account) is None:
            raise ValueError(f"Compte Teams inconnu : « {account[:40]} » — déclare-le d'abord dans Teams › Paramètres "
                             "(en haut à droite).")
        key = new_key(KEY_PREFIX)
        await self.settings.save_teams_key(account, digest(key), key[:len(KEY_PREFIX) + 4], self.clock(), by)
        return key

    async def revoke_key(self, account: str) -> bool:
        return await self.settings.revoke_teams_key(account)

    # ── la porte ──
    def _recognized(self, key: str) -> str:
        """Le compte de cette clé (vide : aucun). Chaque clé rangée est comparée, toujours toutes et au moins une, du
        même coût : rien ne dit laquelle a répondu, ni s'il y en a."""
        given = presented(key, KEY_PREFIX)
        stored = [(name, str(k.get("digest") or "")) for name, k in sorted(self.settings.teams_keys().items())]
        found = ""
        for name, wanted in stored or [("", "")]:
            if matches(given, wanted) and not found:
                found = name
        return found

    def _check(self, key: str) -> tuple[str, GateResult | None]:
        """La clé et l'état, sans compter la requête : (le compte, un refus ou rien)."""
        account = self._recognized(key)
        cfg = self.settings.teams()
        if not account or cfg.account(account) is None:  # une clé d'un compte retiré depuis ne vaut plus
            return "", GateResult(UNKNOWN, "Clé refusée.")
        if not cfg.enabled:
            return account, GateResult(DISABLED, "Teams est désactivé dans ses réglages.")
        if account in cfg.accounts and not cfg.accounts[account].enabled:
            return account, GateResult(DISABLED, "Ce compte Teams est désactivé dans ses réglages.")
        return account, None

    def _admit(self, key: str) -> tuple[str, GateResult | None]:
        """La clé, l'état, la cadence : (le compte, un refus ou rien — admis)."""
        account, refused = self._check(key)
        if refused is not None:
            return account, refused
        if not self._minute.allow(key=account):
            return account, GateResult(BUSY, "Trop de requêtes.", retry_after=self._minute.wait_s(account))
        return account, None

    async def inbox(self, key: str, data: Any) -> GateResult:
        account, refused = self._admit(key)
        if refused is not None:
            return refused
        if self.port is None:
            return GateResult(BUSY, "Elle n'est pas prête.", retry_after=10)
        now = self.clock()
        try:
            batch, dropped = batch_of(data if isinstance(data, dict) else {}, now // 1000)
        except ValueError as exc:
            return GateResult(INVALID, str(exc))
        async with self._lock:
            # hors de la boucle : un paquet d'historique, c'est jusqu'à 200 messages cherchés, comparés, rangés
            stored = await asyncio.to_thread(self.store.store_batch, account, batch, now)
            drafts = [SETTLED.draft(draft=s.draft, state=s.state, edited=s.edited, reason=s.reason,
                                    dedupe_key=f"teams-regle:{s.draft}:{s.state}") for s in stored.settled]
            # ce qu'elle remarque : ce qui s'est rangé comme du direct — l'historique plus vieux que 24 h se range
            # déjà lu, rien n'en est journalisé (ADR 0251)
            if stored.recent or stored.replied:
                drafts.insert(0, RECEIVED.draft(new=stored.recent, replied=stored.replied, account=account))
            if drafts:
                await self.port.kernel.mind.append(drafts, emitter="teams", correlation="teams:inbox",
                                                   origin=Origin.EXTERNAL)
        return GateResult(ACCEPTED, "Reçu.", data={"accepted": stored.new, "known": stored.known, "twins": stored.twins,
                                                  "dropped": dropped})

    def _items(self, account: str) -> list[dict[str, Any]]:
        """La boîte d'envoi d'un compte, telle que l'extension la lit (le relevé comme la connexion en direct)."""
        return [{"id": i.id, "conversation": i.conversation, "title": i.title, "kind": i.kind, "mode": i.mode,
                 "status": i.status, "text": i.text, "created_at": i.created_at, "expires_at": i.expires_at}
                for i in self.store.outbox(account, self.clock())]

    async def outbox(self, key: str) -> GateResult:
        account, refused = self._admit(key)
        if refused is not None:
            return refused
        return GateResult(ACCEPTED, "", data={"items": self._items(account)})

    # ── en direct (ADR 0251) ──
    async def live(self, key: str) -> GateResult:
        """Ouvrir la boîte d'envoi en direct (``/api/teams/live``) : admise comme un relevé — la clé, l'état, la
        minute —, avec la boîte telle qu'elle est."""
        return await self.outbox(key)

    async def live_items(self, key: str) -> GateResult:
        """La boîte d'une connexion ouverte, relue chaque seconde hors de la boucle, sans compter dans la minute ; la
        clé et l'état revérifiés toutes les ``LIVE_RECHECK_S`` secondes (une clé retirée, un compte ou Teams coupés
        ferment la connexion), pas à chaque relecture : ce sont deux lectures des réglages."""
        now = time.monotonic()
        known = self._live_checked.get(key)
        if known is None or now - known[1] >= LIVE_RECHECK_S:
            account, refused = self._check(key)
            if refused is not None:
                self._live_checked.pop(key, None)
                return refused
            known = (account, now)
            self._live_checked[key] = known
            if len(self._live_checked) > 64:  # des clés d'avant (retirées, remplacées) : on oublie la plus vieille
                self._live_checked.pop(min(self._live_checked, key=lambda k: self._live_checked[k][1]))
        return GateResult(ACCEPTED, "", data={"items": await asyncio.to_thread(self._items, known[0])})

    async def image(self, key: str, data: Any) -> GateResult:
        """Une image d'un message (ADR 0258) : admise comme un lot (la clé, l'état, la minute), validée avant que rien
        ne soit rangé ; gardée avec son message — inconnu : 404, l'extension la renverra quand il sera arrivé. Une
        image neuve journalise ``teams.images`` (rien d'elle) : la lecture la regardera."""
        account, refused = self._admit(key)
        if refused is not None:
            return refused
        if self.port is None:
            return GateResult(BUSY, "Elle n'est pas prête.", retry_after=10)
        try:
            image = image_of(data if isinstance(data, dict) else {})
        except ValueError as exc:
            return GateResult(INVALID, str(exc))
        outcome = await asyncio.to_thread(self.store.keep_image, account, image, self.clock())
        if outcome == IMAGE_NO_MESSAGE:
            return GateResult(MISSING, "Son message n'est pas encore arrivé.")
        if outcome == IMAGE_KEPT:
            await self.port.kernel.mind.append([IMAGES.draft(account=account)], emitter="teams",
                                               correlation="teams:image", origin=Origin.EXTERNAL)
        return GateResult(ACCEPTED, "Reçue.", data={"kept": outcome == IMAGE_KEPT})

    async def ack(self, key: str, item: str, data: Any) -> GateResult:
        account, refused = self._admit(key)
        if refused is not None:
            return refused
        if self.port is None:
            return GateResult(BUSY, "Elle n'est pas prête.", retry_after=10)
        data = data if isinstance(data, dict) else {}
        result = str(data.get("result") or "")
        if result not in RESULTS or not re.fullmatch(r"t[0-9a-f]{12}", item or ""):
            return GateResult(INVALID, "Un accusé : « sending », « placed », « sent » ou « failed », sur un élément de "
                                       "la file.")
        text = clean_text(str(data.get("text") or "")[:8000])
        reason = one_line(str(data.get("reason") or ""), 200)
        async with self._lock:
            outcome, done = self.store.settle(item, result, now=self.clock(), text=text, reason=reason,
                                              account=account)
            if done is not None:
                # la raison que donne l'extension reste dans le cache (la console la montre) : au journal, une
                # raison écrite par le code, jamais un texte venu d'ailleurs
                said = FAILED_BY_EXTENSION if result == "failed" else ""
                await self.port.kernel.mind.append(
                    [SETTLED.draft(draft=done.draft, state=done.state, edited=done.edited, reason=said,
                                   dedupe_key=f"teams-regle:{done.draft}:{done.state}")],
                    emitter="teams", correlation="teams:outbox", origin=Origin.EXTERNAL)
        if outcome == MISSING:
            return GateResult(MISSING, "Élément inconnu.")
        if outcome == CONFLICT:
            return GateResult(CONFLICT, "Cet accusé ne va pas avec l'état de cet élément.")
        found = self.store.draft(item)
        return GateResult(ACCEPTED, "", data={"status": found.state if found is not None else ""})

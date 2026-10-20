"""Les messages du téléphone (ADR 0120), côté application : la porte de ``/api/phone/…`` et l'envoi au téléphone.

- *La porte* : ce que le transport web appelle, une fois le jeton de l'application reconnu (``mw_…``, client
  ``mobile``). Elle vérifie que l'adresse parle en propriétaire, que le plugin est actif, la forme et les tailles du
  lot, sa cadence — **avant** que rien ne s'écrive. Chaque message admis devient un ``phone.received`` (dédoublonné
  par son identifiant : la même notification revient à chaque mise à jour) ; l'expéditeur y prend sa clé de contact
  (``phone:<empreinte>:<nom>``, celle de la première fois). Un sort de réponse rendu par le téléphone devient un
  ``phone.settled``.
- *L'envoi* : la capacité ``phone.send`` passe par ``offer`` — une notification scellée pour chaque téléphone du
  compte, ouvert ou non (``seal.phone_payload``) ; c'est le téléphone qui demande l'autorisation.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mika.adapters.push import seal
from mika.adapters.web.accounts import account_of_handle
from mika.contracts import identity as identity_c
from mika.contracts import phone as c
from mika.kernel.events import Content, Origin
from mika.plugins.phone import PhoneParams, PhoneState
from mika.ports.phone import (
    ACCEPTED,
    APPS,
    BUSY,
    DISABLED,
    FORBIDDEN,
    INVALID,
    RESULTS,
    GateResult,
)
from mika.vocab.privacy import Sensitivity

#: requêtes par minute, au plus (le téléphone pousse à chaque message, et rejoue sa file au retour du réseau)
PER_MINUTE = 120
#: un identifiant, une clé de conversation ou d'expéditeur : ce que le téléphone calcule (des empreintes en hex)
_OPAQUE = re.compile(r"^[0-9a-f]{8,64}$")
#: une date plausible (ms) : ni avant 2015, ni plus d'un jour dans le futur
_EPOCH_2015_MS = 1_420_070_400_000
_DAY_MS = 86_400_000
_REASON = re.compile(r"^[a-z_]{0,40}$")
LEVEL = int(Sensitivity.PERSONAL)


class _InMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=8, max_length=64)
    app: str = Field(max_length=40)
    thread: str = Field(min_length=8, max_length=64)
    title: str = Field(default="", max_length=200)
    group: bool = False
    sender: str = Field(default="", max_length=64)
    name: str = Field(default="", max_length=200)
    text: str = Field(default="", max_length=4000)
    time: int
    own: bool = False


class _Inbox(BaseModel):
    model_config = ConfigDict(extra="ignore")
    messages: list[Any] = Field(default_factory=list, max_length=200)


class _InSettled(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int = Field(ge=1)
    result: str
    reason: str = Field(default="", max_length=40)


class _Settled(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[Any] = Field(default_factory=list, max_length=100)


def _clean(text: str) -> str:
    """Un texte sans octet nul ni demi-caractère (une coupe au milieu d'un emoji laisse un « surrogate » seul)."""
    return text.replace("\x00", "").encode("utf-8", "replace").decode("utf-8")


def _flat(text: str, limit: int) -> str:
    """Un nom ou un titre sur une ligne, sans caractères de contrôle."""
    return " ".join("".join(ch for ch in _clean(text) if ch.isprintable() or ch == " ").split())[:limit]


def message_of(raw: Any, now_ms: int) -> _InMessage | None:
    """Un message lisible, ou ``None`` (écarté seul : le reste du lot passe)."""
    if isinstance(raw, dict):
        raw = {k: _clean(v) if isinstance(v, str) else v for k, v in raw.items()}
    try:
        m = _InMessage.model_validate(raw)
    except ValidationError:
        return None
    if not _OPAQUE.fullmatch(m.id) or not _OPAQUE.fullmatch(m.thread) or m.app not in APPS:
        return None
    if not m.own and not _OPAQUE.fullmatch(m.sender):
        return None
    if not _EPOCH_2015_MS <= m.time <= now_ms + _DAY_MS or not m.text.strip():
        return None
    return m


class PhoneDesk:
    """La porte de ``/api/phone/…`` et l'envoi au téléphone. ``port`` (le ``KernelPort``) est relié après la
    construction du noyau ; ``push`` (``MobilePush``), après celle du transport."""

    def __init__(self) -> None:
        self.port: Any = None
        self.push: Any = None
        self._minute: deque[float] = deque()
        #: un lot s'écrit d'un tenant : deux lots simultanés ne s'entremêlent pas (les clés de contact)
        self._lock = asyncio.Lock()

    def _admit(self, handle: str) -> tuple[GateResult | None, Any]:
        """Prête, propriétaire, active, dans sa cadence : un refus, ou rien (admis) avec le cadre du moment."""
        if self.port is None:
            return GateResult(BUSY, "Elle n'est pas prête.", retry_after=10), None
        frame = self.port.kernel.mind.frame()
        if not frame.get(identity_c.SPEAKS_AS_OWNER(handle)):
            return GateResult(FORBIDDEN, "Les messages du téléphone sont réservés à sa propriétaire."), None
        p = frame.env.params_of("phone", frame.root)
        if not (p if p is not None else PhoneParams()).enabled:
            return GateResult(DISABLED, "Les messages du téléphone sont coupés dans ses réglages."), None
        now = time.monotonic()
        while self._minute and now - self._minute[0] >= 60:
            self._minute.popleft()
        if len(self._minute) >= PER_MINUTE:
            return GateResult(BUSY, "Trop de requêtes.", retry_after=max(1, int(60 - (now - self._minute[0])))), None
        self._minute.append(now)
        return None, frame

    async def inbox(self, handle: str, data: Any) -> GateResult:
        refused, frame = self._admit(handle)
        if refused is not None:
            return refused
        try:
            got = _Inbox.model_validate(data if isinstance(data, dict) else {})
        except ValidationError:
            return GateResult(INVALID, "Lot illisible.")
        mind = self.port.kernel.mind
        now_ms = mind.clock.now() // 1000
        found = [message_of(raw, now_ms) for raw in got.messages]
        messages = [m for m in found if m is not None]
        dropped = len(found) - len(messages)
        person = frame.get(identity_c.PERSON(handle)) or handle
        async with self._lock:
            contacts = dict(mind.frame().state(c.OWNER).contacts) if messages else {}
            drafts = []
            for m in sorted(messages, key=lambda m: m.time):
                sender = ""
                if not m.own:
                    digest = c.contact_hash(person, m.app, m.sender)
                    sender = contacts.setdefault(digest, c.contact_key(digest, _flat(m.name, 120)))
                title = _flat(m.title, 120) if m.group else ""
                name = _flat(m.name, 120) if not m.own else ""
                drafts.append(c.RECEIVED.draft(
                    recipient=person, handle=handle, source=m.app, thread=m.thread, sender=sender,
                    sender_name=Content.of(name, level=LEVEL) if name else None,
                    title=Content.of(title, level=LEVEL) if title else None, group=m.group, own=m.own,
                    text=Content.of(m.text.strip(), level=LEVEL), sent_at=m.time * 1000,
                    dedupe_key=f"phone:{handle}:{m.id}"))
            commit = await mind.append(drafts, emitter=c.OWNER, correlation=f"phone:{handle}",
                                       origin=Origin.EXTERNAL) if drafts else None
        accepted = len(commit.events) if commit is not None and not commit.deduped else 0
        return GateResult(ACCEPTED, "Reçu.", data={"accepted": accepted, "known": len(messages) - accepted,
                                                   "dropped": dropped})

    async def settled(self, handle: str, data: Any) -> GateResult:
        refused, frame = self._admit(handle)
        if refused is not None:
            return refused
        try:
            got = _Settled.model_validate(data if isinstance(data, dict) else {})
        except ValidationError:
            return GateResult(INVALID, "Accusés illisibles.")
        person = frame.get(identity_c.PERSON(handle)) or handle
        state: PhoneState = frame.state(c.OWNER)
        drafts, unknown = [], 0
        for raw in got.items:
            try:
                item = _InSettled.model_validate(raw)
            except ValidationError:
                unknown += 1
                continue
            offer = state.offers.get(item.id)
            if offer is None or offer.person != person or item.result not in RESULTS:
                unknown += 1
                continue
            reason = item.reason if _REASON.fullmatch(item.reason) else ""
            drafts.append(c.SETTLED.draft(draft=item.id, result=item.result, reason=reason,
                                          dedupe_key=f"phone-regle:{item.id}"))
        if drafts:
            await self.port.kernel.mind.append(drafts, emitter=c.OWNER, correlation=f"phone:{handle}",
                                               origin=Origin.EXTERNAL)
        return GateResult(ACCEPTED, "", data={"settled": len(drafts), "unknown": unknown})

    async def offer(self, handle: str, body: dict[str, Any]) -> int:
        """Une réponse proposée, vers chaque téléphone du compte de ``handle`` (scellée pour chacun) : combien de
        téléphones la recevront. Le port ``phone`` de la capacité ``phone.send``."""
        account = account_of_handle(handle)
        if self.push is None or account is None:
            return 0
        now_ms = int(self.port.kernel.mind.clock.now() // 1000) if self.port is not None else 0
        payload = seal.phone_payload(draft=int(body["id"]), app=str(body["app"]), thread=str(body["thread"]),
                                     to=str(body["to"]), text=str(body["text"]), expires_ms=int(body["exp"]),
                                     ts_ms=now_ms)
        return self.push.offer(account, payload)

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
- *Les profils* (ADR 0298) : un lot peut joindre le profil des auteurs et des personnes mentionnées de ses messages
  (``profiles``) ; chacun est lu seul, comme un message (un profil illisible est laissé de côté, jamais le lot), avec
  les formes d'identifiant que l'extension reconnaît ; une adresse mal formée est laissée vide. Rien n'en est
  journalisé : l'annuaire les relit dans le cache.
- *Les réactions* (ADR 0300) : un message peut porter les siennes (``reactions`` : la clé de Teams, combien, la sienne,
  dix identifiants), lues une à une (une réaction illisible est laissée de côté, jamais le message). Un message déjà
  connu qui revient avec d'autres réactions est rangé « connu » : rien n'est journalisé, rien ne se remarque.
- *Les photos de profil* (ADR 0300) : ``POST /api/teams/photo`` (``{person, etag, type, data}``), admise comme une
  image, vérifiée (64 Ko, JPEG, PNG ou WebP, des octets de ce type), gardée seulement pour une personne dont ce compte a
  le profil, à l'empreinte qu'il dit. Rien n'en est journalisé : elle ne fait rien remarquer.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import re
import time
from collections.abc import Callable
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

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
from mika.ports.changes import OUTBOX, Change
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
    PHOTO_KEPT,
    PHOTO_MAX_BYTES,
    PHOTO_UNKNOWN,
    RESULTS,
    ImageIn,
    InboxBatch,
    InboxConversation,
    InboxMessage,
    InboxProfile,
    PhotoIn,
    Quote,
    Reaction,
)
from mika.runtime.boundary import call

#: requêtes par minute, au plus (l'extension pousse quand Teams reçoit, relève toutes les 30 s)
PER_MINUTE = 240
#: une connexion en direct revérifie sa clé et l'état de Teams au plus tant de secondes après (ADR 0251)
LIVE_RECHECK_S = 10.0
#: la présence de l'extension (``last_seen``, ADR 0308) se dit aux écrans quand sa connexion en direct s'ouvre ou se
#: ferme, et au plus une fois par ce délai (s) quand elle se manifeste : l'âge qu'ils en montrent ne vieillit pas sans
#: raison (la pastille passe à l'orange après un quart d'heure de silence), et un retour après un silence se voit
PRESENCE_EVERY_S = 5 * 60
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
#: un profil (ADR 0298) : l'identifiant d'une personne (en minuscules) et une adresse, des formes que l'extension
#: reconnaît (``frontend/Extension/lib/extract.js``, ``PROFILE_ID`` et ``PROFILE_EMAIL``) ; ses bornes
PROFILE_ID = re.compile(r"^(8:orgid:[0-9a-f-]{36}|8:live:[a-z0-9._-]{1,80}|8:teamsvisitor:[0-9a-f-]{32,36})$")
PROFILE_EMAIL = re.compile(r"^[^\s@<>\"',;]{1,64}@[a-z0-9.-]{1,253}\.[a-z]{2,}$")
PROFILE_TEXT_MAX, PROFILE_EMAIL_MAX, PROFILE_PHONES, PHONE_MAX = 120, 254, 3, 40
#: un numéro compte au moins tant de chiffres
PHONE_DIGITS = 6
#: l'empreinte d'une photo de profil (``avatarETag``, ADR 0300 : ``frontend/Extension/lib/extract.js``, ``AVATAR``)
AVATAR = re.compile(r"^[A-Za-z0-9._:+/=-]{1,200}$")
#: les photos de profil : leurs types et ce par quoi leurs octets commencent (pas de GIF : un avatar n'en est pas un)
PHOTO_TYPES = {k: v for k, v in IMAGE_TYPES.items() if k != "image/gif"}
PHOTO_B64_MAX = (PHOTO_MAX_BYTES * 4) // 3 + 8
#: une réaction (ADR 0300) : sa clé de Teams ; qui l'a posée (un identifiant de personne) ; au plus tant par message,
#: tant d'identifiants par réaction
REACTION_KEY = re.compile(r"^[a-z0-9_+-]{1,40}$")
REACTOR = re.compile(r"^[\w.:@-]{1,200}$")
REACTIONS_MAX, REACTORS_MAX, REACTION_COUNT_MAX = 20, 10, 1_000_000


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
    #: ses réactions (ADR 0300), lues une à une (les ``REACTIONS_MAX`` premières) ; absentes : l'extension n'en dit rien
    #: (le cache garde les siennes)
    reactions: list[Any] | None = None
    #: le message qu'il cite (ADR 0305), séparé de son texte par l'extension ; illisible, il est ignoré, jamais le message
    quote: Any = None


class _InReaction(BaseModel):
    """Une réaction à un message (ADR 0300) : ``frontend/Extension/lib/signals.js``, ``wireReactions``."""

    model_config = ConfigDict(extra="ignore")
    key: str = Field(min_length=1, max_length=40)
    count: int = Field(default=0, ge=0, le=REACTION_COUNT_MAX)
    mine: bool = False
    #: qui l'a posée (les ``REACTORS_MAX`` premiers identifiants qui en ont la forme)
    by: list[Any] = Field(default_factory=list)


class _InPhoto(BaseModel):
    """La photo de profil d'une personne (ADR 0300) : son identifiant Teams, son empreinte, son type, ses octets."""

    model_config = ConfigDict(extra="ignore")
    person: str = Field(min_length=3, max_length=200)
    etag: str = Field(min_length=1, max_length=200)
    type: str = Field(max_length=40)
    data: str = Field(min_length=8, max_length=PHOTO_B64_MAX)


class _InImage(BaseModel):
    """Une image d'un message (ADR 0258) : son message, son identifiant, son rang, son type, ses octets en base64."""

    model_config = ConfigDict(extra="ignore")
    conv: str = Field(min_length=3, max_length=320)
    id: str = Field(min_length=1, max_length=200)
    image: str = Field(min_length=1, max_length=200)
    position: int = Field(default=0, ge=0, le=7)
    type: str = Field(max_length=40)
    data: str = Field(min_length=8, max_length=IMAGE_B64_MAX)


class _InProfile(BaseModel):
    """Le profil d'une personne (ADR 0298) : ``frontend/Extension/lib/signals.js``, ``wireProfile``."""

    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=3, max_length=200)
    name: str = Field(default="", max_length=PROFILE_TEXT_MAX)
    email: str = Field(default="", max_length=PROFILE_EMAIL_MAX)
    title: str = Field(default="", max_length=PROFILE_TEXT_MAX)
    company: str = Field(default="", max_length=PROFILE_TEXT_MAX)
    department: str = Field(default="", max_length=PROFILE_TEXT_MAX)
    tenant: str = Field(default="", max_length=PROFILE_TEXT_MAX)
    phones: list[Annotated[str, StringConstraints(max_length=PHONE_MAX)]] = Field(default_factory=list,
                                                                                 max_length=PROFILE_PHONES)
    #: l'empreinte de sa photo (ADR 0300) ; illisible, elle est laissée vide
    avatar: str = Field(default="", max_length=200)


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
    #: les profils des auteurs et des mentionnés de ses messages (ADR 0298), lus un à un
    profiles: list[Any] = Field(default_factory=list, max_length=200)


def reaction_of(raw: Any) -> Reaction | None:
    """Une réaction reçue, validée (``None`` : illisible) : une clé de Teams (lue en minuscules), des identifiants de
    personne (en minuscules, chacun une fois), un compte au moins égal à leur nombre."""
    try:
        r = _InReaction.model_validate(raw)
    except ValidationError:
        return None
    key = r.key.strip().lower()
    if not REACTION_KEY.fullmatch(key):
        return None
    by = tuple(dict.fromkeys(b.strip().lower() for b in r.by if isinstance(b, str) and REACTOR.fullmatch(b.strip())))
    count = max(len(by), r.count)
    return Reaction(key, count, r.mine, by[:REACTORS_MAX]) if count else None


def _reactions(raw: list[Any] | None) -> tuple[Reaction, ...] | None:
    """Les réactions d'un message (``None`` : rien de dit) : chacune lue seule, une clé une fois."""
    if raw is None:
        return None
    out: dict[str, Reaction] = {}
    for r in (reaction_of(x) for x in raw[:REACTIONS_MAX]):
        if r is not None and r.key not in out:
            out[r.key] = r
    return tuple(out.values())


#: une citation reçue (ADR 0305) : l'identifiant de service du message cité, l'identifiant Teams de son auteur
QUOTE_MESSAGE = re.compile(r"\d{10,16}")
QUOTE_AUTHOR = re.compile(r"\d{1,2}:[A-Za-z0-9:._-]{1,200}")
#: l'extrait d'une citation reçue, au plus (ce que Teams en a mis : souvent tout le message cité)
QUOTE_KEPT_MAX = 300


def quote_of(raw: Any) -> Quote | None:
    """La citation d'un message reçu (``frontend/Extension/lib/extract.js``, ``quoteIn``), validée ; ``None`` si elle
    est absente ou illisible : un identifiant de service, un auteur Teams, un nom et un extrait sur une ligne, bornés."""
    if not isinstance(raw, dict):
        return None
    message, author_id = str(raw.get("message") or ""), str(raw.get("author_id") or "")
    if not QUOTE_MESSAGE.fullmatch(message) or not QUOTE_AUTHOR.fullmatch(author_id):
        return None
    at = raw.get("at")
    at_ms = int(at) if isinstance(at, int | float) and not isinstance(at, bool) and at > 0 else int(message)
    return Quote(message, author_id, one_line(str(raw.get("author") or ""), 120), at_ms,
                 one_line(str(raw.get("preview") or ""), QUOTE_KEPT_MAX))


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
                        m.mentions_me, m.deleted, images=m.images,
                        reactions=None if m.deleted else _reactions(m.reactions),
                        quote=None if m.deleted else quote_of(m.quote))


def profile_of(raw: Any) -> InboxProfile | None:
    """Un profil reçu, validé (``None`` : illisible) : un identifiant de personne que l'extension reconnaît (lu en
    minuscules), des textes sur une ligne et bornés, une adresse bien formée (sinon vide), trois numéros au plus qui ont
    chacun assez de chiffres ; un profil qui ne dit rien de la personne est illisible."""
    if isinstance(raw, dict) and isinstance(raw.get("phones"), list):
        raw = {**raw, "phones": [clean_text(n) if isinstance(n, str) else n for n in raw["phones"]]}
    try:
        p = _InProfile.model_validate(clean_fields(raw))
    except ValidationError:
        return None
    pid = p.id.strip().lower()
    if not PROFILE_ID.fullmatch(pid):
        return None
    email = one_line(p.email, PROFILE_EMAIL_MAX).lower()
    phones = tuple(dict.fromkeys(n for n in (one_line(x, PHONE_MAX) for x in p.phones)
                                 if sum(c.isdigit() for c in n) >= PHONE_DIGITS))
    avatar = p.avatar.strip()
    found = InboxProfile(pid, one_line(p.name, PROFILE_TEXT_MAX), email if PROFILE_EMAIL.fullmatch(email) else "",
                         one_line(p.title, PROFILE_TEXT_MAX), one_line(p.company, PROFILE_TEXT_MAX),
                         one_line(p.department, PROFILE_TEXT_MAX), one_line(p.tenant, PROFILE_TEXT_MAX), phones,
                         avatar if AVATAR.fullmatch(avatar) else "")
    if not (found.name or found.email or found.title or found.company or found.department or found.phones):
        return None
    return found


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


def photo_of(data: dict[str, Any]) -> PhotoIn:
    """Une photo de profil envoyée (ADR 0300), validée : une personne de Teams (lue en minuscules), une empreinte, un
    type admis (JPEG, PNG, WebP), des octets lisibles, 64 Ko au plus, qui commencent comme ce type le veut. Lève
    ``ValueError`` sinon."""
    try:
        got = _InPhoto.model_validate(clean_fields(data))
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        raise ValueError(f"photo illisible ({'.'.join(str(x) for x in first.get('loc', ())) or 'forme'})") from None
    person, etag = got.person.strip().lower(), got.etag.strip()
    if not PROFILE_ID.fullmatch(person) or not AVATAR.fullmatch(etag):
        raise ValueError("photo illisible (identifiants)")
    magics = PHOTO_TYPES.get(got.type.lower())
    if magics is None:
        raise ValueError("un type de photo admis : " + ", ".join(sorted(PHOTO_TYPES)))
    try:
        raw = base64.b64decode(got.data, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("photo illisible (base64)") from None
    if not raw or len(raw) > PHOTO_MAX_BYTES:
        raise ValueError(f"une photo de {PHOTO_MAX_BYTES // 1024} Ko au plus")
    if not any(raw.startswith(m) for m in magics) or (got.type.lower() == "image/webp" and raw[8:12] != b"WEBP"):
        raise ValueError("ces octets ne sont pas une image de ce type")
    return PhotoIn(person, etag, got.type.lower(), raw)


def batch_of(data: dict[str, Any], now_ms: int) -> tuple[InboxBatch, int]:
    """Le lot, validé — formes, tailles, identifiants, dates plausibles — et combien de ses conversations et de ses
    messages ont été écartés (un message illisible est laissé de côté, le reste passe ; un profil illisible aussi, sans
    compter : l'extension lit ce nombre comme des messages refusés). Lève ``ValueError`` si l'enveloppe est
    illisible."""
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
    profiles = tuple(p for p in (profile_of(raw) for raw in got.profiles) if p is not None)
    return (InboxBatch(one_line(got.self.id, 200), one_line(got.self.name, 120), tuple(conversations),
                       tuple(messages), history=got.history, profiles=profiles), dropped)


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
        #: la dernière fois que l'extension de chaque compte s'est manifestée (µs, en mémoire depuis le démarrage) : un
        #: relevé, la connexion en direct, un lot, un accusé — un dimanche sans message neuf, elle est là quand même
        self._contact: dict[str, int] = {}
        #: la boîte d'envoi de chaque compte a changé (ADR 0308) : son numéro de version, et ce qui réveille les
        #: connexions en direct qui l'attendent ; la boucle où elles vivent (posée à la première)
        self._versions: dict[str, int] = {}
        self._moved_events: dict[str, asyncio.Event] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        #: prévenu quand la présence de l'extension d'un compte se voit autrement (son compte) : les écrans relisent
        #: ses comptes (ADR 0308 ; posé par le serveur) ; et la dernière présence ainsi dite, par compte (µs)
        self.on_presence: Callable[[str], None] | None = None
        self._told: dict[str, int] = {}

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
        self._recheck(account)  # l'ancienne ne vaut plus
        return key

    async def revoke_key(self, account: str) -> bool:
        done = await self.settings.revoke_teams_key(account)
        self._recheck(account)
        return done

    def _recheck(self, account: str) -> None:
        """Sa clé a changé : ses connexions en direct la revérifient tout de suite (ADR 0308)."""
        self._live_checked = {k: v for k, v in self._live_checked.items() if v[0] != account}
        self._moved(account)

    def last_contact(self, account: str) -> int:
        """La dernière fois que l'extension de ce compte s'est manifestée depuis le démarrage (µs ; 0 : pas encore) —
        le dernier lot (``last_batch``) dit seulement quand elle a eu du neuf à pousser."""
        return self._contact.get(account, 0)

    def _heard(self, account: str, *, tell: bool = False) -> None:
        """L'extension de ce compte s'est manifestée : sa présence se dit aux écrans si ``tell`` (sa connexion en
        direct s'ouvre), ou si on ne l'a pas dite depuis ``PRESENCE_EVERY_S`` (elle revient d'un silence)."""
        now = int(self.clock())
        self._contact[account] = now
        if tell or now - self._told.get(account, 0) >= PRESENCE_EVERY_S * 1_000_000:
            self._tell(account, now)

    def _tell(self, account: str, now: int) -> None:
        self._told[account] = now
        if self.on_presence is not None:
            call(self.on_presence, account, label="la présence de l'extension Teams")

    def live_closed(self, key: str) -> None:
        """Sa connexion en direct s'est fermée : les écrans de ce compte le relisent (son dernier signe de vie)."""
        known = self._live_checked.get(key)
        account = known[0] if known is not None else self._recognized(key)
        if account:
            self._tell(account, int(self.clock()))

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
        self._heard(account)
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
        said = {"accepted": stored.new, "known": stored.known, "twins": stored.twins, "dropped": dropped}
        if isinstance(data, dict) and data.get("profiles"):
            said["profiles"] = stored.profiles  # les profils neufs ou changés (un lot sans profils : la réponse d'avant)
        return GateResult(ACCEPTED, "Reçu.", data=said)

    def _items(self, account: str) -> list[dict[str, Any]]:
        """La boîte d'envoi d'un compte, telle que l'extension la lit (le relevé comme la connexion en direct)."""
        return [{"id": i.id, "conversation": i.conversation, "title": i.title, "kind": i.kind, "mode": i.mode,
                 "status": i.status, "text": i.text, "created_at": i.created_at, "expires_at": i.expires_at,
                 # le message qu'il cite (ADR 0305), ou rien
                 "quote": {"message": i.quote.message, "author_id": i.quote.author_id, "author": i.quote.author,
                           "at": i.quote.at, "preview": i.quote.preview} if i.quote is not None else None}
                for i in self.store.outbox(account, self.clock())]

    async def outbox(self, key: str) -> GateResult:
        account, refused = self._admit(key)
        if refused is not None:
            return refused
        return GateResult(ACCEPTED, "", data={"items": self._items(account)})

    # ── en direct (ADR 0251, 0308) ──
    async def live(self, key: str) -> GateResult:
        """Ouvrir la boîte d'envoi en direct (``/api/teams/live``) : admise comme un relevé — la clé, l'état, la
        minute —, avec la boîte telle qu'elle est et son numéro de version (``live_wait``)."""
        self._loop = asyncio.get_running_loop()
        account, refused = self._admit(key)
        if refused is not None:
            return refused
        self._heard(account, tell=True)  # elle est là, en direct : ses écrans le voient tout de suite
        version = self._versions.get(account, 0)
        return GateResult(ACCEPTED, "", data={"items": self._items(account), "version": version})

    def store_changed(self, change: Change) -> None:
        """Une écriture du cache de Teams (ADR 0308, ``TeamsStore.on_change``), depuis n'importe quel fil : la boîte
        d'envoi d'un compte a changé (aucun compte nommé : tous), ses connexions en direct la relisent."""
        loop = self._loop
        if change.topic != OUTBOX or loop is None:
            return
        for account in change.accounts or ("",):
            with contextlib.suppress(RuntimeError):  # la boucle s'est arrêtée : plus personne n'attend
                loop.call_soon_threadsafe(self._moved, account)

    def _moved(self, account: str) -> None:
        """(Sur la boucle.) La boîte de ce compte a changé (vide : de tous) : sa version avance, ses attentes
        s'éveillent."""
        for name in (set(self._versions) | set(self._moved_events)) if not account else {account}:
            self._versions[name] = self._versions.get(name, 0) + 1
            event = self._moved_events.pop(name, None)
            if event is not None:
                event.set()

    async def live_wait(self, key: str, seen: int, timeout: float) -> int:
        """Attendre que la boîte d'envoi du compte de cette clé change, au plus ``timeout`` secondes (ADR 0308) : rend
        son numéro de version — autre que ``seen`` si elle a changé depuis la lecture qui l'a donné (``live``,
        ``live_items``). Rien ne se perd entre deux attentes : une version déjà passée rend aussitôt. Une clé qui ne
        vaut plus attend son délai : la relecture qui suit la refuse."""
        known = self._live_checked.get(key)
        account = known[0] if known is not None else self._check(key)[0]
        current = self._versions.get(account, 0)
        if current != seen or timeout <= 0:
            return current
        event = self._moved_events.setdefault(account, asyncio.Event())
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(event.wait(), timeout)
        return self._versions.get(account, 0)

    async def live_items(self, key: str) -> GateResult:
        """La boîte d'une connexion ouverte, relue hors de la boucle quand elle change (``live_wait``) et au plus
        tard au bout du filet de la porte, sans compter dans la minute, avec son numéro de version ; la clé et l'état
        revérifiés toutes les ``LIVE_RECHECK_S`` secondes (une clé retirée, un compte ou Teams coupés ferment la
        connexion), pas à chaque relecture : ce sont deux lectures des réglages."""
        now = time.monotonic()  # noqa: TID251 — la cadence d'une porte HTTP : le vrai temps de la connexion ouverte
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
        self._heard(known[0])  # connectée en direct : elle est là
        version = self._versions.get(known[0], 0)  # lue avant la boîte : un changement pendant la lecture se relira
        return GateResult(ACCEPTED, "", data={"items": await asyncio.to_thread(self._items, known[0]),
                                              "version": version})

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

    async def photo(self, key: str, data: Any) -> GateResult:
        """La photo de profil d'une personne (ADR 0300) : admise comme une image (la clé, l'état, la minute), validée
        avant que rien ne soit rangé ; gardée seulement pour une personne dont ce compte a le profil, à l'empreinte que
        ce profil dit — sinon 404, et l'extension ne la renvoie plus. Rien n'en est journalisé."""
        account, refused = self._admit(key)
        if refused is not None:
            return refused
        try:
            photo = photo_of(data if isinstance(data, dict) else {})
        except ValueError as exc:
            return GateResult(INVALID, str(exc))
        outcome = await asyncio.to_thread(self.store.keep_photo, account, photo, self.clock())
        if outcome == PHOTO_UNKNOWN:
            return GateResult(MISSING, "Cette personne n'est pas connue de ce compte, ou pas avec cette photo.")
        return GateResult(ACCEPTED, "Reçue.", data={"kept": outcome == PHOTO_KEPT})

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

"""Telegram : traduire des messages en perceptions, et livrer ce qu'elle dit.

- **Fermé par défaut** : une conversation n'est admise que si elle est dans la
  liste blanche, ou si c'est la conversation privée d'une propriétaire ; ouvrir
  à tout le monde est une option explicite (``open_to_all``). La liste blanche
  passe avant toute écriture : une conversation non admise ne laisse aucune
  trace (ni perception, ni adresse) ; si on s'adresse à elle, on le lui dit, une
  fois de temps en temps — le bavardage d'un groupe non admis, lui, est ignoré
  sans un mot.
- **Une limite par compte** : le nom d'un robot se découvre, et chaque
  message coûte un tour complet. Au-delà, on le dit.
- **Un groupe est un salon public** : elle y entend tout, mais ne répond
  qu'à ce qui lui est adressé — une mention du robot (lue dans les entités du
  message, jamais par sous-chaîne), une réponse à son message, ou son prénom
  (celui de sa persona).
- **Une réponse part dans le salon d'où vient la question** ; seules les
  conversations privées deviennent des adresses où lui écrire d'elle-même. Une
  pensée à voix haute ne part jamais en message.
- **Un message est traité une fois** : dédoublonné par (conversation, message) ;
  une édition n'est pas un nouveau message (la relève les écarte).
- La livraison est idempotente par clé (la file de sortie livre au moins une
  fois) ; un texte de plus de 4096 caractères est découpé, jamais tronqué.
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from mika.contracts.entry import MindPort
from mika.contracts.runtime import AttachmentMeta, PerceptionReceived
from mika.kernel.events import Content
from mika.ports import delivery as delivery_p
from mika.ports.delivery import Delivery
from mika.ports.preprocess import Perceived, Preprocessor, Upload, render
from mika.vocab import voice
from mika.vocab.affect import strip_prosody

CHANNEL = "telegram"
HANDLE_PREFIX = "tg_"
ROOM_PREFIX = "tg_chat_"
MAX_TEXT = 2000
MAX_FILE = 5_000_000
MAX_FILES = 3
TELEGRAM_LIMIT = 4096
REFUSAL_SPACING_S = 600.0
SENT_MEMORY = 2048

REFUSED = "Désolée, je ne parle pas dans cette conversation."
TOO_FAST = "Doucement… je n'arrive pas à suivre, réessaie dans un instant."
TOO_LONG = "C'est un peu long pour moi : tu peux faire plus court ?"
OVERLOADED = "Je suis débordée, réessaie un peu plus tard."
FAILED = "Désolée, je n'arrive pas à te répondre là tout de suite… Réessaie dans un instant ?"
#: ce qu'elle perçoit quand quelqu'un ouvre la conversation (``/start``) : une arrivée, pas des mots
OPENED = "(vient d'ouvrir la conversation avec toi sur Telegram)"

#: les jetons de voix (canoniques et variantes) et toute balise d'émotion restée : rien de ça ne s'écrit
_VOICE_TOKENS = re.compile(
    r"\[\s*(?:SIGHS?|LAUGH(?:S|ING)?|BREATH(?:E|ES|ING)?|PAUSE[^\]]*|SOUPIR(?:E|S)?|RIRE?S?|RESPIR\w*|EMOTION[^\]]*)\s*\]",
    re.IGNORECASE)


class Bot(Protocol):
    async def send_message(self, chat_id: int, text: str) -> None: ...

    async def download(self, file_id: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class Media:
    """Un fichier joint, par sa référence : il n'est téléchargé qu'une fois
    le message admis (liste blanche, limites)."""

    file_id: str
    name: str
    mime: str
    size: int = 0


@dataclass(frozen=True, slots=True)
class Inbound:
    """Un message Telegram, réduit à ce qui compte."""

    update_id: int
    chat_id: int
    chat_type: str  # private | group | supergroup | channel
    user_id: int
    name: str
    text: str
    mentions_me: bool = False
    reply_to_me: bool = False
    media: tuple[Media, ...] = ()
    #: l'identifiant du message dans sa conversation (0 : inconnu, on dédoublonne sur la mise à jour)
    message_id: int = 0
    #: ``/start`` : la personne ouvre la conversation
    opened: bool = False


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    #: Les conversations admises (identifiants de chat). Vide et fermé : seules les
    #: conversations privées des propriétaires.
    allowed_chats: frozenset[int] = frozenset()
    #: Les comptes propriétaires : leur conversation privée est toujours admise.
    owners: frozenset[int] = frozenset()
    #: Ouvert à tous (liste blanche vide comprise) : seulement sur option explicite.
    open_to_all: bool = False
    #: Messages adressés : au plus ``n`` par ``window`` secondes et par compte.
    rate: tuple[int, float] = (20, 10.0)
    #: Bavardage de groupe entendu (non adressé) : au plus tant par minute et par salon.
    overheard_per_minute: int = 30
    #: le prénom de sa persona : le dire dans un groupe, c'est s'adresser à elle
    name: str = "Mika"

    @property
    def closed(self) -> bool:
        """Personne ne peut lui écrire : la relève n'a pas lieu d'être."""
        return not (self.open_to_all or self.allowed_chats or self.owners)


def handle_of(user_id: int) -> str:
    return f"{HANDLE_PREFIX}{user_id}"


def room_of(chat_id: int) -> str:
    return f"{ROOM_PREFIX}{chat_id}"


def clean_outgoing(text: str) -> str:
    """Le texte d'une messagerie : sans jetons de voix ni balise (Telegram n'a pas de voix), la
    ponctuation recollée là où un jeton laissait un trou (« Bon . » ; l'espace française avant
    « ! ? ; : » reste)."""
    text = strip_prosody(_VOICE_TOKENS.sub("", text))
    text = re.sub(r"[ \t]+([,.…)])", r"\1", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Découpe un texte trop long en messages, aux paragraphes, sinon aux phrases,
    sinon aux mots ; jamais au milieu d'un mot quand c'est évitable."""
    text = text.strip()
    out: list[str] = []
    while len(text) > limit:
        window = text[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 3:
            ends = [m.end() for m in re.finditer(r"[.!?…][»\"')\]]*\s", window)]
            cut = ends[-1] if ends and ends[-1] >= limit // 3 else window.rfind(" ")
        if cut <= 0:
            cut = limit
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        out.append(text)
    return out


class _Window:
    def __init__(self, n: int, window: float) -> None:
        self.n, self.window = n, window
        self.hits: list[float] = []

    def allow(self, now: float) -> bool:
        self.hits = [t for t in self.hits if now - t < self.window]
        if len(self.hits) >= self.n:
            return False
        self.hits.append(now)
        return True


@dataclass(slots=True)
class TelegramChannel:
    port: MindPort
    bot: Bot
    config: TelegramConfig = field(default_factory=TelegramConfig)
    monotonic: Callable[[], float] = time.monotonic
    preprocess: Preprocessor | None = None
    _limits: dict[str, _Window] = field(default_factory=dict)
    _overheard: dict[int, _Window] = field(default_factory=dict)
    _told: dict[tuple[int, str], float] = field(default_factory=dict)
    _sent: OrderedDict[str, None] = field(default_factory=OrderedDict)
    delivered: list[tuple[int, str]] = field(default_factory=list)

    def admitted(self, chat_id: int, chat_type: str, user_id: int) -> bool:
        """Cette conversation peut-elle lui parler ? Fermé par défaut."""
        if self.config.open_to_all or chat_id in self.config.allowed_chats:
            return True
        return chat_type == "private" and user_id in self.config.owners and chat_id == user_id

    def addressed(self, m: Inbound) -> bool:
        if m.chat_type == "private" or m.mentions_me or m.reply_to_me or m.opened:
            return True
        name = self.config.name.strip()
        return bool(name) and bool(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", m.text, re.IGNORECASE))

    async def _say_once(self, chat_id: int, what: str, text: str) -> None:
        """Un refus se dit, mais pas à chaque message (sinon le refus devient
        lui-même un amplificateur)."""
        now = self.monotonic()
        last = self._told.get((chat_id, what))
        if last is not None and now - last < REFUSAL_SPACING_S:
            return
        self._told[(chat_id, what)] = now
        if len(self._told) > SENT_MEMORY:
            for key in [k for k, t in self._told.items() if now - t >= REFUSAL_SPACING_S]:
                del self._told[key]
        await self.bot.send_message(chat_id, text)

    async def _files(self, m: Inbound) -> tuple[str, tuple[AttachmentMeta, ...]]:
        """Ce qu'elle perçoit des fichiers joints : téléchargés maintenant (le
        message est admis), bornés, lus par le même prétraitement que le web."""
        uploads: list[Upload] = []
        notes: list[Perceived] = []
        for f in m.media[:MAX_FILES]:
            kind = Upload(f.name, f.mime, b"").kind
            if f.size > MAX_FILE:
                notes.append(Perceived(f.name, kind, "trop gros pour moi (5 Mo au plus)", False, "too_large"))
                continue
            try:
                data = await self.bot.download(f.file_id)
            except (OSError, RuntimeError, ValueError) as exc:
                notes.append(Perceived(f.name, kind, "je n'ai pas réussi à le récupérer", False, type(exc).__name__))
                continue
            if len(data) > MAX_FILE:
                notes.append(Perceived(f.name, kind, "trop gros pour moi (5 Mo au plus)", False, "too_large"))
                continue
            uploads.append(Upload(f.name, f.mime, data))
        if uploads and self.preprocess is not None:
            notes += await self.preprocess.perceive(uploads)
        elif uploads:
            notes += [Perceived(u.name, u.kind, "reçu, mais je ne peux pas encore le lire", False) for u in uploads]
        meta = tuple(AttachmentMeta(name=p.name, kind=p.kind, extracted=p.extracted, error=p.error) for p in notes)
        return render(notes), meta

    async def receive(self, m: Inbound) -> str:
        if m.chat_type == "channel" or (not m.text.strip() and not m.media and not m.opened):
            return "ignored"
        addressed = self.addressed(m)
        if not self.admitted(m.chat_id, m.chat_type, m.user_id):
            if addressed:  # on lui parle : elle le dit, de temps en temps ; le bavardage est ignoré sans un mot
                await self._say_once(m.chat_id, "refused", REFUSED)
            return "refused"  # rien n'est écrit : ni perception, ni adresse
        private = m.chat_type == "private"
        handle = handle_of(m.user_id)
        now = self.monotonic()
        if addressed:
            window = self._limits.setdefault(handle, _Window(*self.config.rate))
            if not window.allow(now):
                await self._say_once(m.chat_id, "rate", TOO_FAST)
                return "rate_limited"
            if len(m.text) > MAX_TEXT:
                await self.bot.send_message(m.chat_id, TOO_LONG)
                return "too_long"
        else:
            window = self._overheard.setdefault(m.chat_id, _Window(self.config.overheard_per_minute, 60.0))
            if not window.allow(now):
                return "ignored"  # le bavardage d'un groupe très actif ne s'écrit pas en entier
        text, attachments = (OPENED if m.opened else m.text[:MAX_TEXT]), ()
        if addressed and m.media:  # le bavardage d'un groupe n'est pas téléchargé
            seen, attachments = await self._files(m)
            text = "\n".join(x for x in (text, seen) if x)
        if not text.strip():
            return "ignored"
        p = PerceptionReceived(
            handle=handle, channel=CHANNEL, text=Content.of(text), room=None if private else room_of(m.chat_id),
            public=not private, reply_ref=str(m.chat_id), display_name=m.name, addressed=addressed,
            attachments=attachments,
        )
        key = f"tg:{m.chat_id}:{m.message_id}" if m.message_id else f"tg:{m.update_id}"
        got = await self.port.perceive(p, dedupe_key=key)
        if got.status == "overloaded":
            await self._say_once(m.chat_id, "overloaded", OVERLOADED)
            return "overloaded"
        return "duplicate" if got.duplicate else "accepted"

    @staticmethod
    def chat_for(d: Delivery) -> int | None:
        """Le salon d'où venait la question ; sinon la conversation privée."""
        if d.room and d.room.startswith(ROOM_PREFIX):
            try:
                return int(d.room[len(ROOM_PREFIX):])
            except ValueError:
                return None
        if d.target and d.target.startswith(HANDLE_PREFIX):
            try:
                return int(d.target[len(HANDLE_PREFIX):])
            except ValueError:
                return None
        return None

    async def deliver(self, d: Delivery) -> bool:
        if d.kind == delivery_p.REPLY_ABSTAINED or d.kind == delivery_p.STATE:
            return True  # un silence, un changement d'état : rien à écrire dans une messagerie
        if d.kind == delivery_p.SPEECH and d.persona == voice.INNER:
            return True  # une pensée ne part jamais en message
        if d.kind not in (delivery_p.SPEECH, delivery_p.REPLY_FAILED):
            return True
        chat = self.chat_for(d)
        if chat is None:
            return False
        private = chat > 0
        if not self.admitted(chat, "private" if private else "group", chat):
            return True  # plus admise depuis : on n'écrit pas
        if d.key in self._sent:
            return True
        text = FAILED if d.kind == delivery_p.REPLY_FAILED else clean_outgoing(d.text)
        for part in split_message(text):
            await self.bot.send_message(chat, part)
            self.delivered.append((chat, part))
            if len(self.delivered) > SENT_MEMORY:
                del self.delivered[: len(self.delivered) - SENT_MEMORY]
        self._sent[d.key] = None
        while len(self._sent) > SENT_MEMORY:
            self._sent.popitem(last=False)
        return True

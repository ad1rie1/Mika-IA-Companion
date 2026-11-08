"""Le port de Teams (ADR 0069) : ce que l'extension de navigateur lui apporte de Teams, ses brouillons, et ce
qui doit repartir vers Teams.

« Journaliser l'esprit, pas le monde » : les messages, les conversations, les brouillons et la file d'envoi vivent
dans le cache de l'adaptateur (``teams.db``) ; le journal ne garde que ce qu'elle en a remarqué, proposé, appris.
Un message Teams est un texte venu d'ailleurs : une donnée, jamais une consigne.

- **Rien ne parle à Microsoft ici.** L'extension (``frontend/Extension``), dans l'onglet Teams de la personne qui
  s'occupe d'elle, pousse ce que le client reçoit (``store_batch``) et relève ce qui doit repartir (``outbox``),
  puis accuse (``settle``).
- **Une référence est attribuée par l'adaptateur** (``t`` + une empreinte de la conversation et de l'identifiant du
  message) : l'extension ne choisit pas comment un message se désigne dans un prompt.
- **Elle écrit à la place de sa propriétaire** : le message part du compte Teams de cette personne, sous son nom.
  Un brouillon vit ici ; une proposition d'envoi ne porte que son identifiant et le condensé de ce qui a été montré
  (``Preview.digest``). La signature (facultative) est ajoutée ici, jamais écrite par le modèle.
- **Trois façons de partir** (le mode, réglé par un opérateur) : *brouillon* — posé dans la zone de saisie de la
  conversation, c'est la personne qui l'envoie (ou pas) ; *validation* — il part après son accord ; *autonome* — il
  part sans accord. Dans tous les cas, ce qui part est ce que l'aperçu montrait.
- **Un Teams par personne** (ADR 0186) : chaque compte (``accounts``) a sa clé d'extension, ses conversations, ses
  brouillons et sa file. Tout ce que l'extension pousse ou relève ne concerne que le compte de sa clé ; une
  conversation se désigne par son compte et son identifiant (``conversation_key``) ; une référence de message reste
  unique entre les comptes (``message_ref``). Le compte d'avant (un seul Teams) est ``DEFAULT_ACCOUNT``.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from mika.ports.drafts import to_fill as to_fill
from mika.ports.gate import ACCEPTED as ACCEPTED
from mika.ports.gate import CONFLICT as CONFLICT
from mika.ports.gate import MISSING as MISSING
from mika.ports.gate import GateResult, KeyState
from mika.ports.sql import HANDLE_MAX, fit

#: le compte d'avant l'ADR 0186 (un seul Teams) : ce qui était déjà là, et le compte d'une installation neuve
DEFAULT_ACCOUNT = "principal"
#: la clé d'un compte : des minuscules, chiffres, - ou _ (40 au plus), comme celle d'une boîte (``ports.mail``)
ACCOUNT_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
ACCOUNT_KEY_RULE = "des minuscules, chiffres, - ou _ (40 au plus), en commençant par une lettre ou un chiffre"
#: ce qui sépare le compte de l'identifiant dans la clé d'une conversation (ni dans l'un, ni dans l'autre)
_SEPARATOR = "~"

#: le préfixe d'une clé d'extension (une clé se reconnaît, et ne se confond ni avec un jeton de compte, ``mw_``,
#: ni avec une clé de réveil, ``mwk_``)
KEY_PREFIX = "mtk_"

# ── Les modes d'envoi ──
Mode = Literal["brouillon", "validation", "autonome"]
MODES: tuple[tuple[str, str], ...] = (
    ("brouillon", "brouillon dans Teams — posé dans la zone de saisie, c'est toi qui l'envoies"),
    ("validation", "après ton accord — il part une fois que tu l'as accepté"),
    ("autonome", "autonome — il part sans te demander"),
)
#: ce que fait l'extension d'un élément de la file : le poser dans la zone de saisie, ou l'envoyer
DRAFT, SEND = "draft", "send"

# ── Les états d'un brouillon (dans l'adaptateur) ──
WRITTEN = "brouillon"  # écrit, pas encore en file (il attend un accord, ou d'être proposé)
QUEUED = "en_file"  # dans la file : l'extension le relèvera
SENDING = "envoi"  # réservé par une extension qui l'envoie (validation, autonome) : personne d'autre ne l'enverra
PLACED = "pose"  # posé dans la zone de saisie de Teams (mode brouillon) : la personne l'enverra, ou pas
GONE = "parti"
UNUSED = "inutilise"  # jamais envoyé : la personne a écrit autre chose, ou personne ne l'a envoyé à temps
FAILED = "echec"
DISCARDED = "abandonne"  # refusé avant de partir
OPEN_STATES = frozenset({QUEUED, SENDING, PLACED})

# ── Les accusés de l'extension ──
#: « sending » réserve un envoi avant de le faire (un seul navigateur l'enverra ; le second reçoit un refus)
RESULTS = ("sending", "placed", "sent", "failed")

#: un identifiant de conversation Teams tel que le client les écrit (``19:…@thread.v2``, ``19:a_b@unq.gbl.spaces``)
CONVERSATION_ID = re.compile(r"^\d{1,3}:[A-Za-z0-9@._:=+\-]{1,300}$")
#: le préfixe des sujets (au sens de l'oubli) d'une personne connue par Teams
HANDLE_PREFIX = "teams:"


def message_ref(conversation: str, external_id: str, account: str = DEFAULT_ACCOUNT) -> str:
    """La référence d'un message : attribuée ici, stable pour un même message, sans rien de ce que l'expéditeur a
    choisi. Le même message vu par deux comptes (un groupe où deux personnes sont) a deux références ; celle du
    compte d'avant ne change pas (ce qui est déjà au journal la retrouve)."""
    salt = "" if account == DEFAULT_ACCOUNT else f"{account}\n"
    return "t" + hashlib.sha256(f"{salt}{conversation}\n{external_id}".encode()).hexdigest()[:12]


def conversation_key(account: str, conversation: str) -> str:
    """Une conversation, désignée entre les comptes (une fiche, une ressource) : son identifiant seul pour le compte
    d'avant (ses liens restent), sinon ``<compte>~<identifiant>``."""
    return conversation if account in ("", DEFAULT_ACCOUNT) else f"{account}{_SEPARATOR}{conversation}"


def split_conversation_key(key: str) -> tuple[str, str]:
    """``(compte, identifiant)`` d'une clé de conversation (``conversation_key``)."""
    account, sep, conversation = key.partition(_SEPARATOR)
    if sep and ACCOUNT_KEY.fullmatch(account):
        return account, conversation
    return DEFAULT_ACCOUNT, key


def person_handle(author_id: str) -> str:
    """``teams:8:orgid:…`` : le sujet (au sens de l'oubli) de quelqu'un qu'on ne connaît que par Teams."""
    return fit(f"{HANDLE_PREFIX}{author_id.strip().lower()}", HANDLE_MAX) if author_id.strip() else ""


def plain(text: str) -> str:
    """Un texte comparé à un autre : blancs repliés, casse ignorée (un brouillon envoyé tel quel l'est encore si
    l'éditeur de Teams a touché aux espaces)."""
    return " ".join(unicodedata.normalize("NFKC", text or "").split()).casefold()


@dataclass(frozen=True, slots=True)
class Message:
    """Un message d'une conversation Teams, tel que l'adaptateur le garde."""

    ref: str
    conversation: str
    author: str
    author_id: str
    at: int  # µs
    text: str
    own: bool = False  # écrit par la personne à qui est le compte (depuis son compte)
    mentions_me: bool = False  # il mentionne cette personne
    #: le compte Teams qui l'a reçu (ADR 0186)
    account: str = DEFAULT_ACCOUNT


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str
    title: str
    kind: str  # dm | group | channel | meeting | other
    last_at: int = 0
    messages: int = 0
    account: str = DEFAULT_ACCOUNT


@dataclass(frozen=True, slots=True)
class Draft:
    """Un brouillon : écrit par elle (``author`` vide) ; retouché par un opérateur (``edited_by``)."""

    id: str
    conversation: str
    body: str
    #: la référence du message auquel il répond (vide : un message dans la conversation)
    reply_to: str = ""
    author: str = ""
    created: int = 0
    updated: int = 0
    state: str = WRITTEN
    #: ce que fera l'extension quand il sera en file (``draft`` : le poser ; ``send`` : l'envoyer)
    mode: str = ""
    #: le condensé de ce qui a été mis en file (ce qui part est ce qui a été montré)
    digest: str = ""
    #: le texte mis en file, signature comprise : ce que l'extension posera ou enverra
    final: str = ""
    #: µs ; au-delà, un élément de la file que personne n'a traité ne part plus
    expires_at: int = 0
    placed_at: int = 0
    sent_at: int = 0
    #: ce qui est vraiment parti (la personne l'a peut-être retouché dans Teams)
    sent_text: str = ""
    edited: bool = False
    edited_by: str = ""
    reason: str = ""
    #: le compte d'où il part (celui de la conversation à laquelle il répond)
    account: str = DEFAULT_ACCOUNT


@dataclass(frozen=True, slots=True)
class Preview:
    """Exactement ce qui partira, et son condensé."""

    conversation: str
    title: str
    text: str
    digest: str
    #: pourquoi il ne peut pas partir tel quel (vide : il peut)
    blocked: str = ""


@dataclass(frozen=True, slots=True)
class OutboxItem:
    """Ce que l'extension relève : un brouillon à poser, ou un message à envoyer."""

    id: str
    conversation: str
    title: str
    kind: str
    mode: str
    status: str  # queued | placed
    text: str
    created_at: int  # ms (pour le navigateur)
    expires_at: int  # ms, 0 : jamais


@dataclass(frozen=True, slots=True)
class Settled:
    """Ce qu'est devenu un brouillon en file : posé, parti (``edited`` : la personne l'a retouché), inutilisé,
    échoué."""

    draft: str
    state: str
    edited: bool = False
    reason: str = ""


@dataclass(frozen=True, slots=True)
class InboxMessage:
    id: str
    conversation: str
    author: str
    author_id: str
    time_ms: int
    text: str
    own: bool = False
    mentions_me: bool = False
    #: supprimé dans Teams : son texte est effacé du cache
    deleted: bool = False


@dataclass(frozen=True, slots=True)
class InboxConversation:
    id: str
    title: str = ""
    kind: str = "other"


@dataclass(frozen=True, slots=True)
class InboxBatch:
    """Un lot poussé par l'extension (déjà validé et borné par la porte)."""

    self_id: str = ""
    self_name: str = ""
    conversations: tuple[InboxConversation, ...] = ()
    messages: tuple[InboxMessage, ...] = ()


@dataclass(frozen=True, slots=True)
class Stored:
    """Ce qu'un lot a changé : les messages neufs, ceux déjà connus, les conversations où la personne a écrit (avec
    l'heure Teams, µs, de son dernier message dans chacune), et les brouillons que ses messages ont réglés."""

    new: int = 0
    known: int = 0
    replied: tuple[tuple[str, int], ...] = ()
    settled: tuple[Settled, ...] = ()


@dataclass(frozen=True, slots=True)
class Voice:
    """Comment elle écrit dans Teams (réglé par un opérateur : de confiance)."""

    display_name: str = ""
    tone: str = ""
    instructions: str = ""
    signature: str = ""


@dataclass(frozen=True, slots=True)
class AccountInfo:
    """Un compte Teams (ADR 0186) : ses réglages sans voix, et ce que son extension en a dit."""

    key: str
    label: str = ""
    #: à qui il est : vide, ses propriétaires (toi) ; ``elle`` ; ``personne:<clé>``
    owner: str = ""
    #: le dernier lot poussé par son extension (µs, 0 : jamais)
    last_batch: int = 0
    #: l'identifiant et le nom que Teams donne à la personne de ce compte (vides : pas encore vus)
    self_id: str = ""
    self_name: str = ""
    #: décoché : son extension est refusée, rien n'arrive ni ne part
    enabled: bool = True

    @property
    def name(self) -> str:
        return self.label or self.key


class TeamsPort(Protocol):
    def accounts(self) -> list[AccountInfo]:
        """Ses comptes réglés, dans l'ordre de leur clé."""
        ...

    def account(self, key: str) -> AccountInfo | None: ...

    def configured(self, account: str = "") -> bool:
        """L'extension de ce compte (vide : d'un compte au moins) a déjà poussé quelque chose."""
        ...

    def last_batch(self, account: str) -> int: ...

    def voice(self, account: str) -> Voice: ...

    def owner(self, account: str) -> tuple[str, str]:
        """L'identifiant Teams et le nom de la personne de ce compte (vides : pas encore vus)."""
        ...

    def store_batch(self, account: str, batch: InboxBatch, now: int) -> Stored: ...

    async def fetch_new(self, limit: int, *, accounts: Sequence[str] | None = None) -> list[Message]:
        """Les messages reçus (pas ceux de la personne du compte) pas encore accusés, du plus ancien au plus
        récent ; ``accounts`` : de ces comptes seulement."""
        ...

    def ack(self, refs: Sequence[str]) -> None: ...

    def message(self, ref: str) -> Message | None: ...

    def thread(self, account: str, conversation: str, limit: int, *, before: int = 0) -> list[Message]:
        """Les derniers messages d'une conversation (avant ``before`` µs, 0 : tous), du plus ancien au plus
        récent."""
        ...

    def conversation(self, account: str, conversation: str) -> Conversation | None: ...

    def conversations(self, limit: int, *, text: str = "", accounts: Sequence[str] | None = None) \
            -> list[Conversation]: ...

    def title(self, account: str, conversation: str) -> str: ...

    def save_draft(self, d: Draft) -> Draft: ...

    def draft(self, draft_id: str) -> Draft | None: ...

    def drafts(self, limit: int, *, state: str = "", accounts: Sequence[str] | None = None) -> list[Draft]: ...

    def discard_draft(self, draft_id: str) -> None: ...

    def preview(self, draft_id: str, *, her: str = "") -> Preview | None:
        """Ce qui partirait ; ``her`` : son nom (celui de sa persona), que la signature peut citer."""
        ...

    def enqueue(self, draft_id: str, *, mode: str, digest: str, expires_at: int, now: int, her: str = "") -> str:
        """Met en file ce qui a été montré : vide si c'est fait (ou l'était déjà), sinon pourquoi pas."""
        ...

    def outbox(self, account: str, now: int) -> list[OutboxItem]:
        """Ce que l'extension de ce compte doit poser ou envoyer."""
        ...

    def settle(self, draft_id: str, result: str, *, now: int, text: str = "", reason: str = "",
               account: str = "") -> tuple[str, Settled | None]:
        """Un accusé (« placed », « sent », « failed ») ou une échéance (« expired ») : (issue, ce qui a changé).
        Rejoué, il rend la même issue sans rien changer. ``account`` : l'extension de ce compte accuse — un brouillon
        d'un autre compte lui est inconnu."""
        ...

    def expire_written(self, account: str, now: int) -> int:
        """Ce que la personne a écrit elle-même (ADR 0189) et qui n'est pas parti à temps : réglé (``inutilise``, ou
        ``echec`` s'il était en cours d'envoi). Rend combien."""
        return 0

    def drop_account(self, account: str) -> int:
        """Un compte supprimé des réglages : tout ce que son extension avait apporté s'efface (lignes effacées)."""
        ...

    async def forget(self, subject: str) -> int: ...


class TeamsKeys(Protocol):
    """Les clés de l'extension, une par compte (le port ``teams_keys`` : ``app/teams.TeamsDesk``). Une clé neuve
    rend l'ancienne de ce compte inutile ; seule son empreinte est gardée."""

    def key_state(self, account: str) -> KeyState | None: ...

    async def new_key(self, account: str, by: str) -> str:
        """Une clé neuve pour ce compte, montrée une seule fois ; ``ValueError`` si le compte n'existe pas."""
        ...

    async def revoke_key(self, account: str) -> bool:
        """Retirer la clé de ce compte ; ``False`` s'il n'en avait pas."""
        ...


class TeamsGate(Protocol):
    """La porte (``app/teams.TeamsDesk``) : ce que le transport web lui passe, ce qu'elle a décidé. Rien n'est rangé
    ni journalisé avant qu'elle ait admis la clé et la requête."""

    async def inbox(self, key: str, data: object) -> GateResult: ...

    async def outbox(self, key: str) -> GateResult: ...

    async def ack(self, key: str, item: str, data: object) -> GateResult: ...

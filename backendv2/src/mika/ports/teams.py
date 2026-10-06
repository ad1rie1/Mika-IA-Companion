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
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

#: le préfixe d'une clé d'extension (une clé se reconnaît, et ne se confond ni avec un jeton de compte, ``mw_``,
#: ni avec une clé de réveil, ``mwk_``)
KEY_PREFIX = "mtk_"

# ── Les issues de la porte (``POST /api/teams/…``) ──
ACCEPTED = "accepted"
#: clé absente ou fausse : la même réponse dans les deux cas
UNKNOWN = "unknown"
#: Teams est désactivé dans ses réglages
DISABLED = "disabled"
#: une requête illisible (forme, tailles)
INVALID = "invalid"
#: trop de requêtes
BUSY = "busy"
#: un élément de la file inconnu
MISSING = "missing"
#: un accusé impossible (« posé » pour un message déjà parti)
CONFLICT = "conflict"

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

#: ce qu'un brouillon ne peut pas contenir au moment de partir (ce qu'elle n'a pas su), sous toutes ses graphies
_TO_FILL = re.compile(r"\[\s*(?:a\s*)?(?:completer|remplir|preciser)\b")
#: un identifiant de conversation Teams tel que le client les écrit (``19:…@thread.v2``, ``19:a_b@unq.gbl.spaces``)
CONVERSATION_ID = re.compile(r"^\d{1,3}:[A-Za-z0-9@._:=+\-]{1,300}$")
#: le préfixe des sujets (au sens de l'oubli) d'une personne connue par Teams
HANDLE_PREFIX = "teams:"


def to_fill(*texts: str) -> bool:
    """Reste-t-il un « [À COMPLÉTER » (casse, accents, « à remplir », « à préciser ») ?"""
    for text in texts:
        folded = "".join(ch for ch in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(ch))
        if _TO_FILL.search(folded.casefold()):
            return True
    return False


def message_ref(conversation: str, external_id: str) -> str:
    """La référence d'un message : attribuée ici, stable pour un même message, sans rien de ce que l'expéditeur a
    choisi."""
    return "t" + hashlib.sha256(f"{conversation}\n{external_id}".encode()).hexdigest()[:12]


def person_handle(author_id: str) -> str:
    """``teams:8:orgid:…`` : le sujet (au sens de l'oubli) de quelqu'un qu'on ne connaît que par Teams."""
    return f"{HANDLE_PREFIX}{author_id.strip().lower()}" if author_id.strip() else ""


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
    own: bool = False  # écrit par la personne qui s'occupe d'elle (depuis son compte)
    mentions_me: bool = False  # il mentionne cette personne


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str
    title: str
    kind: str  # dm | group | channel | meeting | other
    last_at: int = 0
    messages: int = 0


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
class GateResult:
    outcome: str
    message: str = ""
    data: dict[str, object] = field(default_factory=dict)
    retry_after: int = 0


@dataclass(frozen=True, slots=True)
class KeyState:
    """Ce qu'on montre de la clé de l'extension : jamais le secret, de quoi la reconnaître."""

    hint: str
    created_at: int
    by: str = ""


class TeamsPort(Protocol):
    def configured(self) -> bool:
        """L'extension a déjà poussé quelque chose."""
        ...

    def voice(self) -> Voice: ...

    def owner(self) -> tuple[str, str]:
        """L'identifiant Teams et le nom de la personne qui s'occupe d'elle (vides : pas encore vus)."""
        ...

    def store_batch(self, batch: InboxBatch, now: int) -> Stored: ...

    async def fetch_new(self, limit: int) -> list[Message]:
        """Les messages reçus (pas les siens) pas encore accusés, du plus ancien au plus récent."""
        ...

    def ack(self, refs: Sequence[str]) -> None: ...

    def message(self, ref: str) -> Message | None: ...

    def thread(self, conversation: str, limit: int, *, before: int = 0) -> list[Message]:
        """Les derniers messages d'une conversation (avant ``before`` µs, 0 : tous), du plus ancien au plus
        récent."""
        ...

    def conversation(self, conversation: str) -> Conversation | None: ...

    def conversations(self, limit: int, *, text: str = "") -> list[Conversation]: ...

    def save_draft(self, d: Draft) -> Draft: ...

    def draft(self, draft_id: str) -> Draft | None: ...

    def drafts(self, limit: int, *, state: str = "") -> list[Draft]: ...

    def discard_draft(self, draft_id: str) -> None: ...

    def preview(self, draft_id: str, *, her: str = "") -> Preview | None:
        """Ce qui partirait ; ``her`` : son nom (celui de sa persona), que la signature peut citer."""
        ...

    def enqueue(self, draft_id: str, *, mode: str, digest: str, expires_at: int, now: int, her: str = "") -> str:
        """Met en file ce qui a été montré : vide si c'est fait (ou l'était déjà), sinon pourquoi pas."""
        ...

    def outbox(self, now: int) -> list[OutboxItem]: ...

    def settle(self, draft_id: str, result: str, *, now: int, text: str = "", reason: str = "") \
            -> tuple[str, Settled | None]:
        """Un accusé (« placed », « sent », « failed ») ou une échéance (« expired ») : (issue, ce qui a changé).
        Rejoué, il rend la même issue sans rien changer."""
        ...

    async def forget(self, subject: str) -> int: ...


class TeamsGate(Protocol):
    """La porte (``app/teams.TeamsDesk``) : ce que le transport web lui passe, ce qu'elle a décidé. Rien n'est rangé
    ni journalisé avant qu'elle ait admis la clé et la requête."""

    async def inbox(self, key: str, data: object) -> GateResult: ...

    async def outbox(self, key: str) -> GateResult: ...

    async def ack(self, key: str, item: str, data: object) -> GateResult: ...

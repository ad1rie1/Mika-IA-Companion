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

from mika.ports.gate import GateResult, KeyState

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
#: ce que fait l'extension d'un élément de la file (``Draft.mode``, ``OutboxItem.mode``) : le poser dans la
#: zone de saisie, ou l'envoyer. Ces valeurs sont le protocole de l'extension ; ni la capacité ni la raison de
#: preuve du contrat (``contracts.teams.SEND``, ``contracts.teams.DRAFT``)
OUTBOX_PLACE, OUTBOX_SEND = "draft", "send"

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


#: un compte d'organisation, quelle que soit la forme de son identifiant (« orgid:<uuid> », une adresse qui le contient)
_ORGID = re.compile(r"orgid:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.IGNORECASE)


def person_key(identifier: str) -> str:
    """L'identifiant d'une personne tel que ses profils et ses photos se rangent (ADR 0298, 0300) : ``8:orgid:<uuid>``
    en minuscules pour un compte d'organisation, quelle que soit la forme reçue ; sinon tel quel, en minuscules."""
    found = _ORGID.search(identifier or "")
    return f"8:orgid:{found.group(1).lower()}" if found else (identifier or "").strip().lower()


def plain(text: str) -> str:
    """Un texte comparé à un autre : blancs repliés, casse ignorée (un brouillon envoyé tel quel l'est encore si
    l'éditeur de Teams a touché aux espaces)."""
    return " ".join(unicodedata.normalize("NFKC", text or "").split()).casefold()


@dataclass(frozen=True, slots=True)
class Reaction:
    """Une réaction à un message (👍, ❤️…, ADR 0300) : sa clé dans Teams (``like``, ``heart``, ``1f44f_clappinghands``…),
    combien l'ont posée, si la personne du compte en est (``mine``), et qui — ``by`` : leurs identifiants Teams en
    minuscules (dix au plus, les premiers à l'avoir posée ; le compte, lui, est entier) ; ``names`` : leurs noms tels
    que ce compte les connaît, au même rang (vide : inconnu, ou la personne du compte)."""

    key: str
    count: int
    mine: bool = False
    by: tuple[str, ...] = ()
    names: tuple[str, ...] = ()


#: les réactions classiques de Teams, et quelques alias de Skype ; une clé qui commence par ses points de code
#: (``1f44f_clappinghands``, ``2764-fe0f_heart``) se lit par eux (``emoji_of``)
REACTION_EMOJI: dict[str, str] = {
    "like": "👍", "heart": "❤️", "laugh": "😆", "surprised": "😮", "sad": "😢", "angry": "😡",
    "yes": "👍", "smile": "🙂", "cry": "😢", "wink": "😉", "clap": "👏", "fire": "🔥", "ok": "👌", "pray": "🙏",
    "party": "🎉", "celebrate": "🎉", "rocket": "🚀", "eyes": "👀", "thinking": "🤔", "muscle": "💪", "100": "💯",
}
_CODE_POINTS = re.compile(r"((?:[0-9a-f]{4,6})(?:-[0-9a-f]{4,6})*)(?:_[a-z0-9_+-]*)?")


def emoji_of(key: str) -> str:
    """L'emoji d'une réaction : celui de sa clé connue, ou de ses points de code ; vide si on ne sait pas (le code
    montre alors la clé)."""
    if key in REACTION_EMOJI:
        return REACTION_EMOJI[key]
    found = _CODE_POINTS.fullmatch(key or "")
    groups = found.group(1).split("-") if found is not None else []
    # un mot fait de lettres hexadécimales (« face », « cafe ») n'est pas un point de code : ceux des emojis ont tous un
    # chiffre
    if not groups or not all(any(c.isdigit() for c in h) for h in groups):
        return ""
    points = [int(h, 16) for h in groups]
    if not all(0x20 < p <= 0x10FFFF and not 0xD800 <= p <= 0xDFFF for p in points):
        return ""
    return "".join(chr(p) for p in points)


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
    #: ses réactions (ADR 0300), dans l'ordre de Teams : lues avec lui, elles ne déclenchent jamais rien
    reactions: tuple[Reaction, ...] = ()
    #: le message qu'il cite (ADR 0305) — son texte (``text``) ne le reprend pas
    quote: Quote | None = None


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


#: l'extrait d'un message cité, au plus (caractères) : Teams montre le message cité d'après son identifiant, l'extrait
#: n'est que ce que dit la citation elle-même (ADR 0305)
QUOTE_PREVIEW_MAX = 160
#: les conversations où un envoi cite le message auquel il répond (ADR 0305) : un tête-à-tête (sous condition), un groupe
QUOTE_KINDS = ("dm", "group")


@dataclass(frozen=True, slots=True)
class Quote:
    """Le message que cite un envoi, ou un message reçu (ADR 0305) : son identifiant chez Teams (l'heure de son
    arrivée, en ms — le seul que Teams sache citer), son auteur (son identifiant Teams, ``8:orgid:…`` ou ``28:…`` pour
    un robot, et son nom), son heure (ms) et un court extrait ; ``ref`` : la référence du message cité chez elle, quand
    elle l'a (de quoi y aller depuis la citation)."""

    message: str
    author_id: str
    author: str
    at: int
    preview: str
    ref: str = ""


@dataclass(frozen=True, slots=True)
class OutboxItem:
    """Ce que l'extension relève : un brouillon à poser, ou un message à envoyer — avec, s'il y a lieu, le message
    qu'il cite (ADR 0305)."""

    id: str
    conversation: str
    title: str
    kind: str
    mode: str
    status: str  # queued | placed
    text: str
    created_at: int  # ms (pour le navigateur)
    expires_at: int  # ms, 0 : jamais
    quote: Quote | None = None


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
    #: ses images, que l'extension annonce et enverra à part (ADR 0258) : il attend qu'elles soient lues
    images: int = 0
    #: ses réactions (ADR 0300), sans ``names`` ; ``None`` : l'extension n'en a rien dit (le cache garde les siennes),
    #: ``()`` : aucune (le cache efface les siennes)
    reactions: tuple[Reaction, ...] | None = None
    #: le message qu'il cite (ADR 0305), séparé de son texte par l'extension ; ``None`` : rien de dit
    quote: Quote | None = None


@dataclass(frozen=True, slots=True)
class ImageIn:
    """Une image d'un message, telle que l'extension l'envoie (déjà validée par la porte, ADR 0258) : son message
    (sa conversation, son identifiant Teams), son identifiant d'image, son rang dans le message, ses octets."""

    conversation: str
    message_id: str
    image: str
    position: int
    mime: str
    data: bytes


@dataclass(frozen=True, slots=True)
class ImageToRead:
    """Une image gardée que Mika n'a pas encore regardée (``id`` : sa ligne)."""

    id: int
    ref: str
    image: str
    mime: str
    data: bytes


@dataclass(frozen=True, slots=True)
class MessageImage:
    """Une image d'un message, sans ses octets : ce que le fil en montre."""

    ref: str
    image: str
    position: int
    mime: str
    size: int
    seen: str
    read: bool


#: une image gardée, au plus (octets, ADR 0258) : la porte refuse au-delà
IMAGE_MAX_BYTES = 8 * 1024 * 1024
#: ce que devient une image envoyée : gardée, déjà là, ou sans message connu (son message n'est pas arrivé)
IMAGE_KEPT = "kept"
IMAGE_KNOWN = "known"
IMAGE_NO_MESSAGE = "no_message"


@dataclass(frozen=True, slots=True)
class PhotoIn:
    """La photo de profil d'une personne (ADR 0300), telle que l'extension l'envoie (déjà validée par la porte) : son
    identifiant Teams (en minuscules), l'empreinte que Teams donne à cette photo (``avatarETag``), son type, ses
    octets (64 px)."""

    person: str
    etag: str
    mime: str
    data: bytes


@dataclass(frozen=True, slots=True)
class Photo:
    """Une photo de profil gardée (ADR 0300) : son compte, sa personne, son empreinte, son type, ses octets."""

    account: str
    person: str
    etag: str
    mime: str
    data: bytes


#: une photo de profil, au plus (octets : 64 px, ADR 0300)
PHOTO_MAX_BYTES = 64 * 1024
#: ce que devient une photo envoyée : gardée, déjà là (la même empreinte), ou d'une personne que ce compte ne connaît
#: pas (ou plus : l'oubli), ou d'une autre empreinte que celle de son profil
PHOTO_KEPT = "kept"
PHOTO_KNOWN = "known"
PHOTO_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class InboxConversation:
    id: str
    title: str = ""
    kind: str = "other"


@dataclass(frozen=True, slots=True)
class InboxProfile:
    """Le profil d'une personne croisée dans Teams (ADR 0298), tel que l'extension le lit dans la base du client et
    le joint aux messages de cette personne (ou qui la mentionnent) : son identifiant Teams (``8:orgid:<guid>``…, en
    minuscules), son nom, son e-mail (vide s'il n'en a pas une bien formée), son poste, son entreprise, son service,
    l'organisation Teams du compte (pas forcément son employeur), trois numéros au plus, et l'empreinte de sa photo
    (``avatar``, ADR 0300 : vide sans photo). Déjà validé par la porte."""

    id: str
    name: str = ""
    email: str = ""
    title: str = ""
    company: str = ""
    department: str = ""
    tenant: str = ""
    phones: tuple[str, ...] = ()
    avatar: str = ""


@dataclass(frozen=True, slots=True)
class InboxBatch:
    """Un lot poussé par l'extension (déjà validé et borné par la porte)."""

    self_id: str = ""
    self_name: str = ""
    conversations: tuple[InboxConversation, ...] = ()
    messages: tuple[InboxMessage, ...] = ()
    #: l'historique chargé à la mise en service (ADR 0251) : rangé déjà lu — elle ne le remarque pas comme du neuf —,
    #: sans régler de brouillon ni rien journaliser
    history: bool = False
    #: les profils des auteurs et des personnes mentionnées de ses messages (ADR 0298), historique compris
    profiles: tuple[InboxProfile, ...] = ()


@dataclass(frozen=True, slots=True)
class Stored:
    """Ce qu'un lot a changé : les messages neufs, ceux déjà connus, les conversations où la personne a écrit (avec
    l'heure Teams, µs, de son dernier message dans chacune), les brouillons que ses messages ont réglés, et les
    jumeaux : un message déjà rangé sous un autre identifiant (ADR 0251), laissé de côté ; et parmi les neufs, ceux
    rangés comme du direct (``recent`` : tout le lot hors historique, l'historique de moins de 24 h)."""

    new: int = 0
    known: int = 0
    replied: tuple[tuple[str, int], ...] = ()
    settled: tuple[Settled, ...] = ()
    twins: int = 0
    recent: int = 0
    #: les profils neufs ou changés (ADR 0298) : un profil redit tel quel ne compte pas
    profiles: int = 0


@dataclass(frozen=True, slots=True)
class SeenAuthor:
    """Quelqu'un qui a écrit dans un compte (pas la personne du compte), dans les messages qu'une lecture a parcourus
    (``people_since``, l'annuaire : ADR 0298) : son identifiant Teams, le dernier nom qu'il y porte, combien de
    messages, le premier et le dernier (µs, l'heure de Teams)."""

    account: str
    author_id: str
    name: str
    count: int
    first: int
    last: int


@dataclass(frozen=True, slots=True)
class PeopleSince:
    """Ce qu'une lecture de ``people_since`` a trouvé, où elle s'est arrêtée (le dernier message parcouru et son
    arrivée, µs : à repasser à la suivante), et s'il reste des messages après."""

    people: tuple[SeenAuthor, ...] = ()
    cursor: tuple[int, int] = (0, 0)
    more: bool = False


@dataclass(frozen=True, slots=True)
class TeamsProfile:
    """Le profil d'une personne tel qu'un compte l'a reçu en dernier (ADR 0298) : ``id``, l'identifiant Teams en
    minuscules (``author_key``) ; ``updated``, son dernier changement (µs, l'horloge du serveur) ; ``seq``, son rang
    dans l'ordre des changements (``profiles_since``) ; ``said_at``, son dernier message dans ce compte (µs, l'heure
    de Teams ; 0 : aucun) — ce que le profil atteste, et la date qui compte face à un oubli (un profil reçu après
    l'oubli, avec un historique rechargé, ne la ramène pas)."""

    account: str
    id: str
    name: str = ""
    email: str = ""
    title: str = ""
    company: str = ""
    department: str = ""
    tenant: str = ""
    phones: tuple[str, ...] = ()
    updated: int = 0
    seq: int = 0
    said_at: int = 0


@dataclass(frozen=True, slots=True)
class ProfilesSince:
    """Ce qu'une lecture de ``profiles_since`` a trouvé (les profils changés, dans l'ordre de leurs changements), où
    elle s'est arrêtée (à repasser à la suivante), et s'il en reste après."""

    profiles: tuple[TeamsProfile, ...] = ()
    cursor: int = 0
    more: bool = False


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

    def thread_count(self, account: str, conversation: str, *, before: int = 0) -> int:
        """Combien de messages compte une conversation (avant ``before`` µs, 0 : tous) — de quoi dire, à qui relit un
        fil, combien il en reste avant ce qu'il vient de lire (ADR 0303)."""
        ...

    def last_messages(self, conversations: Sequence[tuple[str, str]]) -> dict[tuple[str, str], Message]:
        """Le dernier message de chacune de ces conversations (compte, identifiant), en une seule requête quel que soit
        leur nombre. Une conversation sans message n'y est pas."""
        ...

    def others(self, conversations: Sequence[tuple[str, str]]) -> dict[tuple[str, str], str]:
        """L'autre personne de chacun de ces tête-à-tête (compte, identifiant) : l'identifiant Teams du dernier à y
        avoir écrit qui n'est pas la personne du compte — celle dont ``title`` dit le nom —, en une seule requête (ADR
        0300 : sa photo est celle de la conversation). Une conversation qui n'est pas un tête-à-tête, ou où l'autre
        n'a encore rien écrit, n'y est pas."""
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

    def people_since(self, cursor: tuple[int, int], limit: int) -> PeopleSince:
        """Qui a écrit dans les ``limit`` messages arrivés après ``cursor`` (l'ordre d'arrivée, tous les comptes,
        l'historique compris), par compte : les messages de la personne du compte n'y comptent pas. ``cursor`` : celui
        que rendait la lecture d'avant ((0, 0) : depuis le début)."""
        ...

    def profiles_since(self, cursor: int, limit: int) -> ProfilesSince:
        """Les profils (ADR 0298) neufs ou changés depuis ``cursor`` (0 : tous), ``limit`` au plus, dans l'ordre de
        leurs changements, chacun sous son compte ; un profil changé deux fois n'est rendu qu'à son dernier état. Le
        rang d'un changement ne resert jamais, même après un oubli : rien de neuf n'est sauté."""
        ...

    def written_in(self, authors: Sequence[str], limit: int, *, accounts: Sequence[str] | None = None) \
            -> list[tuple[Conversation, int, int]]:
        """Les conversations où ces personnes (leurs identifiants Teams, sans casse) ont écrit, dans ces comptes
        (``None`` : tous), la plus récente d'abord : chacune sous son nom (comme ``conversations``), combien de leurs
        messages, le dernier (µs). Ce que la personne du compte a écrit n'y compte pas (l'écran Contacts, ADR 0298)."""
        ...

    def exchanged(self, since: int, *, limit: int = 2000, accounts: Sequence[str] | None = None) \
            -> list[tuple[str, str, int, int]]:
        """Qui échange vraiment avec la personne de chaque compte (ADR 0298, lot 6) : les auteurs qui ont écrit depuis
        ``since`` (µs, l'heure des messages) en tête-à-tête avec elle, quand elle y a écrit aussi depuis ; ou dans un
        petit groupe (``EXCHANGE_GROUP_MAX`` personnes au plus, elle comprise — jamais un canal) où elle a écrit après
        l'un de leurs messages, ou dont un message la mentionne quand elle y a écrit — (compte, son identifiant en
        minuscules, combien de ces messages, le dernier), le plus récent d'abord, ``limit`` au plus. Ses propres
        messages n'y sont jamais ; ce qui n'a pas d'auteur non plus."""
        ...

    def authored(self, authors: Sequence[str], *, since: int = 0, limit: int = 30,
                 accounts: Sequence[str] | None = None) -> list[Message]:
        """Les derniers messages de ces personnes (leurs identifiants Teams, sans casse) depuis ``since`` (µs, l'heure
        des messages), dans ces comptes (``None`` : tous), le plus récent d'abord, ``limit`` au plus (200) ; jamais
        ceux de la personne du compte (ce qu'elle sait d'un contact, ADR 0298)."""
        ...

    async def forget(self, subject: str) -> int: ...

    # ── les images (ADR 0258) ──
    def keep_image(self, account: str, image: ImageIn, now: int) -> str:
        """Garder une image de ce message (``IMAGE_KEPT``, ``IMAGE_KNOWN`` ou ``IMAGE_NO_MESSAGE``)."""
        ...

    def image_to_read(self) -> ImageToRead | None:
        """La plus ancienne image pas encore regardée."""
        ...

    def image_read(self, image_id: int, *, seen: str, sensitive: bool, read: bool) -> str:
        """Ce que Mika a vu d'une image (``read`` faux : un échec passager, retentée quelques fois) ; son texte
        rejoint celui du message. Rend la référence du message."""
        ...

    def images_of(self, refs: Sequence[str]) -> list[MessageImage]:
        """Les images de ces messages, sans leurs octets."""
        ...

    def image_bytes(self, ref: str, image: str) -> tuple[str, bytes] | None:
        """Le type et les octets d'une image (``None`` : pas d'image)."""
        ...

    # ── les photos de profil (ADR 0300) ──
    def keep_photo(self, account: str, photo: PhotoIn, now: int) -> str:
        """Garder la photo d'une personne que ce compte connaît, à l'empreinte que son profil a dite (``PHOTO_KEPT``,
        ``PHOTO_KNOWN`` ou ``PHOTO_UNKNOWN``)."""
        ...

    def photo(self, account: str, person: str) -> Photo | None:
        """La photo d'une personne (son identifiant Teams, sans casse) gardée sous ce compte."""
        ...

    def photos_of(self, people: Sequence[str], *, accounts: Sequence[str] | None = None) -> dict[str, tuple[str, str]]:
        """Parmi ces personnes (leurs identifiants Teams, sans casse), celles qui ont une photo dans ces comptes
        (``None`` : tous) : identifiant en minuscules → (le compte qui la garde, son empreinte) — le premier compte,
        dans l'ordre de leurs clés."""
        ...


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

    def last_contact(self, account: str) -> int:
        """La dernière fois que l'extension de ce compte s'est manifestée depuis le démarrage — un relevé, la
        connexion en direct, un lot (µs ; 0 : pas encore)."""
        ...


class TeamsGate(Protocol):
    """La porte (``app/teams.TeamsDesk``) : ce que le transport web lui passe, ce qu'elle a décidé. Rien n'est rangé
    ni journalisé avant qu'elle ait admis la clé et la requête."""

    async def inbox(self, key: str, data: object) -> GateResult: ...

    async def outbox(self, key: str) -> GateResult: ...

    async def ack(self, key: str, item: str, data: object) -> GateResult: ...

    async def image(self, key: str, data: object) -> GateResult: ...

    async def photo(self, key: str, data: object) -> GateResult: ...

    async def live(self, key: str) -> GateResult: ...

    async def live_items(self, key: str) -> GateResult: ...

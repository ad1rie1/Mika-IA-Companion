"""Le port du courrier : ses boîtes (lire ce qui arrive, ranger), ses brouillons
et l'envoi.

« Journaliser l'esprit, pas le monde » : les mails, les dossiers, les drapeaux
et les brouillons vivent dans le cache de l'adaptateur ; le journal ne garde
que ce qu'elle en a remarqué, décidé ou appris. Un mail est un texte venu
d'ailleurs : une donnée, jamais une consigne.

- **Plusieurs comptes** : chacun a une clé courte (``perso``) ; un mail se
  désigne par sa **référence** ``compte:Message-ID`` (``mail_ref``). Une
  référence sans compte (les journaux d'avant les comptes) désigne le mail
  dans n'importe quelle boîte.
- **Sa voix** par compte (``AccountInfo.voice``) : en son nom, en assistante,
  ou à la place de son opérateur — la façon d'écrire est dite par le plugin,
  la mise en forme finale (expéditeur, signature, citation) par l'adaptateur.
- **Un brouillon** vit ici, jamais dans le journal : une proposition d'envoi ne
  porte que son identifiant et le condensé de ce qui a été montré
  (``Preview.digest``).
"""

from __future__ import annotations

import email.utils
import hashlib
import re
from dataclasses import dataclass
from typing import Literal, Protocol

from mika.ports.paging import Page

#: les trois façons d'écrire depuis une boîte
Voice = Literal["elle", "assistante", "proprietaire"]
VOICES: tuple[tuple[str, str], ...] = (
    ("elle", "en son nom (Mika)"),
    ("assistante", "en assistante (« Mika, pour … »)"),
    ("proprietaire", "à ta place (en ton nom)"),
)
#: ce qu'un brouillon ne peut pas contenir au moment de partir (ce qu'elle n'a pas su)
TO_FILL = "[À COMPLÉTER"
#: les rôles de dossiers reconnus (special-use, RFC 6154)
ROLES: tuple[tuple[str, str], ...] = (
    ("inbox", "Réception"), ("sent", "Envoyés"), ("drafts", "Brouillons"), ("archive", "Archives"),
    ("junk", "Indésirables"), ("trash", "Corbeille"), ("", "Autres"),
)
_ACCOUNT = re.compile(r"^([a-z0-9][a-z0-9_-]{0,39}):(.+)$", re.S)
ACCOUNT_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def mail_ref(account: str, message_id: str) -> str:
    """La référence d'un mail : ``compte:Message-ID`` (sans compte : le Message-ID seul)."""
    return f"{account}:{message_id}" if account else message_id


def split_ref(ref: str) -> tuple[str, str]:
    """``(compte, Message-ID)`` d'une référence ; ``("", ref)`` pour une ancienne référence."""
    found = _ACCOUNT.match(ref or "")
    return (found.group(1), found.group(2)) if found else ("", ref or "")


def reference_key(ref: str) -> str:
    """Clé imprimable utilisable dans une URL, stable même pour un Message-ID long."""
    if 0 < len(ref) <= 200 and ref.isprintable() and "/" not in ref and not ref.startswith("#"):
        return ref
    return "#" + hashlib.sha256(ref.encode("utf-8", "replace")).hexdigest()[:24]


def reply_subject(subject: str) -> str:
    subject = " ".join((subject or "").split())
    return subject if subject.lower().startswith(("re:", "re :", "réf :", "rép :")) else f"Re: {subject}"


def forward_subject(subject: str) -> str:
    subject = " ".join((subject or "").split())
    return subject if subject.lower().startswith(("fwd:", "tr :", "tr:", "fw:")) else f"Tr : {subject}"


def forwarded_text(mail, introduction: str = "") -> str:
    """Le texte transféré n'est jamais coupé ; l'opérateur écrit son introduction séparément."""
    sender = getattr(mail, "sender", "")
    head = f"De : {sender}\nObjet : {mail.subject}\nÀ : {mail.to}"
    return introduction.rstrip() + f"\n\n---------- Message transféré ----------\n{head}\n\n{mail.body}"


def addresses(field: str) -> list[tuple[str, str]]:
    """Les ``(nom, adresse)`` d'un en-tête (adresses en minuscules, vides écartées)."""
    return [(n, a.lower()) for n, a in email.utils.getaddresses([field or ""]) if "@" in a]


def reply_recipients(mail: Mail, own: tuple[str, ...], *, everyone: bool = False) -> tuple[str, str]:
    """``(à, copie)`` d'une réponse : à l'adresse de réponse (sinon l'expéditeur) ;
    pour tous, les autres destinataires en copie — jamais ses propres adresses."""
    mine = {a.lower() for a in own}
    first = addresses(mail.reply_to) or addresses(mail.sender)
    to = [email.utils.formataddr(p) for p in first if p[1] not in mine] or [mail.sender]
    if not everyone:
        return ", ".join(to), ""
    taken = {a for _, a in first} | mine
    cc = []
    for name, address in addresses(mail.to) + addresses(mail.cc):
        if address not in taken:
            taken.add(address)
            cc.append(email.utils.formataddr((name, address)))
    return ", ".join(to), ", ".join(cc)


@dataclass(frozen=True, slots=True)
class Attachment:
    name: str
    mime: str
    size: int


@dataclass(frozen=True, slots=True)
class Mail:
    message_id: str
    sender: str  # « Nom <adresse> » tel qu'écrit
    address: str  # l'adresse seule, en minuscules
    subject: str
    date: int  # instant (µs), 0 si illisible
    body: str  # texte brut, borné
    to: str = ""
    in_reply_to: str = ""
    #: un envoi de masse (lettre d'information, notification automatique)
    bulk: bool = False
    account: str = ""
    folder: str = ""
    cc: str = ""
    reply_to: str = ""
    references: str = ""
    #: les drapeaux du serveur (lu, suivi, répondu)
    seen: bool = False
    flagged: bool = False
    answered: bool = False
    attachments: tuple[Attachment, ...] = ()
    has_html: bool = False
    #: source de lecture, jamais transmise au modèle ; assainie avant tout rendu web
    html: str = ""
    #: Un ancien cache peut ne contenir qu'un extrait ; le lecteur peut le compléter.
    complete: bool = True

    @property
    def ref(self) -> str:
        return mail_ref(self.account, self.message_id)


@dataclass(frozen=True, slots=True)
class MailQuery:
    account: str = ""
    folder: str = ""
    text: str = ""
    sender: str = ""
    seen: bool | None = None
    flagged: bool | None = None
    refs: tuple[str, ...] | None = None
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MailHit:
    ref: str
    message_id: str
    account: str
    subject: str
    date: int
    who: str
    sent: bool = False


@dataclass(frozen=True, slots=True)
class Contact:
    address: str
    name: str
    received: int
    sent: int
    last: int


@dataclass(frozen=True, slots=True)
class File:
    name: str
    mime: str
    data: bytes


@dataclass(frozen=True, slots=True)
class Sent:
    """Un mail parti de sa boîte : par elle (``by`` vide, après accord) ou par un
    opérateur depuis la console (``by`` = son adresse) — elle le sait (``email.sent``)."""

    message_id: str
    to: str
    subject: str
    body: str
    date: int
    in_reply_to: str = ""
    by: str = ""
    account: str = ""
    #: le brouillon d'où il vient (vide : écrit directement)
    draft: str = ""
    cc: str = ""
    attachments: tuple[Attachment, ...] = ()

    @property
    def ref(self) -> str:
        return mail_ref(self.account, self.message_id)


@dataclass(frozen=True, slots=True)
class AccountInfo:
    """Un compte, sans ses secrets : ce que le plugin et la console en savent."""

    key: str
    label: str
    address: str
    #: le nom de son opérateur, pour écrire en assistante ou à sa place
    display_name: str = ""
    voice: str = "elle"
    #: son nom d'expéditrice quand elle écrit en son nom (vide : celui par défaut)
    sender_name: str = ""
    tone: str = ""
    instructions: str = ""
    signature: str = ""
    #: les dossiers qu'elle relève (les autres se consultent)
    folders: tuple[str, ...] = ("INBOX",)
    ready: bool = False
    can_send: bool = False
    enabled: bool = True
    autodraft: bool = False
    autodraft_skip: tuple[str, ...] = ()
    #: ses réglages sans secret, pour les montrer (« lire » : « imap.x.fr:993, SSL, utilisateur u »)
    details: tuple[tuple[str, str], ...] = ()

    @property
    def name(self) -> str:
        return self.label or self.key


@dataclass(frozen=True, slots=True)
class Folder:
    account: str
    name: str  # le nom IMAP (décodé)
    role: str = ""  # voir ``ROLES``
    polled: bool = False
    total: int = 0
    unseen: int = 0
    last_sync: int = 0  # µs, 0 : jamais relu

    @property
    def label(self) -> str:
        if self.role:
            return dict(ROLES)[self.role]
        return self.name.replace("INBOX.", "").replace("INBOX/", "") or self.name


@dataclass(frozen=True, slots=True)
class Draft:
    """Un brouillon : écrit par elle (``author`` vide) ou par un opérateur."""

    id: str
    account: str
    to: str
    subject: str
    body: str
    cc: str = ""
    #: la référence du mail auquel il répond (vide : un nouveau mail)
    reply_to: str = ""
    #: citer le mail auquel il répond sous le texte
    quote: bool = True
    author: str = ""
    created: int = 0
    updated: int = 0
    #: ``brouillon`` | ``envoye`` | ``abandonne``
    state: str = "brouillon"
    #: le Message-ID du mail parti (une fois envoyé)
    sent_id: str = ""
    #: retouché par un opérateur après qu'elle l'a écrit
    edited_by: str = ""


@dataclass(frozen=True, slots=True)
class Preview:
    """Exactement ce qui partira : les en-têtes et le texte final, et son condensé."""

    sender: str
    to: str
    cc: str
    subject: str
    text: str
    digest: str
    #: pourquoi il ne peut pas partir tel quel (vide : il peut)
    blocked: str = ""


@dataclass(frozen=True, slots=True)
class AccountStatus:
    key: str
    #: le dernier relevé (µs), 0 : jamais
    last_poll: int = 0
    #: la dernière erreur (vide : tout va bien)
    error: str = ""
    error_at: int = 0


class MailPort(Protocol):
    def find_ref(self, key: str) -> str | None: ...

    async def older(self, account: str, folder: str, limit: int = 50) -> int: ...

    def messages_page(self, query: MailQuery, page: int = 1, size: int = 25) -> Page[Mail]: ...

    def outgoing_page(self, query: MailQuery, page: int = 1, size: int = 25) -> Page[tuple[Mail | Sent, bool]]: ...

    def contacts_page(self, account: str = "", text: str = "", page: int = 1, size: int = 25) -> Page[Contact]: ...

    def thread_page(self, ref: str, page: int = 1, size: int = 25) -> Page[MailHit]: ...

    def search_page(self, text: str, limit: int = 25, offset: int = 0) -> list[MailHit]: ...

    def search_count(self, text: str) -> int: ...

    def drafts_page(self, text: str = "", page: int = 1, size: int = 25) -> Page[Draft]: ...

    async def document(self, ref: str) -> Mail | None: ...

    async def file(self, ref: str, part: str) -> File: ...

    async def forward(self, ref: str, to: str, subject: str, body: str, *, cc: str = "", by: str = "",
                      attachments: bool = True) -> str: ...

    def configured(self) -> bool:
        """Au moins un compte prêt à relever."""
        ...

    def accounts(self) -> list[AccountInfo]: ...

    def account(self, key: str) -> AccountInfo | None: ...

    async def fetch_new(self, limit: int) -> list[Mail]:
        """Les mails arrivés depuis la dernière fois dans les dossiers relevés de
        chaque compte (chacun rendu une seule fois, même s'il change de dossier)."""
        ...

    def seen_elsewhere(self) -> list[str]:
        """Les références des mails lus ailleurs (dans un autre client) depuis la
        dernière fois qu'on l'a demandé (vidé à la lecture)."""
        ...

    async def get(self, ref: str) -> Mail | None: ...

    async def recent(self, limit: int) -> list[Mail]: ...

    def cached(self, limit: int, *, account: str = "", folder: str = "") -> list[Mail]:
        """Les derniers mails déjà arrivés, sans relever (lecture seule : l'inspecteur)."""
        ...

    def cached_one(self, ref: str) -> Mail | None:
        """Un mail déjà arrivé, sans relever (lecture seule : l'inspecteur)."""
        ...

    def search(self, text: str, limit: int, *, account: str = "") -> list[Mail]: ...

    def folders(self, account: str) -> list[Folder]:
        """Les dossiers connus d'un compte (sans aller au serveur)."""
        ...

    async def refresh_folders(self, account: str) -> list[Folder]: ...

    async def sync_folder(self, account: str, folder: str, limit: int) -> int:
        """Relit un dossier pour la console (ce qu'elle ne relève pas n'est jamais
        rendu par ``fetch_new``) ; rend le nombre de mails nouveaux dans le cache."""
        ...

    async def set_flags(self, ref: str, *, seen: bool | None = None, flagged: bool | None = None) -> None: ...

    async def move(self, ref: str, folder: str) -> str:
        """Déplace ; rend le dossier d'arrivée."""
        ...

    async def archive(self, ref: str) -> str: ...

    async def trash(self, ref: str) -> str: ...

    async def delete(self, ref: str) -> None:
        """Supprime définitivement (seulement depuis la corbeille)."""
        ...

    async def send(self, to: str, subject: str, body: str, in_reply_to: str = "", by: str = "", *,
                   account: str = "", cc: str = "", quote: bool = False) -> str:
        """Envoie depuis un compte (le premier prêt, par défaut) ; ``in_reply_to`` est la
        référence du mail auquel on répond. Rend le Message-ID parti (gardé dans
        « Envoyés », avec qui l'a écrit). Lève si l'envoi échoue."""
        ...

    def sent_mails(self, limit: int, *, account: str = "") -> list[Sent]:
        """Les derniers mails partis, le plus récent d'abord (lecture seule)."""
        ...

    def sent_mail(self, message_id: str) -> Sent | None: ...

    def save_draft(self, draft: Draft) -> Draft:
        """Crée (``id`` vide) ou remplace un brouillon ; rend ce qui est gardé."""
        ...

    def draft(self, draft_id: str) -> Draft | None: ...

    def drafts(self, limit: int, *, state: str = "") -> list[Draft]: ...

    def discard_draft(self, draft_id: str) -> None: ...

    def preview(self, draft_id: str) -> Preview | None:
        """Ce qui partirait si on envoyait ce brouillon maintenant."""
        ...

    async def send_draft(self, draft_id: str, *, by: str = "", digest: str = "") -> str:
        """Envoie un brouillon tel que ``preview`` le montre ; refuse (``ValueError``)
        si ``digest`` ne correspond plus (il a changé depuis qu'on l'a lu)."""
        ...

    async def test(self, account: str) -> tuple[bool, str]:
        """Se connecte (lecture puis envoi) ; rend si tout va bien et ce qui s'est passé, en français."""
        ...

    def status(self, account: str) -> AccountStatus: ...

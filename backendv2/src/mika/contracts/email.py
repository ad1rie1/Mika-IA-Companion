"""Contrat du plugin ``email`` : ce qu'elle remarque de ses boîtes aux lettres.

Un mail remarqué est un **signal** (``attention.Signal``) : l'attention le
dose et l'habitue comme tout ce qui vient d'ailleurs. Son texte est cité,
jamais obéi. Un mail se désigne par sa **référence** ``compte:Message-ID``
(``ports.mail.mail_ref`` ; les journaux d'avant les comptes n'ont que le
Message-ID).

Écrire est un effet externe (capacité ``email.send``) : elle rédige un
**brouillon** (gardé par l'adaptateur, jamais au journal), le propose, et il
ne part qu'avec l'accord d'un opérateur — qui peut le retoucher avant. Un
opérateur peut aussi écrire lui-même depuis sa boîte, et elle le sait
(``email.sent``), ou lui demander de rédiger une réponse (``email.draft_asked``).
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.contracts.attention import Signal
from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactKey

OWNER = "email"
MAIL = "mail"
#: raison de preuve : dire à sa propriétaire qu'un mail important est arrivé
MENTION = "mail_mention"
#: raison de preuve : préparer un brouillon de réponse (une tâche silencieuse)
DRAFT = "mail_draft"
SEND = "email.send"
#: l'adresse (au sens d'identity) d'un courriel : ce qui concerne quelqu'un qu'on ne connaît que par son courriel
HANDLE_PREFIX = "mail:"


def address_handle(address: str) -> str:
    """``mail:alice@exemple.fr`` : le sujet (au sens de l'oubli) d'un correspondant."""
    return f"{HANDLE_PREFIX}{address.strip().lower()}" if address.strip() else ""


class MailNoticed(Signal):
    mail: str  # la référence (``compte:Message-ID`` ; le Message-ID seul dans les anciens journaux)
    sender: str
    address: str
    importance: float
    needs_reply: bool = False
    account: str = ""
    folder: str = ""


class MailSent(Signal):
    """Un mail est parti de sa boîte, écrit par un opérateur depuis la console
    (``by``), ou un brouillon d'elle qu'un opérateur a retouché puis envoyé
    (``draft``, ``edited``) : elle le sait — son attention le remarque, sa boîte
    le montre, une réponse ne la surprendra pas. Le texte du mail reste dans le
    cache de l'adaptateur (« Envoyés »)."""

    mail: str  # Message-ID du mail parti
    to: str
    address: str
    by: str  # l'adresse de l'opérateur
    in_reply_to: str = ""
    account: str = ""
    #: le brouillon d'où il vient (vide : écrit directement par l'opérateur)
    draft: str = ""
    #: elle l'avait écrit, l'opérateur l'a retouché avant de l'envoyer
    edited: bool = False


class DraftAsked(Payload):
    """Un opérateur lui demande de rédiger une réponse à un mail (ce qu'il veut
    dire, s'il le précise) : une tâche qu'elle fera, silencieusement."""

    mail: str  # la référence du mail
    account: str = ""
    by: str = ""
    instruction: Content | None = None
    #: les personnes que la consigne peut citer (l'opérateur) : l'oubli l'atteint
    about: tuple[str, ...] = ()


NOTICED = event_type("email.noticed", OWNER, MailNoticed, public=True, content=("summary",), subjects=("about",))
SENT = event_type("email.sent", OWNER, MailSent, public=True, content=("summary",), subjects=("about",))
DRAFT_ASKED = event_type("email.draft_asked", OWNER, DraftAsked, public=True, content=("instruction",),
                         subjects=("about",))
ALL = (NOTICED, SENT, DRAFT_ASKED)
#: la sorte du signal d'un mail écrit par un opérateur
SENT_KIND = "sent_by_operator"


@dataclass(frozen=True, slots=True)
class MailView:
    mail: str
    sender: str
    importance: float
    needs_reply: bool
    at: int
    summary_ref: str
    account: str = ""


@dataclass(frozen=True, slots=True)
class DraftView:
    """Un brouillon d'elle qui attend l'accord d'un opérateur."""

    proposal: int
    draft: str
    account: str
    mail: str  # la référence du mail auquel il répond (vide : un nouveau mail)
    at: int


#: Les mails remarqués et pas encore lus, le plus important d'abord.
UNREAD = FactKey("email.unread", type=tuple)
#: Ses brouillons en attente d'accord, le plus ancien d'abord.
DRAFTS = FactKey("email.drafts", type=tuple)

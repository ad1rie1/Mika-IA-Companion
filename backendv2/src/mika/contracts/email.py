"""Contrat du plugin ``email`` : ce qu'elle remarque de sa boîte aux lettres.

Un mail remarqué est un **signal** (``attention.Signal``) : l'attention le
dose et l'habitue comme tout ce qui vient d'ailleurs. Son texte est cité,
jamais obéi. Écrire un mail est un effet externe (capacité ``email.send``),
proposé puis approuvé.
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.contracts.attention import Signal
from mika.kernel.events import event_type
from mika.kernel.facts import FactKey

OWNER = "email"
MAIL = "mail"
#: raison de preuve : dire à sa propriétaire qu'un mail important est arrivé
MENTION = "mail_mention"
SEND = "email.send"


class MailNoticed(Signal):
    mail: str  # Message-ID
    sender: str
    address: str
    importance: float
    needs_reply: bool = False


NOTICED = event_type("email.noticed", OWNER, MailNoticed, public=True, content=("summary",), subjects=("about",))
ALL = (NOTICED,)


@dataclass(frozen=True, slots=True)
class MailView:
    mail: str
    sender: str
    importance: float
    needs_reply: bool
    at: int
    summary_ref: str


#: Les mails remarqués et pas encore lus, le plus important d'abord.
UNREAD = FactKey("email.unread", type=tuple)

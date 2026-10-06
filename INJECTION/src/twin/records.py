"""Ce qu'un lecteur rend : des enregistrements normalisés, quel que soit le format d'origine.

Un lecteur ne décide de rien : il dit ce que la source dit (qui a écrit, quand — autant
qu'on le sache —, dans quelle conversation, dans quel ordre) et ce qu'elle laisse deviner
(« ce message a été envoyé depuis ce téléphone : c'est elle »). Qui est qui à travers les
sources, c'est l'étape « personnes » ; quand c'était vraiment, l'étape « dater ».
"""

from __future__ import annotations

from dataclasses import dataclass, field

from twin.timing import Temps

#: canaux connus — un canal regroupe les sources où une même clé désigne la même personne
WHATSAPP, MESSENGER, INSTAGRAM, MSN, SMS, SIGNAL, MAIL, NOTES = (
    "whatsapp", "messenger", "instagram", "msn", "sms", "signal", "mail", "notes")

#: la clé d'auteur de la propriétaire des archives quand la source ne la nomme pas
ME = "moi"


@dataclass(frozen=True, slots=True)
class Author:
    """Quelqu'un qui écrit dans un canal, tel que la source le nomme."""

    channel: str
    key: str  # stable dans le canal : un numéro, une adresse, un nom
    name: str = ""
    address: str = ""  # numéro, adresse mail, identifiant de compte
    me: bool | None = None  # indice du lecteur : c'est elle / ce n'est pas elle / on ne sait pas
    me_reason: str = ""
    aliases: tuple[str, ...] = ()  # autres noms vus pour la même clé (pseudos MSN…)


@dataclass(frozen=True, slots=True)
class Conversation:
    channel: str
    key: str
    title: str = ""
    group: bool = False
    members: tuple[str, ...] = ()  # clés d'auteurs


@dataclass(frozen=True, slots=True)
class Attachment:
    name: str
    mime: str = ""
    size: int | None = None


@dataclass(frozen=True, slots=True)
class Message:
    channel: str
    conversation: str  # clé de conversation
    author: str  # clé d'auteur
    text: str
    temps: Temps
    rank: int  # ordre dans la source (la vérité quand la date manque)
    native_key: str = ""  # identifiant de la source s'il y en a un (Message-ID…)
    reply_to: str = ""
    kind: str = "message"  # message, systeme, appel, masse (newsletter)…
    subject: str = ""
    attachments: tuple[Attachment, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class Document:
    """Un texte qui n'est pas une conversation : une note, une page de journal."""

    channel: str
    key: str
    kind: str  # note, journal, document
    title: str
    text: str
    temps: Temps
    rank: int
    author: str = ME
    path: str = ""


Item = Author | Conversation | Message | Document

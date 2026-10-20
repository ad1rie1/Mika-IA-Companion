"""Contrat du plugin ``phone`` : les messages du téléphone de sa propriétaire, qu'elle lit, dont elle se souvient,
et auxquels elle l'aide à répondre (ADR 0120).

Un message reçu (``phone.received``) a la forme ``memory.Relayed`` : la mémoire le relit sans connaître ce plugin.
Son texte, le nom de qui l'a écrit et celui du groupe sont des contenus personnels ; la personne qui l'a reçu, son
adresse et l'expéditeur en sont les sujets — l'oubli de l'un efface les textes. Un expéditeur est désigné par une clé
``phone:<empreinte>:<nom>`` (``contact_key``) : ce n'est pas une personne à qui elle parle, et personne n'a de lien
avec elle — rien de ce qu'il a confié ne s'ouvre à un tiers.

Répondre : elle prépare une réponse **à la place** de la personne (``phone.drafted``, son texte est un contenu) et la
propose (capacité ``phone.send``) ; la capacité l'envoie au téléphone, qui demande l'autorisation — le geste de la
personne vaut accord. Ce qu'elle est devenue revient en ``phone.settled``.
"""

from __future__ import annotations

import hashlib

from mika.contracts.memory import Relayed
from mika.kernel.events import Content, Payload, event_type
from mika.vocab.people import PHONE_PREFIX, clean_display_name

OWNER = "phone"
SEND = "phone.send"
#: les sorts d'une réponse proposée : préparée (pas encore au téléphone), offerte (au téléphone, qui attend le geste),
#: puis ce que le téléphone en dit (``ports.phone.RESULTS``), ou l'échéance
PREPARED, OFFERED, EXPIRED = "prepared", "offered", "expired"
#: le nom d'un contact gardé dans sa clé, au plus
CONTACT_NAME_MAX = 40


class Drafted(Payload):
    """Une réponse qu'elle prépare à la place de la personne, dans une conversation de son téléphone : l'adresse et
    la personne, la conversation et l'appli, le message auquel elle répond (son ``seq``), à qui (la clé du contact,
    vide pour un groupe), son texte."""

    handle: str
    person: str
    thread: str
    source: str
    reply_to: int
    to: str = ""
    body: Content


class Settled(Payload):
    """Ce qu'est devenue une réponse proposée (``draft`` : le ``seq`` de ``phone.drafted``) : ce que le téléphone en
    dit (``sent``, ``other``, ``copied``, ``ignored``, ``failed``), ou l'échéance (``expired``). ``reason`` : un code
    écrit par le code, jamais un texte venu d'ailleurs."""

    draft: int
    result: str
    reason: str = ""


RECEIVED = event_type("phone.received", OWNER, Relayed, public=True, content=("text", "sender_name", "title"),
                      subjects=("recipient", "handle", "sender"))
DRAFTED = event_type("phone.drafted", OWNER, Drafted, content=("body",), subjects=("handle", "person", "to"))
SETTLED = event_type("phone.settled", OWNER, Settled)
ALL = (RECEIVED, DRAFTED, SETTLED)


def contact_hash(recipient: str, source: str, sender: str) -> str:
    """L'empreinte d'un contact : la personne qui reçoit, l'appli et la clé opaque que donne le téléphone."""
    return hashlib.sha256(f"{recipient}|{source}|{sender}".encode()).hexdigest()[:12]


def contact_key(digest: str, name: str) -> str:
    """La clé d'un contact : « phone:<empreinte>:<nom> » (le nom de la première fois, nettoyé et borné)."""
    shown = clean_display_name(name, max_chars=CONTACT_NAME_MAX)
    return f"{PHONE_PREFIX}{digest}:{shown}"


def message_ref(seq: int) -> str:
    """La référence d'un message telle qu'elle la lit : « p<seq> »."""
    return f"p{seq}"


def message_seq(ref: str) -> int | None:
    tail = ref.strip().strip("[]").removeprefix("p")
    return int(tail) if tail.isdigit() and len(tail) <= 18 else None

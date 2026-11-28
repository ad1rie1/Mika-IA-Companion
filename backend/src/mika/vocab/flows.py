"""Les flux où une autrice récrit ce qui part, et ce qu'est une autrice (ADR 0124).

Une autrice, c'est une façon d'écrire : un nom, ses codes (le registre, les formules, la longueur, les émojis…) et,
facultatif, un exemple de la forme. Le flux dit où le texte part, et donc le cadre de la passe : le fil de SMS du chat
(ses réponses et ses initiatives), un courriel d'une boîte, un message Teams, un SMS ou un WhatsApp écrit à la place de
la personne. Un flux a au plus une autrice ; sans autrice, ce qui part est le premier jet. Partagé par le runtime (la
passe), l'expression (ses consignes), le courrier, Teams, le téléphone (leurs brouillons) et la console.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: le chat : ses réponses et ses initiatives (la seconde passe, ADR 0112)
CHAT = "chat"
#: une boîte mail (``courrier:<boîte>``) : les brouillons de ses courriels
MAIL = "courrier"
#: Teams : les réponses qu'elle prépare à la place de la personne
TEAMS = "teams"
#: le téléphone : les réponses WhatsApp ou SMS qu'elle prépare à la place de la personne
PHONE = "telephone"
#: les formes d'un flux (sa forme, c'est son préfixe)
FORMS = (CHAT, MAIL, TEAMS, PHONE)
#: les formes dont le texte est un brouillon d'outil (le chat passe par la seconde passe de sa parole)
DRAFTS = (MAIL, TEAMS, PHONE)


@dataclass(frozen=True, slots=True)
class Author:
    """Une autrice : sa clé, son nom, ses codes d'écriture, un exemple de la forme (vides : le cadre du flux seul)."""

    key: str
    name: str
    codes: str = ""
    example: str = ""


def mail(box: str) -> str:
    """Le flux d'une boîte mail."""
    return f"{MAIL}:{box}"


def form_of(flow: str) -> str:
    """La forme d'un flux (``courrier:perso`` → ``courrier``)."""
    return flow.split(":", 1)[0]


async def written(ctx: Any, flow: str, text: str, about: str = "") -> str:
    """Un brouillon récrit par l'autrice de son flux (``ToolContext.authored``) ; tel quel si le contexte n'en a pas
    (un contexte de test, un outil prêté)."""
    authored = getattr(ctx, "authored", None)
    if not callable(authored):
        return text
    got = await authored(flow, text, about)
    return got if isinstance(got, str) and got.strip() else text

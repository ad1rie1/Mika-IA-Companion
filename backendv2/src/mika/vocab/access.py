"""Qui peut quoi, en lignes lues de haut en bas comme les règles d'un pare-feu (ADR 0131, 0133) : ce qu'en partagent
les services MCP, les projets et leurs apps.

Une ligne dit **qui** (sa propriétaire, toute personne qui a un compte, une personne nommée — reconnue seulement
authentifiée) et **quand** (des moments, ou toujours) ; ce qu'elle accorde est à son propriétaire (un service : ce
qu'elle fait d'un outil, ce qu'elle en garde ; un projet : le voir, le piloter, se servir de ses apps). Pour
quelqu'un, à un moment, la première ligne qui le désigne décide ; aucune : la ligne par défaut. Jamais dans un salon,
avec une inconnue, ni sans personne, quelles que soient les lignes (``situation``).

Une valeur partagée, sans faculté : les lignes sont ce que chaque propriétaire range (``who``, ``when``, le reste à
lui), lues ici par leurs champs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, TypeVar

from mika.vocab.episodes import Kind
from mika.vocab.privacy import ChannelTrust

#: qui une ligne désigne : sa propriétaire, toute personne qui a un compte chez elle, ou une personne nommée
#: (``personne:<clé>``, reconnue seulement authentifiée). Jamais un salon ni une inconnue.
WHO_OWNER, WHO_ACCOUNTS, WHO_PERSON = "toi", "comptes", "personne:"
#: les moments où une ligne vaut (plusieurs à la fois ; aucun : toujours)
MOMENTS = (("conversation", "quand elle répond"), ("initiative", "quand elle prend la parole"),
           ("travail", "quand elle travaille seule"))
#: les sortes d'épisode de chaque moment
KINDS_OF: Mapping[str, frozenset[str]] = {
    "conversation": frozenset({Kind.REPLY}),
    "initiative": frozenset({Kind.INITIATIVE}),
    # une tâche aussi (lire la file d'une app, ADR 0105 ; un brouillon) : ses lots sont ceux que la tâche choisit
    "travail": frozenset({Kind.STEP, Kind.WORK, Kind.JOB, Kind.WAKE, Kind.WAKE_JOB, Kind.TASK}),
}
#: ce qu'une ligne laisse faire d'un outil : seule, l'appel part aussitôt ; sur accord de la personne en face (une
#: carte dans son chat ; sans personne en face, l'opérateur) ; sur ton accord à toi (une carte dans ton chat quand
#: c'est toi en face, sinon la console) ; ou non : l'outil ne lui est pas offert
NO, ALONE, CARD, OWNER_OK = "non", "seule", "carte", "toi"
POLICIES = ((ALONE, "seule — sans demander"), (CARD, "demande à la personne en face"),
            (OWNER_OK, "demande ton accord"), (NO, "non"))

L = TypeVar("L")


def situation(audience: Any) -> str | None:
    """Où elle est : avec sa propriétaire (``proprietaire``), avec une personne authentifiée en tête-à-tête
    (``compte``), quand elle travaille seule (``travail``) ; ``None`` dans un salon, avec une inconnue, sans
    personne."""
    if audience is None:
        return None
    if audience.trust == ChannelTrust.INTERNAL.value:
        return "travail"
    if not audience.persons or audience.public or audience.room:
        return None
    if audience.owner:
        return "proprietaire"
    return "compte" if audience.trust == ChannelTrust.AUTHENTICATED.value else None


def who_is(who: str, where: str, person: str) -> bool:
    """Une ligne désigne-t-elle qui est en face ? Toi (et quand elle travaille seule, pour toi), toute personne qui a
    un compte, une personne nommée (authentifiée) ; la ligne par défaut (``who`` vide) : tout le monde."""
    if not who:
        return True
    if who == WHO_OWNER:
        return where in ("proprietaire", "travail")
    if who == WHO_ACCOUNTS:
        return where == "compte"
    return where == "compte" and bool(person) and who == WHO_PERSON + person


def moment(when: Iterable[str], kind: str) -> bool:
    """Une ligne vaut-elle dans cette sorte d'épisode ? Sans moment : toujours."""
    when = tuple(when)
    return not when or any(kind in KINDS_OF.get(w, frozenset()) for w in when)


def first(lines: Iterable[L], default: L, audience: Any, kind: str,
          concerns: Callable[[L], bool] | None = None) -> L | None:
    """La ligne qui décide pour qui est en face, à ce moment : la première qui le désigne (et le concerne :
    ``concerns``, un outil dans sa colonne), sinon la ligne par défaut ; ``None`` hors de toute situation — jamais
    dans un salon, avec une inconnue, ni sans personne."""
    where = situation(audience)
    if where is None:
        return None
    person = (audience.person or "") if where == "compte" else ""
    for line in (*lines, default):
        if (line is default or concerns is None or concerns(line)) and \
                who_is(getattr(line, "who", ""), where, person) and moment(getattr(line, "when", ()), kind):
            return line
    return None


def granted(lines: Iterable[L], default: L, opens: Callable[[L], bool]) -> frozenset[str]:
    """Les sortes d'épisode où une ligne (ou la ligne par défaut) peut ouvrir quelque chose (``opens``) : ce qu'on
    offre au plus — qui l'a vraiment se décide devant chaque audience (``first``)."""
    always = frozenset().union(*KINDS_OF.values())
    out: frozenset[str] = frozenset()
    for line in (*lines, default):
        if opens(line):
            when = tuple(getattr(line, "when", ()))
            out |= frozenset().union(*(KINDS_OF.get(w, frozenset()) for w in when)) if when else always
    return out

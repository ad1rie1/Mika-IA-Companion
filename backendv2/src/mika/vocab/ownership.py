"""Un compte sert à son propriétaire, ou à qui on le partage (ADR 0185, 0186, 0188) : la règle, dite une fois.

Une boîte aux lettres, un compte Teams : vide, il est à ses propriétaires (toi) ; ``elle``, à elle ;
``personne:<clé>``, à une personne. On le partage à une personne, à un niveau (``vocab.access.SHARES``). La règle vaut
pour le courrier, pour Teams et pour l'API par personne.

Des valeurs simples, sans lire de cadre : ``owners`` (compte → propriétaire), ``shares`` (compte → personne → niveau),
``given`` (personne → niveau, pour un compte), une audience et la sorte d'épisode. Chaque greffon garde son enveloppe,
qui lit ses paramètres ; ce qu'il sait seul (sa famille d'outils, la tâche en cours) arrive en arguments.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any

from mika.vocab.access import ACCOUNT, AT_OWNER, PERSON, SELF, SHARE_READ, SHARE_USE, WORK, reaches, situation

#: comment un compte sert : par ce qu'il est (à toi, à elle, à la personne en face, le compte d'une tâche), ou
#: seulement par un partage
OWNED, SHARED = "proprietaire", "partage"


def facing(audience: Any, kind: str) -> str:
    """Qui est en face, comme propriétaire possible d'un compte : ``personne:<clé>`` d'une personne reconnue en
    tête-à-tête ; vide sinon (toi, elle seule, un salon, une inconnue)."""
    person = getattr(audience, "person", "") or ""
    return PERSON + person if person and situation(audience, kind) == ACCOUNT else ""


def shared_with(audience: Any, kind: str) -> str:
    """Qui est en face, comme personne à qui l'on partage un compte : ``personne:<clé>`` d'une personne reconnue en
    tête-à-tête — une de ses propriétaires aussi, à qui l'on peut partager le compte d'une autre ; vide sinon (elle
    seule, un salon, une inconnue)."""
    person = getattr(audience, "person", "") or ""
    return PERSON + person if person and situation(audience, kind) in (ACCOUNT, AT_OWNER) else ""


def reach(owner: str, given: Mapping[str, str], audience: Any, kind: str, need: str = SHARE_USE, *, family: bool,
          task: bool = False) -> str:
    """Par où ce compte sert ici : ``OWNED``, ``SHARED`` (un partage qui atteint ``need``), ou vide (il ne sert pas).

    - les tiens (sans propriétaire nommé) : là où sa famille d'outils le permet (``family``) — toi en privé, elle
      quand elle travaille, et qui une ligne de la famille ouvre ;
    - les siens, et celui d'une tâche de rédaction (``task`` : on la lui a demandée, ou elle l'a proposée pour un
      compte à toi ou à elle) : quand elle travaille, là où sa famille le permet ;
    - celui d'une personne : avec elle, reconnue, en tête-à-tête — et nulle part ailleurs ;
    - ceux qu'on lui partage : avec elle, reconnue, en tête-à-tête, si son partage atteint ce que l'outil demande
      (``need`` : lire, préparer, s'en servir — par défaut, s'en servir)."""
    person = facing(audience, kind)
    if (not owner and family) or (person and owner == person):
        return OWNED
    if family and (owner == SELF or task) and situation(audience, kind) == WORK:
        return OWNED
    shared = shared_with(audience, kind)
    return SHARED if shared and reaches(given.get(shared, ""), need) else ""


def owns_one(owners: Mapping[str, str], shares: Mapping[str, Mapping[str, str]], audience: Any, kind: str,
             need: str = SHARE_READ) -> bool:
    """Qui est en face a un compte à son nom, ou qu'on lui partage à ce niveau : ses outils lui sont offerts, réduits à
    ces comptes."""
    person = facing(audience, kind)
    if person and person in owners.values():
        return True
    shared = shared_with(audience, kind)
    return bool(shared) and any(reaches(given.get(shared, ""), need) for given in shares.values())


def must_approve(owner: str, given: Mapping[str, str], person: str, owners: Iterable[str]) -> bool:
    """Ce qu'elle prépare dans ce compte attend l'accord de son propriétaire, quoi que dise la règle de son canal : la
    personne pour qui elle l'écrit (``personne:<clé>``) n'atteint le compte que par un partage qui ne s'en sert pas
    (« lire et préparer »). Son compte, ou un compte « à toi » quand elle est une de ses propriétaires (``owners`` : ses
    clés de personne) : un partage n'y retire rien."""
    if not person or owner == person or (not owner and person.removeprefix(PERSON) in set(owners)):
        return False
    level = given.get(person, "")
    return bool(level) and not reaches(level, SHARE_USE)


def held(keys: Iterable[str], owners: Mapping[str, str], shares: Mapping[str, Mapping[str, str]], person: str, *,
         owner: bool) -> dict[str, str]:
    """Ce qu'une personne (``personne:<clé>``) a de ces comptes, et à quel niveau : ``OWNED`` pour les siens — à son
    nom, ou sans propriétaire nommé si elle est une de ses propriétaires (``owner``) —, le niveau de son partage pour
    ceux qu'on lui partage. Les autres n'y sont pas."""
    out: dict[str, str] = {}
    for key in keys:
        holder = owners.get(key, "")
        if (not holder and owner) or holder == person:
            out[key] = OWNED
        elif level := shares.get(key, {}).get(person, ""):
            out[key] = level
    return out


def best_handle(handles: Sequence[str], here: Collection[str], reachable: Collection[str]) -> str:
    """L'adresse où trouver une personne, pour qu'elle décide : une présente, sinon une où l'on peut lui écrire, sinon
    la première. Vide : elle n'en a pas."""
    return next((h for h in handles if h in here), None) or next((h for h in handles if h in reachable), None) \
        or (handles[0] if handles else "")

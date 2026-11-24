"""Contrat du plugin ``agenda`` (ADR 0309) : ce que les autres en lisent — les raisons de ce qu'elle fait d'elle-même
avec un agenda (lot 3b), la provenance d'un rappel dit, et où en sont un rappel et une invitation (ce que gardent les
épisodes qui les portent).

- **Ses rappels** : avant un rendez-vous, au délai que son agenda demande (« Mika te le rappelle »), elle prévient la
  personne — une initiative **due** (``REMIND``, dans ``agency.OWED`` : un rappel que la personne a demandé en réglant
  son agenda, comme celui qu'on lui demande en mots), que l'arbitre juge comme les autres : son sommeil, le quota, ce
  qu'elle fait déjà. Le sujet de l'épisode est l'occurrence (``reminder_subject``) ; ce que son prompt lui montrait du
  rendez-vous quand elle a parlé porte la même clé (sa provenance) : c'est dit.
- **Les invitations préparées** : une invitation qui attend sa réponse appelle une tâche (``PREPARE``) qui prépare la
  réponse ; elle part toujours sur l'accord de la personne.
"""

from __future__ import annotations

from mika.kernel.facts import FactFamily

OWNER = "agenda"
#: sa famille d'outils
BUNDLE = "agenda"

#: Raison (due) : un rendez-vous approche, et son agenda lui demande de le rappeler à la personne.
REMIND = "agenda_remind"
#: Raison d'une tâche : une invitation attend sa réponse — préparer celle que la personne enverra.
PREPARE = "agenda_prepare"

#: le sujet d'un rappel (celui de son épisode), et la provenance de ce que son prompt en montrait
REMINDER_PREFIX = "agenda:rappel:"
#: où en est un rappel : dû (pas encore dit), dit, tombé (le rendez-vous a bougé, été annulé, refusé, ou son agenda ne
#: le demande plus) ; « » : inconnu
DUE, TOLD, DROPPED = "du", "dit", "tombe"
#: où en est une invitation : elle attend une réponse ; réglée (répondue, partie, commencée) ; « » : inconnue
PENDING, SETTLED = "attend", "reglee"

#: Où en est ce rappel (sa clé) : ce que garde l'initiative qui le dit.
REMINDER = FactFamily("agenda.reminder", arg=str, type=str)
#: Où en est cette invitation (sa clé) : ce que garde la tâche qui prépare sa réponse.
INVITATION = FactFamily("agenda.invitation", arg=str, type=str)


def reminder_subject(key: str) -> str:
    """Le sujet d'un rappel, et la provenance de ce que son prompt en montrait : ``agenda:rappel:<clé>``."""
    return f"{REMINDER_PREFIX}{key}"


def reminder_of(subject: str | None) -> str:
    """La clé d'un rappel d'après un sujet ou une provenance ; vide sinon."""
    return subject[len(REMINDER_PREFIX):] if subject and subject.startswith(REMINDER_PREFIX) else ""


__all__ = ["BUNDLE", "DROPPED", "DUE", "INVITATION", "OWNER", "PENDING", "PREPARE", "REMIND", "REMINDER",
           "REMINDER_PREFIX", "SETTLED", "TOLD", "reminder_of", "reminder_subject"]

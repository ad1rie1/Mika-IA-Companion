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
- **Le tableau de droits d'un agenda** : son type de ligne (``AgendaRule``, dans le cadre commun de ``vocab.access`` :
  qui, par où, quand) et ses colonnes, que lisent son plugin, ses réglages, son API et sa console ; les tableaux
  réglés se rangent sous sa sorte (``RIGHTS_SORT``, ``Rights.sort``). Le type de ligne d'une sorte de ressource est au
  contrat de son propriétaire, son calcul dans son plugin (``plugins/agenda/rights.py``, ADR 0316).
"""

from __future__ import annotations

from typing import Annotated, Literal

from mika.kernel.facts import FactFamily
from mika.kernel.forms import Knob
from mika.vocab.access import ALONE, CARD, KEEPS, NO, Keep, Rule

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


# ── son tableau de droits ───────────────────────────────────────────────────

#: la sorte de ses tableaux de droits (ADR 0316) : celle sous laquelle ses réglages rendent le tableau réglé de chaque
#: agenda (``Rights.sort``) — la même chaîne que la sorte de droits que son plugin déclare (``@AGENDA.rights``) et que
#: son sous-onglet de Réglages › Droits (``RightsSort``)
RIGHTS_SORT = "agendas"

#: un agenda (ADR 0309) : y écrire — ajouter, modifier, supprimer — seule, avec l'accord de qui s'en sert (une carte
#: d'accord), ou non ; répondre à ses invitations avec cet accord, ou non
AGREE = "accord"
WRITES = ((NO, "non"), (AGREE, "avec ton accord"), (ALONE, "seule"))
RESPONDS = ((NO, "non"), (AGREE, "avec ton accord"))
WRITE_WORDS = dict(WRITES)
#: ce qu'une colonne d'agenda vaut parmi les règles d'un outil (``POLICIES``) : l'accord est une carte
AGENDA_POLICY = {NO: NO, AGREE: CARD, ALONE: ALONE}
Write = Literal["non", "accord", "seule"]
Respond = Literal["non", "accord"]


class AgendaRule(Rule):
    """Une ligne du tableau d'un agenda (ADR 0309), dans le cadre commun (qui, par où, quand) : le lire, y écrire
    (``WRITES``), répondre à ses invitations (``RESPONDS``), et ce qu'elle garde de ce qu'elle y lit (``KEEPS``)."""

    read: Annotated[bool, Knob(label="Lire", advanced=False)] = False
    write: Annotated[Write, Knob(label="Ajouter, modifier, supprimer", choices=WRITES, advanced=False)] = NO
    respond: Annotated[Respond, Knob(label="Répondre aux invitations", choices=RESPONDS, advanced=False)] = NO
    keep: Annotated[Keep, Knob(label="Ce qu'elle en garde", choices=KEEPS, advanced=False)] = "rien"


#: une ligne d'agenda fermée (la ligne par défaut : personne d'autre)
CLOSED_AGENDA = AgendaRule()


__all__ = ["AGENDA_POLICY", "AGREE", "BUNDLE", "CLOSED_AGENDA", "DROPPED", "DUE", "INVITATION", "OWNER", "PENDING",
           "PREPARE", "REMIND", "REMINDER", "REMINDER_PREFIX", "RESPONDS", "RIGHTS_SORT", "SETTLED", "TOLD",
           "WRITES", "WRITE_WORDS", "AgendaRule", "Respond", "Write", "reminder_of", "reminder_subject"]

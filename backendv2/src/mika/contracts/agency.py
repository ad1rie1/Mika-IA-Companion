"""Contrat d'``agency`` : le budget d'initiatives, la période réfractaire —
et ce qui n'est pas « prendre la parole ».

Une initiative ne compte qu'une fois **dite** (un énoncé visible) : un
silence, une panne, une initiative supplantée ne consomment rien. Une
abstention laisse une courte hésitation ; un murmure « sans suite » (elle
s'apprêtait à écrire à quelqu'un, puis s'est ravisée) arrête l'initiative
qu'il précédait.

Toutes les raisons d'aller vers quelqu'un ne se valent pas : certaines sont
**dues** (tenir parole), d'autres **préviennent** (ce qui ne peut pas
attendre), d'autres **saluent** qui arrive. C'est déclaré ici, une fois, et
lu par chaque retenue (le budget, ne pas harceler, la rancune, l'heure où la
personne répond) — jamais redit dans une faculté.
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.contracts import email as email_c
from mika.contracts import goals as goals_c
from mika.contracts import memory as memory_c
from mika.contracts import projects as projects_c
from mika.contracts import social as social_c
from mika.kernel.episode import Outcome
from mika.kernel.facts import FactFamily, FactKey

OWNER = "agency"

DAILY_CAP = "daily_cap"
REFRACTORY = "refractory"
#: Veto : des initiatives restées sans réponse vers cette personne — plus rien tant qu'elle n'a pas écrit (une
#: seule relance douce, après un long délai, vers une amie ou une proche).
UNANSWERED = "unanswered"
#: Veto : son dernier message à cette personne attend encore sa réponse (quelques heures de retenue).
AWAITING_REPLY = "awaiting_reply"
#: on s'est dit au revoir (« bonne nuit », « je file ») : pas d'initiative ordinaire tout de suite après, même
#: si la personne reste connectée
FAREWELL = "farewell"
#: Veto : elle allait lui écrire et s'est ravisée (un murmure sans suite) — pas tout de suite, donc.
CHANGED_MIND = "changed_mind"
#: Raison (sans preuve) des candidats qui portent la garde « elle s'est ravisée » vers une adresse présente.
SECOND_THOUGHTS = "second_thoughts"

#: Ce qui est **dû** : tenir parole — dire à l'heure dite le rappel qu'on lui a demandé, faire au moment dit ce
#: qu'elle avait promis (« je te demanderai jeudi soir comment ça s'est passé », ``memory.KEEP_PROMISE``). Ce
#: n'est pas « prendre la parole » : ni le plafond du jour, ni la période réfractaire, ni la retenue envers qui
#: ne répond pas, ni l'heure où la personne répond d'habitude ne s'y appliquent ; une rancune non plus — elle
#: colore le ton, elle ne reprend pas la promesse.
OWED = frozenset({goals_c.REMIND, memory_c.KEEP_PROMISE})
#: Ce qui **prévient** : ce qui ne peut pas attendre et regarde la personne au premier chef — un mail important
#: arrivé pour sa propriétaire, un projet qu'elle lui a confié qui n'avance plus sans elle. Prévenir n'est pas
#: relancer : la retenue « ne pas harceler » ne s'y applique pas, une rancune le décale au plus (on prévient
#: quelqu'un même fâchée contre lui), et être ignorée n'y change rien — ni l'allongement de la période
#: réfractaire par les initiatives restées sans réponse, ni l'envie moindre envers qui n'a pas répondu, ni s'être
#: ravisée de lui écrire pour autre chose. C'est déjà borné par sa source (une fois par mail, une fois par
#: objectif bloqué) ; le plafond du jour et la période réfractaire **de base** s'y appliquent toujours (ne pas
#: annoncer trois mails en trois messages d'affilée).
INFORMS = frozenset({email_c.MENTION, projects_c.NEED})
#: **Saluer** qui arrive : pas « prendre la parole » non plus (ni plafond, ni période réfractaire, ni retenue
#: envers qui ne répond pas) — mais une rancune l'empêche (ADR 0013 : pas même une salutation).
GREETS = frozenset({social_c.GREETING})
#: Ce qui n'est pas prendre la parole pour qu'on lui réponde : saluer qui arrive, tenir parole. Ni compté au
#: budget, ni suivi d'une période réfractaire, ni attendu en retour (ce n'était pas une question).
NOT_SPEAKING_UP = GREETS | OWED

#: Les fins d'une initiative qui ne sont pas un **essai** : elle a été devancée (la personne a écrit pendant
#: qu'elle composait), interrompue, annulée — elle n'a pas eu lieu. (Un murmure sans suite non plus : elle s'est
#: ravisée, « pas maintenant » — ``RENOUNCED`` le dit, à l'adresse visée.) Un silence choisi, une panne, si. Ce
#: qu'une faculté compte comme tentatives (dire un rappel, raconter, demander un coup de main) se compte ainsi.
UNTRIED = frozenset({Outcome.SUPERSEDED, Outcome.PREEMPTED, Outcome.CANCELLED, Outcome.INTERRUPTED})


def tried(outcome: str, started: int, renounced: int) -> bool:
    """Une initiative partie à ``started`` finit sans avoir rien dit : est-ce un essai ? Un silence choisi, une
    panne, oui ; pas une initiative devancée, interrompue ou annulée (``UNTRIED``), ni un murmure sans suite —
    ``renounced`` (le fait ``RENOUNCED`` de l'adresse visée) postérieur à son départ."""
    return outcome not in UNTRIED and not (renounced and started and renounced >= started)


@dataclass(frozen=True, slots=True)
class AgencyReading:
    initiatives_today: int
    last_initiative_at: int
    refractory_until: int
    murmured_at: int = 0
    #: la dernière hésitation (une abstention, une panne, un murmure sans suite)
    hesitated_at: int = 0
    #: la fin de la période réfractaire **de base** (sans l'allongement par les initiatives ignorées) : celle
    #: qui s'applique à ce qui prévient (``INFORMS``)
    base_until: int = 0


AGENCY = FactKey("agency.agency", type=AgencyReading, time_varying=True)
#: Quand elle s'est ravisée pour la dernière fois d'écrire à cette adresse (0 : jamais).
RENOUNCED = FactFamily("agency.renounced", arg=str, type=int)

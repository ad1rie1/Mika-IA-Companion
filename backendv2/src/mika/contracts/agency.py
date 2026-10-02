"""Contrat d'``agency`` : le budget d'initiatives, la période réfractaire.

Une initiative ne compte qu'une fois **dite** (un énoncé visible) : un
silence, une panne, une initiative supplantée ne consomment rien. Une
abstention laisse une courte hésitation ; un murmure « sans suite » (elle
s'apprêtait à écrire à quelqu'un, puis s'est ravisée) arrête l'initiative
qu'il précédait.
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.facts import FactFamily, FactKey

OWNER = "agency"

DAILY_CAP = "daily_cap"
REFRACTORY = "refractory"
#: Veto : des initiatives restées sans réponse vers cette personne — plus rien tant qu'elle n'a pas écrit (une
#: seule relance douce, après un long délai, vers une amie ou une proche).
UNANSWERED = "unanswered"
#: Veto : son dernier message à cette personne attend encore sa réponse (quelques heures de retenue).
AWAITING_REPLY = "awaiting_reply"
#: Veto : elle allait lui écrire et s'est ravisée (un murmure sans suite) — pas tout de suite, donc.
CHANGED_MIND = "changed_mind"
#: Raison (sans preuve) des candidats qui portent la garde « elle s'est ravisée » vers une adresse présente.
SECOND_THOUGHTS = "second_thoughts"


@dataclass(frozen=True, slots=True)
class AgencyReading:
    initiatives_today: int
    last_initiative_at: int
    refractory_until: int
    murmured_at: int = 0
    #: la dernière hésitation (une abstention, une panne, un murmure sans suite)
    hesitated_at: int = 0


AGENCY = FactKey("agency.agency", type=AgencyReading, time_varying=True)
#: Quand elle s'est ravisée pour la dernière fois d'écrire à cette adresse (0 : jamais).
RENOUNCED = FactFamily("agency.renounced", arg=str, type=int)

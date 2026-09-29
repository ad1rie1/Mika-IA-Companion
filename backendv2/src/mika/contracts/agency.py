"""Contrat d'``agency`` : le budget d'initiatives, la période réfractaire."""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.facts import FactKey

OWNER = "agency"

DAILY_CAP = "daily_cap"
REFRACTORY = "refractory"


@dataclass(frozen=True, slots=True)
class AgencyReading:
    initiatives_today: int
    last_initiative_at: int
    refractory_until: int
    murmured_at: int = 0


AGENCY = FactKey("agency.agency", type=AgencyReading, time_varying=True)

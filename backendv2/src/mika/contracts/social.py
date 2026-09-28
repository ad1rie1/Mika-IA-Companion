"""Contrat de ``social`` : les liens (minimal en M1 : la salutation)."""

from __future__ import annotations

from mika.kernel.facts import FactFamily

OWNER = "social"

GREETING = "greeting"
PRESENT_PERSON = "present"

#: Instant de la dernière salutation adressée à cette personne (0 si jamais).
GREETED = FactFamily("social.greeted", arg=str, type=int)

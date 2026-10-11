"""Ses absences : revenue d'un arrêt de son serveur (``kernel.absences``), elle sait quelques heures durant qu'elle
n'était pas là, de quand à quand — ce silence, elle ne l'a pas vécu."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.contracts import self_ as c
from mika.faculties.self import days
from mika.faculties.self.faculty import SELF, SelfState
from mika.faculties.self.knobs import params
from mika.kernel.builtin import ABSENCES
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.vocab.episodes import CONVERSATIONAL
from mika.vocab.phrasebook import phrase


@SELF.section("absence", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=80,
              title=phrase("self.absence.title"), reads=[ABSENCES])
def _absence(s: SelfState, frame: Frame, enrich: Mapping[str, Any]) -> str | None:
    """Revenue d'un arrêt de son serveur, elle sait qu'elle n'était pas là, de quand à quand — quelques heures
    après son retour : un « ça fait longtemps ! » ferait croire qu'elle a vécu ce silence. Un fait, sans s'en
    excuser ; une persona incarnée n'entend pas parler de serveur (ADR 0070)."""
    p = params(frame.env.params_of("self", frame.root))
    if not p.absence_told_us:
        return None
    recent = [a for a in frame.get(ABSENCES) if 0 <= frame.now - a.until <= p.absence_told_us]
    if not recent:
        return None
    tz = frame.env.tz_of(frame.root)
    spans = phrase("self.absence.then").join(
        phrase("self.absence.span", since=days.instant_fr(a.since, frame.now, tz),
               until=days.instant_fr(a.until, frame.now, tz)) for a in recent)
    if s.persona.nature == c.EMBODIED:
        return phrase("self.absence.embodied", spans=spans)
    return phrase("self.absence.machine", spans=spans)

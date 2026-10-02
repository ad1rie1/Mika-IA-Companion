"""Ses journées vécues : où commence une journée, à quelle journée appartient
une nuit.

Une journée vécue commence une heure avant son matin (5 h pour le profil type,
plus tard pour un oiseau de nuit) : une heure du matin appartient encore à la
veille. Une nuit appartient à la journée qu'elle clôt : s'endormir à 6 h 30
après une nuit blanche, c'est encore finir la veille.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from mika.kernel.clock import HOUR, instant, local
from mika.vocab import circadian

#: un endormissement jusqu'à tant d'heures après le début de la journée appartient encore à la veille
NIGHT_SPILL_US = 5 * HOUR


def day_starts(profile: circadian.Profile | None) -> int:
    """La minute locale où commence une journée vécue : une heure avant son matin."""
    morning = (profile or circadian.DEFAULT).start_of(circadian.Phase.MORNING)
    return (morning - 60) % (24 * 60)


def lived_day(t: int, tz: Any, starts: int) -> date:
    return (local(t, tz) - timedelta(minutes=starts)).date()


def night_of(t: int, tz: Any, starts: int) -> date:
    """La journée qu'un endormissement à ``t`` vient clore."""
    return lived_day(t - NIGHT_SPILL_US, tz, starts)


def day_window(day: date, tz: Any, starts: int) -> tuple[int, int]:
    start = datetime.combine(day, time(starts // 60, starts % 60), tzinfo=tz)
    return instant(start), instant(start + timedelta(days=1))


def moment(t: int, tz: Any, profile: circadian.Profile | None) -> str:
    """« le matin », « l'après-midi »… selon son rythme."""
    return circadian.MOMENT_FR[circadian.phase_of(local(t, tz), profile or circadian.DEFAULT)]

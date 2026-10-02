"""Dire quand, comme on le dit : en jours du calendrier, pas en durées.

« Hier soir » pour la veille à 21 h, même si ça ne fait que douze heures ;
« avant-hier », « il y a quatre jours ». Une durée de moins d'un jour n'est
pas « aujourd'hui » quand elle a franchi minuit.
"""

from __future__ import annotations

from typing import Any

from mika.kernel.clock import HOUR, local


def _part(hour: int) -> str:
    """Le moment de la journée (heure locale)."""
    if 5 <= hour < 12:
        return "matin"
    if 12 <= hour < 18:
        return "après-midi"
    if 18 <= hour < 24:
        return "soir"
    return "nuit"


_TODAY = {"matin": "ce matin", "après-midi": "cet après-midi", "soir": "ce soir", "nuit": "cette nuit"}
_YESTERDAY = {"matin": "hier matin", "après-midi": "hier après-midi", "soir": "hier soir",
              "nuit": "dans la nuit d'hier"}


def when_fr(then: int, now: int, tz: Any) -> str:
    """« tout à l'heure », « ce matin », « hier soir », « avant-hier », « il y a 4 jours »."""
    if then <= 0:
        return "il y a longtemps"
    if now - then < HOUR and now >= then:
        return "tout à l'heure"
    a, b = local(then, tz), local(now, tz)
    days = (b.date() - a.date()).days
    if days <= 0:
        return _TODAY[_part(a.hour)]
    if days == 1:
        return _YESTERDAY[_part(a.hour)]
    if days == 2:
        return "avant-hier"
    return f"il y a {days} jours"

"""Dire quand, comme on le dit : en jours du calendrier, pas en durées.

« Hier soir » pour la veille à 21 h, même si ça ne fait que douze heures ;
« avant-hier », « il y a quatre jours ». Une durée de moins d'un jour n'est
pas « aujourd'hui » quand elle a franchi minuit.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, time, timedelta
from typing import Any

from mika.kernel.clock import HOUR, instant, local
from mika.vocab.phrasebook import phrase


def part_of_day(hour: int) -> str:
    """Le moment de la journée (heure locale) : midi n'est pas l'après-midi (« ce midi », pas « cet après-midi
    (vers 12 h) »)."""
    if 5 <= hour < 12:
        return "matin"
    if 12 <= hour < 14:
        return "midi"
    if 14 <= hour < 18:
        return "après-midi"
    if 18 <= hour < 24:
        return "soir"
    return "nuit"


#: le moment de la journée → sa clé dans sa voix (``expression.when.today.…``, ``expression.when.yesterday.…``)
_PART_KEYS = {"matin": "morning", "midi": "noon", "après-midi": "afternoon", "soir": "evening", "nuit": "night"}


def when_fr(then: int, now: int, tz: Any) -> str:
    """« tout à l'heure », « ce matin », « hier soir », « avant-hier », « il y a 4 jours » — ``expression.when``
    dans sa voix."""
    if then <= 0:
        return phrase("expression.when.long_ago")
    if now - then < HOUR and now >= then:
        return phrase("expression.when.just_now")
    a, b = local(then, tz), local(now, tz)
    days = (b.date() - a.date()).days
    if days <= 0:
        return phrase(f"expression.when.today.{_PART_KEYS[part_of_day(a.hour)]}")
    if days == 1:
        return phrase(f"expression.when.yesterday.{_PART_KEYS[part_of_day(a.hour)]}")
    if days == 2:
        return phrase("expression.when.day_before")
    return phrase("expression.when.days_ago", days=days)


_WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
#: les moments d'une journée, en heures locales [début, fin)
_PARTS = {"matin": (5, 12), "midi": (11, 14), "apres-midi": (12, 18), "aprem": (12, 18), "soir": (17, 24),
          "nuit": (21, 29)}
_WHEN = re.compile(r"\b(avant-hier|hier|ce|cet|cette|" + "|".join(_WEEKDAYS) + r")\b"
                   r"(?:\s+(?:dernier|derniere))?(?:\s+(matin|midi|apres-midi|aprem|soir|nuit))?")


def _folded(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def window_of(text: str, now: int, tz: Any) -> tuple[int, int] | None:
    """Le moment passé qu'une phrase désigne, en instants [début, fin) : « lundi matin » (le dernier lundi passé),
    « hier soir », « avant-hier », « ce matin ». ``None`` si elle n'en désigne aucun. Sert à se souvenir par le
    temps — « tu te souviens de ce que je t'ai dit lundi matin ? » ne contient aucun mot du souvenir."""
    m = next((m for m in _WHEN.finditer(_folded(text))
              if m.group(1) not in ("ce", "cet", "cette") or m.group(2)), None)  # « ce que », « ce truc » : non
    if m is None:
        return None
    word, part = m.group(1), m.group(2)
    today = local(now, tz).date()
    if word in ("ce", "cet", "cette"):
        day = today
    elif word == "hier":
        day = today - timedelta(days=1)
    elif word == "avant-hier":
        day = today - timedelta(days=2)
    else:
        back = (today.weekday() - _WEEKDAYS.index(word)) % 7 or 7  # le dernier passé, jamais aujourd'hui
        day = today - timedelta(days=back)
    lo, hi = _PARTS.get(part, (0, 24)) if part else (0, 24)
    start = datetime.combine(day, time(0), tzinfo=tz) + timedelta(hours=lo)
    end = datetime.combine(day, time(0), tzinfo=tz) + timedelta(hours=hi)
    return instant(start), min(instant(end), now)

"""Dire quand, comme on le dit : en jours du calendrier, pas en durées.

« Hier soir » pour la veille à 21 h, même si ça ne fait que douze heures ;
« avant-hier », « il y a quatre jours ». Une durée de moins d'un jour n'est
pas « aujourd'hui » quand elle a franchi minuit.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from typing import Any

from mika.kernel.clock import HOUR, MINUTE, instant, local
from mika.kernel.text import fold
from mika.vocab.phrasebook import phrase


def part_of_day(hour: int) -> str:
    """La clé de voix du moment de la journée (heure locale) : ``morning``, ``noon``, ``afternoon``, ``evening`` ou
    ``night``, celle des familles ``expression.when.today`` / ``yesterday`` et ``identity.calendar.today`` /
    ``yesterday``. Midi n'est pas l'après-midi (« ce midi », pas « cet après-midi (vers 12 h) »)."""
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 14:
        return "noon"
    if 14 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 24:
        return "evening"
    return "night"


def _calendar(then: int, now: int, tz: Any) -> tuple[str, int, str]:
    """Le cas d'un instant passé, en jours du calendrier, que ``when_fr`` et ``since_fr`` disent chacune à sa façon :
    ``long_ago`` (instant inconnu), ``just_now`` (moins d'une heure), ``today``, ``yesterday``, ``day_before`` ou
    ``days_ago`` (trois jours ou plus) ; avec le nombre de jours et le moment de la journée (``part_of_day``)."""
    if then <= 0:
        return "long_ago", 0, ""
    if now - then < HOUR and now >= then:
        return "just_now", 0, ""
    a, b = local(then, tz), local(now, tz)
    days, part = (b.date() - a.date()).days, part_of_day(a.hour)
    if days <= 0:
        return "today", days, part
    if days == 1:
        return "yesterday", days, part
    if days == 2:
        return "day_before", days, part
    return "days_ago", days, part


def _when(case: str, days: int, part: str) -> str:
    if case == "long_ago":
        return phrase("expression.when.long_ago")
    if case == "just_now":
        return phrase("expression.when.just_now")
    if case == "today":
        return phrase(f"expression.when.today.{part}")
    if case == "yesterday":
        return phrase(f"expression.when.yesterday.{part}")
    if case == "day_before":
        return phrase("expression.when.day_before")
    return phrase("expression.when.days_ago", days=days)


def when_fr(then: int, now: int, tz: Any) -> str:
    """« tout à l'heure », « ce matin », « hier soir », « avant-hier », « il y a 4 jours » — ``expression.when``
    dans sa voix. Après « depuis », ``since_fr``."""
    return _when(*_calendar(then, now, tz))


def since_fr(then: int, now: int, tz: Any) -> str:
    """Depuis quand, à placer après « depuis » : « 4 jours », « hier soir », « la nuit d'hier », « longtemps ». Les
    mêmes cas que ``when_fr``, dans le même ordre ; trois se disent autrement après « depuis »
    (``expression.when.since`` dans sa voix) : l'instant inconnu, trois jours ou plus, et la veille entre 0 et 5 h.
    Les autres sont ceux de ``when_fr`` (« tout à l'heure », « ce matin », « avant-hier »). Le texte d'une phrase ne
    se découpe jamais : le cas se lit sur l'instant."""
    case, days, part = _calendar(then, now, tz)
    if case == "long_ago":
        return phrase("expression.when.since.long_ago")
    if case == "days_ago":
        return phrase("expression.when.since.days_ago", days=days)
    if case == "yesterday" and part == "night":
        return phrase("expression.when.since.yesterday_night")
    return _when(case, days, part)


def ago_words(us: int) -> str:
    """Depuis combien de temps, en peu de mots, à mettre après « il y a » ou « depuis » : en minutes jusqu'à deux
    heures, en heures jusqu'à deux jours, en jours au-delà — ``timespan.ago`` dans sa voix. Une durée, pas un moment :
    pour le jour du calendrier, ``when_fr`` (``since_fr`` après « depuis »)."""
    minutes = max(1, us // MINUTE)
    if minutes < 120:
        return phrase("timespan.ago.minutes", n=minutes)
    hours = minutes // 60
    return phrase("timespan.ago.hours", n=hours) if hours < 48 else phrase("timespan.ago.days", n=hours // 24)


_WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
#: les moments d'une journée, en heures locales [début, fin)
_PARTS = {"matin": (5, 12), "midi": (11, 14), "apres-midi": (12, 18), "aprem": (12, 18), "soir": (17, 24),
          "nuit": (21, 29)}
_WHEN = re.compile(r"\b(avant-hier|hier|ce|cet|cette|" + "|".join(_WEEKDAYS) + r")\b"
                   r"(?:\s+(?:dernier|derniere))?(?:\s+(matin|midi|apres-midi|aprem|soir|nuit))?")


def window_of(text: str, now: int, tz: Any) -> tuple[int, int] | None:
    """Le moment passé qu'une phrase désigne, en instants [début, fin) : « lundi matin » (le dernier lundi passé),
    « hier soir », « avant-hier », « ce matin ». ``None`` si elle n'en désigne aucun. Sert à se souvenir par le
    temps — « tu te souviens de ce que je t'ai dit lundi matin ? » ne contient aucun mot du souvenir."""
    m = next((m for m in _WHEN.finditer(fold(text))
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

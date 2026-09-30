"""Le temps, injecté.

Un ``Instant`` est un nombre entier de microsecondes depuis l'époque Unix, en
UTC : exact, hachable, sans dérive de flottants. Tout le code lit le temps par
une ``Clock`` ; seules les implémentations d'horloge (adaptateurs, simulateur)
touchent à l'heure du système.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import NewType, Protocol
from zoneinfo import ZoneInfo

Instant = NewType("Instant", int)

US = 1_000_000
MINUTE = 60 * US
HOUR = 60 * MINUTE
DAY = 24 * HOUR

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def instant(dt: datetime) -> Instant:
    """Convertit une date avec fuseau en ``Instant``."""
    if dt.tzinfo is None:
        raise ValueError("date sans fuseau : ambiguë, refusée")
    delta = dt - _EPOCH
    return Instant((delta.days * 86_400 + delta.seconds) * US + delta.microseconds)


def as_datetime(t: int) -> datetime:
    """``Instant`` → date UTC avec fuseau."""
    return _EPOCH + timedelta(microseconds=int(t))


def seconds(t: int) -> float:
    return t / US


def of_seconds(s: float) -> int:
    return round(s * US)


def local(t: int, tz: ZoneInfo) -> datetime:
    """L'heure locale d'un instant dans un fuseau (heure d'été comprise)."""
    return as_datetime(t).astimezone(tz)


def next_local(after: int, hour: int, minute: int, tz: ZoneInfo) -> Instant:
    """Le prochain instant strictement après ``after`` où l'horloge murale locale
    affiche ``hour:minute``.

    Robuste aux changements d'heure : une heure qui n'existe pas (passage à
    l'heure d'été) est repoussée d'autant ; une heure qui existe deux fois
    (passage à l'heure d'hiver) n'est prise qu'à sa première occurrence.
    """
    day = local(after, tz).date()
    for offset in range(0, 3):
        d = day + timedelta(days=offset)
        candidate = datetime(d.year, d.month, d.day, hour, minute, tzinfo=tz, fold=0)
        # Une heure inexistante se normalise en aller-retour UTC.
        roundtrip = candidate.astimezone(UTC).astimezone(tz)
        t = instant(roundtrip)
        if t > after:
            return t
    raise AssertionError("aucune occurrence locale trouvée en trois jours")


def within_daily_window(minute: int, start: int, end: int) -> bool:
    """``minute`` (depuis minuit, heure locale) tombe-t-elle dans la plage
    quotidienne ``[start, end]`` ? Une plage dont la fin précède le début passe
    minuit (22 h – 2 h) ; début = fin : cette minute-là seulement."""
    if start <= end:
        return start <= minute <= end
    return minute >= start or minute <= end


def local_date_of_night(t: int, tz: ZoneInfo, day_starts_at_hour: int = 5):
    """La date « de la journée vécue » : avant ``day_starts_at_hour`` h, une
    heure de la nuit appartient encore à la veille."""
    dt = local(t, tz)
    return (dt - timedelta(hours=day_starts_at_hour)).date()


class Clock(Protocol):
    """Source unique du temps."""

    def now(self) -> Instant: ...

    async def sleep_until(self, t: int) -> None: ...


class ManualClock:
    """Horloge réglée à la main, pour les tests sans boucle à temps virtuel.

    ``sleep_until`` avance l'horloge jusqu'à l'échéance et rend la main.
    """

    def __init__(self, start: int = 0) -> None:
        self._t = int(start)

    def now(self) -> Instant:
        return Instant(self._t)

    def set(self, t: int) -> None:
        if t < self._t:
            raise ValueError("le temps ne recule pas")
        self._t = int(t)

    def advance(self, dt: int) -> Instant:
        self.set(self._t + int(dt))
        return self.now()

    async def sleep_until(self, t: int) -> None:
        if t > self._t:
            self._t = int(t)

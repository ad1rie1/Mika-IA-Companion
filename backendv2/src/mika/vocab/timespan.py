"""Le temps des choses (ADR 0084) : une date dite avec sa précision.

Un moment n'a pas toujours un jour : « en novembre », « au printemps 2027 », « l'an prochain », « entre le 3 et le
10 ». ``Timespan`` garde le début et la fin de la période, sa précision et l'instant qui la représente (un jour à
18 h, la fin d'une journée — ADR 0052 —, le début d'une période). ``parse`` lit ce que la relecture écrit (des formes
qu'on lui demande : AAAA-MM-JJ, AAAA-MM, AAAA, « printemps AAAA », AAAA-MM-JJ/AAAA-MM-JJ) — jamais une phrase de la
conversation ; ``words`` le redit comme on le dit, jamais un nombre de plus qu'une date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from mika.kernel.clock import instant
from mika.vocab.phrasebook import phrase, phrases
from mika.vocab.words import fold

#: la précision d'une date : un jour (ou une heure) — la forme d'avant, vide —, un mois, une saison, une année, une
#: période entre deux dates
DAY, MONTH, SEASON, YEAR, RANGE = "", "month", "season", "year", "range"
PRECISIONS = (DAY, MONTH, SEASON, YEAR, RANGE)
#: les saisons (météorologiques : un mois plein de plus ou de moins ne change pas ce qu'on attend) — le premier mois,
#: et les noms qu'écrit un modèle
SEASONS = {"spring": 3, "summer": 6, "autumn": 9, "winter": 12}
_SEASON_NAMES = {"printemps": "spring", "spring": "spring", "ete": "summer", "summer": "summer",
                 "automne": "autumn", "autumn": "autumn", "fall": "autumn", "hiver": "winter", "winter": "winter"}
_RANGE = re.compile(r"\s*(?:/|\.\.|\bau\b|\bto\b|→)\s*")
_DAY_HOUR = time(18, 0)


@dataclass(frozen=True, slots=True)
class Timespan:
    """Une période : son début et sa fin (µs, compris), sa précision, et l'instant qui la représente (``point`` : un
    jour à 18 h, ou l'heure dite ; le début d'une période plus large)."""

    start: int
    end: int
    precision: str
    point: int
    all_day: bool = True

    @property
    def vague(self) -> bool:
        """Plus large qu'un jour : ni la veille ni le lendemain n'ont de sens."""
        return self.precision != DAY

    def current(self, now: int) -> bool:
        return self.start <= now <= self.end

    def ahead(self, now: int, within_us: int) -> bool:
        """Commence dans les ``within_us`` qui viennent (ou a commencé et dure encore)."""
        return self.current(now) or now < self.start <= now + within_us

    def past(self, now: int) -> bool:
        return self.end < now


def _at(d: date, t: time, tz: ZoneInfo) -> int:
    return instant(datetime.combine(d, t, tzinfo=tz))


def _whole(first: date, last: date, precision: str, tz: ZoneInfo) -> Timespan:
    start = _at(first, time(0, 0), tz)
    return Timespan(start, _at(last, time(23, 59, 59), tz), precision, _at(first, _DAY_HOUR, tz))


def _month_end(year: int, month: int) -> date:
    return (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1))


def _one(text: str, tz: ZoneInfo) -> Timespan | None:
    """Une date seule, avec sa précision."""
    raw = text.strip()
    folded = fold(raw)
    words = folded.replace("-", " ").split()
    season = next((_SEASON_NAMES[w] for w in words if w in _SEASON_NAMES), None)
    if season is not None:
        year = next((int(w) for w in words if w.isdigit() and len(w) == 4), None)
        if year is None:
            return None
        first = SEASONS[season]
        last_year, last_month = (year + 1, 2) if first == 12 else (year, first + 2)
        return _whole(date(year, first, 1), _month_end(last_year, last_month), SEASON, tz)
    if re.fullmatch(r"\d{4}", raw):
        year = int(raw)
        return _whole(date(year, 1, 1), date(year, 12, 31), YEAR, tz)
    if re.fullmatch(r"\d{4}-\d{2}", raw):
        year, month = int(raw[:4]), int(raw[5:])
        if not 1 <= month <= 12:
            return None
        return _whole(date(year, month, 1), _month_end(year, month), MONTH, tz)
    try:
        moment = datetime.fromisoformat(raw)
        all_day = len(raw) <= 10
    except ValueError:
        try:
            moment, all_day = datetime.combine(date.fromisoformat(raw[:10]), _DAY_HOUR), True
        except ValueError:
            return None
    if all_day:
        moment = datetime.combine(moment.date(), _DAY_HOUR)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    day = moment.date()
    return Timespan(_at(day, time(0, 0), tz), _at(day, time(23, 59, 59), tz), DAY, instant(moment), all_day)


def parse(value: str | None, tz: ZoneInfo) -> Timespan | None:
    """Ce que la relecture écrit dans « quand » : un jour (AAAA-MM-JJ, l'heure si elle est dite), un mois (AAAA-MM),
    une année (AAAA), une saison (« printemps 2027 »), ou une période (« 2026-11-03/2026-11-10 ») ; ``None`` si
    illisible. Une période d'un seul jour est ce jour."""
    if not value or not value.strip():
        return None
    parts = [p for p in _RANGE.split(value.strip()) if p]
    if len(parts) == 2:
        first, last = _one(parts[0], tz), _one(parts[1], tz)
        if first is None or last is None or last.end < first.start:
            return None
        if first.start == last.start and first.end == last.end:
            return first
        return Timespan(first.start, last.end, RANGE, first.point)
    return _one(value, tz) if len(parts) == 1 else None


# ── en mots ─────────────────────────────────────────────────────────────────


def _month(n: int) -> str:
    return phrases("memory.dates.months")[n - 1]


def _day_month(d: date) -> str:
    day = phrase("memory.dates.first") if d.day == 1 else str(d.day)
    return phrase("memory.dates.date", day=day, month=_month(d.month))


def words(span: Timespan, now: int, tz: ZoneInfo) -> str:
    """Une période comme on la dit : « en novembre », « au printemps 2027 », « l'an prochain », « du 3 au 10
    novembre ». Un jour n'est pas son affaire (le rappel dit « jeudi », « demain »)."""
    return period_words(span.start, span.end, span.precision, now, tz)


def period_words(start_us: int, end_us: int, precision: str, now: int, tz: ZoneInfo) -> str:
    """``words`` d'après le début, la fin et la précision (un moment gardé n'a plus sa ``Timespan``)."""
    start = datetime.fromtimestamp(start_us / 1e6, tz).date()
    end = datetime.fromtimestamp(end_us / 1e6, tz).date()
    this_year = datetime.fromtimestamp(now / 1e6, tz).year
    if precision == MONTH:
        if start.year == this_year:
            return phrase("timespan.month", month=_month(start.month))
        return phrase("timespan.month_year", month=_month(start.month), year=start.year)
    if precision == SEASON:
        season = next(name for name, first in SEASONS.items() if first == start.month)
        said = phrase(f"timespan.seasons.{season}")
        return said if start.year == this_year else phrase("timespan.season_year", season=said, year=start.year)
    if precision == YEAR:
        if start.year == this_year:
            return phrase("timespan.this_year")
        if start.year == this_year + 1:
            return phrase("timespan.next_year")
        return phrase("timespan.year", year=start.year)
    if precision == RANGE:
        first = str(start.day) if start.month == end.month and start.year == end.year else _day_month(start)
        if start.day == 1 and first == "1":
            first = phrase("memory.dates.first")
        said = phrase("timespan.range", start=first, end=_day_month(end))
        return said if end.year == this_year else phrase("timespan.with_year", what=said, year=end.year)
    return _day_month(start)

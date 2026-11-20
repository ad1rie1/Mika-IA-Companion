"""Les dates d'un événement (ADR 0245) : ses occurrences telles que DATAtourisme les donne (``takesPlaceAt``) — un
jour, ou une période et ses jours de la semaine, avec ses heures —, ce qui en reste à venir, et comment le dire en
français, à l'heure de Paris : « ven. 20 nov. · 19:00–20:30 » (une date), « du mer. au dim. · 11:00–19:00 » (des dates
qui se suivent dans la semaine, aux mêmes heures), « le dim. · 08:00–12:00 · jusqu'au 31 déc. » (une période),
« jusqu'au 10 janv. ». Des fonctions pures : l'instant est donné."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from mika.adapters.maps.hours import DAYS_FR, PARIS
from mika.ports.maps import EventDate

MONTHS_SHORT = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")
#: les jours de la semaine chez DATAtourisme (``appliesOnDay[].key``), du lundi au dimanche : leur bit
WEEKDAY_KEYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
ALL_DAYS = 0x7F
#: au-delà de tant de jours, une date dit son année
YEAR_AFTER_DAYS = 180
#: des dates à moins d'une semaine l'une de l'autre, aux mêmes heures, se disent par leurs jours
WEEK = 7
#: une période plus longue ne se parcourt pas jour par jour (au-delà, ses jours se lisent par la semaine)
SPAN_DAYS_MAX = 3660
_HM = re.compile(r"^(\d{1,2}):(\d{2})")
_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


@dataclass(frozen=True, slots=True, order=True)
class Occurrence:
    """Une occurrence : du jour ``first`` au jour ``last`` (le même : un seul jour), de ``opens`` à ``closes``
    (« HH:MM », vides : on ne sait pas), les jours de la semaine ``days`` (bits, lundi 1 … dimanche 64 ; 0 : chaque
    jour de la période)."""

    first: date
    last: date
    opens: str = ""
    closes: str = ""
    days: int = 0

    @property
    def single(self) -> bool:
        return self.first == self.last

    def matches(self, d: date) -> bool:
        return self.first <= d <= self.last and (not self.days or bool(self.days >> d.weekday() & 1))

    def sessions(self, start: date, end: date) -> Iterator[date]:
        """Les jours où elle a lieu entre ``start`` et ``end`` (compris)."""
        d, stop = max(self.first, start), min(self.last, end)
        while d <= stop:
            if self.matches(d):
                yield d
            d += timedelta(days=1)

    def next_day(self, start: date) -> date | None:
        """Le premier jour où elle a lieu à partir de ``start`` ; ``None`` : elle est passée."""
        begin = max(self.first, start)
        for d in self.sessions(begin, min(self.last, begin + timedelta(days=WEEK))):
            return d
        return None


def _day(value: object) -> date | None:
    found = _DAY.match(value) if isinstance(value, str) else None
    if found is None:
        return None
    try:
        return date(int(found.group(1)), int(found.group(2)), int(found.group(3)))
    except ValueError:
        return None


def _hm(value: object) -> str:
    found = _HM.match(value.strip()) if isinstance(value, str) else None
    if found is None:
        return ""
    h, m = int(found.group(1)), int(found.group(2))
    if h > 24 or m > 59 or (h == 24 and m):
        return ""
    return f"{h:02d}:{m:02d}"


def occurrence_of(raw: object) -> Occurrence | None:
    """Une occurrence d'une fiche (``takesPlaceAt[]`` : ``startDate``, ``endDate``, ``startTime``, ``endTime``,
    ``appliesOnDay[].key``) ; illisible (sans date de début, à l'envers, démesurée) : ``None``."""
    if not isinstance(raw, dict):
        return None
    first = _day(raw.get("startDate"))
    last = _day(raw.get("endDate")) or first
    if first is None or last is None or last < first or (last - first).days > SPAN_DAYS_MAX:
        return None
    days = 0
    for item in raw.get("appliesOnDay") or ():
        key = item.get("key") if isinstance(item, dict) else None
        if key in WEEKDAY_KEYS:
            days |= 1 << WEEKDAY_KEYS.index(key)
    if days == ALL_DAYS or first == last:
        days = 0
    return Occurrence(first, last, _hm(raw.get("startTime")), _hm(raw.get("endTime")), days)


def merged(occurrences: Iterable[Occurrence]) -> list[Occurrence]:
    """Les occurrences de plusieurs fiches d'un même événement : chacune une fois, dans l'ordre."""
    return sorted(set(occurrences))


def _passed(o: Occurrence, d: date, now: datetime) -> bool:
    """La séance du jour ``d`` est finie à cet instant (aujourd'hui, son heure de fin passée)."""
    local = now.astimezone(PARIS)
    if d != local.date() or not o.closes or (o.opens and o.closes <= o.opens):
        return False  # un autre jour, une fin inconnue, ou après minuit
    return o.closes != "24:00" and o.closes <= f"{local.hour:02d}:{local.minute:02d}"


def _first_session(o: Occurrence, start: date, now: datetime) -> date | None:
    begin = max(o.first, start)
    stop = begin + timedelta(days=WEEK + 1)
    for d in o.sessions(begin, min(o.last, stop)):
        if not _passed(o, d, now):
            return d
    return o.next_day(stop) if o.last > stop else None  # la séance du jour finie : la semaine suivante


def upcoming(occurrences: Iterable[Occurrence], now: datetime, start: date | None = None,
             end: date | None = None) -> list[tuple[date, Occurrence]]:
    """Ce qui reste à venir (à partir de ``start``, aujourd'hui par défaut, et jusqu'à ``end``) : (sa prochaine
    séance, l'occurrence), les plus tôt d'abord. Une séance d'aujourd'hui dont l'heure de fin est passée ne compte
    plus."""
    today = now.astimezone(PARIS).date()
    begin = max(today, start or today)
    out = []
    for o in occurrences:
        if o.last < begin:
            continue
        first = _first_session(o, begin, now)
        if first is not None and (end is None or first <= end):
            out.append((first, o))
    out.sort(key=lambda item: (item[0], item[1].opens, item[1].closes, item[1].last))
    return out


# ── dire ──

def day_fr(d: date, today: date) -> str:
    """« ven. 20 nov. », « mar. 1er déc. », et l'année pour une date lointaine (« sam. 9 oct. 2027 »)."""
    return f"{DAYS_FR[d.weekday()]} {date_fr(d, today)}"


def date_fr(d: date, today: date) -> str:
    """« 20 nov. », « 1er déc. », « 9 oct. 2027 »."""
    text = f"{'1er' if d.day == 1 else d.day} {MONTHS_SHORT[d.month - 1]}"
    if d.year < today.year or (d - today).days > YEAR_AFTER_DAYS:
        text += f" {d.year}"
    return text


def hours_fr(opens: str, closes: str) -> str:
    """« 19:00–20:30 », « 19:00–minuit », « à partir de 19:00 », « jusqu'à 18:00 » ; rien sans heure."""
    def said(hm: str) -> str:
        return "minuit" if hm in ("00:00", "24:00") else hm

    if opens and closes and closes != opens:
        return f"{opens}–{said(closes)}"
    if opens:
        return f"à partir de {opens}" if not closes else opens
    return f"jusqu'à {said(closes)}" if closes else ""


def _run(days: Sequence[int]) -> str:
    """Des jours de la semaine dans l'ordre où on les vit : « du mer. au dim. » (trois et plus qui se suivent),
    « sam., dim. », « jeu., sam., lun. »."""
    follows = all((b - a) % 7 == 1 for a, b in zip(days, days[1:], strict=False))
    if len(days) >= 3 and follows:
        return f"du {DAYS_FR[days[0]]} au {DAYS_FR[days[-1]]}"
    return ", ".join(DAYS_FR[d] for d in days)


def mask_days(mask: int) -> list[int]:
    """Les jours d'un masque (lundi 0 … dimanche 6), dans l'ordre où on les dit : une suite qui passe par le dimanche
    commence après le jour qui manque (« du ven. au lun. »)."""
    days = [d for d in range(7) if mask >> d & 1]
    starts = [d for d in days if (d - 1) % 7 not in days]
    if len(starts) == 1 and len(days) < 7:
        return [(starts[0] + k) % 7 for k in range(len(days))]
    return days


def mask_fr(mask: int) -> str:
    """« le dim. », « du mar. au dim. », « mar., jeu., sam. » ; rien pour chaque jour."""
    if not mask or mask == ALL_DAYS:
        return ""
    days = mask_days(mask)
    return f"le {DAYS_FR[days[0]]}" if len(days) == 1 else _run(days)


def period_fr(o: Occurrence, today: date, *, start: date | None = None) -> str:
    """Une période commencée : ses jours de la semaine, ses heures, puis « jusqu'au … » ; à venir : « du … au … »
    d'abord, puis ses jours et ses heures."""
    begin = max(today, start or today)
    week = [mask_fr(o.days), hours_fr(o.opens, o.closes)]
    if o.first <= begin:
        parts = [*week, f"jusqu'au {date_fr(o.last, today)}"]
    else:
        parts = [f"du {date_fr(o.first, today)} au {date_fr(o.last, today)}", *week]
    return " · ".join(p for p in parts if p)


def when_text(occurrences: Iterable[Occurrence], now: datetime, start: date | None = None,
              end: date | None = None) -> str:
    """Quand, en mots, la prochaine date d'abord (à partir de ``start``) ; rien s'il n'en reste aucune."""
    ahead = upcoming(occurrences, now, start, end)
    if not ahead:
        return ""
    today = now.astimezone(PARIS).date()
    first, head = ahead[0]
    if not head.single:
        return period_fr(head, today, start=start)
    week = [(d, o) for d, o in ahead if o.single and (d - first).days < WEEK]
    times = {(o.opens, o.closes) for _d, o in week}
    dates = [d for d, _o in week]
    if len(week) >= 2 and len(times) == 1 and len(set(dates)) == len(dates):
        run = 1
        while run < len(dates) and (dates[run] - dates[run - 1]).days == 1:
            run += 1
        if run >= 3:  # des jours qui se suivent d'abord : eux seuls (« du mer. au dim. », fermé le lundi)
            dates = dates[:run]
        days = [d.weekday() for d in dates]
        said = "tous les jours" if len(days) == 7 else _run(days)
        return " · ".join(p for p in (said, hours_fr(head.opens, head.closes)) if p)
    return " · ".join(p for p in (day_fr(first, today), hours_fr(head.opens, head.closes)) if p)


def _iso(d: date, hm: str, *, end: bool = False) -> str:
    """Un jour, ou un jour et une heure à l'heure de Paris (« 2026-11-20T19:00+01:00 ») ; une fin à minuit se dit le
    lendemain à 00:00."""
    if not hm:
        return d.isoformat()
    h, m = int(hm[:2]), int(hm[3:])
    if h == 24 or (end and h == 0 and m == 0):
        d, h, m = d + timedelta(days=1), 0, 0
    return datetime.combine(d, time(h, m), PARIS).isoformat(timespec="minutes")


def bounds(day: date, o: Occurrence) -> tuple[str, str]:
    """Le début et la fin d'une séance (ISO 8601) : ce jour-là, à ses heures ; pour une période, sa fin est la
    sienne."""
    start = _iso(day, o.opens)
    last = day if o.single else o.last
    closes = o.closes
    if o.opens and closes and closes <= o.opens and closes not in ("00:00", "24:00"):
        last += timedelta(days=1)  # après minuit : le lendemain
    return start, _iso(last, closes, end=True) if closes else last.isoformat()


def dates_fr(occurrences: Iterable[Occurrence], now: datetime, most: int) -> tuple[list[EventDate], int]:
    """Toutes les dates à venir, la prochaine d'abord, en clair (au plus ``most``) ; et combien en plus."""
    today = now.astimezone(PARIS).date()
    ahead = upcoming(occurrences, now)
    out = []
    for day, o in ahead[:most]:
        start, stop = bounds(day, o)
        if o.single:
            text = " · ".join(p for p in (day_fr(day, today), hours_fr(o.opens, o.closes)) if p)
            out.append(EventDate(start, stop, text))
        else:
            out.append(EventDate(start, stop, period_fr(o, today),
                                 tuple(DAYS_FR[d] for d in mask_days(o.days)) if o.days else ()))
    return out, max(0, len(ahead) - most)

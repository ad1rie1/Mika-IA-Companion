"""Les horaires d'OpenStreetMap (la clé ``opening_hours``, ADR 0244) : un analyseur pur du sous-ensemble courant, qui
dit à un instant donné, à l'heure de Paris, si le lieu est ouvert, fermé, ou si on ne sait pas — en une phrase
(« Ouvert · ferme à 22:30 », « Ouvre à 19:00 », « Fermé · ouvre demain 08:00 ») — et la semaine en français
(« mar.–sam. 12:00–14:00, 19:00–22:30 · lun. fermé »).

**Ce qu'il comprend** : des règles séparées par ``;`` (la dernière qui vaut pour un jour le décide ; une règle
ajoutée après une virgule, ``Mo-Fr 08:00-12:00, Sa 09:00-12:00``, s'y ajoute), chacune faite de dates (``Jun-Sep``,
``Apr-Oct:``, ``Dec 24-Jan 02``, ``Dec 24,31``, ``2024 May 20``), de jours (``Mo-Fr``, ``Sa,Su``, ``Fr-Mo``), des jours
fériés de France (``PH``, ``PH Su`` : un férié qui tombe un dimanche), de plages (``09:00-12:00,14:00-18:30``, après
minuit ``18:00-02:00`` ou ``18:00-26:00``), de ``off``/``closed`` ; et ``24/7``.

**Ce qu'il ne comprend pas** (vacances scolaires ``SH``, semaines, années, ``Su[1]``, lever du soleil, heure de fin
ouverte ``18:00+``, commentaires entre guillemets, règles de repli ``||``…) : ``unknown`` et le texte tel quel —
jamais une supposition. Il ne lève jamais : un texte quelconque donne un horaire ou rien."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
OPEN, CLOSED, UNKNOWN = "open", "closed", "unknown"
#: un texte plus long ne se lit pas (la clé d'OpenStreetMap est bornée à 255 caractères)
RAW_MAX = 255
DAY = 1440
WEEKDAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DAYS_FR = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")
DAY_NAMES_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
#: au plus tant de jours devant : au-delà, « fermé » sans dire quand il rouvre
HORIZON_DAYS = 8

_DAY = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)"
_MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
_TIME = r"(\d{1,2}):(\d{2})"
_SPAN = re.compile(rf"^{_TIME}-{_TIME}$")
_DAYS_ITEM = re.compile(rf"^({_DAY})(?:-({_DAY}))?$")
#: une date ou une période, l'année devant si elle est dite (« Jun-Sep », « Apr01-Oct31 », « Aug01-15 », « Dec25 »,
#: « 2024May20 ») ; un jour seul après une virgule garde le mois d'avant (« Dec24,31 »)
_MONTH_ITEM = re.compile(rf"^(\d{{4}})?({_MON})?(\d{{1,2}})?(?:-(\d{{4}})?({_MON})?(\d{{1,2}})?)?$")
_DATES = re.compile(rf"^(?:\d{{4}})?{_MON}")
#: une virgule entre deux règles (« Mo-Fr 08:00-12:00, Sa 09:00-12:00 ») : après une heure ou « off », avant des jours
_ADDED = re.compile(rf"(?<=\d|f|d),\s*(?=(?:{_DAY}|PH|{_MON})\b)")


class _Unreadable(Exception):
    """Une forme hors du sous-ensemble compris."""


@dataclass(frozen=True, slots=True)
class Rule:
    """Une règle : ses périodes (``(début, fin)`` en année × 10 000 + mois × 100 + jour, l'année 0 pour toutes ; vide :
    toute l'année), ses jours (0 lundi ; vide et sans ``holiday`` : tous), ``holiday`` (``PH`` : les jours fériés ;
    avec ``both``, seulement ceux qui tombent un de ses jours), ses plages en minutes depuis minuit (la fin peut passer
    24:00), ``off``, et ``added`` (après une virgule : s'ajoute à la précédente au lieu de la remplacer)."""

    periods: tuple[tuple[int, int], ...]
    days: frozenset[int]
    holiday: bool
    spans: tuple[tuple[int, int], ...]
    off: bool
    added: bool = False
    both: bool = False

    def matches(self, d: date, *, holiday: bool) -> bool:
        if self.periods and not any(_in_period(d, a, b) for a, b in self.periods):
            return False
        if self.both:
            return holiday and d.weekday() in self.days
        if not self.days and not self.holiday:
            return True
        return d.weekday() in self.days or (self.holiday and holiday)


@dataclass(frozen=True, slots=True)
class Schedule:
    rules: tuple[Rule, ...]

    def spans(self, d: date, *, holiday: bool | None = None) -> tuple[tuple[int, int], ...]:
        """Les plages de ce jour (la dernière règle qui le vise, plus celles qui s'y ajoutent)."""
        is_holiday = holiday_fr(d) if holiday is None else holiday
        found: list[tuple[int, int]] = []
        for rule in self.rules:
            if not rule.matches(d, holiday=is_holiday):
                continue
            if rule.off:
                found = []  # « off » ferme le jour, même ajouté après une virgule (« …, PH off »)
            elif rule.added:
                found += list(rule.spans)
            else:
                found = list(rule.spans)
        return tuple(sorted(found))

    @property
    def mentions_holidays(self) -> bool:
        return any(rule.holiday for rule in self.rules)


def _in_period(d: date, a: int, b: int) -> bool:
    if a >= 10_000:  # une année dite : de date à date, sans retour
        return a <= d.year * 10_000 + d.month * 100 + d.day <= b
    here = d.month * 100 + d.day
    return a <= here <= b if a <= b else here >= a or here <= b


# ── lire ──

def _minutes(h: str, m: str) -> int:
    hours, minutes = int(h), int(m)
    if minutes >= 60 or hours > 48:
        raise _Unreadable
    return hours * 60 + minutes


def _spans(token: str) -> tuple[tuple[int, int], ...]:
    out = []
    for item in token.split(","):
        found = _SPAN.match(item)
        if found is None:
            raise _Unreadable
        start, end = _minutes(*found.group(1, 2)), _minutes(*found.group(3, 4))
        if start >= DAY:
            raise _Unreadable
        if end <= start:
            end += DAY  # après minuit (« 18:00-02:00 ») ; « 00:00-00:00 » : le jour entier
        if end - start > DAY + 12 * 60:
            raise _Unreadable
        out.append((start, end))
    return tuple(out)


def _days(token: str) -> tuple[frozenset[int], bool]:
    days: set[int] = set()
    holiday = False
    for item in token.split(","):
        if item == "PH":
            holiday = True
            continue
        found = _DAYS_ITEM.match(item)
        if found is None:
            raise _Unreadable
        first = WEEKDAYS.index(found.group(1))
        last = WEEKDAYS.index(found.group(2)) if found.group(2) else first
        k = first
        while True:  # « Fr-Mo » passe par le week-end
            days.add(k)
            if k == last:
                break
            k = (k + 1) % 7
    return frozenset(days), holiday


def _day_of_month(text: str | None, *, last: bool) -> int:
    if text is None:
        return 31 if last else 1
    day = int(text)
    if not 1 <= day <= 31:
        raise _Unreadable
    return day


def _periods(token: str) -> tuple[tuple[int, int], ...]:
    out = []
    year = month = 0
    for item in token.split(","):
        found = _MONTH_ITEM.match(item)
        if found is None:
            raise _Unreadable
        y1, m1, d1, y2, m2, d2 = found.groups()
        if m1 is not None:
            month, year = MONTHS.index(m1) + 1, int(y1) if y1 else 0
        elif y1 or d1 is None or not month:
            raise _Unreadable  # un jour seul sans mois avant lui, une année sans mois
        dash = "-" in item
        start = year * 10_000 + month * 100 + _day_of_month(d1, last=False)
        if not dash:
            end = year * 10_000 + month * 100 + _day_of_month(d1, last=True)
        else:
            if (m2 is None and d2 is None) or (m2 is None and d1 is None) or (y2 and not year):
                raise _Unreadable  # « Jun- », « Jun-15 » : la fin, ou le jour de départ, manque
            last_month = MONTHS.index(m2) + 1 if m2 else month
            end = (int(y2) if y2 else year) * 10_000 + last_month * 100 + _day_of_month(d2, last=True)
        out.append((start, end))
    return tuple(out)


def _rule(text: str, added: bool) -> Rule:
    if text == "24/7":
        return Rule((), frozenset(), False, ((0, DAY),), False, added)
    # une année suivie de son mois, un mois suivi de son jour se lisent d'un seul mot (« 2024 May 20 » → « 2024May20 »,
    # « Apr 01-Oct 31 » → « Apr01-Oct31 »)
    text = re.sub(rf"(\d{{4}}) ({_MON})", r"\1\2", text)
    text = re.sub(rf"({_MON}) (\d{{1,2}})(?![\d:])", r"\1\2", text)
    tokens = text.split(" ")
    periods: tuple[tuple[int, int], ...] = ()
    days: frozenset[int] = frozenset()
    holiday = both = False
    spans: tuple[tuple[int, int], ...] = ()
    off = False
    i = 0
    if i < len(tokens) and _DATES.match(tokens[i]):
        periods = _periods(tokens[i])
        i += 1
    if i < len(tokens) and re.match(rf"^(?:{_DAY}|PH)", tokens[i]):
        days, holiday = _days(tokens[i])
        i += 1
        if holiday and not days and i < len(tokens) and re.match(rf"^{_DAY}", tokens[i]):
            days, again = _days(tokens[i])  # « PH Su » : un férié qui tombe un dimanche
            if again:
                raise _Unreadable
            both = True
            i += 1
    if i < len(tokens) and tokens[i][:1].isdigit():
        spans = _spans(tokens[i])
        i += 1
    if i < len(tokens) and tokens[i] in ("off", "closed"):
        off = True
        i += 1
    elif i < len(tokens) and tokens[i] == "open":
        i += 1
    if i != len(tokens) or (not spans and not off and not periods and not days and not holiday):
        raise _Unreadable
    if not spans and not off:
        spans = ((0, DAY),)  # « Mo-Fr » seul, « Dec 24 open » : le jour entier
    return Rule(periods, days, holiday, spans, off, added, both)


@lru_cache(maxsize=4096)
def parse(raw: str) -> Schedule | None:
    """L'horaire de ce texte, ou ``None`` s'il sort du sous-ensemble compris (jamais d'exception)."""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > RAW_MAX or '"' in raw or "||" in raw:
        return None
    text = " ".join(raw.split())
    text = re.sub(rf"({_MON}(?: ?\d{{1,2}})?) ?: ", r"\1 ", text)  # « Apr-Oct: 07:30-21:00 »
    text = re.sub(r"\s*([-,:])\s*", r"\1", text)  # « 12:00 - 14:00 », « Mo, We »
    try:
        rules: list[Rule] = []
        for part in text.split(";"):
            part = part.strip()
            if not part:
                continue
            for k, piece in enumerate(_ADDED.split(part)):
                rules.append(_rule(piece.strip(), added=k > 0))
    except (_Unreadable, ValueError):
        return None
    return Schedule(tuple(rules)) if rules else None


# ── les jours fériés de France ──

def _easter(year: int) -> date:
    """Pâques (l'algorithme de Meeus, calendrier grégorien)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = (h + ell - 7 * m + 114) % 31 + 1
    return date(year, month, day)


@lru_cache(maxsize=64)
def _holidays(year: int) -> frozenset[date]:
    easter = _easter(year)
    fixed = [(1, 1), (5, 1), (5, 8), (7, 14), (8, 15), (11, 1), (11, 11), (12, 25)]
    return frozenset([date(year, m, d) for m, d in fixed] +
                     [easter + timedelta(days=n) for n in (1, 39, 50)])  # lundi de Pâques, Ascension, Pentecôte


def holiday_fr(d: date) -> bool:
    """Un jour férié en France (métropole : ni le Vendredi saint ni la Saint-Étienne d'Alsace-Moselle)."""
    return d in _holidays(d.year)


# ── dire ──

def _hhmm(minutes: int) -> str:
    minutes %= DAY
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _local(at: datetime) -> datetime:
    return (at if at.tzinfo is not None else at.replace(tzinfo=UTC)).astimezone(PARIS)


def _timeline(schedule: Schedule, today: date) -> list[tuple[int, int]]:
    """Les plages d'hier à l'horizon, en minutes depuis minuit aujourd'hui, fusionnées."""
    raw = []
    for k in range(-1, HORIZON_DAYS):
        d = today + timedelta(days=k)
        raw += [(a + k * DAY, b + k * DAY) for a, b in schedule.spans(d)]
    raw.sort()
    merged: list[tuple[int, int]] = []
    for a, b in raw:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _when(minutes: int, today: date, *, closing: bool) -> str:
    """« à 22:30 », « demain 08:00 », « lundi 12:00 » : un moment de l'horizon, vu d'aujourd'hui. Une fermeture juste
    après minuit se dit « à 02:00 » (la soirée d'aujourd'hui)."""
    k = minutes // DAY
    if closing and minutes % DAY == 0 and k <= 1:
        return "à minuit"
    if k == 0 or (closing and k == 1 and minutes % DAY <= 6 * 60):
        return f"à {_hhmm(minutes)}"
    if k == 1:
        return f"demain {_hhmm(minutes)}"
    return f"{DAY_NAMES_FR[(today + timedelta(days=k)).weekday()]} {_hhmm(minutes)}"


def state_at(raw: str, at: datetime) -> tuple[str, str]:
    """``(état, phrase)`` à cet instant (heure de Paris) : ``open`` (« Ouvert · ferme à 22:30 »), ``closed`` (« Ouvre à
    19:00 », « Fermé · ouvre demain 08:00 », « Fermé ») ou ``unknown`` (sans phrase)."""
    schedule = parse(raw) if raw else None
    if schedule is None:
        return UNKNOWN, ""
    local = _local(at)
    today = local.date()
    now = local.hour * 60 + local.minute
    timeline = _timeline(schedule, today)
    for a, b in timeline:
        if a <= now < b:
            if b >= HORIZON_DAYS * DAY:
                return OPEN, "Ouvert 24 h/24"
            return OPEN, f"Ouvert · ferme {_when(b, today, closing=True)}"
    upcoming = [a for a, _b in timeline if a > now]
    if not upcoming:
        return CLOSED, "Fermé"
    first = upcoming[0]
    if first // DAY == 0:
        return CLOSED, f"Ouvre à {_hhmm(first)}"
    return CLOSED, f"Fermé · ouvre {_when(first, today, closing=False)}"


def _spans_fr(spans: tuple[tuple[int, int], ...]) -> str:
    if spans == ((0, DAY),):
        return "24 h/24"
    return ", ".join(f"{_hhmm(a)}–{'24:00' if b == DAY else _hhmm(b)}" for a, b in spans)


def _days_fr(days: list[int]) -> str:
    """« lun., mer.–ven. » : les jours, les suites de trois et plus en une plage (et de deux : « sam.–dim. »)."""
    runs: list[list[int]] = []
    for d in days:
        if runs and d == runs[-1][-1] + 1:
            runs[-1].append(d)
        else:
            runs.append([d])
    return ", ".join(DAYS_FR[r[0]] if len(r) == 1 else f"{DAYS_FR[r[0]]}–{DAYS_FR[r[-1]]}" for r in runs)


def week_fr(raw: str, at: datetime) -> str:
    """La semaine de cet instant en français (« mar.–sam. 12:00–14:00, 19:00–22:30 · lun. fermé ») ; un horaire qu'on
    ne comprend pas : son texte tel quel. Les fériés se disent à part (« jours fériés fermé »)."""
    schedule = parse(raw) if raw else None
    if schedule is None:
        return " ".join(str(raw or "").split())[:RAW_MAX]
    monday = _local(at).date()
    monday -= timedelta(days=monday.weekday())
    week = [schedule.spans(monday + timedelta(days=k), holiday=False) for k in range(7)]
    groups: dict[tuple[tuple[int, int], ...], list[int]] = {}
    for k, spans in enumerate(week):
        groups.setdefault(spans, []).append(k)
    opened = [(spans, days) for spans, days in groups.items() if spans]
    closed = groups.get((), [])
    if not opened:
        parts = ["fermé cette semaine"]
    elif len(opened) == 1 and not closed:
        parts = [f"tous les jours {_spans_fr(opened[0][0])}"]
    else:
        parts = [f"{_days_fr(days)} {_spans_fr(spans)}" for spans, days in opened]
        if closed:
            parts.append(f"{_days_fr(closed)} fermé")
    if any(rule.both for rule in schedule.rules):
        # « PH Mo-Sa …; PH Su … » : chaque règle des fériés, dans l'ordre
        for rule in schedule.rules:
            if rule.holiday and not rule.periods:
                what = "fermé" if rule.off else _spans_fr(rule.spans)
                parts.append(f"jours fériés {_days_fr(sorted(rule.days))} {what}" if rule.both else
                             f"jours fériés {what}")
    elif schedule.mentions_holidays:
        spans: list[tuple[int, int]] | None = None
        for rule in schedule.rules:
            if rule.holiday and not rule.periods:
                if rule.off:
                    spans = []
                elif rule.added:
                    spans = (spans or []) + list(rule.spans)
                else:
                    spans = list(rule.spans)
        if spans is not None:
            parts.append(f"jours fériés {_spans_fr(tuple(sorted(spans)))}" if spans else "jours fériés fermé")
    return " · ".join(parts)

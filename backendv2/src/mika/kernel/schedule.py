"""Règles d'agenda d'un projet, en fonctions pures.

- ``""`` / ``manual`` : pas d'agenda — elle y avance quand elle en a le temps ;
- ``interval:30m`` (s, m, h, d ; au moins cinq minutes) : un pas par intervalle ;
- ``cron:0 9 * * MON-FRI`` : minute, heure, jour, mois, jour de semaine, en
  heure locale ; listes, plages, pas, noms de jours et de mois ; dimanche = 0
  ou 7 ; jour du mois et jour de semaine en OU quand les deux sont
  restreints (comme cron).

Une règle illisible est refusée à l'écriture (``parse`` lève) ; relue, elle
vaut « pas d'agenda » — jamais une échéance fausse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mika.kernel.clock import MINUTE, US, instant, local

_INTERVAL = re.compile(r"^interval:(\d+)\s*([smhd])$", re.IGNORECASE)
_UNIT = {"s": US, "m": MINUTE, "h": 60 * MINUTE, "d": 24 * 60 * MINUTE}
MIN_INTERVAL = 5 * MINUTE
_DOW = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}
_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10,
           "NOV": 11, "DEC": 12}


@dataclass(frozen=True, slots=True)
class Rule:
    kind: str  # "manual" | "interval" | "cron"
    every_us: int = 0
    minutes: frozenset[int] = frozenset()
    hours: frozenset[int] = frozenset()
    days: frozenset[int] = frozenset()
    months: frozenset[int] = frozenset()
    weekdays: frozenset[int] = frozenset()  # numérotation Python (lundi = 0)
    dom_restricted: bool = False
    dow_restricted: bool = False


MANUAL = Rule("manual")


def _field(text: str, lo: int, hi: int, names: dict[str, int] | None = None) -> frozenset[int]:
    names = names or {}

    def value(s: str) -> int:
        s = s.strip().upper()
        n = names[s] if s in names else int(s)
        if not lo <= n <= hi:
            raise ValueError(f"{n} hors de [{lo}, {hi}]")
        return n

    out: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise ValueError("segment vide")
        step = 1
        span = part
        if "/" in part:
            span, raw = part.split("/", 1)
            step = int(raw)
            if step < 1:
                raise ValueError(f"pas invalide : {raw}")
        if span == "*":
            a, b = lo, hi
        elif "-" in span:
            x, y = span.split("-", 1)
            a, b = value(x), value(y)
            if b < a:
                raise ValueError(f"plage inversée : {span}")
        else:
            a = value(span)
            b = hi if "/" in part else a
        out.update(range(a, b + 1, step))
    return frozenset(out)


def parse(rule: str) -> Rule:
    """Lève ``ValueError`` sur une règle illisible."""
    s = (rule or "").strip()
    if not s or s.lower() == "manual":
        return MANUAL
    m = _INTERVAL.match(s)
    if m:
        return Rule("interval", every_us=max(MIN_INTERVAL, int(m.group(1)) * _UNIT[m.group(2).lower()]))
    if s.lower().startswith("cron:"):
        fields = s[5:].split()
        if len(fields) != 5:
            raise ValueError("une règle cron a cinq champs : minute heure jour mois jour-de-semaine")
        mi, ho, dom, mo, dow = fields
        weekdays = frozenset((n + 6) % 7 for n in _field(dow, 0, 7, _DOW))
        return Rule("cron", minutes=_field(mi, 0, 59), hours=_field(ho, 0, 23), days=_field(dom, 1, 31),
                    months=_field(mo, 1, 12, _MONTHS), weekdays=weekdays,
                    dom_restricted=not dom.startswith("*"), dow_restricted=not dow.startswith("*"))
    raise ValueError(f"règle d'agenda inconnue : {rule!r} (manual, interval:30m, cron:0 9 * * MON-FRI)")


def read(rule: str) -> Rule:
    """Relire une règle déjà acceptée ; illisible → pas d'agenda."""
    try:
        return parse(rule)
    except ValueError:
        return MANUAL


def _day_ok(r: Rule, d: datetime) -> bool:
    ok_dom, ok_dow = d.day in r.days, d.weekday() in r.weekdays
    if r.dom_restricted and r.dow_restricted:
        return ok_dom or ok_dow
    return ok_dom and ok_dow


def _next_cron(r: Rule, after: datetime) -> datetime | None:
    cursor = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = after + timedelta(days=366)
    while cursor <= end:
        if cursor.month not in r.months or not _day_ok(r, cursor):
            cursor = (cursor + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if cursor.hour not in r.hours:
            cursor = (cursor + timedelta(hours=1)).replace(minute=0)
            continue
        if cursor.minute in r.minutes:
            return cursor
        cursor += timedelta(minutes=1)
    return None


def next_after(rule: Rule, t: int, tz: ZoneInfo) -> int | None:
    """La prochaine échéance strictement après ``t`` ; ``None`` sans agenda."""
    if rule.kind == "interval":
        return t + rule.every_us
    if rule.kind == "cron":
        # l'heure locale naïve, puis ré-attachée au fuseau : les changements
        # d'heure donnent l'heure murale attendue
        nxt = _next_cron(rule, local(t, tz).replace(tzinfo=None))
        return instant(nxt.replace(tzinfo=tz)) if nxt is not None else None
    return None

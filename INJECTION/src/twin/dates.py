"""Lire une date là où un humain l'a écrite : un nom de fichier, un dossier, un en-tête.

Tout ce qui est lu ici est en heure **locale** (le fuseau de la personne) et rendu en
``Temps`` avec sa précision : « 2009 » est une année, « mars 2009 » un mois,
« été 2009 » une saison, « 12/03/2009 » un jour. L'ordre jour/mois est français par
défaut (12/03 = 12 mars) ; une source anglaise se lit avec ``month_first=True``.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from twin.timing import Origin, Temps, from_us

MONTHS = {
    # français
    "janvier": 1, "janv": 1, "fevrier": 2, "fevr": 2, "fev": 2, "mars": 3, "avril": 4, "avr": 4, "mai": 5,
    "juin": 6, "juillet": 7, "juil": 7, "aout": 8, "septembre": 9, "sept": 9, "octobre": 10, "oct": 10,
    "novembre": 11, "nov": 11, "decembre": 12, "dec": 12,
    # anglais
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
    "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9,
    "october": 10, "november": 11, "december": 12,
}
SEASON_WORDS = {"hiver": "hiver", "printemps": "printemps", "ete": "ete", "automne": "automne",
                "winter": "hiver", "spring": "printemps", "summer": "ete", "autumn": "automne", "fall": "automne"}
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche", "monday", "tuesday",
            "wednesday", "thursday", "friday", "saturday", "sunday")

#: années plausibles pour une archive personnelle
YEAR_MIN, YEAR_MAX = 1980, 2035


def fold(text: str) -> str:
    """minuscules, sans accents (« Février » → « fevrier »)."""
    norm = unicodedata.normalize("NFKD", text)
    return "".join(c for c in norm if not unicodedata.combining(c)).lower()


def _year(y: int) -> int | None:
    if y < 100:  # 09 → 2009, 98 → 1998
        y += 2000 if y < 50 else 1900
    return y if YEAR_MIN <= y <= YEAR_MAX else None


def _day(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


_MONTH_WORDS = "|".join(sorted(MONTHS, key=len, reverse=True))
_SEP = r"[-_./ ]"
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # 2009-03-12, 2009_03_12, 2009.03.12, 2009 03 12
    ("ymd", re.compile(rf"(?<!\d)((?:19|20)\d\d){_SEP}(0?[1-9]|1[0-2]){_SEP}(0?[1-9]|[12]\d|3[01])(?!\d)")),
    # 20090312 (huit chiffres collés)
    ("ymd8", re.compile(r"(?<!\d)((?:19|20)\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")),
    # 12/03/2009, 12-03-09
    ("dmy", re.compile(rf"(?<!\d)(0?[1-9]|[12]\d|3[01]){_SEP}(0?[1-9]|1[0-2]){_SEP}((?:19|20)?\d\d)(?!\d)")),
    # 12 mars 2009, 1er mars 2009, mardi 12 mars 2009
    ("d_month_y", re.compile(rf"(?<!\d)(0?[1-9]|[12]\d|3[01])(?:er)?\s+({_MONTH_WORDS})\.?\s+((?:19|20)\d\d)(?!\d)")),
    # March 12, 2009
    ("month_d_y", re.compile(rf"({_MONTH_WORDS})\.?\s+(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?,?\s+((?:19|20)\d\d)(?!\d)")),
    # mars 2009
    ("month_y", re.compile(rf"(?<![a-z])({_MONTH_WORDS})\.?\s+((?:19|20)\d\d)(?!\d)")),
    # 2009-03 (un dossier par mois)
    ("ym", re.compile(rf"(?<!\d)((?:19|20)\d\d){_SEP}(0[1-9]|1[0-2])(?![\d])")),
    # été 2009
    ("season_y", re.compile(r"(hiver|printemps|ete|automne|winter|spring|summer|autumn|fall)\s+((?:19|20)\d\d)(?!\d)")),
    # 2009 seul
    ("y", re.compile(r"(?<!\d)((?:19|20)\d\d)(?!\d)")),
    # 12 mars (sans année : complétée par un parent)
    ("d_month", re.compile(rf"(?<!\d)(0?[1-9]|[12]\d|3[01])(?:er)?\s+({_MONTH_WORDS})(?![a-z])")),
]


def find_date(text: str, tz: ZoneInfo, origin: Origin, *, year_hint: int | None = None,
              month_first: bool = False) -> Temps | None:
    """La date la plus précise écrite dans ``text`` (une seule ; la première trouvée à précision égale)."""
    s = fold(text)
    for kind, pat in _PATTERNS:
        for m in pat.finditer(s):
            t = _build(kind, m.groups(), tz, origin, year_hint, month_first)
            if t is not None:
                return t
    return None


def _build(kind: str, g: tuple[str, ...], tz: ZoneInfo, origin: Origin, year_hint: int | None,
           month_first: bool) -> Temps | None:
    if kind in ("ymd", "ymd8"):
        y = _year(int(g[0]))
        d = y and _day(y, int(g[1]), int(g[2]))
        return Temps.day(d, tz, origin) if d else None
    if kind == "dmy":
        a, b, y = int(g[0]), int(g[1]), _year(int(g[2]))
        if y is None:
            return None
        day, month = (b, a) if month_first else (a, b)
        d = _day(y, month, day)
        return Temps.day(d, tz, origin) if d else None
    if kind == "d_month_y":
        y = _year(int(g[2]))
        d = y and _day(y, MONTHS[g[1]], int(g[0]))
        return Temps.day(d, tz, origin) if d else None
    if kind == "month_d_y":
        y = _year(int(g[2]))
        d = y and _day(y, MONTHS[g[0]], int(g[1]))
        return Temps.day(d, tz, origin) if d else None
    if kind == "month_y":
        y = _year(int(g[1]))
        return Temps.month(y, MONTHS[g[0]], tz, origin) if y else None
    if kind == "ym":
        y = _year(int(g[0]))
        return Temps.month(y, int(g[1]), tz, origin) if y else None
    if kind == "season_y":
        y = _year(int(g[1]))
        return Temps.season(y, SEASON_WORDS[g[0]], tz, origin) if y else None
    if kind == "y":
        y = _year(int(g[0]))
        return Temps.year(y, tz, origin) if y else None
    if kind == "d_month" and year_hint is not None:
        d = _day(year_hint, MONTHS[g[1]], int(g[0]))
        return Temps.day(d, tz, origin) if d else None
    return None


def date_from_path(path: Path, root: Path | None, tz: ZoneInfo) -> Temps | None:
    """La date d'un fichier d'après son nom puis ses dossiers (sous ``root``).

    Le nom du fichier gagne ; « 12 mars » sans année se complète par l'année d'un dossier
    parent (``2009/12 mars.txt``) ; un dossier seul donne au mieux son mois ou son année.
    """
    parts = list(path.relative_to(root).parts if root and path.is_relative_to(root) else path.parts[-3:])
    if not parts:
        return None
    parents = [Path(p).name for p in parts[:-1]]
    year_hint = None
    for p in reversed(parents):
        t = find_date(p, tz, Origin.PATH)
        if t is not None and t.point is not None:
            year_hint = _local_year(t.point, tz)
            break
    name = Path(parts[-1]).stem
    t = find_date(name, tz, Origin.PATH, year_hint=year_hint)
    if t is not None:
        return t
    for p in reversed(parents):
        t = find_date(p, tz, Origin.PATH)
        if t is not None:
            return t
    return None


def date_from_header(text: str, tz: ZoneInfo, *, year_hint: int | None = None, lines: int = 3) -> Temps | None:
    """Une date écrite en tête d'un document (« Le 12 mars 2009 », « # 2009-03-12 »)."""
    head = [ln for ln in text.splitlines() if ln.strip()][:lines]
    for ln in head:
        if len(ln) > 80:  # une phrase, pas un en-tête
            continue
        t = find_date(ln, tz, Origin.HEADER, year_hint=year_hint)
        if t is not None:
            return t
    return None


_DATE_LINE = re.compile(
    rf"^\s*(?:#+\s*)?(?:le\s+)?(?:(?:{'|'.join(WEEKDAYS)})\s*,?\s*)?"
    rf"(?:\d{{1,2}}(?:er)?\s+(?:{_MONTH_WORDS})\.?(?:\s+\d{{4}})?|\d{{4}}[-/.]\d{{1,2}}[-/.]\d{{1,2}}"
    rf"|\d{{1,2}}[-/.]\d{{1,2}}[-/.]\d{{2,4}})\s*[:,.\-–—]?\s*$"
)


def is_date_line(line: str) -> bool:
    """Une ligne qui n'est qu'une date : le début d'une entrée de journal."""
    s = fold(line)
    return len(s) <= 60 and bool(_DATE_LINE.match(s))


def _local_year(us: int, tz: ZoneInfo) -> int:
    return from_us(us, tz).year

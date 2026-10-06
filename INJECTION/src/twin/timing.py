"""Le temps d'un élément d'archive : une plage, un point, une précision, une origine.

Toutes les archives ne sont pas datées. Un message WhatsApp l'est à la seconde ; une
note n'a parfois que le nom de son dossier (« 2009 ») ; une page de journal intime
peut ne rien dire du tout. On ne force donc jamais une date : chaque élément porte
une **plage** ``[debut, fin]`` (bornes en microsecondes UTC, l'une ou l'autre
inconnue), un **point** estimé à l'intérieur (celui où l'avance rapide le placera),
une **précision** et l'**origine** de l'estimation.

L'**ordre** connu d'une source (les messages d'un fil, les pages d'un cahier) est une
contrainte : ``propagate`` resserre les plages par l'ordre, interpole les éléments
sans date entre deux voisins datés et signale — sans jamais trancher en silence — un
élément daté qui contredit l'ordre (une horloge de téléphone fausse, un fuseau mal lu).
"""

from __future__ import annotations

import bisect
import calendar
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

US = 1_000_000
MINUTE = 60 * US
HOUR = 60 * MINUTE
DAY = 24 * HOUR

#: l'heure « neutre » d'un élément daté au jour près : en pleine journée, ni la nuit
#: (elle dormirait) ni un moment où elle parle déjà
NEUTRAL_HOUR = time(14, 0)


class Precision(StrEnum):
    EXACT = "exacte"
    DAY = "jour"
    MONTH = "mois"
    SEASON = "saison"
    YEAR = "annee"
    RANGE = "plage"
    UNKNOWN = "inconnue"


#: de la plus fine à la plus grossière
RANK = {p: i for i, p in enumerate(Precision)}


class Origin(StrEnum):
    SOURCE = "source"  # horodatage écrit par l'application
    HEADER = "entete"  # date écrite dans le document (« Le 12 mars »)
    PATH = "chemin"  # nom de fichier ou de dossier
    FILE = "fichier"  # métadonnées du fichier (mtime) — dernier recours
    ERA = "ere"  # l'époque du format (MSN : 1999–2014)
    INTERPOLATED = "interpolation"  # entre deux voisins datés d'une même source
    CONTENT = "contenu"  # indices lus par Claude Code
    CROSS = "recoupement"  # ancré sur un élément daté du corpus
    MANUAL = "manuel"  # corrigé à la main (dates.yaml)
    NONE = "aucune"


def precision_for_width(width_us: int) -> Precision:
    """La précision que mérite une plage de cette largeur."""
    if width_us <= 2 * MINUTE:
        return Precision.EXACT
    if width_us <= DAY + HOUR:  # une journée locale, changement d'heure compris
        return Precision.DAY
    if width_us <= 31 * DAY + HOUR:
        return Precision.MONTH
    if width_us <= 92 * DAY + HOUR:
        return Precision.SEASON
    if width_us <= 366 * DAY + HOUR:
        return Precision.YEAR
    return Precision.RANGE


def to_us(dt: datetime) -> int:
    if dt.tzinfo is None:
        raise ValueError("une date sans fuseau n'a pas d'instant : passer par un fuseau")
    delta = dt.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * US + delta.microseconds


def from_us(us: int, tz: ZoneInfo | None = None) -> datetime:
    dt = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=us)
    return dt.astimezone(tz) if tz else dt


def _local(d: date, t: time, tz: ZoneInfo) -> int:
    return to_us(datetime.combine(d, t, tzinfo=tz))


def _day_bounds(first: date, last: date, tz: ZoneInfo) -> tuple[int, int]:
    """Du début du premier jour local à la fin du dernier."""
    return _local(first, time(0), tz), _local(last + timedelta(days=1), time(0), tz) - 1


SEASONS = {
    # mois de début (année relative), mois de fin
    "hiver": ((-1, 12), (0, 2)),
    "printemps": ((0, 3), (0, 5)),
    "ete": ((0, 6), (0, 8)),
    "automne": ((0, 9), (0, 11)),
}


@dataclass(frozen=True, slots=True)
class Temps:
    """Quand c'est arrivé, autant qu'on le sache."""

    start: int | None = None
    end: int | None = None
    point: int | None = None
    precision: Precision = Precision.UNKNOWN
    origin: Origin = Origin.NONE

    def __post_init__(self) -> None:
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError(f"plage à l'envers : {self.start} > {self.end}")
        if self.point is not None:
            if self.start is not None and self.point < self.start:
                raise ValueError("le point est avant le début de sa plage")
            if self.end is not None and self.point > self.end:
                raise ValueError("le point est après la fin de sa plage")

    # -- construction -----------------------------------------------------------------

    @classmethod
    def exact(cls, at: int | datetime, origin: Origin = Origin.SOURCE) -> Temps:
        us = to_us(at) if isinstance(at, datetime) else at
        return cls(us, us, us, Precision.EXACT, origin)

    @classmethod
    def day(cls, d: date, tz: ZoneInfo, origin: Origin) -> Temps:
        start, end = _day_bounds(d, d, tz)
        return cls(start, end, _local(d, NEUTRAL_HOUR, tz), Precision.DAY, origin)

    @classmethod
    def month(cls, year: int, month: int, tz: ZoneInfo, origin: Origin) -> Temps:
        last = calendar.monthrange(year, month)[1]
        start, end = _day_bounds(date(year, month, 1), date(year, month, last), tz)
        return cls(start, end, _local(date(year, month, min(15, last)), NEUTRAL_HOUR, tz), Precision.MONTH, origin)

    @classmethod
    def season(cls, year: int, name: str, tz: ZoneInfo, origin: Origin) -> Temps:
        (dy0, m0), (dy1, m1) = SEASONS[name]
        first = date(year + dy0, m0, 1)
        last_year = year + dy1
        last = date(last_year, m1, calendar.monthrange(last_year, m1)[1])
        start, end = _day_bounds(first, last, tz)
        middle = first + (last - first) / 2
        return cls(start, end, _local(middle, NEUTRAL_HOUR, tz), Precision.SEASON, origin)

    @classmethod
    def year(cls, year: int, tz: ZoneInfo, origin: Origin) -> Temps:
        start, end = _day_bounds(date(year, 1, 1), date(year, 12, 31), tz)
        return cls(start, end, _local(date(year, 7, 1), NEUTRAL_HOUR, tz), Precision.YEAR, origin)

    @classmethod
    def span(cls, start: int | None, end: int | None, origin: Origin, point: int | None = None) -> Temps:
        """Une plage ; son point est le milieu quand on ne dit rien (et inconnu si elle est ouverte)."""
        if start is not None and end is not None:
            if point is None:
                point = start + (end - start) // 2
            return cls(start, end, point, precision_for_width(end - start), origin)
        return cls(start, end, point, Precision.UNKNOWN if point is None else Precision.RANGE, origin)

    @classmethod
    def unknown(cls) -> Temps:
        return cls()

    # -- lecture ----------------------------------------------------------------------

    @property
    def known(self) -> bool:
        return self.point is not None

    @property
    def width(self) -> int | None:
        if self.start is None or self.end is None:
            return None
        return self.end - self.start

    def finer_than(self, other: Temps) -> bool:
        return RANK[self.precision] < RANK[other.precision]

    def intersect(self, other: Temps) -> Temps | None:
        """Ce que deux estimations ont en commun ; ``None`` si elles se contredisent."""
        start = _max(self.start, other.start)
        end = _min(self.end, other.end)
        if start is not None and end is not None and start > end:
            return None
        best = self if self.finer_than(other) or self.precision == other.precision else other
        point = best.point
        if point is not None:
            point = _clamp(point, start, end)
        if self.precision == Precision.EXACT or other.precision == Precision.EXACT:
            exact = self if self.precision == Precision.EXACT else other
            return exact
        width = None if start is None or end is None else end - start
        precision = best.precision if width is None else _coarsest_allowed(best.precision, width)
        return Temps(start, end, point, precision, best.origin)

    def as_row(self) -> tuple[int | None, int | None, int | None, str, str]:
        return self.start, self.end, self.point, self.precision.value, self.origin.value

    @classmethod
    def from_row(cls, start: int | None, end: int | None, point: int | None, precision: str,
                 origin: str) -> Temps:
        return cls(start, end, point, Precision(precision), Origin(origin))


def _coarsest_allowed(precision: Precision, width: int) -> Precision:
    """Une plage resserrée peut devenir plus précise, jamais moins."""
    by_width = precision_for_width(width)
    return by_width if RANK[by_width] < RANK[precision] else precision


def _max(a: int | None, b: int | None) -> int | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def _min(a: int | None, b: int | None) -> int | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def _inside(v: int, lo: int | None, hi: int | None) -> int:
    """``v`` s'il est dans la plage ; sinon le milieu de la plage (bornée des deux côtés), à défaut sa borne."""
    if (lo is None or v >= lo) and (hi is None or v <= hi):
        return v
    if lo is not None and hi is not None:
        return lo + (hi - lo) // 2
    return _clamp(v, lo, hi)


def _order_points(out: list[Temps], flagged: set[int]) -> None:
    """Les points qui reculent dans l'ordre de la source (deux estimations indépendantes, chacune dans sa plage)
    sont replacés au rang entre les voisins qui tiennent ensemble. Une date exacte ne bouge jamais : après le
    resserrement, elle est compatible avec tous les points et fait toujours partie de la suite gardée."""
    idx = [i for i, t in enumerate(out) if t.point is not None and i not in flagged]
    if len(idx) < 2:
        return
    kept = sorted(_longest_non_decreasing(idx, [out[i].point for i in idx]))  # type: ignore[misc]
    for i in idx:
        k = bisect.bisect_left(kept, i)
        if k < len(kept) and kept[k] == i:
            continue
        t = out[i]
        before = kept[k - 1] if k > 0 else None
        after = kept[k] if k < len(kept) else None
        pa = out[before].point if before is not None else None
        pb = out[after].point if after is not None else None
        if pa is not None and pb is not None:
            point = pa + (pb - pa) * (i - before) // (after - before)  # type: ignore[operator]
        else:
            point = _inside(pa if pa is not None else pb, t.start, t.end)  # type: ignore[arg-type]
        out[i] = replace(t, point=_clamp(point, _max(t.start, pa), _min(t.end, pb)))
        kept.insert(k, i)


def _clamp(v: int, lo: int | None, hi: int | None) -> int:
    if lo is not None and v < lo:
        v = lo
    if hi is not None and v > hi:
        v = hi
    return v


@dataclass(frozen=True, slots=True)
class Conflict:
    """Un élément daté qui contredit l'ordre de sa source : signalé, jamais corrigé en silence."""

    index: int
    reason: str


def propagate(items: list[Temps]) -> tuple[list[Temps], list[Conflict]]:
    """Resserre une suite **ordonnée** (l'ordre de la source) et interpole ce qui n'est pas daté.

    - Un élément ne peut pas être plus tôt que le début du précédent, ni plus tard que
      la fin du suivant : les plages se resserrent dans les deux sens.
    - Un élément sans point, entre deux voisins qui en ont un, reçoit un point interpolé
      au rang (origine ``interpolation``).
    - Une date exacte n'est jamais déplacée : si elle contredit l'ordre, c'est un conflit,
      et ses voisins ne sont pas contraints par elle.
    - Un point estimé que sa plage resserrée exclut repart au **milieu** de la nouvelle plage,
      pas collé à sa borne (« au plus tard le 3 mars » ne veut pas dire « le 3 mars ») ; et
      les points estimés **suivent l'ordre** : celui qui recule est replacé entre ses voisins.
    """
    n = len(items)
    out = list(items)
    # 0. les dates exactes qui tiennent ensemble : la plus longue suite non décroissante.
    #    Une seule date aberrante (23 h au milieu d'une matinée) est signalée, pas ses voisines.
    exact = [i for i, t in enumerate(items) if t.precision == Precision.EXACT and t.point is not None]
    kept = set(_longest_non_decreasing(exact, [items[i].point for i in exact]))  # type: ignore[misc]
    conflicts = [Conflict(i, "date exacte qui contredit l'ordre de sa source") for i in exact if i not in kept]
    flagged = {c.index for c in conflicts}
    #    puis les plages : on écarte, une à une, la moins sûre de celles qui cassent l'ordre
    for i in sorted(_inconsistent_ranges(items, flagged)):
        conflicts.append(Conflict(i, "plage incompatible avec l'ordre de sa source"))
        flagged.add(i)

    # 1. bornes par l'ordre : au plus tôt le début du précédent, au plus tard la fin du suivant
    lows: list[int | None] = [t.start for t in items]
    highs: list[int | None] = [t.end for t in items]
    floor: int | None = None
    for i, t in enumerate(items):
        if i in flagged:
            continue  # une date fausse ne contraint personne
        lows[i] = _max(lows[i], floor)
        floor = _max(floor, t.start)
    ceiling: int | None = None
    for i in range(n - 1, -1, -1):
        if i in flagged:
            continue
        highs[i] = _min(highs[i], ceiling)
        ceiling = _min(ceiling, items[i].end)

    for i, t in enumerate(items):
        if i in flagged or t.precision == Precision.EXACT:
            continue
        lo, hi = lows[i], highs[i]
        if lo is not None and hi is not None and lo > hi:
            conflicts.append(Conflict(i, "aucune date ne respecte l'ordre de sa source"))
            flagged.add(i)
            continue
        if lo == t.start and hi == t.end:
            continue
        point = None if t.point is None else _inside(t.point, lo, hi)
        origin = t.origin if t.known else Origin.INTERPOLATED
        if lo is not None and hi is not None:
            precision = _coarsest_allowed(t.precision if t.known else Precision.RANGE, hi - lo)
        else:
            precision = t.precision
        out[i] = Temps(lo, hi, point, precision, origin)

    # 1 bis. les points estimés suivent l'ordre de la source
    _order_points(out, flagged)

    # 2. un point interpolé au rang pour ce qui n'en a pas, entre deux voisins qui en ont un ;
    #    la plage, elle, reste celle que l'ordre garantit (on ne la resserre pas sur une estimation)
    anchors = [i for i, t in enumerate(out) if t.point is not None and i not in flagged]
    for a, b in zip(anchors, anchors[1:], strict=False):
        gap = b - a
        pa, pb = out[a].point, out[b].point
        assert pa is not None and pb is not None
        for k in range(1, gap):
            i = a + k
            t = out[i]
            if t.point is not None or i in flagged:
                continue
            point = _clamp(pa + (pb - pa) * k // gap, t.start, t.end)
            width = t.width
            precision = Precision.RANGE if width is None else _coarsest_allowed(Precision.RANGE, width)
            out[i] = Temps(t.start, t.end, point, precision, Origin.INTERPOLATED)
    conflicts.sort(key=lambda c: c.index)
    return out, conflicts


#: à conflit égal, on écarte d'abord l'estimation la moins sûre
TRUST = {Origin.SOURCE: 9, Origin.MANUAL: 8, Origin.HEADER: 7, Origin.CROSS: 6, Origin.CONTENT: 5, Origin.PATH: 4,
         Origin.INTERPOLATED: 3, Origin.ERA: 2, Origin.FILE: 1, Origin.NONE: 0}
#: au-delà, la recherche quadratique du coupable est trop chère : on se contente du signalement local
MAX_RANGED = 3000


def _feasible(items: list[Temps], idx: list[int]) -> bool:
    """Existe-t-il des points non décroissants, chacun dans sa plage ? (glouton, linéaire)"""
    p: int | None = None
    for i in idx:
        t = items[i]
        p = t.start if p is None else max(p, t.start)  # type: ignore[type-var]
        if t.end is not None and p is not None and p > t.end:
            return False
    return True


def _inconsistent_ranges(items: list[Temps], flagged: set[int]) -> set[int]:
    """Les éléments à écarter pour que les plages restantes respectent l'ordre.

    Une suite est tenable si et seulement si aucun élément ne commence après la fin d'un
    élément qui le suit. On compte, pour chacun, les paires qu'il casse, et on écarte le
    pire (à égalité : une plage avant une date exacte, la moins sûre d'abord) jusqu'à ce
    que la suite tienne.
    """
    idx = [i for i, t in enumerate(items) if i not in flagged and t.start is not None and t.end is not None]
    if _feasible(items, idx) or len(idx) > MAX_RANGED:
        return set()
    removed: set[int] = set()
    while True:
        live = [i for i in idx if i not in removed]
        counts: dict[int, int] = {}
        for pos, i in enumerate(live):
            si = items[i].start
            for j in live[pos + 1:]:
                if si > items[j].end:  # type: ignore[operator]
                    counts[i] = counts.get(i, 0) + 1
                    counts[j] = counts.get(j, 0) + 1
        if not counts:
            return removed
        worst = max(counts, key=lambda k: (counts[k], items[k].precision != Precision.EXACT,
                                           -TRUST[items[k].origin], items[k].width or 0))
        removed.add(worst)


def _longest_non_decreasing(indices: list[int], values: list[int]) -> list[int]:
    """Les indices d'une plus longue sous-suite non décroissante (patience, n log n)."""
    tails: list[int] = []  # valeur de fin de chaque longueur
    tail_at: list[int] = []  # position (dans values) de cette fin
    parent = [-1] * len(values)
    for pos, v in enumerate(values):
        k = bisect.bisect_right(tails, v)
        if k == len(tails):
            tails.append(v)
            tail_at.append(pos)
        else:
            tails[k] = v
            tail_at[k] = pos
        parent[pos] = tail_at[k - 1] if k > 0 else -1
    chain: list[int] = []
    pos = tail_at[-1] if tail_at else -1
    while pos != -1:
        chain.append(indices[pos])
        pos = parent[pos]
    return chain[::-1]


def with_point(t: Temps, point: int) -> Temps:
    return replace(t, point=_clamp(point, t.start, t.end))

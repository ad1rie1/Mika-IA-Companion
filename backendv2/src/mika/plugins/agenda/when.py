"""Le temps de l'agenda, en mots et en dates (ADR 0309) : pur — ni outil, ni base, ni horloge ; ses mots viennent de
sa voix (``agenda.words.*``, ``agenda.tools.bad_time``).

- **La borne d'un jour** (``midnight``) : minuit local d'une date dans un fuseau, en microsecondes — sa seule
  écriture. Une période de jours se lit de minuit à minuit : ses outils, la journée de son prompt (``prompt.py``),
  la console (``inspect/views.py::bounds``), l'API par personne (``app/domains/agenda/api.py``), « L'agenda de
  Mika » (``app/domains/agenda/her.py``) ; une journée entière commence à minuit (``watch.py::starts_at``).
- **Quand il occupe** (``local_span``) : une journée entière, de minuit à minuit dans ce fuseau.
- **En mots** : une heure (``hm`` : « 9 h », « 14 h 30 »), un moment (``when_words``), une période
  (``period_words``).
- **Ce qu'un outil demande** : une période, en mots ou en dates (``period``, jamais plus de ``DAYS_MAX`` jours), ou
  le moment d'un rendez-vous (``span_of``, jamais plus de ``LONGEST_DAYS`` jours ; une heure par défaut).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from mika.kernel.clock import instant, local
from mika.ports.agenda import Span, local_days, whole_days
from mika.vocab.circadian import day_fr
from mika.vocab.phrasebook import phrase

#: au plus tant de jours lus d'un coup (une période)
DAYS_MAX = 62
#: un rendez-vous d'au plus tant de jours ; une durée par défaut (min)
LONGEST_DAYS, DEFAULT_MINUTES = 14, 60


def hm(dt: datetime) -> str:
    """« 9 h », « 14 h 30 »."""
    return phrase("agenda.words.hour", h=dt.hour) if not dt.minute else \
        phrase("agenda.words.hour_minute", h=dt.hour, m=f"{dt.minute:02d}")


def midnight(d: date, tz: ZoneInfo) -> int:
    """La borne d'un jour : minuit de cette date dans ce fuseau, en microsecondes."""
    return instant(datetime.combine(d, time(), tzinfo=tz))


def local_span(span: Span, tz: ZoneInfo) -> tuple[int, int]:
    """Quand il occupe, en instants : une journée entière, de minuit à minuit dans ce fuseau (ses instants sont à
    minuit UTC de ses dates)."""
    return local_days(span, tz)


def when_words(span: Span, tz: ZoneInfo) -> str:
    """Quand, en mots : « mardi 24 novembre, 9 h 30 – 10 h 30 », « samedi 28 novembre, toute la journée », « du
    samedi 28 au lundi 30 novembre »."""
    if span.all_day:
        first, last = date.fromisoformat(span.first_day), date.fromisoformat(span.last_day)
        if first == last:
            return phrase("agenda.words.all_day", day=day_fr(first))
        return phrase("agenda.words.days", first=day_fr(first), last=day_fr(last))
    start, end = local(span.start, tz), local(max(span.start, span.end), tz)
    if start.date() == end.date() or (end - start <= timedelta(hours=24) and end.time() == time()):
        return phrase("agenda.words.timed", day=day_fr(start.date()), start=hm(start), end=hm(end))
    return phrase("agenda.words.timed_days", first=day_fr(start.date()), start=hm(start), last=day_fr(end.date()),
                  end=hm(end))


def period(when: str, start: str, end: str, today: date) -> tuple[date, date] | None:
    """Une période, du premier jour au lendemain du dernier : en mots (``Period``) ou en dates (``AAAA-MM-JJ``, la
    dernière comprise ; une seule, ce jour-là) ; rien : les sept jours qui viennent. ``None`` : une date illisible, ou
    une fin avant le début. Jamais plus de ``DAYS_MAX`` jours."""
    if start.strip() or end.strip():
        try:
            first = date.fromisoformat((start or end).strip())
            last = date.fromisoformat((end or start).strip())
        except ValueError:
            return None
        if last < first:
            return None
        return first, min(last + timedelta(days=1), first + timedelta(days=DAYS_MAX))
    monday = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    following = (month + timedelta(days=32)).replace(day=1)
    spans = {
        "aujourdhui": (today, today + timedelta(days=1)),
        "demain": (today + timedelta(days=1), today + timedelta(days=2)),
        "apres_demain": (today + timedelta(days=2), today + timedelta(days=3)),
        "cette_semaine": (today, monday + timedelta(days=7)),
        "semaine_prochaine": (monday + timedelta(days=7), monday + timedelta(days=14)),
        "ce_weekend": (max(today, monday + timedelta(days=5)), monday + timedelta(days=7)),
        "ce_mois": (today, following),
        "mois_prochain": (following, (following + timedelta(days=32)).replace(day=1)),
    }
    return spans.get(when, (today, today + timedelta(days=7)))


def period_words(first: date, after: date) -> str:
    last = after - timedelta(days=1)
    return day_fr(first) if first == last else phrase("agenda.words.period", first=day_fr(first), last=day_fr(last))


def _moment(text: str, tz: ZoneInfo) -> datetime | date | None:
    """Une date (``AAAA-MM-JJ``) ou une heure (``AAAA-MM-JJTHH:MM``, dans ce fuseau) ; ``None`` : illisible."""
    text = text.strip().replace(" ", "T")
    if not text:
        return None
    try:
        if "T" not in text:
            return date.fromisoformat(text)
        got = datetime.fromisoformat(text)
    except ValueError:
        return None
    return got.replace(tzinfo=tz) if got.tzinfo is None else got.astimezone(tz)


def span_of(start: str, end: str, minutes: int | None, all_day: bool, tz: ZoneInfo, *,
            current: Span | None = None) -> Span | str | None:
    """La période qu'un outil demande : une journée entière (une date, ou ``all_day``), ou de telle heure à telle
    heure (la fin, sinon une durée, sinon celle de l'événement changé ``current``, sinon une heure). ``None`` : rien
    de demandé ; un texte : pourquoi c'est illisible."""
    if not start.strip() and not end.strip() and minutes is None and current is None:
        return None
    if not start.strip() and current is None:
        return phrase("agenda.tools.bad_time")
    begin = _moment(start, tz) if start.strip() else None
    if begin is None and start.strip():
        return phrase("agenda.tools.bad_time")
    if begin is None:  # on ne change que la fin, ou la durée : depuis le début d'aujourd'hui
        assert current is not None
        begin = date.fromisoformat(current.first_day) if current.all_day else local(current.start, tz)
    finish = _moment(end, tz) if end.strip() else None
    if end.strip() and finish is None:
        return phrase("agenda.tools.bad_time")
    if all_day or (isinstance(begin, date) and not isinstance(begin, datetime)):
        first = begin.date() if isinstance(begin, datetime) else begin
        last = (finish.date() if isinstance(finish, datetime) else finish) if finish is not None else first
        if current is not None and current.all_day and finish is None and not start.strip():
            last = date.fromisoformat(current.last_day)
        if last < first or (last - first).days > LONGEST_DAYS:
            return phrase("agenda.tools.bad_time")
        return whole_days(first.isoformat(), last.isoformat())
    assert isinstance(begin, datetime)
    if isinstance(finish, datetime):
        stop = finish
    elif isinstance(finish, date):
        return phrase("agenda.tools.bad_time")
    elif minutes is not None:
        stop = begin + timedelta(minutes=minutes)
    elif current is not None and not current.all_day:
        stop = begin + timedelta(microseconds=current.end - current.start)
    else:
        stop = begin + timedelta(minutes=DEFAULT_MINUTES)
    if stop <= begin or stop - begin > timedelta(days=LONGEST_DAYS):
        return phrase("agenda.tools.bad_time")
    return Span(instant(begin), instant(stop), getattr(tz, "key", ""), False)


__all__ = ["local_span", "period", "span_of", "when_words"]

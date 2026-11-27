"""Le temps de l'agenda (``plugins/agenda/when.py``) : le moment d'un rendez-vous qu'un outil demande.

Une durée se compte en temps réel, la nuit d'un changement d'heure aussi : « 2 h 30 pendant 30 min », un 29 mars à
Paris, ne finit pas avant de commencer, et une heure d'automne ne dure pas deux heures.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from mika.kernel.clock import HOUR, MINUTE, instant, local
from mika.plugins.agenda.when import LONGEST_DAYS, midnight, span_of
from mika.ports.agenda import Span

PARIS = ZoneInfo("Europe/Paris")
#: à Paris en 2026 : le 29 mars, 2 h devient 3 h ; le 25 octobre, 3 h redevient 2 h
SPRING, AUTUMN = "2026-03-29", "2026-10-25"


def _span(start: str, end: str = "", minutes: int | None = None, *, current: Span | None = None) -> Span:
    got = span_of(start, end, minutes, False, PARIS, current=current)
    assert isinstance(got, Span), got
    return got


def _said(t: int) -> str:
    return local(t, PARIS).strftime("%H:%M%z")


def test_a_duration_is_real_time_on_an_ordinary_day():
    s = _span("2026-06-10T14:00", minutes=45)
    assert (_said(s.start), _said(s.end), s.end - s.start) == ("14:00+0200", "14:45+0200", 45 * MINUTE)
    assert _span("2026-06-10T14:00").end - _span("2026-06-10T14:00").start == HOUR  # une heure par défaut
    assert (s.zone, s.all_day) == ("Europe/Paris", False)


def test_an_hour_that_does_not_exist_still_ends_after_it_begins():
    """2 h 30 n'existe pas le 29 mars : le rendez-vous se pose à 3 h 30, et dure ce qu'on a dit."""
    s = _span(f"{SPRING}T02:30", minutes=30)
    assert s.end - s.start == 30 * MINUTE
    assert (_said(s.start), _said(s.end)) == ("03:30+0200", "04:00+0200")


@pytest.mark.parametrize(("start", "minutes", "ends"), [
    (f"{SPRING}T01:00", 180, "05:00+0200"),  # par-dessus l'heure qui saute : trois vraies heures
    (f"{AUTUMN}T02:30", 60, "02:30+0100"),   # l'heure qui revient : une heure après, il est de nouveau 2 h 30
    (f"{AUTUMN}T01:00", 180, "03:00+0100"),
])
def test_a_duration_across_a_change_of_hour_lasts_what_was_said(start, minutes, ends):
    s = _span(start, minutes=minutes)
    assert s.end - s.start == minutes * MINUTE and _said(s.end) == ends


def test_two_moments_said_with_their_offset_are_compared_with_it():
    """La nuit d'automne, 2 h 10 d'hiver vient après 2 h 30 d'été : quarante minutes, pas un refus."""
    s = _span(f"{AUTUMN}T02:30+02:00", f"{AUTUMN}T02:10+01:00")
    assert s.end - s.start == 40 * MINUTE
    assert isinstance(span_of(f"{AUTUMN}T02:10+01:00", f"{AUTUMN}T02:30+02:00", None, False, PARIS), str)


def test_a_changed_start_keeps_the_real_length_of_the_event():
    current = Span(instant(datetime(2026, 6, 10, 14, 0, tzinfo=PARIS)),
                   instant(datetime(2026, 6, 10, 15, 30, tzinfo=PARIS)), "Europe/Paris", False)
    moved = _span(f"{SPRING}T01:30", current=current)
    assert moved.end - moved.start == 90 * MINUTE and _said(moved.end) == "04:00+0200"


def test_an_end_before_its_start_and_a_span_too_long_are_refused():
    assert isinstance(span_of("2026-06-10T14:00", "2026-06-10T13:00", None, False, PARIS), str)
    assert isinstance(span_of("2026-06-10T14:00", "2026-06-10T14:00", None, False, PARIS), str)
    assert isinstance(span_of("2026-06-10T14:00", "", 0, False, PARIS), str)
    assert isinstance(span_of("2026-06-10T14:00", "", (LONGEST_DAYS * 24 * 60) + 1, False, PARIS), str)
    assert isinstance(span_of("2026-06-10T14:00", "", LONGEST_DAYS * 24 * 60, False, PARIS), Span)


@pytest.mark.parametrize(("start", "end", "minutes", "kept"), [
    # quatorze jours au calendrier par-dessus le passage à l'heure d'hiver : 337 h réelles, acceptées
    ("2026-10-20T10:00", "2026-11-03T10:00", None, True),
    ("2026-10-20T10:00", "2026-11-03T10:01", None, False),
    # quatorze jours au calendrier par-dessus le passage à l'heure d'été : 335 h réelles
    ("2026-03-20T10:00", "2026-04-03T10:00", None, True),
    ("2026-03-20T10:00", "2026-04-03T11:00", None, True),  # quatorze jours réels, tout juste
    ("2026-03-20T10:00", "2026-04-03T11:01", None, False),
    # quatorze jours réels dits en minutes, par-dessus l'un et l'autre
    ("2026-03-20T10:00", "", 14 * 24 * 60, True),
    ("2026-10-20T10:00", "", 14 * 24 * 60, True),
    ("2026-10-20T10:00", "", 14 * 24 * 60 + 60, True),  # la fin tombe à 10 h murales, quatorze jours plus tard
    ("2026-10-20T10:00", "", 14 * 24 * 60 + 61, False),
])
def test_fourteen_days_count_by_the_calendar_or_by_real_time(start, end, minutes, kept):
    """La borne se lit au plus court des deux mesures : le changement d'heure ne fait refuser ni quatorze jours du
    calendrier ni quatorze jours réels."""
    assert LONGEST_DAYS == 14
    assert isinstance(span_of(start, end, minutes, False, PARIS), Span) is kept


def test_a_moved_start_keeps_fourteen_days_that_span_the_change_of_hour():
    """Déplacer le seul début d'un rendez-vous de quatorze jours qui enjambait le 25 octobre reprend sa durée réelle
    (337 h) : elle passe encore."""
    current = Span(instant(datetime(2026, 10, 20, 10, 0, tzinfo=PARIS)),
                   instant(datetime(2026, 11, 3, 10, 0, tzinfo=PARIS)), "Europe/Paris", False)
    assert current.end - current.start == 337 * HOUR
    moved = span_of("2026-10-19T10:00", "", None, False, PARIS, current=current)
    assert isinstance(moved, Span) and moved.end - moved.start == 337 * HOUR


def test_the_bound_of_a_day_is_local_midnight_whatever_the_day():
    """La borne d'un jour : minuit local — un jour de changement d'heure fait 23 ou 25 heures."""
    def day(iso: str) -> int:
        d = datetime.fromisoformat(iso).date()
        return midnight(d.replace(day=d.day + 1), PARIS) - midnight(d, PARIS)

    assert (day("2026-06-10"), day(SPRING), day(AUTUMN)) == (24 * HOUR, 23 * HOUR, 25 * HOUR)
    assert _said(midnight(datetime.fromisoformat(SPRING).date(), PARIS)) == "00:00+0100"

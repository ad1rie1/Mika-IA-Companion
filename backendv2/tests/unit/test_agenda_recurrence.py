"""Les occurrences d'un agenda (ADR 0309, ``ports/agenda.py``) : des fonctions pures sur la RFC 5545.

- une série revient à la même heure de son fuseau, l'heure d'été n'y change rien ; une journée entière reste une date ;
- EXDATE retire, RDATE ajoute, COUNT et UNTIL bornent (un UNTIL en date ou flottant se lit dans le fuseau de la série) ;
- une exception remplace l'occurrence qu'elle désigne (annulée, elle la retire) ; une série annulée ne se montre pas ;
  un refus du compte non plus ;
- couper une série (« celui-ci et les suivants ») donne deux règles qui, ensemble, redonnent les mêmes occurrences ;
- une règle illisible ou trop fine ne donne que sa première occurrence ; une série sans fin n'a pas de fin ;
- les clés : d'un agenda (jamais une adresse), d'une occurrence, du compte du système d'une personne.
"""

from __future__ import annotations

import gc
import time
import tracemalloc
from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from dateutil.rrule import rrulestr

from mika.ports.agenda import (
    CANCELLED,
    DAY_US,
    FOREVER,
    NO,
    US_PER_S,
    Calendar,
    Connection,
    Event,
    Participant,
    Recurrence,
    Span,
    at_us,
    calendar_key,
    counted_before,
    default_reminder,
    expand,
    follows,
    instance,
    key_instant,
    local_key,
    masked,
    occurrence_key,
    occurrences,
    owner_of,
    series_end,
    shifted_key,
    split_calendar_key,
    split_rule,
    system_account,
    system_person,
    us_of,
    whole_days,
)

PARIS = ZoneInfo("Europe/Paris")
CAL = "moi:user_1~mon-agenda"
HOUR = 3600 * US_PER_S


def paris(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> int:
    return us_of(datetime(y, m, d, h, mi, tzinfo=PARIS))


def series(rule: str, start: int, *, minutes: int = 30, exdates=(), rdates=(), title: str = "Point") -> Event:
    return Event(CAL, "u1", Span(start, start + minutes * 60 * US_PER_S, "Europe/Paris"), title,
                 recurrence=Recurrence(rule, tuple(exdates), tuple(rdates)))


def local_hours(occ) -> list[str]:
    return [at_us(o.span.start, PARIS).strftime("%Y-%m-%d %H:%M") for o in occ]


def test_a_weekly_meeting_stays_at_nine_across_the_change_of_hour():
    point = series("FREQ=WEEKLY;BYDAY=MO", paris(2026, 10, 19, 9))
    got = occurrences(point, paris(2026, 10, 1), paris(2026, 11, 10))
    assert local_hours(got) == ["2026-10-19 09:00", "2026-10-26 09:00", "2026-11-02 09:00", "2026-11-09 09:00"]
    # la clé d'une occurrence est son instant UTC : l'heure d'hiver la décale d'une heure en UTC
    assert [o.key for o in got[:2]] == ["20261019T070000Z", "20261026T080000Z"]
    assert all(o.span.end - o.span.start == 30 * 60 * US_PER_S for o in got)


def test_a_whole_day_stays_a_date_every_year():
    birthday = Event(CAL, "anniv", whole_days("2026-11-28", "2026-11-28"), "Anniversaire de Léa",
                     recurrence=Recurrence("FREQ=YEARLY"))
    got = occurrences(birthday, paris(2027, 1, 1), paris(2029, 1, 1))
    assert [o.key for o in got] == ["20271128", "20281128"]
    assert [o.span.first_day for o in got] == ["2027-11-28", "2028-11-28"]
    assert all(o.span.all_day and o.span.last_day == o.span.first_day for o in got)
    assert series_end(birthday) == FOREVER


def test_exdate_removes_rdate_adds_count_and_until_bound():
    start = paris(2026, 11, 2, 9)
    kept = series("FREQ=WEEKLY;COUNT=4", start, exdates=[occurrence_key(paris(2026, 11, 9, 9), False)],
                  rdates=[occurrence_key(paris(2026, 11, 12, 14), False)])
    assert local_hours(occurrences(kept, start, paris(2027, 1, 1))) == [
        "2026-11-02 09:00", "2026-11-12 14:00", "2026-11-16 09:00", "2026-11-23 09:00"]
    assert series_end(kept) == paris(2026, 11, 23, 9, 30)
    # un UNTIL en date se lit dans le fuseau de la série : ce jour-là compte encore
    until_day = series("FREQ=DAILY;UNTIL=20261104", start)
    assert local_hours(occurrences(until_day, start, paris(2027, 1, 1)))[-1] == "2026-11-04 09:00"
    # un UNTIL flottant aussi, et un UNTIL en UTC tel quel
    floating = series("FREQ=DAILY;UNTIL=20261103T090000", start)
    assert len(occurrences(floating, start, paris(2027, 1, 1))) == 2
    utc = series("FREQ=DAILY;UNTIL=20261103T080000Z", start)
    assert len(occurrences(utc, start, paris(2027, 1, 1))) == 2


def test_an_occurrence_running_when_the_period_opens_is_in_it():
    night = series("FREQ=DAILY", paris(2026, 11, 2, 22), minutes=180)
    got = occurrences(night, paris(2026, 11, 3), paris(2026, 11, 3, 12))
    assert local_hours(got) == ["2026-11-02 22:00"]


def test_an_exception_replaces_its_occurrence_and_a_cancelled_one_removes_it():
    start = paris(2026, 11, 2, 9)
    point = series("FREQ=WEEKLY;COUNT=3", start)
    second = occurrence_key(paris(2026, 11, 9, 9), False)
    third = occurrence_key(paris(2026, 11, 16, 9), False)
    moved = replace(instance(point, second), span=Span(paris(2026, 11, 10, 15), paris(2026, 11, 10, 16),
                                                        "Europe/Paris"), title="Point (décalé)")
    gone = replace(instance(point, third), status=CANCELLED)
    got = expand([point, moved, gone], start, paris(2027, 1, 1))
    assert [(o.event.title, o.key) for o in got] == [("Point", "20261102T080000Z"), ("Point (décalé)", second)]
    assert local_hours(got) == ["2026-11-02 09:00", "2026-11-10 15:00"]


def test_a_cancelled_series_shows_no_occurrence():
    start = paris(2026, 11, 2, 9)
    cancelled = replace(series("FREQ=WEEKLY;COUNT=3", start), status=CANCELLED)
    assert occurrences(cancelled, start, paris(2027, 1, 1)) == []
    assert expand([cancelled], start, paris(2027, 1, 1)) == []


def test_what_the_account_declined_is_hidden_unless_asked():
    start = paris(2026, 11, 2, 9)
    invitation = replace(series("FREQ=WEEKLY;COUNT=2", start), response=NO)
    assert expand([invitation], start, paris(2027, 1, 1)) == []
    assert len(expand([invitation], start, paris(2027, 1, 1), declined=True)) == 2
    # refusée pour une seule occurrence (une exception) : les autres restent
    one = replace(instance(invitation, occurrence_key(start, False)), response=NO)
    kept = expand([replace(invitation, response="oui"), one], start, paris(2027, 1, 1))
    assert local_hours(kept) == ["2026-11-09 09:00"]


@pytest.mark.parametrize("rule", ["FREQ=WEEKLY;COUNT=6", "FREQ=WEEKLY;UNTIL=20261207T080000Z", "FREQ=WEEKLY"])
def test_splitting_a_series_keeps_the_same_occurrences(rule):
    start = paris(2026, 11, 2, 9)
    point = series(rule, start)
    cut = occurrence_key(paris(2026, 11, 16, 9), False)
    before_rule, after_rule = split_rule(point, cut)
    before = replace(point, recurrence=Recurrence(before_rule))
    after = replace(instance(point, cut), uid="u2", original="", recurrence=Recurrence(after_rule))
    window = (start, paris(2026, 12, 31))
    whole = [o.key for o in occurrences(point, *window)]
    assert [o.key for o in occurrences(before, *window)] + [o.key for o in occurrences(after, *window)] == whole
    assert [o.key for o in occurrences(before, *window)][-1] == "20261109T080000Z"
    if "COUNT" in rule:
        assert counted_before(point, cut) == 2 and after_rule.endswith("COUNT=4")


def test_a_whole_day_series_splits_on_the_day_before():
    birthday = Event(CAL, "anniv", whole_days("2026-11-28", "2026-11-28"), "Anniv", recurrence=Recurrence("FREQ=YEARLY"))
    before_rule, _after = split_rule(birthday, "20281128")
    assert "UNTIL=20281127" in before_rule and "COUNT" not in before_rule


def test_an_unreadable_or_too_fine_rule_gives_its_first_occurrence_only():
    start = paris(2026, 11, 2, 9)
    for rule in ("FREQ=SECONDLY", "FREQ=MINUTELY;INTERVAL=5", "FREQ=JAMAIS;BYDAY=XX", "BYDAY=MO"):
        got = occurrences(series(rule, start), start - DAY_US, start + 30 * DAY_US)
        assert local_hours(got) == ["2026-11-02 09:00"], rule


def test_a_mad_rule_is_bounded():
    daily = series("FREQ=DAILY", paris(2020, 1, 1, 9))
    assert len(occurrences(daily, paris(2020, 1, 1), paris(2040, 1, 1), limit=50)) == 50


def _seconds(fn) -> float:
    began = time.perf_counter()
    fn()
    return time.perf_counter() - began


def _retained(fn) -> int:
    """Ce qu'un appel laisse en mémoire derrière lui (octets) : ce qu'une règle garde de ce qu'elle a parcouru."""
    gc.collect()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        fn()
        gc.collect()
        return tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()


#: des règles venues d'un abonnement hostile : née en 1900 heure par heure, qui ne tombe jamais, née en l'an 1…
HOSTILE = [
    ("FREQ=HOURLY", datetime(1900, 1, 1, tzinfo=UTC)),
    ("FREQ=HOURLY;COUNT=1000000000", datetime(1900, 1, 1, 0, 30, tzinfo=UTC)),
    ("FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30", datetime(2020, 1, 1, 9, tzinfo=PARIS)),
    ("FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30;COUNT=3", datetime(2020, 1, 2, 9, tzinfo=PARIS)),
    ("FREQ=DAILY;BYMONTH=4;BYMONTHDAY=31;UNTIL=99991230T000000Z", datetime(2020, 1, 3, 9, tzinfo=PARIS)),
    ("FREQ=HOURLY;BYSETPOS=2", datetime(2026, 1, 1, tzinfo=PARIS)),
    ("FREQ=DAILY", datetime(1, 1, 1, 9, tzinfo=UTC)),
    ("FREQ=DAILY;COUNT=100000000", datetime(1, 1, 2, 9, tzinfo=UTC)),
    ("FREQ=WEEKLY;UNTIL=99991230T000000Z", datetime(1, 1, 3, 9, tzinfo=UTC)),
]


@pytest.mark.parametrize(("rule", "born"), HOSTILE, ids=[r for r, _ in HOSTILE])
def test_a_hostile_rule_costs_little_time_and_keeps_no_memory(rule, born):
    hostile = series(rule, us_of(born))
    week = (paris(2026, 11, 23), paris(2026, 11, 30))
    assert _seconds(lambda: occurrences(hostile, *week)) < 0.2
    assert _seconds(lambda: series_end(hostile)) < 0.2
    assert _seconds(lambda: counted_before(hostile, "20261125T080000Z")) < 0.2
    again = series(rule, us_of(born) + HOUR)  # une autre série : rien de ce qu'elle a parcouru ne reste
    assert _retained(lambda: (occurrences(again, *week), series_end(again))) < 1_000_000


def test_rdates_in_bulk_cost_little_time():
    start = paris(2026, 1, 5, 9)
    bulk = series("", start, rdates=[occurrence_key(start + i * HOUR, False) for i in range(300_000)],
                  exdates=[occurrence_key(start + i * HOUR + 1, False) for i in range(300_000)])
    week = (paris(2026, 11, 23), paris(2026, 11, 30))
    assert _seconds(lambda: occurrences(bulk, *week)) < 0.2
    assert _seconds(lambda: series_end(bulk)) < 0.2


#: des séries réelles : elles rendent exactement ce que la règle donne, lue depuis le début de la série
LEGIT = [
    ("FREQ=WEEKLY;BYDAY=MO,TH", paris(2016, 11, 21, 9)),
    ("FREQ=WEEKLY;INTERVAL=2;BYDAY=TU", paris(2016, 11, 22, 18, 30)),
    ("FREQ=WEEKLY", paris(2016, 11, 23, 12)),
    ("FREQ=MONTHLY;BYDAY=-1FR", paris(2016, 1, 29, 17)),
    ("FREQ=MONTHLY", paris(2016, 1, 31, 10)),
    ("FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=15,-1", paris(2016, 2, 15, 8)),
    ("FREQ=YEARLY", paris(2016, 2, 29, 20)),
    ("FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU", paris(2016, 3, 27, 3)),
    ("FREQ=DAILY;INTERVAL=3", paris(2016, 11, 24, 7, 15)),
    ("FREQ=DAILY;BYHOUR=9,14", paris(2016, 11, 24, 9)),
    ("FREQ=HOURLY;INTERVAL=5", paris(2026, 3, 20, 1)),
    ("FREQ=WEEKLY;COUNT=500", paris(2017, 3, 6, 8)),
    ("FREQ=WEEKLY;UNTIL=20270101T000000Z", paris(2016, 11, 25, 9)),
]


def _expected(rule: str, start: int, lo: int, hi: int, minutes: int = 30) -> list[str]:
    """Ce que la règle donne, parcourue depuis le début de la série (la lecture d'avant)."""
    duration = minutes * 60 * US_PER_S
    out = []
    for d in rrulestr(rule, dtstart=at_us(start, PARIS)):
        at = us_of(d)
        if at >= hi:
            break
        if at + duration > lo:
            out.append(occurrence_key(at, False))
    return out


@pytest.mark.parametrize(("rule", "start"), LEGIT, ids=[r for r, _ in LEGIT])
def test_a_long_running_series_gives_the_same_occurrences(rule, start):
    point = series(rule, start)
    for lo, hi in ((paris(2026, 3, 1), paris(2026, 4, 30)), (paris(2026, 10, 20), paris(2026, 11, 3)),
                   (paris(2016, 1, 1), paris(2017, 1, 1)), (paris(2026, 11, 24, 9, 10), paris(2026, 11, 24, 9, 11)),
                   (paris(2026, 4, 15), paris(2026, 6, 15)), (paris(2027, 1, 15), paris(2029, 3, 15))):
        assert [o.key for o in occurrences(point, lo, hi)] == _expected(rule, start, lo, hi), (lo, hi)
    if "COUNT" in rule or "UNTIL" in rule:
        last = list(rrulestr(rule, dtstart=at_us(start, PARIS)))[-1]
        assert series_end(point) == us_of(last) + 30 * 60 * US_PER_S


def test_keys_of_calendars_occurrences_and_accounts():
    assert local_key("primary") == "primary"
    secret = local_key("adrien.moreau@gmail.com")
    assert secret.startswith("h") and "@" not in secret and secret == local_key("adrien.moreau@gmail.com")
    key = calendar_key("moi:user_1", "mon-agenda")
    assert split_calendar_key(key) == ("moi:user_1", "mon-agenda") and split_calendar_key("rien") == ("", "")
    assert key_instant(occurrence_key(paris(2026, 11, 2, 9), False)) == paris(2026, 11, 2, 9)
    assert shifted_key("20261102T080000Z", HOUR) == "20261102T090000Z"
    assert system_account("personne:user_7") == system_account("user_7") == "moi:user_7"
    assert system_person("moi:user_7") == "user_7" and system_person("google-perso") == ""
    assert owner_of("moi:user_7", {}) == "personne:user_7"
    assert owner_of("google-perso", {"google-perso": "personne:user_2"}) == "personne:user_2"
    assert owner_of("feries", {}) == ""


def test_reminders_by_kind_and_what_a_connection_follows():
    assert default_reminder("systeme") == "30" and default_reminder("google") == "non"
    assert default_reminder("ical", provider="15") == "non"  # un abonnement n'en a pas
    assert default_reminder("caldav", provider="15") == "15" and default_reminder("systeme", system="60") == "60"
    main = Calendar("google~primary", "google", "primary", primary=True, selected=False)
    other = Calendar("google~fetes", "google", "fetes", selected=False)
    picked = Calendar("google~travail", "google", "travail", selected=True)
    plain = Connection("google", "google")
    assert follows(plain, main) and not follows(plain, other) and follows(plain, picked)
    said = Connection("google", "google", followed={"fetes": True, "travail": False})
    assert follows(said, other) and not follows(said, picked)


def test_a_private_event_shows_its_slot_only():
    e = Event(CAL, "u", Span(0, HOUR), "Médecin", location="Cabinet", description="résultats",
              participants=(Participant("a@b.fr", "A"),), private=True)
    shown = masked(e)
    assert (shown.title, shown.location, shown.description, shown.participants) == ("", "", "", ())
    assert shown.span == e.span and shown.busy

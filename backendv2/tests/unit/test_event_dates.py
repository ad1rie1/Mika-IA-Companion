"""Les dates d'un événement en français (ADR 0245), à l'heure de Paris, la prochaine d'abord : une date, des dates qui
se suivent dans la semaine, une période et ses jours, « jusqu'au … » ; ce qui est passé ne compte plus — une séance
d'aujourd'hui finie non plus ; les bornes en ISO 8601, une fin à minuit le lendemain."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from mika.adapters.maps.hours import PARIS
from mika.adapters.maps.when import Occurrence, dates_fr, mask_fr, occurrence_of, upcoming, when_text

#: le mercredi 18 novembre 2026, 10:00 à Paris
NOW = datetime(2026, 11, 18, 10, 0, tzinfo=PARIS)
SUNDAY, TUE_TO_SUN = 1 << 6, 0b1111110


def day(text: str, opens: str = "", closes: str = "", until: str = "", days: int = 0) -> Occurrence:
    return Occurrence(date.fromisoformat(text), date.fromisoformat(until or text), opens, closes, days)


@pytest.mark.parametrize(("occurrences", "said"), [
    ([day("2026-11-20", "19:00", "20:30"), day("2026-12-20", "19:00", "20:30")], "ven. 20 nov. · 19:00–20:30"),
    # des dates qui se suivent, aux mêmes heures : leurs jours
    ([day(f"2026-11-{d}", "11:00", "19:00") for d in (18, 19, 20, 21, 22, 25)], "du mer. au dim. · 11:00–19:00"),
    ([day(f"2026-11-{d}", "11:00", "19:00") for d in (18, 19, 20, 21, 22, 24)], "du mer. au dim. · 11:00–19:00"),
    ([day(f"2026-11-{d}", "09:00", "12:00") for d in range(18, 26)], "tous les jours · 09:00–12:00"),
    ([day(d, "10:00", "18:00") for d in ("2026-11-19", "2026-11-21", "2026-11-23")], "jeu., sam., lun. · 10:00–18:00"),
    ([day("2026-11-21", "19:00", "00:00")], "sam. 21 nov. · 19:00–minuit"),
    ([day("2026-12-01")], "mar. 1er déc."),
    ([day("2027-10-09", "20:00")], "sam. 9 oct. 2027 · à partir de 20:00"),
    # une période : ses jours, ses heures, sa fin ; à venir, son début d'abord
    ([day("2026-01-01", "08:00", "12:00", "2026-12-31", SUNDAY)], "le dim. · 08:00–12:00 · jusqu'au 31 déc."),
    ([day("2026-11-01", until="2027-01-10")], "jusqu'au 10 janv."),
    ([day("2026-12-03", "13:00", "19:00", "2027-01-10", TUE_TO_SUN)],
     "du 3 déc. au 10 janv. · du mar. au dim. · 13:00–19:00"),
    ([day("2026-11-01", until="2026-11-17")], ""),
])
def test_when_text_says_the_next_date_first(occurrences, said):
    assert when_text(occurrences, NOW) == said


@pytest.mark.parametrize(("occurrences", "said"), [
    # le week-end du 5 décembre, cherché le 18 novembre : « sam., dim. » se lisait « ce week-end »
    ([day("2026-12-05", "10:00", "19:00"), day("2026-12-06", "10:00", "19:00")], "sam. 5 et dim. 6 déc. · 10:00–19:00"),
    ([day(f"2026-12-{d}", "10:00", "18:00") for d in (24, 25, 26)], "du jeu. 24 au sam. 26 déc. · 10:00–18:00"),
    ([day(d, "10:00", "18:00") for d in ("2026-11-30", "2026-12-01", "2026-12-02")],
     "du lun. 30 nov. au mer. 2 déc. · 10:00–18:00"),
    ([day(f"2026-12-0{d}", "14:00", "16:00") for d in (3, 5, 7)], "jeu. 3, sam. 5 et lun. 7 déc. · 14:00–16:00"),
    ([day(f"2026-12-{d:02d}", "09:00", "12:00") for d in range(7, 14)], "du lun. 7 au dim. 13 déc. · 09:00–12:00"),
    ([day("2026-11-24", "20:00", "22:00"), day("2026-11-25", "20:00", "22:00")],
     "mar. 24 et mer. 25 nov. · 20:00–22:00"),  # le mercredi qui vient est à sept jours : dit avec sa date
    ([day("2026-11-21", "20:00", "22:00"), day("2026-11-22", "20:00", "22:00")], "sam., dim. · 20:00–22:00"),
])
def test_a_series_in_a_later_week_says_its_dates(occurrences, said):
    """R1-06 : des dates qui se suivent ne se disent par leurs jours seuls que dans les six jours qui viennent ;
    au-delà, avec leurs dates — Mika n'a que ce texte."""
    assert when_text(occurrences, NOW) == said


def test_a_session_of_today_that_has_ended_no_longer_counts():
    morning = day("2026-11-18", "08:00", "09:00")
    assert upcoming([morning], NOW) == []
    assert when_text([morning, day("2026-11-25", "08:00", "09:00")], NOW) == "mer. 25 nov. · 08:00–09:00"
    evening = day("2026-11-18", "20:00", "23:00")
    assert when_text([evening], NOW) == "mer. 18 nov. · 20:00–23:00"
    assert upcoming([day("2026-11-18", "22:00", "02:00")], NOW.replace(hour=23))  # après minuit : pas finie


def test_a_window_starts_the_dates_later():
    market = day("2026-01-01", "08:00", "12:00", "2026-12-31", SUNDAY)
    [(first, _o)] = upcoming([market], NOW, start=date(2026, 11, 25))
    assert first == date(2026, 11, 29)
    assert upcoming([day("2026-12-20")], NOW, end=date(2026, 12, 1)) == []


def test_every_date_is_told_with_its_bounds_in_paris_time():
    dates, more = dates_fr([day("2026-11-21", "19:00", "00:00"),
                            day("2026-12-03", "13:00", "19:00", "2027-01-10", TUE_TO_SUN), day("2026-12-24")], NOW, 2)
    assert more == 1
    assert (dates[0].start, dates[0].end, dates[0].text) == ("2026-11-21T19:00+01:00", "2026-11-22T00:00+01:00",
                                                              "sam. 21 nov. · 19:00–minuit")
    assert dates[1].days == ("mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")
    assert dates[1].end == "2027-01-10T19:00+01:00"
    summer, _ = dates_fr([day("2027-07-14", "22:00", "23:00")], NOW, 5)
    assert summer[0].start == "2027-07-14T22:00+02:00"  # l'heure d'été


def test_an_occurrence_reads_its_weekdays_and_refuses_what_makes_no_sense():
    raw = {"startDate": "2026-01-01", "endDate": "2026-12-31", "startTime": "08:00", "endTime": "12:00",
           "appliesOnDay": [{"key": "Sunday", "label": {"@fr": "Dimanche"}}, {"key": "Funday"}]}
    assert occurrence_of(raw) == day("2026-01-01", "08:00", "12:00", "2026-12-31", SUNDAY)
    assert occurrence_of({"startDate": "2026-11-20"}) == day("2026-11-20")
    assert occurrence_of({"startDate": "2026-11-20", "startTime": "25:00"}) == day("2026-11-20")
    for broken in ({"endDate": "2026-11-20"}, {"startDate": "2026-12-01", "endDate": "2026-11-01"},
                   {"startDate": "2000-01-01", "endDate": "2099-01-01"}, {"startDate": "hier"}, "x"):
        assert occurrence_of(broken) is None


def test_weekdays_that_run_through_sunday_start_after_the_gap():
    assert mask_fr(0b1110001) == "du ven. au lun."
    assert mask_fr(0b0010101) == "lun., mer., ven."
    assert mask_fr(0) == "" and mask_fr(0x7F) == ""

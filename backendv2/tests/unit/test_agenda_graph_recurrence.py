"""La récurrence d'Outlook (ADR 0309, lot 2) : la ``patternedRecurrence`` de Microsoft Graph lue en RRULE
(``adapters/agenda/graph.py::pattern_rule``) et une RRULE écrite en ``patternedRecurrence`` (``rule_pattern``).

- chaque sorte de Graph (chaque jour, semaine, mois à date fixe ou relative, année) et chaque fin (un nombre, une
  date, jamais) devient la RRULE qui donne les mêmes occurrences ;
- une RRULE devient ce qu'Outlook sait : « chaque jour ouvré » en semaine, « le deuxième jeudi » en relatif, un UNTIL
  à l'heure qui exclut le jour même quand l'occurrence de ce jour viendrait après lui ;
- ce qu'Outlook ne sait pas (toutes les heures, plusieurs jours du mois) est refusé en mots ;
- les fuseaux : un nom Windows lu IANA, un nom IANA écrit Windows ; une journée entière que Graph donne en UTC
  retrouve son jour.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from mika.adapters.agenda.graph import (
    iana_zone,
    instant_of,
    nearest_day,
    pattern_rule,
    rule_pattern,
    windows_zone,
)
from mika.ports.agenda import AgendaError, Event, Recurrence, Span, at_us, day_at, occurrences, us_of

PARIS = ZoneInfo("Europe/Paris")


def paris(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> int:
    return us_of(datetime(y, m, d, h, mi, tzinfo=PARIS))


def days(rule: str, start: int, until: int, *, all_day: bool = False) -> list[str]:
    series = Event("c", "u", Span(start, start + 3600 * 1_000_000, "" if all_day else "Europe/Paris", all_day),
                   recurrence=Recurrence(rule))
    zone = ZoneInfo("UTC") if all_day else PARIS
    return [at_us(o.span.start, zone).strftime("%Y-%m-%d %H:%M") for o in occurrences(series, start, until)]


def graph(kind: str, *, end: dict | None = None, **pattern) -> dict:
    return {"pattern": {"type": kind, "interval": 1, **pattern},
            "range": {"startDate": "2026-11-02", "recurrenceTimeZone": "Romance Standard Time",
                      **(end or {"type": "noEnd"})}}


@pytest.mark.parametrize(("recurrence", "rule"), [
    (graph("daily", interval=2, end={"type": "numbered", "numberOfOccurrences": 3}), "FREQ=DAILY;INTERVAL=2;COUNT=3"),
    (graph("weekly", daysOfWeek=["monday", "thursday"], firstDayOfWeek="sunday"), "FREQ=WEEKLY;BYDAY=MO,TH"),
    (graph("weekly", interval=2, daysOfWeek=["friday"], firstDayOfWeek="monday"),
     "FREQ=WEEKLY;INTERVAL=2;BYDAY=FR;WKST=MO"),
    (graph("absoluteMonthly", dayOfMonth=15, end={"type": "endDate", "endDate": "2027-06-30"}),
     "FREQ=MONTHLY;BYMONTHDAY=15;UNTIL=20270630"),
    (graph("relativeMonthly", daysOfWeek=["thursday"], index="second"), "FREQ=MONTHLY;BYDAY=TH;BYSETPOS=2"),
    (graph("relativeMonthly", daysOfWeek=["friday"], index="last"), "FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1"),
    (graph("absoluteYearly", month=11, dayOfMonth=28), "FREQ=YEARLY;BYMONTH=11;BYMONTHDAY=28"),
    (graph("relativeYearly", month=11, daysOfWeek=["thursday"], index="fourth"),
     "FREQ=YEARLY;BYMONTH=11;BYDAY=TH;BYSETPOS=4"),
])
def test_each_graph_pattern_reads_as_its_rrule(recurrence, rule):
    assert pattern_rule(recurrence) == rule


def test_a_fixed_end_date_keeps_its_last_day_and_an_unknown_pattern_reads_as_nothing():
    rule = pattern_rule(graph("weekly", daysOfWeek=["monday"], end={"type": "endDate", "endDate": "2026-11-16"}))
    assert days(rule, paris(2026, 11, 2, 9), paris(2027, 1, 1)) == ["2026-11-02 09:00", "2026-11-09 09:00",
                                                                     "2026-11-16 09:00"]
    assert pattern_rule(graph("hourly")) == "" and pattern_rule(None) == "" and pattern_rule({"pattern": {}}) == ""


def test_a_rrule_becomes_what_outlook_knows():
    start = paris(2026, 11, 3, 18)  # un mardi
    assert rule_pattern("FREQ=WEEKLY;COUNT=10", start, "Europe/Paris", False) == {
        "pattern": {"type": "weekly", "interval": 1, "daysOfWeek": ["tuesday"], "firstDayOfWeek": "monday"},
        "range": {"startDate": "2026-11-03", "recurrenceTimeZone": "Romance Standard Time", "type": "numbered",
                  "numberOfOccurrences": 10}}
    weekdays = rule_pattern("FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR", start, "Europe/Paris", False)["pattern"]
    assert weekdays["type"] == "weekly" and weekdays["daysOfWeek"] == ["monday", "tuesday", "wednesday",
                                                                       "thursday", "friday"]
    assert rule_pattern("FREQ=MONTHLY;BYDAY=2TH", start, "Europe/Paris", False)["pattern"] == {
        "type": "relativeMonthly", "interval": 1, "daysOfWeek": ["thursday"], "index": "second"}
    assert rule_pattern("FREQ=MONTHLY;BYDAY=-1FR;INTERVAL=3", start, "Europe/Paris", False)["pattern"] == {
        "type": "relativeMonthly", "interval": 3, "daysOfWeek": ["friday"], "index": "last"}
    assert rule_pattern("FREQ=MONTHLY", start, "Europe/Paris", False)["pattern"] == {
        "type": "absoluteMonthly", "interval": 1, "dayOfMonth": 3}
    birthday = rule_pattern("FREQ=YEARLY", day_at("2026-11-28"), "", True)
    assert birthday["pattern"] == {"type": "absoluteYearly", "interval": 1, "month": 11, "dayOfMonth": 28}
    assert birthday["range"] == {"startDate": "2026-11-28", "recurrenceTimeZone": "UTC", "type": "noEnd"}


def test_an_until_at_the_hour_excludes_its_own_day_when_that_occurrence_comes_after_it():
    start = paris(2026, 11, 3, 18)
    # « celui-ci et les suivants » coupe une seconde avant l'occurrence du 15 décembre (UTC) : le 14 est le dernier jour
    cut = rule_pattern("FREQ=DAILY;UNTIL=20261215T165959Z", start, "Europe/Paris", False)
    assert cut["range"] == {"startDate": "2026-11-03", "recurrenceTimeZone": "Romance Standard Time",
                            "type": "endDate", "endDate": "2026-12-14"}
    late = rule_pattern("FREQ=DAILY;UNTIL=20261215T200000Z", start, "Europe/Paris", False)
    assert late["range"]["endDate"] == "2026-12-15"
    assert rule_pattern("FREQ=DAILY;UNTIL=20261231", start, "Europe/Paris", False)["range"]["endDate"] == "2026-12-31"


@pytest.mark.parametrize("rule", ["FREQ=HOURLY", "FREQ=MONTHLY;BYMONTHDAY=1,15", "FREQ=WEEKLY;BYHOUR=9",
                                  "FREQ=MONTHLY;BYDAY=5MO", "FREQ=WEEKLY;BYDAY=XX", "INTERVAL=2"])
def test_what_outlook_does_not_know_is_refused_in_words(rule):
    with pytest.raises(AgendaError, match="récurrence"):
        rule_pattern(rule, paris(2026, 11, 3, 18), "Europe/Paris", False)


def test_the_zones_and_the_hours_of_graph():
    assert windows_zone("Europe/Paris") == "Romance Standard Time" and windows_zone("") == "UTC"
    assert windows_zone("UTC") == "UTC" and windows_zone("America/Argentina/Ushuaia") == "America/Argentina/Ushuaia"
    assert iana_zone("Romance Standard Time") == "Europe/Paris" and iana_zone("tzone://Microsoft/Utc") == ""
    assert iana_zone("W. Europe Standard Time") == "Europe/Berlin" and iana_zone("UTC") == ""
    assert instant_of({"dateTime": "2026-11-23T09:00:00.0000000", "timeZone": "UTC"}) == paris(2026, 11, 23, 10)
    assert instant_of({"dateTime": "2026-11-23T10:00:00", "timeZone": "Romance Standard Time"}) == \
        paris(2026, 11, 23, 10)
    assert instant_of("2026-12-07T08:00:00Z") == paris(2026, 12, 7, 9) and instant_of({"x": 1}) is None
    # une journée entière : minuit de son fuseau, lu en UTC la veille au soir (Paris) ou le matin même (New York)
    assert nearest_day(paris(2026, 11, 27)) == day_at("2026-11-27")
    assert nearest_day(us_of(datetime(2026, 11, 27, tzinfo=ZoneInfo("America/New_York")))) == day_at("2026-11-27")

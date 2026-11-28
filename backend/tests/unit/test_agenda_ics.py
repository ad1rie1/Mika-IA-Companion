"""Le format iCalendar de l'agenda (ADR 0309, lot 1), ``adapters/agenda/ics.py`` : une seule lecture et une seule
écriture, partagées par l'abonnement iCal et CalDAV.

- trois fichiers réels : le calendrier des jours fériés de Google (209 journées entières, « disponible ») ; un export
  au format de Google (VTIMEZONE, une série hebdomadaire qui passe l'heure d'été, une EXDATE, une occurrence déplacée,
  une annulée, des invités et leurs réponses, l'organisateur, le compte parmi les invités en attente de sa réponse,
  un lien Meet et un lien Teams, les rappels, une invitation privée, des vacances sur plusieurs jours, un
  anniversaire annuel, un concert annulé) ; un export d'Outlook (le nom Windows d'un fuseau, un VTIMEZONE à un nom
  inventé, la nuit du passage à l'heure d'été, une heure flottante) ;
- un VTIMEZONE propre au fichier se lit par ses règles à lui, jamais par celles d'un autre fichier au même TZID ;
- ce qui n'est pas un agenda se dit en mots ; un VEVENT illisible est sauté, le reste se lit ;
- écrire un événement puis le relire rend ce que les écrans montrent ; une occurrence devient une exception écrite
  comme le DTSTART de sa série ; une EXDATE aussi ; une série se coupe en deux (la suite sous un nouvel UID, avec ses
  EXDATE) ; une réponse pose le PARTSTAT de la ligne du compte ; ce qu'on n'y touche pas (une propriété inconnue)
  reste.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from mika.adapters.agenda import ics
from mika.ports.agenda import (
    CANCELLED,
    DATES_MAX,
    EMAIL,
    MAYBE,
    NEEDS,
    US_PER_S,
    YES,
    AgendaError,
    Alert,
    EventChange,
    EventDraft,
    Participant,
    Span,
    at_us,
    day_at,
    expand,
    occurrence_key,
    split_rule,
    us_of,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "agenda"
PARIS = ZoneInfo("Europe/Paris")
HOUR = 3600 * US_PER_S
NOW = us_of(datetime(2026, 11, 23, 15, tzinfo=PARIS))
ME = "adrien.martin@example.fr"


def paris(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> int:
    return us_of(datetime(y, m, d, h, mi, tzinfo=PARIS))


def read(name: str, **kw):
    return ics.read((FIXTURES / name).read_bytes(), calendar="compte~abonnement", **kw)


def local(us: int) -> str:
    return at_us(us, PARIS).strftime("%Y-%m-%d %H:%M")


def test_the_real_french_holidays_calendar_reads_as_whole_free_days():
    feed = read("feries-france-google.ics")
    assert feed.name == "Jours fériés et autres fêtes en France" and feed.skipped == 0
    assert len(feed.events) == 209
    assert all(e.span.all_day and not e.busy and e.span.end - e.span.start == 24 * HOUR for e in feed.events)
    days = expand(list(feed.events), paris(2026, 7, 1), paris(2026, 8, 31))
    assert [(o.span.first_day, o.event.title) for o in days] == [("2026-07-14", "La fête nationale"),
                                                                ("2026-08-15", "L'Assomption")]


def test_a_google_export_reads_its_series_exceptions_and_summer_time():
    feed = read("export-google.ics", mine={ME})
    assert feed.zone == "Europe/Paris" and feed.skipped == 0
    weekly = [e for e in feed.events if e.title.startswith("Point d'équipe")]
    master = next(e for e in weekly if not e.original)
    assert master.recurrence.rule.startswith("FREQ=WEEKLY") and master.span.zone == "Europe/Paris"
    assert master.recurrence.exdates == ("20260406T080000Z",)
    assert master.location == "Salle Lumière" and master.reminders == (Alert(10),) and master.sequence == 2
    assert master.conference == "https://meet.google.com/abc-defg-hij"
    assert master.organizer.address == ME and master.organizer.me and master.response == ""
    assert [(p.address, p.response, p.optional) for p in master.participants[1:]] == [
        ("lea.dubois@example.org", YES, False), ("karim@example.org", MAYBE, True)]
    shown = expand(weekly, paris(2026, 3, 20), paris(2026, 5, 12))
    # 10 h à Paris avant comme après le passage à l'heure d'été (le 29 mars) ; le 6 avril retiré ; le 13 déplacé
    # l'après-midi ; le 4 mai annulé
    assert [(local(o.span.start), o.event.title) for o in shown] == [
        ("2026-03-23 10:00", "Point d'équipe"), ("2026-03-30 10:00", "Point d'équipe"),
        ("2026-04-13 14:00", "Point d'équipe (décalé)"), ("2026-04-20 10:00", "Point d'équipe"),
        ("2026-04-27 10:00", "Point d'équipe"), ("2026-05-11 10:00", "Point d'équipe")]
    assert at_us(shown[0].span.start).hour == 9 and at_us(shown[1].span.start).hour == 8  # UTC, l'heure d'été


def test_an_invitation_says_who_answered_and_where_the_meeting_is():
    feed = read("export-google.ics", mine={ME})
    invite = next(e for e in feed.events if e.title == "Devis — point d'étape")
    assert invite.response == NEEDS and invite.private and invite.busy
    assert invite.organizer.name == "Sophie Laurent" and not invite.organizer.me
    assert [(p.address, p.me) for p in invite.participants] == [(ME, True), ("sophie.laurent@example.com", False)]
    assert invite.conference.startswith("https://teams.microsoft.com/l/meetup-join/")
    assert invite.reminders == (Alert(15), Alert(1440, EMAIL))  # une notification, un e-mail
    assert "On fait le point sur le devis." in invite.description


def test_whole_days_cancelled_events_and_yearly_series_read_as_the_screens_show_them():
    feed = read("export-google.ics", mine={ME})
    holiday = next(e for e in feed.events if e.title == "Vacances")
    assert holiday.span.all_day and (holiday.span.first_day, holiday.span.last_day) == ("2026-08-10", "2026-08-14")
    assert not holiday.busy and holiday.location == "Annecy"
    concert = next(e for e in feed.events if e.title.startswith("Concert"))
    assert concert.status == CANCELLED
    assert not expand([concert], paris(2026, 12, 1), paris(2026, 12, 2))
    birthday = next(e for e in feed.events if e.title == "Anniversaire de Léa")
    assert [o.span.first_day for o in expand([birthday], paris(2026, 1, 1), paris(2028, 12, 31))] == [
        "2026-03-15", "2027-03-15", "2028-03-15"]


def test_outlook_windows_zones_and_its_own_vtimezone_read_as_iana_zones():
    feed = read("outlook-heure-ete-paris.ics")
    coffee = next(e for e in feed.events if e.title == "Café du matin")
    assert coffee.span.zone == "Europe/Paris"  # « Romance Standard Time »
    days = expand([coffee], paris(2026, 3, 27), paris(2026, 3, 31))
    assert [local(o.span.start) for o in days] == ["2026-03-27 08:30", "2026-03-28 08:30", "2026-03-29 08:30",
                                                   "2026-03-30 08:30"]
    guitar = next(e for e in feed.events if e.title == "Cours de guitare")
    # « (UTC+01:00) Brussels, Copenhagen, Madrid, Paris » : un fuseau IANA aux mêmes règles, que la série suit
    assert guitar.span.zone in ("Europe/Brussels", "Europe/Copenhagen", "Europe/Madrid", "Europe/Paris")
    assert [local(o.span.start) for o in expand([guitar], paris(2026, 10, 1), paris(2026, 11, 30))] == [
        "2026-10-19 18:00", "2026-10-26 18:00", "2026-11-02 18:00"]
    night = next(e for e in feed.events if e.title == "Garde de nuit")
    assert local(night.span.start) == "2026-03-29 01:30" and night.span.end - night.span.start == HOUR
    assert not night.busy  # X-MICROSOFT-CDO-BUSYSTATUS:FREE


def test_a_floating_hour_reads_in_the_calendars_zone():
    data = (FIXTURES / "outlook-heure-ete-paris.ics").read_bytes()
    feed = ics.read(data, calendar="c~a", zone="Europe/Paris")
    floating = next(e for e in feed.events if e.title == "Heure flottante")
    assert local(floating.span.start) == "2026-03-27 20:00" and floating.span.zone == "Europe/Paris"


def _custom(offset: str, dst: str) -> str:
    return (f"BEGIN:VTIMEZONE\nTZID:Bureau\nBEGIN:STANDARD\nDTSTART:16010101T030000\nTZOFFSETFROM:{dst}\n"
            f"TZOFFSETTO:{offset}\nRRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=10\nEND:STANDARD\nBEGIN:DAYLIGHT\n"
            f"DTSTART:16010101T020000\nTZOFFSETFROM:{offset}\nTZOFFSETTO:{dst}\n"
            "RRULE:FREQ=YEARLY;BYDAY=-1SU;BYMONTH=3\nEND:DAYLIGHT\nEND:VTIMEZONE\n")


def test_a_vtimezone_of_its_own_never_reads_by_another_files_rules():
    event = "BEGIN:VEVENT\nUID:u\nDTSTART;TZID=Bureau:20261123T100000\nDTEND;TZID=Bureau:20261123T110000\nSUMMARY:x\nEND:VEVENT\n"
    paris_like = ics.read(f"BEGIN:VCALENDAR\nVERSION:2.0\n{_custom('+0100', '+0200')}{event}END:VCALENDAR\n",
                          calendar="c~a")
    lisbon_like = ics.read(f"BEGIN:VCALENDAR\nVERSION:2.0\n{_custom('+0000', '+0100')}{event}END:VCALENDAR\n",
                           calendar="c~a")
    assert at_us(paris_like.events[0].span.start).hour == 9
    assert at_us(lisbon_like.events[0].span.start).hour == 10


def test_what_is_not_a_calendar_is_said_in_words_and_a_broken_event_is_skipped():
    with pytest.raises(AgendaError, match="pas un agenda iCalendar"):
        ics.read(b"<!doctype html><html><body>Connexion</body></html>", calendar="c~a")
    feed = ics.read("BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:bad\nDTSTART:2026XX23\nSUMMARY:cassé\nEND:VEVENT\n"
                    "BEGIN:VEVENT\nUID:ok\nDTSTART:20261123T100000Z\nSUMMARY:bon\nEND:VEVENT\nEND:VCALENDAR\n",
                    calendar="c~a")
    assert [e.title for e in feed.events] == ["bon"] and feed.skipped == 1


def test_rdates_and_exdates_in_bulk_are_read_up_to_a_bound():
    many = ",".join(occurrence_key(paris(2026, 1, 1) + i * HOUR, False) for i in range(DATES_MAX * 3))
    feed = ics.read("BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:masse\nDTSTART:20260101T090000Z\n"
                    f"RRULE:FREQ=DAILY\nRDATE:{many}\nEXDATE:{many}\nSUMMARY:masse\nEND:VEVENT\nEND:VCALENDAR\n",
                    calendar="c~a")
    rec = feed.events[0].recurrence
    assert len(rec.rdates) == DATES_MAX and len(rec.exdates) == DATES_MAX


def test_a_drafted_event_writes_and_reads_back_what_the_screens_show():
    draft = EventDraft("Réunion, budget ; T4", Span(paris(2026, 12, 3, 14), paris(2026, 12, 3, 15), "Europe/Paris"),
                       location="Salle 2", description="Ordre du jour :\n- budget", conference="https://meet.jit.si/x",
                       rule="FREQ=WEEKLY;COUNT=4", participants=(Participant("lea@example.org", "Léa"),
                                                                 Participant("karim@example.org", optional=True)),
                       busy=False, private=True, reminders=(Alert(30), Alert(10, EMAIL)))
    vevent = ics.draft_vevent(draft, uid="u1@mika", now=NOW, organizer=Participant("adrien@example.org", "Adrien"))
    data = ics.to_bytes(ics.new_resource([vevent]))
    assert b"BEGIN:VTIMEZONE" in data and b"TZID=Europe/Paris" in data
    back = ics.read(data, calendar="c~a", mine={"adrien@example.org"}).events[0]
    assert (back.title, back.location, back.description, back.conference) == (
        draft.title, "Salle 2", "Ordre du jour :\n- budget", "https://meet.jit.si/x")
    assert (back.span.start, back.span.end, back.span.zone) == (draft.span.start, draft.span.end, "Europe/Paris")
    assert back.recurrence.rule == "FREQ=WEEKLY;COUNT=4" and not back.busy and back.private
    assert b"ACTION:EMAIL" in data and b"ACTION:DISPLAY" in data
    assert back.reminders == (Alert(10, EMAIL), Alert(30)) and back.organizer.me and back.organizer.address == "adrien@example.org"
    assert [(p.address, p.response, p.optional) for p in back.participants] == [
        ("lea@example.org", NEEDS, False), ("karim@example.org", NEEDS, True)]
    day = ics.draft_vevent(EventDraft("Congés", Span(day_at("2026-12-24"), day_at("2026-12-27"), all_day=True)),
                           uid="u2@mika", now=NOW)
    whole = ics.read(ics.to_bytes(ics.new_resource([day])), calendar="c~a").events[0]
    assert whole.span.all_day and (whole.span.first_day, whole.span.last_day) == ("2026-12-24", "2026-12-26")


def test_an_invitee_without_address_is_refused_in_words():
    with pytest.raises(AgendaError, match="sans adresse"):
        ics.draft_vevent(EventDraft("x", Span(NOW, NOW + HOUR), participants=(Participant(name="Léa"),)),
                         uid="u", now=NOW)


def _google_series() -> ics.Resource:
    data = (FIXTURES / "export-google.ics").read_bytes().decode()
    head, _sep, rest = data.partition("BEGIN:VEVENT")
    series = "BEGIN:VEVENT" + rest.split("BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20260810")[0]
    return ics.Resource(head + series + "END:VCALENDAR\r\n")


def test_an_occurrence_becomes_an_exception_written_like_its_series_start():
    res = _google_series()
    key = occurrence_key(paris(2026, 4, 20, 10), False)
    one = res.instance(key)
    ics.apply_change(one, EventChange(title="Point d'équipe (visio)"), now=NOW)
    text = res.to_bytes().decode()
    assert "RECURRENCE-ID;TZID=Europe/Paris:20260420T100000" in text
    rows = res.events(calendar="c~a", mine={ME})
    shown = expand(rows, paris(2026, 4, 19), paris(2026, 4, 21))
    assert [(local(o.span.start), o.event.title) for o in shown] == [("2026-04-20 10:00", "Point d'équipe (visio)")]
    res.exclude(occurrence_key(paris(2026, 4, 27, 10), False))
    assert "EXDATE;TZID=Europe/Paris:20260427T100000" in res.to_bytes().decode()
    assert not expand(res.events(calendar="c~a"), paris(2026, 4, 26), paris(2026, 4, 28))


def test_a_series_splits_at_an_occurrence_with_its_later_exceptions():
    res = _google_series()
    master = res.event(res.master(), calendar="c~a")
    key = occurrence_key(paris(2026, 5, 4, 10), False)
    before, after = split_rule(master, key)
    tail = res.split(key, after, "suite@mika")
    moved = res.truncate(key, before)
    tail.adopt(moved, "suite@mika")
    old = res.events(calendar="c~a")
    new = tail.events(calendar="c~a")
    assert {e.original for e in old if e.original} == {"20260413T080000Z"}  # le 13 avril reste à la série d'avant
    assert {e.uid for e in new} == {"suite@mika"} and {e.original for e in new if e.original} == {"20260504T080000Z"}
    last_old = expand(old, paris(2026, 3, 1), paris(2026, 12, 31))[-1]
    first_new = expand(new, paris(2026, 3, 1), paris(2026, 12, 31))[0]
    assert local(last_old.span.start) == "2026-04-27 10:00" and local(first_new.span.start) == "2026-05-11 10:00"


def test_an_answer_sets_the_accounts_partstat_and_keeps_what_it_does_not_touch():
    data = (FIXTURES / "export-google.ics").read_bytes().decode().replace(
        "SUMMARY:Devis — point d'étape", "SUMMARY:Devis — point d'étape\r\nX-INCONNU;P=1:garde-moi")
    res = ics.Resource(data)
    invite = next(v for v in res.vevents if str(v.get("SUMMARY")) == "Devis — point d'étape")
    res.answer(invite, YES, {ME}, comment="Avec plaisir", now=NOW)
    text = res.to_bytes().decode()
    assert "X-INCONNU;P=1:garde-moi" in text and "COMMENT:Avec plaisir" in text
    back = next(e for e in ics.read(text, calendar="c~a", mine={ME}).events if e.title.startswith("Devis"))
    assert back.response == YES
    with pytest.raises(AgendaError, match="pas parmi les invités"):
        res.answer(invite, YES, {"quelquun@example.org"}, now=NOW)

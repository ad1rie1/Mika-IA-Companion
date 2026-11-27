"""L'API par personne, l'agenda (ADR 0309, lot 4) : à travers le vrai serveur composé. Une personne ne voit que ses
agendas et ceux qu'on lui partage, à leur niveau ; un événement d'une autre n'existe pas ; un privé d'une autre se lit
« Occupé ». Ce qu'elle écrit passe par les actions du plugin, en son nom ; ce que Mika propose se décide là ; ses
comptes se branchent (Google, Microsoft, CalDAV contre leurs faux serveurs) ; le direct pousse ce qui change à qui le
voit, et à personne d'autre."""

from __future__ import annotations

import asyncio
import dataclasses
import html
import json
import re
import time
from datetime import date, datetime, timedelta

import pytest

from mika.adapters.agenda import (
    CalDavProvider,
    GoogleProvider,
    GoogleSignIn,
    MicrosoftProvider,
    Web,
    microsoft_signin,
)
from mika.app.domains.agenda.live import signed
from mika.app.domains.agenda.settings import AgendaSettings
from mika.app.domains.mail.settings import MailSettings
from mika.contracts import runtime as rt
from mika.kernel.events import Content
from mika.plugins.agenda import CAPABILITY, DONE, OWNER, SYNC_ASKED, AgendaParams
from mika.plugins.agenda.sync import sync_account
from mika.ports.agenda import Calendar, EventDraft, Participant, Span, calendar_key, us_of
from mika.ports.signin import SIGNED_IN
from tests.contract.test_agenda_caldav import INVITE
from tests.fixtures.caldav_server import FakeCalDav
from tests.fixtures.google_calendar import FakeGoogle
from tests.fixtures.graph_calendar import FakeGraph
from tests.protocol.test_moi_changes import SETTLED_S, changes, lea_session, received
from tests.protocol.test_moi_mail import API, append, journal, login, post, second_person
from tests.protocol.test_web import WS, bootstrap, csrf, world  # noqa: F401 — fixture partagée

HOUR_US = 3600 * 1_000_000


def tomorrow() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


def mine(client) -> str:
    """La clé de son « Mon agenda » (né à la première lecture)."""
    got = client.get(API + "/agenda/calendars").json()["calendars"]
    return next(c["key"] for c in got if c["primary"] and c["level"] == "proprietaire")


def create(client, calendar: str, title: str, hour: int = 10, **more) -> object:
    return post(client, "/agenda/event/create", {"calendar": calendar, "title": title,
                                                 "start": f"{tomorrow()}T{hour:02d}:00",
                                                 "end": f"{tomorrow()}T{hour + 1:02d}:00", **more})


def period(client, **more) -> dict:
    q = "&".join(f"{k}={v}" for k, v in {"start": tomorrow(), "end": tomorrow(), **more}.items())
    return client.get(API + "/agenda/period?" + q).json()


def share(client, calendar: str, person: str, level: str) -> object:
    return post(client, "/shares/set", {"kind": "agenda", "key": calendar, "person": person, "level": level})


# ── lire, écrire ──


def test_her_calendars_a_period_an_event_and_a_search(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    got = client.get(API + "/agenda/calendars").json()
    keys = [c["key"] for c in got["calendars"]]
    assert keys[-1] == "mika" and got["calendars"][-1]["kind"] == "mika"  # l'agenda de Mika, en lecture seule
    cal = mine(client)
    assert cal == "moi:user_1~mon-agenda"
    made = create(client, cal, "Dentiste", location="12 rue de Béthune", remind="60")
    assert made.status_code == 200, made.text
    assert made.json()["made"]["calendar"] == cal and made.json()["made"]["event"] > 0
    shown = period(client)
    [item] = shown["items"]
    assert item["title"] == "Dentiste" and item["location"] == "12 rue de Béthune" and item["remind"] == "60"
    assert item["can"] == {"edit": True, "delete": True, "respond": False, "duplicate": True, "remind": True}
    assert item["added"] is None and not item["masked"]
    one = client.get(API + f"/agenda/event?event={item['event']}").json()
    assert one["title"] == "Dentiste" and one["proposals"] == [] and one["prepared"] is None
    assert client.get(API + "/agenda/search?q=dentis").json()["items"][0]["event"] == item["event"]
    assert client.get(API + "/agenda/search?q=x").status_code == 400
    assert client.get(API + "/agenda/event?event=999999").status_code == 404
    assert client.get(API + "/agenda/period?calendars=lea~ailleurs").status_code == 404
    assert "agenda" in client.get(API).json()["counts"]


def test_editing_deleting_duplicating_and_her_reminder(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    cal = mine(client)
    event = create(client, cal, "Coiffeur").json()["made"]["event"]
    assert post(client, "/agenda/event/edit", {"event": event, "title": "Coiffeur · Paul",
                                               "start": f"{tomorrow()}T15:00"}).status_code == 200
    [item] = period(client)["items"]
    assert item["title"] == "Coiffeur · Paul" and item["end"] - item["start"] == 3600 * 1000
    copy = post(client, "/agenda/event/duplicate", {"event": event})
    assert copy.status_code == 200 and len(period(client)["items"]) == 2
    assert any(x["title"] == "Coiffeur · Paul (copie)" for x in period(client)["items"])
    assert post(client, "/agenda/event/remind", {"event": event, "value": "veille"}).status_code == 200
    assert post(client, "/agenda/event/remind", {"event": event, "value": "jamais"}).status_code == 400
    assert post(client, "/agenda/event/delete", {"event": event}).status_code == 200
    assert [x["title"] for x in period(client)["items"]] == ["Coiffeur · Paul (copie)"]
    audited = {e.data.action for e in journal(live, rt.OPERATED)}
    assert {"moi.agenda.creer", "moi.agenda.modifier", "moi.agenda.dupliquer", "moi.agenda.rappel",
            "moi.agenda.supprimer"} <= audited


def test_a_form_that_does_not_read_is_refused_by_field(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    cal = mine(client)
    bad = post(client, "/agenda/event/create", {"calendar": cal, "title": "X", "start": "demain"})
    assert bad.status_code == 400 and "start" in bad.json()["fields"]
    late = post(client, "/agenda/event/create", {"calendar": cal, "title": "X", "start": f"{tomorrow()}T10:00",
                                                 "end": f"{tomorrow()}T09:00"})
    assert late.status_code == 400 and "end" in late.json()["fields"]
    rule = post(client, "/agenda/event/create", {"calendar": cal, "title": "X", "start": f"{tomorrow()}T10:00",
                                                 "rule": "FREQ=SECONDLY"})
    assert rule.status_code == 400 and "rule" in rule.json()["fields"]
    weekly = post(client, "/agenda/event/create", {"calendar": cal, "title": "Escalade",
                                                   "start": f"{tomorrow()}T19:00", "rule": "FREQ=WEEKLY;COUNT=3"})
    assert weekly.status_code == 200, weekly.text
    item = period(client)["items"][0]
    assert item["recurring"] and item["rule"] == "FREQ=WEEKLY;COUNT=3" and item["occurrence"]


def test_an_occurrence_key_that_does_not_read_or_no_longer_exists_is_refused_in_words(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    cal = mine(client)
    made = post(client, "/agenda/event/create", {"calendar": cal, "title": "Point", "start": f"{tomorrow()}T09:00",
                                                 "rule": "FREQ=DAILY;COUNT=3"})
    event = made.json()["made"]["event"]
    first = period(client)["items"][0]["occurrence"]
    assert client.get(API + f"/agenda/event?event={event}&occurrence=abc").status_code == 400
    for path, body in (("/agenda/event/edit", {"title": "X"}), ("/agenda/event/delete", {}),
                       ("/agenda/event/duplicate", {})):
        bad = post(client, path, {"event": event, "occurrence": "abc", "scope": "un", **body})
        assert bad.status_code == 400 and "occurrence" in bad.json()["fields"], (path, bad.text)
    moved = post(client, "/agenda/event/edit", {"event": event, "occurrence": first, "scope": "tous",
                                                "start": f"{tomorrow()}T10:00"})
    assert moved.status_code == 200, moved.text
    stale = post(client, "/agenda/event/edit", {"event": event, "occurrence": first, "scope": "un", "title": "9 h"})
    assert stale.status_code == 409 and "n'existe plus" in stale.json()["error"]
    assert all(x["title"] == "Point" for x in period(client)["items"])  # aucun rendez-vous fabriqué à 9 h


def test_the_fiche_of_a_series_opened_without_occurrence_designates_its_first(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    cal = mine(client)
    made = post(client, "/agenda/event/create", {"calendar": cal, "title": "Escalade", "start": f"{tomorrow()}T19:00",
                                                 "rule": "FREQ=WEEKLY;COUNT=3"})
    event = made.json()["made"]["event"]  # la fiche qu'un client ouvre après la création : sans occurrence
    first = period(client)["items"][0]["occurrence"]
    one = client.get(API + f"/agenda/event?event={event}").json()
    assert one["recurring"] and one["occurrence"] == first  # supprimer depuis elle demande donc la portée
    plain = create(client, cal, "Dentiste", hour=8).json()["made"]["event"]
    assert client.get(API + f"/agenda/event?event={plain}").json()["occurrence"] == ""


def test_a_period_reads_the_whole_days_of_its_own_days_only(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    cal = mine(client)
    day_after = (date.today() + timedelta(days=2)).isoformat()
    for title, day in (("Grève", tomorrow()), ("Congé", day_after)):
        made = post(client, "/agenda/event/create", {"calendar": cal, "title": title, "start": day, "end": day,
                                                     "all_day": True})
        assert made.status_code == 200, made.text
    assert [x["title"] for x in period(client)["items"]] == ["Grève"]  # demain seul : pas le congé d'après-demain
    assert [x["title"] for x in period(client, start=day_after, end=day_after)["items"]] == ["Congé"]


def test_a_creation_replayed_with_the_same_key_does_not_double(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    cal = mine(client)
    body = {"calendar": cal, "title": "Une fois", "start": f"{tomorrow()}T08:00", "nonce": "clic-1"}
    first, again = post(client, "/agenda/event/create", body), post(client, "/agenda/event/create", body)
    assert first.status_code == again.status_code == 200 and again.json()["deduped"] is True
    assert len(period(client)["items"]) == 1


# ── une autre personne, et ce qu'on lui partage ──


def test_another_persons_agenda_does_not_exist_until_shared_at_its_level(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    cal = mine(client)
    public = create(client, cal, "Atelier").json()["made"]["event"]
    secret = create(client, cal, "Médecin", hour=14, private=True).json()["made"]["event"]
    login(client, "lea")
    assert all(c["key"] != cal for c in client.get(API + "/agenda/calendars").json()["calendars"])
    assert client.get(API + f"/agenda/event?event={public}").status_code == 404
    assert post(client, "/agenda/event/delete", {"event": public}).status_code == 404
    login(client, "adrien")
    assert share(client, cal, lea, "lire").status_code == 200
    login(client, "lea")
    shared = next(c for c in client.get(API + "/agenda/calendars").json()["calendars"] if c["key"] == cal)
    assert shared["level"] == "lire" and shared["group"] == "shared" and not shared["writable"]
    assert "shares" not in shared and "error" not in shared  # ce qui reste au propriétaire
    items = {x["event"]: x for x in period(client, calendars=cal)["items"]}
    assert items[public]["title"] == "Atelier"
    assert items[secret]["masked"] and items[secret]["title"] == "" and items[secret]["location"] == ""
    assert create(client, cal, "Chez Léa").status_code == 403
    assert client.get(API + "/shares").json()["received"] == [
        {"kind": "agenda", "key": cal, "title": "Mon agenda", "level": "lire", "owner_name": "adrien"}]
    assert share(client, cal, "user_1", "lire").status_code in (400, 403)  # un partage reçu ne se repartage pas
    login(client, "adrien")
    assert share(client, cal, lea, "servir").status_code == 200
    login(client, "lea")
    assert create(client, cal, "Chez Léa", hour=16).status_code == 200
    assert post(client, "/agenda/event/delete", {"event": secret}).status_code == 409  # un privé d'une autre
    assert post(client, "/agenda/event/remind", {"event": public, "value": "15"}).status_code == 403
    login(client, "adrien")
    assert share(client, cal, lea, "").status_code == 200
    login(client, "lea")
    assert client.get(API + f"/agenda/event?event={public}").status_code == 404


def test_her_reminder_is_the_owners_and_is_refused_to_a_share_before_anything_is_written(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    cal = mine(client)
    event = create(client, cal, "Atelier").json()["made"]["event"]
    assert share(client, cal, lea, "servir").status_code == 200
    login(client, "lea")
    made = create(client, cal, "Chez Léa", hour=16, remind="15")
    assert made.status_code == 400 and "remind" in made.json()["fields"], made.text
    assert [x["title"] for x in period(client, calendars=cal)["items"]] == ["Atelier"]  # rien n'a été écrit
    edited = post(client, "/agenda/event/edit", {"event": event, "title": "Atelier · Léa", "remind": "15"})
    assert edited.status_code == 400 and "remind" in edited.json()["fields"], edited.text
    [item] = period(client, calendars=cal)["items"]
    assert item["title"] == "Atelier" and item["remind"] == ""  # le titre n'est pas parti chez le fournisseur
    assert create(client, cal, "Chez Léa", hour=16).status_code == 200  # sans rappel, elle y écrit


def test_a_private_invitation_is_answered_by_its_owner_alone_as_it_is_deleted(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    cal = mine(client)
    event = create(client, cal, "Psy", hour=9, private=True).json()["made"]["event"]
    store = live.kernel.ports["agenda"]
    row = store.event(event)
    client.portal.call(lambda: store.save([dataclasses.replace(
        row, response="attente", organizer=Participant(address="cabinet@roux.example", name="Roux"))]))
    assert share(client, cal, lea, "servir").status_code == 200
    login(client, "lea")
    [item] = period(client, calendars=cal)["items"]
    assert item["masked"] and not item["can"]["respond"] and "privé" in item["respond_why"]
    deleted = post(client, "/agenda/event/delete", {"event": event})
    answered = post(client, "/agenda/event/respond", {"event": event, "answer": "non"})
    assert deleted.status_code == answered.status_code == 409
    assert answered.json()["error"] == deleted.json()["error"]
    assert store.event(event).response == "attente"


def test_only_the_owner_reads_and_sets_the_rights_table(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    cal = mine(client)
    table = client.get(API + f"/agenda/rights?calendar={cal}").json()
    assert table["set"] is False and table["lines"][0]["words"]["read"] == "oui"
    lines = [{**{k: v for k, v in x.items() if k != "words"}, "write": "seule"} if i == 0 else x
             for i, x in enumerate(table["lines"])]
    assert post(client, "/agenda/rights/save", {"calendar": cal, "lines": lines,
                                                "default": table["default"]}).status_code == 200
    again = client.get(API + f"/agenda/rights?calendar={cal}").json()
    assert again["set"] and again["lines"][0]["write"] == "seule"
    assert post(client, "/agenda/rights/save", {"calendar": cal, "reset": True}).status_code == 200
    assert share(client, cal, lea, "lire").status_code == 200
    login(client, "lea")
    assert client.get(API + f"/agenda/rights?calendar={cal}").status_code == 403


def test_her_settings_a_new_calendar_and_its_color(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    made = post(client, "/agenda/calendar/new", {"name": "Sport"})
    assert made.status_code == 200, made.text
    key = made.json()["made"]["calendar"]
    assert post(client, "/agenda/calendar/save", {"calendar": key, "color": "vert", "reminder": "15"}).status_code \
        == 200
    got = next(c for c in client.get(API + "/agenda/calendars").json()["calendars"] if c["key"] == key)
    assert got["color"] == "vert" and got["reminder"] == "15" and got["reminder_set"] == "15"
    assert post(client, "/agenda/calendar/save", {"calendar": key, "color": "rose"}).status_code == 400
    assert post(client, "/agenda/calendar/save", {"calendar": key, "hidden": True}).status_code == 200
    assert key not in [x["calendar"] for x in period(client)["items"]]
    accounts = client.get(API + "/agenda/accounts").json()
    assert accounts["accounts"][0]["system"] and accounts["accounts"][0]["label"] == "Ce serveur"
    assert {c["key"] for c in accounts["accounts"][0]["calendars"]} >= {key, mine(client)}


def test_renaming_a_calendar_of_the_system_for_good_and_a_branched_one_in_mika(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    cal = mine(client)
    assert post(client, "/agenda/calendar/save", {"calendar": cal, "name": "Ma vie"}).status_code == 200
    got = next(c for c in client.get(API + "/agenda/calendars").json()["calendars"] if c["key"] == cal)
    assert got["name"] == "Ma vie" and got["provider_name"] == "" and got["can"]["rename"]
    empty = post(client, "/agenda/calendar/save", {"calendar": cal, "name": " "})
    assert empty.status_code == 400 and "name" in empty.json()["fields"]  # un agenda du système a un nom
    account = post(client, "/agenda/account/save", {"kind": "ical", "values": {
        "label": "Fériés", "url": "https://calendrier.example.org/feries.ics"}}).json()["account"]
    store = live.kernel.ports["agenda"]
    listed = [Calendar(calendar_key(account, "feries"), account, "https://calendrier.example.org/feries.ics",
                       "Jours fériés en France", writable=False, primary=True)]
    store.keep_calendars(account, listed)
    key = listed[0].key
    both = post(client, "/agenda/calendar/save", {"calendar": key, "name": "Fériés", "color": "ardoise"})
    assert both.status_code == 200, both.text
    store.keep_calendars(account, listed)  # une synchronisation redit le nom du fournisseur : le sien reste
    got = next(c for c in client.get(API + "/agenda/calendars").json()["calendars"] if c["key"] == key)
    assert (got["name"], got["provider_name"], got["color"]) == ("Fériés", "Jours fériés en France", "ardoise")
    assert store.calendar(key).name == "Fériés"  # ce que ses outils et la console lisent aussi
    assert post(client, "/agenda/calendar/save", {"calendar": key, "name": ""}).status_code == 200
    got = next(c for c in client.get(API + "/agenda/calendars").json()["calendars"] if c["key"] == key)
    assert got["name"] == "Jours fériés en France" and got["provider_name"] == ""
    assert "moi.agenda.renommer" in {e.data.action for e in journal(live, rt.OPERATED)}


def _google(client, live) -> tuple[FakeGoogle, str]:
    """Un compte Google connecté par l'adresse collée, puis synchronisé."""
    google = FakeGoogle()
    providers = live.kernel.ports["agenda_providers"]
    client.portal.call(lambda: live.settings.of(AgendaSettings).save_google_application(google.client_id, google.secret))
    signin = GoogleSignIn(live.settings.of(AgendaSettings), live.settings.of(AgendaSettings).google_application, transport=google.transport())
    provider = GoogleProvider(signin, transport=google.transport())
    providers.add(provider)
    account = post(client, "/agenda/account/save", {"kind": "google", "values": {"label": "Perso"}}).json()["account"]
    started = post(client, "/agenda/account/google/start", {"account": account}).json()
    assert post(client, "/agenda/account/google/finish", {"account": account,
                                                          "text": google.consent(started["url"])}).status_code == 200

    async def sync() -> None:  # dans la boucle du serveur, où ses réglages se lisent
        await sync_account(live.kernel.ports["agenda"], provider, providers.connection(account), AgendaParams(),
                           live.kernel.deps.clock.now())

    client.portal.call(sync)
    return google, account


def test_the_providers_reminders_go_with_the_event_and_the_system_has_none(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    google, _account = _google(client, live)
    cals = client.get(API + "/agenda/calendars").json()["calendars"]
    perso = next(c for c in cals if c["kind"] == "google" and c["name"] == "Perso")
    assert perso["provider_reminders"] == {"max": 5, "email": True,
                                           "defaults": [{"method": "notification", "minutes": 30}]}
    system = next(c for c in cals if c["key"] == mine(client))
    assert system["provider_reminders"]["max"] == 0
    alerts = [{"method": "email", "minutes": 1440}, {"method": "notification", "minutes": 10}]
    made = create(client, perso["key"], "Rando", reminders=alerts)
    assert made.status_code == 200, made.text
    sent = google.seen("POST", "/events")[-1].body
    assert sent["reminders"] == {"useDefault": False, "overrides": [{"method": "popup", "minutes": 10},
                                                                     {"method": "email", "minutes": 1440}]}
    plain = create(client, perso["key"], "Ciné", hour=20)
    assert google.seen("POST", "/events")[-1].body["reminders"] == {"useDefault": True}
    items = {x["title"]: x for x in period(client, calendars=perso["key"])["items"]}
    assert items["Rando"]["reminders"] == [{"method": "notification", "minutes": 10},
                                           {"method": "email", "minutes": 1440}]
    assert not items["Rando"]["reminders_default"]
    assert items["Ciné"]["reminders_default"] and items["Ciné"]["reminders"] == perso["provider_reminders"]["defaults"]
    edit = post(client, "/agenda/event/edit", {"event": plain.json()["made"]["event"], "reminders": []})
    assert edit.status_code == 200, edit.text
    assert google.seen("PATCH")[-1].body["reminders"] == {"useDefault": False, "overrides": []}
    bad = create(client, perso["key"], "X", reminders=[{"method": "pigeon", "minutes": 10}])
    assert bad.status_code == 400 and "reminders" in bad.json()["fields"]
    refused = create(client, mine(client), "Dentiste", reminders=[{"method": "notification", "minutes": 10}])
    assert refused.status_code == 400 and "reminders" in refused.json()["fields"]  # « Mika te le rappelle » s'en charge


# ── invitations et propositions de Mika ──


def test_an_invitation_between_two_accounts_is_answered_from_her_agenda(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    providers = live.kernel.ports["agenda_providers"]
    theirs = client.portal.call(providers.system.default_calendar, lea)
    start = us_of(datetime.fromisoformat(f"{tomorrow()}T18:00+01:00"))
    client.portal.call(lambda: providers.system.create(
        providers.connection(theirs.account), theirs,
        EventDraft("Anniversaire de Léa", Span(start, start + 3 * HOUR_US, "Europe/Paris"),
                   participants=(Participant(person="user_1"),))))
    got = client.get(API + "/agenda/invitations").json()["items"]
    assert [x["title"] for x in got] == ["Anniversaire de Léa"] and got[0]["invitation"]
    assert got[0]["can"]["respond"] and not got[0]["can"]["edit"] and got[0]["prepared"] is None
    assert client.get(API).json()["counts"]["agenda"] == 1
    answer = post(client, "/agenda/event/respond", {"event": got[0]["event"], "answer": "oui", "comment": "Avec "
                                                                                                          "plaisir"})
    assert answer.status_code == 200, answer.text
    assert client.get(API + "/agenda/invitations").json()["items"] == []
    assert post(client, "/agenda/event/respond", {"event": got[0]["event"], "answer": "bof"}).status_code == 400


def propose(client, live, calendar: str, decider: str = "user_1") -> int:
    start = us_of(datetime.fromisoformat(f"{tomorrow()}T20:00+01:00"))
    args = {"op": "ajouter", "calendar": calendar, "keep": "perso", "target": decider,
            "ref": f"chat:{decider}:5", "starts": start, rt.DECIDER: decider,
            "draft": {"title": "Dîner chez Léa", "span": {"start": start, "end": start + 3 * HOUR_US,
                                                          "zone": "Europe/Paris", "all_day": False},
                      "location": "rue de Gand", "description": "", "rule": "", "invite": []}}
    append(client, live, [rt.EFFECT_PROPOSED.draft(
        capability=CAPABILITY, owner=OWNER, args_json=json.dumps(args), approval=True, context=decider,
        summary=Content.of("ajouter « Dîner chez Léa » samedi"), about=(decider,))])
    return max(live.kernel.mind.frame().state(OWNER).writes)


def test_what_mika_proposes_is_accepted_as_it_was_read(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    cal = mine(client)
    proposal = propose(client, live, cal)
    [item] = client.get(API + "/agenda/proposals").json()["items"]
    assert item["id"] == proposal and item["decides"] and item["draft"]["title"] == "Dîner chez Léa"
    assert item["preview"]["digest"] and item["conversation"] == "chat:user_1:5"
    assert period(client)["proposals"][0]["id"] == proposal  # hachurée dans la grille
    stale = post(client, "/agenda/proposal/accept", {"proposal": proposal, "seen": "autre"})
    assert stale.status_code == 409, stale.text
    ok = post(client, "/agenda/proposal/accept", {"proposal": proposal, "seen": item["preview"]["digest"]})
    assert ok.status_code == 200, ok.text
    for _ in range(100):  # l'exécuteur écrit après le commit
        if live.kernel.mind.frame().state(OWNER).writes[proposal].status == DONE:
            break
        time.sleep(0.05)
    [added] = period(client)["items"]
    assert added["title"] == "Dîner chez Léa" and added["added"]["by"] == "elle"
    assert client.get(API + "/agenda/proposals").json()["items"] == []


def test_what_mika_proposes_can_be_added_with_your_changes_or_refused(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    cal = mine(client)
    first = propose(client, live, cal)
    edited = post(client, "/agenda/proposal/edit", {"proposal": first, "title": "Dîner chez Léa et Tom",
                                                    "start": f"{tomorrow()}T20:30"})
    assert edited.status_code == 200, edited.text
    [added] = period(client)["items"]
    assert added["title"] == "Dîner chez Léa et Tom" and added["added"]["conversation"] == "chat:user_1:5"
    w = live.kernel.mind.frame().state(OWNER).writes[first]
    assert w.status == DONE and w.edited  # elle l'apprend : ajouté, avec ses changements
    second = propose(client, live, cal)
    assert post(client, "/agenda/proposal/refuse", {"proposal": second, "note": "pas cette semaine"}).status_code \
        == 200
    assert client.get(API + "/agenda/proposals").json()["items"] == []
    third = propose(client, live, cal)
    login(client, "lea")
    assert post(client, "/agenda/proposal/refuse", {"proposal": third}).status_code == 404
    login(client, "adrien")
    assert share(client, cal, lea, "preparer").status_code == 200
    login(client, "lea")
    [waiting] = client.get(API + "/agenda/proposals").json()["items"]
    assert waiting["id"] == third and not waiting["decides"] and waiting["preview"] is None
    assert post(client, "/agenda/proposal/refuse", {"proposal": third}).status_code == 403


def propose_on(client, live, calendar: str, item: dict, op: str, summary: str, decider: str = "user_1",
               **more) -> int:
    """Ce que Mika propose de faire d'un événement (le modifier, répondre), en tête-à-tête avec ``decider``."""
    args = {"op": op, "calendar": calendar, "keep": "perso", "target": decider, "ref": f"chat:{decider}:6",
            "starts": item["start"] * 1000, rt.DECIDER: decider, "event": item["event"], "uid": item["uid"],
            "original": "", "occurrence": "", **more}
    append(client, live, [rt.EFFECT_PROPOSED.draft(
        capability=CAPABILITY, owner=OWNER, args_json=json.dumps(args), approval=True, context=decider,
        summary=Content.of(summary), about=(decider,))])
    return max(live.kernel.mind.frame().state(OWNER).writes)


def test_the_preview_of_a_private_event_names_it_to_its_owner_only(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    cal = mine(client)
    create(client, cal, "Psy", hour=9, private=True)
    [item] = period(client)["items"]
    his = propose_on(client, live, cal, item, "supprimer", "supprimer « Psy »", scope="tous")
    theirs = propose_on(client, live, cal, item, "supprimer", "supprimer « Occupé »", decider=lea, scope="tous")
    [mine_] = [x for x in client.get(API + "/agenda/proposals").json()["items"] if x["id"] == his]
    assert "Psy" in mine_["preview"]["text"]  # il approuve ce qu'il lit : le titre de son propre rendez-vous
    assert share(client, cal, lea, "servir").status_code == 200
    login(client, "lea")
    [hers] = [x for x in client.get(API + "/agenda/proposals").json()["items"] if x["id"] == theirs]
    assert hers["decides"] and "Psy" not in hers["preview"]["text"] and "Occupé" in hers["preview"]["text"]


def test_a_proposal_on_a_private_event_reads_busy_for_a_share_that_prepares(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    cal = mine(client)
    create(client, cal, "Psy", hour=9, private=True, location="Cabinet Roux", description="séance douze")
    [item] = period(client)["items"]
    edit = propose_on(client, live, cal, item, "modifier", "modifier « Psy », demain dans « Mon agenda »",
                      scope="tous", change={"title": "Psy déplacé", "location": "Cabinet Roux"})
    store = live.kernel.ports["agenda"]
    row = store.event(item["event"])
    client.portal.call(lambda: store.save([dataclasses.replace(  # devenu une invitation qui attend sa réponse
        row, response="attente", organizer=Participant(address="cabinet@roux.example", name="Roux"))]))
    answer = propose_on(client, live, cal, item, "repondre", "répondre « refusé » à « Psy », demain",
                        scope="tous", response="non", comment="Pas de psy cette semaine", why="fatigué",
                        invitation="inv-1")
    held = {x["id"]: x for x in client.get(API + "/agenda/proposals").json()["items"]}
    assert "Psy" in held[edit]["summary"] and held[edit]["change"]["title"] == "Psy déplacé"  # à lui, tout
    assert held[answer]["answer"] == "non" and held[answer]["comment"]
    assert share(client, cal, lea, "preparer").status_code == 200
    login(client, "lea")
    got = {x["id"]: x for x in client.get(API + "/agenda/proposals").json()["items"]}
    assert set(got) == {edit, answer}  # un partage qui prépare les voit…
    said = json.dumps(list(got.values()), ensure_ascii=False)
    assert "Psy" not in said and "psy" not in said and "Roux" not in said  # … sans rien de l'événement privé
    assert all("Occupé" in x["summary"] for x in got.values())
    assert all(x["change"] is None and x["answer"] == "" and x["comment"] == "" for x in got.values())
    one = client.get(API + f"/agenda/event?event={item['event']}").json()
    assert one["masked"] and one["prepared"] is not None and one["prepared"]["comment"] == ""
    shown = json.dumps(one, ensure_ascii=False)
    assert "Psy" not in shown and "psy" not in shown and "Roux" not in shown and "douze" not in shown


# ── ses comptes ──


def test_google_is_refused_in_words_without_the_servers_application(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    made = post(client, "/agenda/account/save", {"kind": "google", "values": {"label": "Google"}})
    assert made.status_code == 200, made.text
    started = post(client, "/agenda/account/google/start", {"account": made.json()["account"]})
    assert started.status_code == 409 and "application Google" in started.json()["error"]


def test_google_is_connected_by_pasting_the_return_address(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    google = FakeGoogle()
    providers = live.kernel.ports["agenda_providers"]
    client.portal.call(lambda: live.settings.of(AgendaSettings).save_google_application(google.client_id, google.secret))
    signin = GoogleSignIn(live.settings.of(AgendaSettings), live.settings.of(AgendaSettings).google_application, transport=google.transport())
    providers.add(GoogleProvider(signin, transport=google.transport()))
    account = post(client, "/agenda/account/save", {"kind": "google", "values": {"label": "Perso"}}).json()["account"]
    started = post(client, "/agenda/account/google/start", {"account": account}).json()
    assert started["url"].startswith("https://accounts.google.com/") and started["direct"] is False
    pasted = google.consent(started["url"])
    stale = post(client, "/agenda/account/google/finish", {"account": account,
                                                            "text": "http://127.0.0.1:1/?state=autre&code=4/0Ax"})
    assert stale.status_code == 400 and "text" in stale.json()["fields"]
    done = post(client, "/agenda/account/google/finish", {"account": account, "text": pasted})
    assert done.status_code == 200, done.text
    [g] = [a for a in client.get(API + "/agenda/accounts").json()["accounts"] if a["key"] == account]
    assert g["signin"]["state"] == SIGNED_IN and g["address"] == google.owner
    assert any(e.data.account == account for e in journal(live, SYNC_ASKED))
    assert post(client, "/agenda/account/disconnect", {"account": account}).status_code == 200
    [g] = [a for a in client.get(API + "/agenda/accounts").json()["accounts"] if a["key"] == account]
    assert g["signin"]["state"] != SIGNED_IN


def test_microsoft_gives_a_code_and_its_wait_is_pushed(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    graph = FakeGraph(pending=2)

    async def no_wait(_seconds: float) -> None:
        await asyncio.sleep(0)

    signin = microsoft_signin(live.settings.of(AgendaSettings), live.settings.of(MailSettings).mail_application, transport=graph.transport(),
                              sleep=no_wait)
    signin.on_state = lambda account: signed(live.changes, account)
    live.kernel.ports["agenda_providers"].add(MicrosoftProvider(signin, transport=graph.transport()))
    account = post(client, "/agenda/account/save", {"kind": "microsoft",
                                                    "values": {"label": "Outlook"}}).json()["account"]
    with client.websocket_connect(WS) as adrien:
        time.sleep(SETTLED_S)
        received(adrien, 1)
        started = post(client, "/agenda/account/microsoft/start", {"account": account}).json()
        assert started["code"] == "GRPH-CODE" and started["url"]
        for _ in range(100):
            [m] = [a for a in client.get(API + "/agenda/accounts").json()["accounts"] if a["key"] == account]
            if m["signin"]["state"] == SIGNED_IN:
                break
            time.sleep(0.05)
        time.sleep(SETTLED_S)
        said = changes(received(adrien, 2))
    assert m["signin"]["state"] == SIGNED_IN
    assert any(c["topic"] == "agenda" for c in said)
    assert post(client, "/agenda/account/sync", {"account": account}).status_code == 200


def test_caldav_is_tried_then_chosen_and_a_local_server_is_for_operators(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    server = FakeCalDav()
    live.kernel.ports["agenda_providers"].add(CalDavProvider(Web(transport=server.transport())))
    tried = post(client, "/agenda/account/try", {"url": "https://caldav.example.org/", "username": "adrien",
                                                 "password": "secret"}).json()
    assert tried["ok"] and {c["name"] for c in tried["calendars"]} >= {"Perso", "Fériés"}
    wrong = post(client, "/agenda/account/try", {"url": "https://caldav.example.org/", "username": "adrien",
                                                 "password": "faux"}).json()
    assert not wrong["ok"] and wrong["message"]
    saved = post(client, "/agenda/account/save", {"kind": "caldav", "values": {
        "label": "Nextcloud", "url": "https://caldav.example.org/", "username": "adrien", "password": "secret"}})
    assert saved.status_code == 200, saved.text
    key = saved.json()["account"]
    [c] = [a for a in client.get(API + "/agenda/accounts").json()["accounts"] if a["key"] == key]
    assert c["secrets"] == {"password": True} and '"secret"' not in json.dumps(c)  # le mot de passe ne repart pas
    assert post(client, "/agenda/account/save", {"account": key, "values": {
        "url": "https://autre.example.org/"}}).status_code == 400  # le serveur change : son mot de passe redonné
    second_person(client, live)
    login(client, "lea")
    local = post(client, "/agenda/account/try", {"url": "http://localhost:1080/users/lea/calendar/",
                                                 "username": "lea", "password": "x"})
    assert local.status_code == 400 and "url" in local.json()["fields"]
    assert post(client, "/agenda/account/save", {"kind": "caldav", "values": {
        "url": "http://127.0.0.1:1080/", "username": "lea", "password": "x"}}).status_code == 400
    assert post(client, "/agenda/account/remove", {"account": key}).status_code == 404  # le compte d'un autre
    login(client, "adrien")
    assert post(client, "/agenda/account/remove", {"account": key}).status_code == 200


@pytest.mark.parametrize("schedules", [False, True], ids=["sans planification", "planification"])
def test_an_invitation_offers_an_answer_only_where_it_can_reach_its_organizer(world, schedules):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    server = FakeCalDav(schedules=schedules)
    providers = live.kernel.ports["agenda_providers"]
    provider = CalDavProvider(Web(transport=server.transport()))
    providers.add(provider)
    key = post(client, "/agenda/account/save", {"kind": "caldav", "values": {
        "label": "Nextcloud", "url": "https://caldav.example.org/", "username": "adrien",
        "password": "secret"}}).json()["account"]
    day = (date.today() + timedelta(days=2)).strftime("%Y%m%d")
    server.put("perso", "invite.ics", INVITE.replace("20261202", day))

    async def sync() -> None:
        await sync_account(live.kernel.ports["agenda"], provider, providers.connection(key), AgendaParams(),
                           live.kernel.deps.clock.now())

    client.portal.call(sync)
    [item] = client.get(API + "/agenda/invitations").json()["items"]
    assert item["invitation"] and item["can"]["respond"] is schedules
    assert ("ne transmet pas les réponses" in item["respond_why"]) is not schedules
    one = client.get(API + f"/agenda/event?event={item['event']}").json()
    assert one["can"]["respond"] is schedules and one["respond_why"] == item["respond_why"]
    [perso] = [c for c in client.get(API + "/agenda/calendars").json()["calendars"] if c["key"] == item["calendar"]]
    assert perso["can"]["write"] and perso["can"]["respond"] is schedules


def test_the_key_of_a_branched_account_never_comes_from_its_address(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    bare = post(client, "/agenda/account/save", {"kind": "google", "values": {"address": "adrien.martin@gmail.com"}})
    assert bare.status_code == 200, bare.text
    key = bare.json()["account"]
    assert not {"adrien", "martin", "gmail"} & set(re.split(r"[-_]", key)), key  # ses réglages sont journalisés
    named = post(client, "/agenda/account/save", {"kind": "ical", "values": {
        "label": "Fériés", "url": "https://calendrier.example.org/f.ics"}}).json()["account"]
    assert named.startswith("feries-")  # son nom affiché, s'il en a un
    mailed = post(client, "/agenda/account/save", {"kind": "ical", "values": {
        "label": "lea.dupont@exemple.fr", "url": "https://calendrier.example.org/g.ics"}}).json()["account"]
    assert "lea" not in mailed and "dupont" not in mailed  # un nom qui est une adresse n'en est pas un


def test_a_server_given_by_a_person_who_is_not_an_operator_stays_on_internet(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    mine_ = post(client, "/agenda/account/save", {"kind": "ical", "values": {
        "label": "Fériés", "url": "https://calendrier.example.org/f.ics"}}).json()["account"]
    second_person(client, live)
    login(client, "lea")
    bypass = post(client, "/agenda/account/save", {"kind": "ical", "values": {
        "label": "Club", "url": "https://calendrier.example.org/c.ics", "internet": False}})
    assert bypass.status_code == 400  # elle ne le règle pas elle-même
    hers = post(client, "/agenda/account/save", {"kind": "ical", "values": {
        "label": "Club", "url": "https://calendrier.example.org/c.ics"}}).json()["account"]
    accounts = client.portal.call(live.settings.of(AgendaSettings).agenda).accounts
    assert accounts[hers].internet and not accounts[mine_].internet  # une opératrice peut viser DavMail en local
    [conn] = [c for c in client.portal.call(live.settings.of(AgendaSettings).agenda).connections() if c.key == hers]
    assert conn.internet


def test_a_person_branches_at_most_ten_accounts(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    second_person(client, live)
    login(client, "lea")
    for i in range(10):
        ok = post(client, "/agenda/account/save", {"kind": "ical", "values": {
            "label": f"Fériés {i}", "url": f"https://calendrier.example.org/{i}.ics"}})
        assert ok.status_code == 200, ok.text
    assert post(client, "/agenda/account/save", {"kind": "ical", "values": {
        "url": "https://calendrier.example.org/x.ics"}}).status_code == 409


def test_google_returning_without_a_session_asks_to_paste_its_address_in_the_app(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    second_person(client, live)
    google = FakeGoogle()
    providers = live.kernel.ports["agenda_providers"]
    client.portal.call(lambda: live.settings.of(AgendaSettings).save_google_application(google.client_id, google.secret, web=True))
    signin = GoogleSignIn(live.settings.of(AgendaSettings), live.settings.of(AgendaSettings).google_application, transport=google.transport())
    providers.add(GoogleProvider(signin, transport=google.transport()))
    account = post(client, "/agenda/account/save", {"kind": "google", "values": {"label": "Perso"}}).json()["account"]
    started = client.post(API + "/agenda/account/google/start", json={"account": account},
                          headers={**csrf(client), "Origin": "https://mika.example.org"}).json()
    assert started["direct"] is True
    back = google.consent(started["url"])  # consenti dans le navigateur du téléphone, qui n'a pas de session
    assert back.startswith("https://mika.example.org/api/moi/agenda/google/retour?")
    kept = dict(client.cookies)
    client.cookies.clear()
    page = client.get(back.removeprefix("https://mika.example.org"))
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    said = html.unescape(page.text)
    assert "colle-la dans l'application" in said and "est connecté" not in said
    for k, v in kept.items():
        client.cookies.set(k, v)
    [g] = [a for a in client.get(API + "/agenda/accounts").json()["accounts"] if a["key"] == account]
    assert g["signin"]["state"] != SIGNED_IN  # le state seul ne finit rien
    login(client, "lea")  # une autre personne ne finit pas le parcours d'Adrien, même en collant son adresse
    assert post(client, "/agenda/account/google/finish", {"account": account, "text": back}).status_code == 404
    login(client, "adrien")
    done = post(client, "/agenda/account/google/finish", {"account": account, "text": back})
    assert done.status_code == 200, done.text  # l'adresse de retour directe se colle aussi


# ── le direct, le téléphone ──


def test_a_change_reaches_who_sees_the_agenda_and_no_one_else(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    cal = mine(client)
    session = lea_session(client, live)
    with client.websocket_connect(WS) as adrien, \
            client.websocket_connect(WS, headers={"cookie": f"sessionid={session}"}) as lea:
        time.sleep(SETTLED_S)
        received(adrien, 1), received(lea, 1)
        assert create(client, cal, "Rien qu'à lui").status_code == 200
        time.sleep(SETTLED_S)
        his, hers = changes(received(adrien, 2)), changes(received(lea, 2))
    assert {"topic": "agenda", "calendars": [cal]} in his
    assert "Rien qu'à lui" not in json.dumps(his)
    assert all(c["topic"] != "agenda" for c in hers)


def test_the_phone_writes_with_its_own_token(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    cal = mine(client)
    origin = client.headers.pop("origin")
    try:
        got = client.post("/auth/token", json={"username": "adrien", "password": "un-mot-de-passe-long",
                                               "client": "mobile", "label": "Pixel"})
        assert got.status_code == 200, got.text
        token = got.json()["token"]
        made = client.post(API + "/agenda/event/create", headers={"authorization": f"Bearer {token}"},
                           json={"calendar": cal, "title": "Depuis le téléphone", "start": f"{tomorrow()}T07:00"})
        assert made.status_code == 200, made.text
    finally:
        client.headers["origin"] = origin
    assert [x["title"] for x in period(client)["items"]] == ["Depuis le téléphone"]


@pytest.mark.parametrize("path", ["/agenda/event/create", "/agenda/account/save", "/agenda/proposal/accept"])
def test_writing_needs_the_csrf_token(world, path):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    assert client.post(API + path, json={}).status_code == 403

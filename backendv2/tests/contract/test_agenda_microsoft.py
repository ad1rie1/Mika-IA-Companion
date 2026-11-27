"""Outlook.com / Microsoft 365 (ADR 0309, lot 2), ``adapters/agenda/graph.py`` et ``oauth.py::microsoft_signin`` :
contre un faux Microsoft (``tests/fixtures/graph_calendar.py``, un transport ``httpx`` factice qui suit les formes de
Graph v1.0 et de son point OAuth2), sur le vrai magasin et ``agenda.sync``. Rien ne parle au vrai Microsoft.

- se connecter : le code d'appareil du courrier, à la portée de Graph (``Calendars.ReadWrite``), une connexion à part
  de celle d'une boîte ; l'application de l'instance, ou celle du compte et son annuaire ; une connexion révoquée ou
  refusée (``AADSTS…``) se dit en mots et met le compte « à reconnecter » ; un jeton refusé par Graph se renouvelle
  une fois ;
- ses agendas (nom, couleur, droits, principal, son propriétaire) ; la première synchronisation (chaque occurrence
  d'une série une ligne, une exception, une occurrence annulée, une invitation, une journée entière lue par ses dates,
  Teams, privé), toutes ses pages en un lot complet ; puis le delta, page après page ; un état perdu (``410``) ou une
  fenêtre qui a glissé au-delà de la vue fait tout relire ;
- écrire : un événement simple et une série (sa règle en ``patternedRecurrence``, l'heure de son fuseau sous son nom
  Windows), les trois portées, « celui-ci et les suivants » (la suite d'abord, puis la série finie la veille), une
  invitation à laquelle on répond (la supprimer la refuse), un conflit (``412``) dit en mots ; un lien que Graph
  donnerait vers un autre hôte n'est pas suivi.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from mika.adapters.agenda import AgendaStore, MicrosoftProvider, SignInNeeded, microsoft_signin
from mika.adapters.agenda.oauth import MICROSOFT_SCOPES
from mika.adapters.mail.config import DEFAULT_APPLICATION
from mika.adapters.mail.oauth import REVOKED
from mika.plugins.agenda import AgendaParams
from mika.plugins.agenda.sync import reread, sync_account
from mika.ports.agenda import (
    ALL,
    BY_HER,
    DAY_US,
    EMAIL,
    FOLLOWING,
    NEEDS,
    NO,
    ONE,
    US_PER_S,
    YES,
    AddedBy,
    AgendaError,
    Alert,
    Connection,
    EventChange,
    EventDraft,
    Participant,
    Span,
    at_us,
    occurrence_key,
    us_of,
)
from mika.ports.signin import SIGNED_IN, SIGNIN_NEEDED, SIGNIN_PENDING
from tests.fixtures import backend
from tests.fixtures.graph_calendar import BIRTHDAYS, CAL, FakeGraph

PARIS = ZoneInfo("Europe/Paris")
NOW = us_of(datetime(2026, 11, 23, 15, tzinfo=PARIS))
MINUTE = 60 * US_PER_S
ME = "personne:user_1"
OWNER = "adrien.moreau@outlook.fr"
CLIENT = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


def paris(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> int:
    return us_of(datetime(y, m, d, h, mi, tzinfo=PARIS))


def local(us: int) -> str:
    return at_us(us, PARIS).strftime("%d/%m %H:%M")


def _person(address: str, name: str, response: str, kind: str = "required") -> dict:
    return {"type": kind, "status": {"response": response, "time": "2026-11-20T08:00:00Z"},
            "emailAddress": {"name": name, "address": address}}


async def _no_wait(_seconds: float) -> None:
    await asyncio.sleep(0)


class Vault:
    def __init__(self) -> None:
        self.grants: dict[str, tuple[object, str]] = {}

    def agenda_grant(self, account, kind):
        got = self.grants.get(account)
        return got[0] if got is not None and got[1] == kind else None

    async def save_agenda_grant(self, account, grant, kind) -> None:
        self.grants[account] = (grant, kind)


class World:
    def __init__(self, tmp, graph: FakeGraph | None = None, *, page: int = 100,
                 account: Connection | None = None) -> None:
        self.graph = graph or FakeGraph()
        self.vault = Vault()
        self.clock = [NOW]
        self.signin = microsoft_signin(self.vault, lambda: DEFAULT_APPLICATION, transport=self.graph.transport(),
                                       sleep=_no_wait,
                                       now=lambda: datetime.fromtimestamp(self.clock[0] / US_PER_S, UTC))
        self.provider = MicrosoftProvider(self.signin, transport=self.graph.transport(), now=lambda: self.clock[0],
                                          page=page)
        self.store = AgendaStore(backend.target(tmp, "agenda"), now=lambda: NOW)
        self.account = account or Connection("outlook", "microsoft", owner=ME, label="Outlook.com")
        self.store.keep_account("outlook", "microsoft", owner=ME)

    def connect(self) -> None:
        async def go():
            started = await self.signin.start("outlook", self.account)
            assert started.state == SIGNIN_PENDING and started.code == "GRPH-CODE"
            for _ in range(200):
                if self.signin.state("outlook", self.account).state != SIGNIN_PENDING:
                    return
                await asyncio.sleep(0)
            raise AssertionError("la connexion attend encore")

        asyncio.run(go())

    def sync(self, minutes: int = 0):
        self.clock[0] = NOW + minutes * MINUTE
        return asyncio.run(sync_account(self.store, self.provider, self.account, AgendaParams(), self.clock[0]))

    def cal(self, name: str = "Calendrier"):
        return next(c for c in self.store.calendars("outlook") if c.name == name)

    def shown(self, name: str = "Calendrier", start: int = 0, end: int = 0):
        start, end = start or paris(2026, 11, 23), end or paris(2026, 12, 10)
        return [(local(o.span.start), o.event.title) for o in self.store.period([self.cal(name).key], start, end)]

    def run(self, coro):
        return asyncio.run(coro)

    def reread(self, kept=()):
        return asyncio.run(reread(self.store, self.provider, self.account, self.cal().key, AgendaParams(),
                                  self.clock[0], kept))

    def row(self, title: str, day: int = 0):
        """La ligne de la copie d'une occurrence (son titre, et son jour : 0, la première)."""
        found = [o for o in self.store.period([self.cal().key], paris(2026, 8, 1), paris(2027, 12, 31))
                 if o.event.title == title]
        return found[day].event


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.store.close()


WEEKLY = {"pattern": {"type": "weekly", "interval": 1, "daysOfWeek": ["monday"], "firstDayOfWeek": "sunday"},
          "range": {"type": "endDate", "startDate": "2026-11-02", "endDate": "2027-06-28",
                    "recurrenceTimeZone": "Romance Standard Time"}}
YOGA_RULE = {"pattern": {"type": "weekly", "interval": 1, "daysOfWeek": ["tuesday"], "firstDayOfWeek": "sunday"},
             "range": {"type": "numbered", "startDate": "2026-11-03", "numberOfOccurrences": 10,
                       "recurrenceTimeZone": "Romance Standard Time"}}


def _filled(world: World) -> World:
    g = world.graph
    g.put(CAL, "Point hebdo · Projet Lumen", paris(2026, 11, 2, 9), paris(2026, 11, 2, 9, 30), rule=WEEKLY,
          gid="AAMkHebdo=", isOrganizer=False,
          organizer={"emailAddress": {"name": "Claire Dubois", "address": "claire@lumen-conseil.fr"}},
          responseStatus={"response": "accepted", "time": "2026-10-01T08:00:00Z"},
          attendees=[_person(OWNER, "Adrien Moreau", "accepted"), _person("sophie@lumen-conseil.fr", "Sophie",
                                                                          "tentativelyAccepted", "optional")],
          onlineMeeting={"joinUrl": "https://teams.microsoft.com/l/meetup-join/19%3ameeting_Lumen"})
    g.move("AAMkHebdo=", occurrence_key(paris(2026, 12, 7, 9), False), paris(2026, 12, 7, 10),
           paris(2026, 12, 7, 10, 30))
    g.put(CAL, "Yoga", paris(2026, 11, 3, 18), paris(2026, 11, 3, 19), rule=YOGA_RULE, gid="AAMkYoga=",
          location={"displayName": "Salle B"})
    g.cancel("AAMkYoga=", occurrence_key(paris(2026, 12, 1, 18), False))
    g.put(CAL, "Entretien annuel", paris(2026, 11, 25, 14), paris(2026, 11, 25, 15), gid="AAMkEntretien=",
          isOrganizer=False, location={"displayName": "Salle RH, 2e étage"},
          organizer={"emailAddress": {"name": "Nadia Benali", "address": "nadia@lumen-conseil.fr"}},
          responseStatus={"response": "notResponded", "time": "0001-01-01T00:00:00Z"},
          attendees=[_person(OWNER, "Adrien Moreau", "none"), _person("salle-rh@lumen-conseil.fr", "Salle RH",
                                                                      "accepted", "resource")],
          body={"contentType": "text", "content": "Ton entretien annuel : prévois une heure."})
    g.put(CAL, "Télétravail", paris(2026, 11, 27), paris(2026, 11, 28), all_day=True, gid="AAMkTele=")
    g.put(CAL, "Médecin", paris(2026, 11, 30, 8, 30), paris(2026, 11, 30, 9), gid="AAMkMed=", sensitivity="private")
    g.put(BIRTHDAYS, "Anniversaire de Papa", paris(2026, 12, 6), paris(2026, 12, 7), all_day=True)
    world.connect()
    assert world.sync().error == ""
    return world


# ── se connecter ────────────────────────────────────────────────────────────


def test_signing_in_by_a_code_asks_graph_for_the_calendars_apart_from_the_mail(world):
    assert world.signin.state("outlook", world.account).state == SIGNIN_NEEDED
    world.connect()
    assert world.signin.state("outlook", world.account).state == SIGNED_IN
    grant, kind = world.vault.grants["outlook"]
    assert kind == "microsoft" and grant.client_id == DEFAULT_APPLICATION and grant.tenant == "consumers"
    tenant, endpoint, data = world.graph.oauth[0]
    assert (tenant, endpoint) == ("consumers", "devicecode") and data["scope"] == MICROSOFT_SCOPES
    assert "IMAP" not in data["scope"]  # un jeton à part de celui d'une boîte
    assert world.sync().error == ""


def test_an_account_may_bring_its_own_application_and_directory(tmp_path):
    w = World(tmp_path, account=Connection("pro", "microsoft", oauth_client_id=CLIENT,
                                           oauth_tenant="lumen-conseil.fr"))
    asyncio.run(w.signin.start("pro", w.account))
    tenant, _endpoint, data = w.graph.oauth[0]
    assert tenant == "lumen-conseil.fr" and data["client_id"] == CLIENT
    w.store.close()


def test_a_revoked_or_refused_connection_is_said_and_waits_for_a_new_one(world):
    world.connect()
    assert world.sync().error == ""
    world.graph.access.clear()  # un jeton d'accès refusé par Graph : renouvelé une fois, sans rien dire
    asked = len(world.graph.oauth)
    assert world.sync(10).error == "" and len(world.graph.oauth) == asked + 1
    world.graph.revoke_all()
    state = world.sync(20)
    assert state.error == REVOKED and state.failures == 1
    signin = world.signin.state("outlook", world.account)
    assert signin.state == SIGNIN_NEEDED and signin.error == REVOKED
    with pytest.raises(SignInNeeded):
        world.run(world.provider._token(world.account, False))
    assert "M.C5-renouv" not in state.error and "eyJ0eXAi" not in state.error  # jamais un jeton
    world.connect()
    world.graph.refused = "AADSTS65001"
    world.signin.drop("outlook")
    assert "n'a pas été accordé" in world.sync(30).error
    world.graph.refused = "AADSTS90094"
    world.connect()
    world.signin.drop("outlook")
    assert "accord de son administrateur" in world.sync(40).error


# ── lire ────────────────────────────────────────────────────────────────────


def test_the_calendars_carry_name_colour_rights_and_the_owner(world):
    world.connect()
    world.sync()
    cals = {c.name: c for c in world.store.calendars("outlook")}
    assert cals["Calendrier"].primary and cals["Calendrier"].writable and cals["Calendrier"].color == "#8764b8"
    assert not cals["Anniversaires"].writable and cals["Anniversaires"].color == "#87d28e"
    assert "=" not in cals["Calendrier"].key and cals["Calendrier"].remote == CAL
    assert world.run(world.provider.whoami(world.account)) == OWNER
    made = world.run(world.provider.create_calendar(world.account, "Sport"))
    assert made.name == "Sport" and made.writable and world.graph.seen("POST", "/me/calendars")[-1].body == {
        "name": "Sport"}
    world.sync(10)
    assert "Sport" in {c.name for c in world.store.calendars("outlook")}


def test_the_first_sync_reads_each_occurrence_as_a_row_and_a_whole_day_by_its_dates(tmp_path):
    w = _filled(World(tmp_path, page=7))
    first = w.graph.seen("GET", "/calendarView/delta")[0]
    assert first.params["startDateTime"] == at_us(NOW - 90 * DAY_US).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert first.params["endDateTime"] == at_us(NOW + 395 * DAY_US).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert "odata.maxpagesize=7" in first.headers["prefer"]
    assert len(w.graph.seen("GET", f"/me/calendars/{CAL}/calendarView/delta")) > 3  # plusieurs pages, un lot
    assert w.shown() == [
        ("23/11 09:00", "Point hebdo · Projet Lumen"), ("24/11 18:00", "Yoga"), ("25/11 14:00", "Entretien annuel"),
        ("27/11 01:00", "Télétravail"), ("30/11 08:30", "Médecin"), ("30/11 09:00", "Point hebdo · Projet Lumen"),
        ("07/12 10:00", "Point hebdo · Projet Lumen"), ("08/12 18:00", "Yoga")]  # le yoga du 1er décembre annulé
    hebdo = w.row("Point hebdo · Projet Lumen")
    assert hebdo.uid == "AAMkHebdo=" and hebdo.original == occurrence_key(paris(2026, 11, 2, 9), False)
    assert hebdo.remote == f"AAMkHebdo=OID{hebdo.original}" and hebdo.span.zone == "Europe/Paris"
    assert hebdo.conference.startswith("https://teams.microsoft.com/l/meetup-join/") and hebdo.response == YES
    assert hebdo.organizer.address == "claire@lumen-conseil.fr" and not hebdo.organizer.me
    assert [(p.address, p.optional, p.me) for p in hebdo.participants] == [
        (OWNER, False, True), ("sophie@lumen-conseil.fr", True, False)]
    moved = w.store.find(w.cal().key, "AAMkHebdo=", occurrence_key(paris(2026, 12, 7, 9), False))
    assert moved.span.start == paris(2026, 12, 7, 10)
    interview = w.row("Entretien annuel")
    assert interview.response == NEEDS and interview.description == "Ton entretien annuel : prévois une heure."
    assert [p.address for p in interview.participants] == [OWNER]  # la salle n'est pas une participante
    remote = w.row("Télétravail")
    assert remote.span.all_day and remote.span.first_day == "2026-11-27" and remote.span.last_day == "2026-11-27"
    assert not remote.busy and w.row("Médecin").private and w.row("Yoga").reminders == (Alert(15),)
    assert w.cal().cursor.startswith('{"link": "https://graph.microsoft.com/v1.0/me/calendars/')
    assert all(r.host == "graph.microsoft.com" for r in w.graph.requests)
    w.store.close()


def test_then_the_delta_page_by_page_and_a_lost_state_reads_all_again(tmp_path):
    w = _filled(World(tmp_path, page=2))
    w.graph.requests.clear()
    w.graph.drop("AAMkMed=")
    w.graph.cancel("AAMkYoga=", occurrence_key(paris(2026, 11, 24, 18), False))
    w.graph.change("AAMkEntretien=", subject="Entretien annuel (décalé)")
    w.graph.put(CAL, "Kiné", paris(2026, 11, 26, 18), paris(2026, 11, 26, 18, 30))
    assert w.sync(5).error == ""
    deltas = w.graph.seen("GET", f"/me/calendars/{CAL}/calendarView/delta")
    assert "$deltatoken" in deltas[0].params and "startDateTime" not in deltas[0].params
    assert any("$skiptoken" in d.params for d in deltas)  # le delta lui-même en pages
    shown = w.shown()
    assert ("30/11 08:30", "Médecin") not in shown and ("24/11 18:00", "Yoga") not in shown
    assert ("25/11 14:00", "Entretien annuel (décalé)") in shown and ("26/11 18:00", "Kiné") in shown
    w.graph.expire_tokens()
    w.graph.requests.clear()
    assert w.sync(10).error == ""  # 410 SyncStateNotFound : tout relu
    deltas = w.graph.seen("GET", f"/me/calendars/{CAL}/calendarView/delta")
    assert "$deltatoken" in deltas[0].params and "startDateTime" in deltas[1].params
    assert ("26/11 18:00", "Kiné") in w.shown()
    w.store.close()


def test_a_window_that_slid_past_the_view_asks_for_it_again(world):
    _filled(world)
    world.graph.requests.clear()
    assert world.sync(29 * 24 * 60).error == ""
    assert "$deltatoken" in world.graph.seen("GET", f"/me/calendars/{CAL}/calendarView/delta")[0].params
    world.graph.requests.clear()
    assert world.sync(31 * 24 * 60).error == ""  # la fenêtre a dépassé la fin de la vue
    assert "startDateTime" in world.graph.seen("GET", f"/me/calendars/{CAL}/calendarView/delta")[0].params


# ── écrire ──────────────────────────────────────────────────────────────────


def test_creating_a_single_event_and_a_series(world):
    world.connect()
    world.sync()
    cal = world.cal()
    draft = EventDraft("Déjeuner avec Léa", Span(paris(2026, 12, 3, 12, 30), paris(2026, 12, 3, 14), "Europe/Paris"),
                       location="Chez Paul", participants=(Participant("lea@example.org", "Léa", optional=True),),
                       reminders=(Alert(10), Alert(60, EMAIL)), conference="https://meet.google.com/abc-defg-hij",
                       added=AddedBy(BY_HER, "fil:42", NOW))
    made = world.run(world.provider.create(world.account, cal, draft))
    sent = world.graph.seen("POST", "/events")[-1].body
    assert sent["start"] == {"dateTime": "2026-12-03T12:30:00", "timeZone": "Romance Standard Time"}
    assert sent["attendees"] == [{"emailAddress": {"address": "lea@example.org", "name": "Léa"}, "type": "optional"}]
    assert sent["reminderMinutesBeforeStart"] == 60 and sent["isReminderOn"] and not sent["isAllDay"]
    assert sent["body"] == {"contentType": "text", "content": "https://meet.google.com/abc-defg-hij"}
    assert "fil:42" not in json.dumps(sent)
    assert made.added.ref == "fil:42" and made.organizer.me and made.remote and not made.original
    world.reread([made])
    world.sync(10)
    assert world.store.find(cal.key, made.uid).added.ref == "fil:42"  # sa marque reste chez nous
    series = world.run(world.provider.create(world.account, cal, EventDraft(
        "Course", Span(paris(2026, 12, 2, 7), paris(2026, 12, 2, 8), "Europe/Paris"), rule="FREQ=WEEKLY;BYDAY=WE;COUNT=4")))
    sent = world.graph.seen("POST", "/events")[-1].body
    assert sent["recurrence"] == {"pattern": {"type": "weekly", "interval": 1, "daysOfWeek": ["wednesday"],
                                              "firstDayOfWeek": "monday"},
                                  "range": {"startDate": "2026-12-02", "recurrenceTimeZone": "Romance Standard Time",
                                            "type": "numbered", "numberOfOccurrences": 4}}
    assert series.original == occurrence_key(paris(2026, 12, 2, 7), False) and series.uid  # sa première occurrence
    world.reread([series])
    assert [s for s in world.shown(end=paris(2027, 1, 1)) if s[1] == "Course"] == [
        ("02/12 07:00", "Course"), ("09/12 07:00", "Course"), ("16/12 07:00", "Course"), ("23/12 07:00", "Course")]
    with pytest.raises(AgendaError, match="Outlook ne sait pas cette récurrence"):
        world.run(world.provider.create(world.account, cal, EventDraft(
            "x", Span(NOW, NOW + MINUTE), rule="FREQ=HOURLY")))
    with pytest.raises(AgendaError, match="lecture seule"):
        world.run(world.provider.create(world.account, world.cal("Anniversaires"), draft))


def test_changing_one_occurrence_the_following_or_all(world):
    _filled(world)
    cal = world.cal()
    yoga = world.row("Yoga", 3)  # le 24 novembre
    one = world.run(world.provider.edit(world.account, cal, yoga, yoga.original, EventChange(title="Yoga dehors"),
                                        ONE))
    patch = world.graph.seen("PATCH")[-1]
    assert patch.path == f"/v1.0/me/events/{yoga.remote}" and patch.body == {"subject": "Yoga dehors"}
    assert patch.headers["if-match"].startswith('W/"')
    assert one.original == yoga.original and one.title == "Yoga dehors"
    world.reread([one])
    assert ("24/11 18:00", "Yoga dehors") in world.shown()
    # toute la série, depuis une occurrence : elle garde son premier jour et prend l'heure
    eighth = world.row("Yoga", 3)  # le 8 décembre (le 24 novembre s'appelle autrement, le 1er est annulé)
    whole = world.run(world.provider.edit(world.account, cal, eighth, eighth.original, EventChange(
        span=Span(paris(2026, 12, 8, 19), paris(2026, 12, 8, 20), "Europe/Paris")), ALL))
    patch = world.graph.seen("PATCH")[-1]
    assert patch.path == "/v1.0/me/events/AAMkYoga=" and patch.body["start"] == {
        "dateTime": "2026-11-03T19:00:00", "timeZone": "Romance Standard Time"}
    assert patch.body["recurrence"]["range"]["startDate"] == "2026-11-03"
    assert whole.span.start == paris(2026, 12, 8, 19)
    world.reread()
    assert ("08/12 19:00", "Yoga") in world.shown()
    # celui-ci et les suivants : la suite créée d'abord, puis la série finie la veille
    key = occurrence_key(paris(2026, 12, 15, 19), False)
    row = world.store.find(cal.key, "AAMkYoga=", key)
    after = world.run(world.provider.edit(world.account, cal, row, key, EventChange(location="Parc"), FOLLOWING))
    created, cut = world.graph.seen("POST", "/events")[-1], world.graph.seen("PATCH")[-1]
    assert world.graph.requests.index(created) < world.graph.requests.index(cut)
    assert created.body["recurrence"]["range"] == {"type": "numbered", "startDate": "2026-12-15",
                                                   "numberOfOccurrences": 4,
                                                   "recurrenceTimeZone": "Romance Standard Time"}
    assert created.body["location"] == {"displayName": "Parc"} and created.body["subject"] == "Yoga"
    assert cut.body["recurrence"]["range"]["type"] == "endDate" and cut.body["recurrence"]["range"]["endDate"] == \
        "2026-12-14" and "numberOfOccurrences" not in cut.body["recurrence"]["range"]
    assert after.original == key and after.uid != "AAMkYoga="
    world.reread()
    yogas = [s for s in world.shown(end=paris(2027, 2, 1)) if s[1] == "Yoga"]
    assert yogas[-4:] == [("15/12 19:00", "Yoga"), ("22/12 19:00", "Yoga"), ("29/12 19:00", "Yoga"),
                          ("05/01 19:00", "Yoga")]
    assert world.store.find(cal.key, after.uid, key).location == "Parc"


def test_following_is_undone_when_cutting_the_series_fails(world):
    _filled(world)
    cal = world.cal()
    world.graph.fail[("PATCH", "/v1.0/me/events/AAMkYoga=")] = lambda: httpx.Response(
        503, json={"error": {"code": "ServiceNotAvailable", "message": "Service unavailable"}})
    row = world.row("Yoga", 4)
    with pytest.raises(AgendaError, match="Microsoft est en panne"):
        world.run(world.provider.edit(world.account, cal, row, row.original, EventChange(title="Yoga du soir"),
                                      FOLLOWING))
    assert world.graph.seen("DELETE")[-1].path.startswith("/v1.0/me/events/AAMkEv")
    assert not [i for i in world.graph.items.values() if i["subject"] == "Yoga du soir"]


def test_deleting_one_following_or_all(world):
    _filled(world)
    cal = world.cal()
    row = world.row("Yoga", 3)
    assert world.run(world.provider.delete(world.account, cal, row, row.original, ONE)) == 1
    assert world.graph.seen("DELETE")[-1].path == f"/v1.0/me/events/{row.remote}"
    world.reread()
    assert ("24/11 18:00", "Yoga") not in world.shown() and ("08/12 18:00", "Yoga") in world.shown()
    row = world.row("Yoga", 4)  # le 15 décembre
    world.run(world.provider.delete(world.account, cal, row, row.original, FOLLOWING))
    assert world.graph.seen("PATCH")[-1].body["recurrence"]["range"]["endDate"] == "2026-12-14"
    world.reread()
    assert [s[0] for s in world.shown(end=paris(2027, 2, 1)) if s[1] == "Yoga"] == ["08/12 18:00"]
    world.run(world.provider.delete(world.account, cal, world.row("Yoga"), "", ALL))
    assert world.graph.seen("DELETE")[-1].path == "/v1.0/me/events/AAMkYoga="
    world.reread()
    assert not [s for s in world.shown(start=paris(2026, 9, 1), end=paris(2027, 2, 1)) if s[1] == "Yoga"]


def test_an_invitation_is_answered_and_deleting_it_declines(world):
    _filled(world)
    cal = world.cal()
    interview = world.row("Entretien annuel")
    with pytest.raises(AgendaError, match="se modifie chez qui l'organise"):
        world.run(world.provider.edit(world.account, cal, interview, "", EventChange(title="Autre"), ALL))
    out = world.run(world.provider.respond(world.account, cal, interview, "", YES, ALL, "C'est noté, à mercredi."))
    assert world.graph.answers[-1] == ("AAMkEntretien=", "accept", {"comment": "C'est noté, à mercredi.",
                                                                     "sendResponse": True})
    assert out.response == YES
    hebdo = world.row("Point hebdo · Projet Lumen", 1)
    world.run(world.provider.respond(world.account, cal, hebdo, hebdo.original, NO, ONE, "En congé"))
    assert world.graph.answers[-1][:2] == (hebdo.remote, "decline")
    assert world.run(world.provider.delete(world.account, cal, world.row("Point hebdo · Projet Lumen"), "", ALL)) == 1
    assert world.graph.answers[-1][:2] == ("AAMkHebdo=", "decline") and not world.graph.seen("DELETE")
    with pytest.raises(AgendaError, match="rien à répondre"):
        world.run(world.provider.respond(world.account, cal, world.row("Médecin"), "", YES))
    with pytest.raises(AgendaError, match="toute la série"):
        world.run(world.provider.respond(world.account, cal, hebdo, hebdo.original, YES, FOLLOWING))


def test_a_conflict_and_a_link_to_another_host_are_refused(world):
    _filled(world)
    cal = world.cal()
    medecin = world.row("Médecin")
    world.graph.fail[("PATCH", "/v1.0/me/events/AAMkMed=")] = lambda: httpx.Response(412, json={"error": {
        "code": "ErrorIrresolvableConflict", "message": "The change key does not match."}})
    with pytest.raises(AgendaError, match="a changé chez Microsoft pendant qu'on l'écrivait"):
        world.run(world.provider.edit(world.account, cal, medecin, "", EventChange(title="Médecin du travail"), ALL))
    world.graph.drop("AAMkMed=")
    with pytest.raises(AgendaError, match="n'existe plus chez Microsoft"):
        world.run(world.provider.edit(world.account, cal, medecin, "", EventChange(title="Médecin du travail"), ALL))
    world.store.set_cursor(cal.key, json.dumps({"link": "https://graph.evil.example/v1.0/x?$deltatoken=1",
                                                "end": NOW + 400 * DAY_US}))
    world.graph.requests.clear()
    state = world.sync(10)
    assert "n'est pas la sienne" in state.error
    assert [r.path for r in world.graph.requests] == ["/v1.0/me/calendars"]  # le lien n'est pas suivi

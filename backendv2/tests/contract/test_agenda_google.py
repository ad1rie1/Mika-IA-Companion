"""Google Agenda (ADR 0309, lot 2), ``adapters/agenda/google.py`` et ``oauth.py::GoogleSignIn`` : contre un faux Google
(``tests/fixtures/google_calendar.py``, un transport ``httpx`` factice qui suit les formes de l'API Calendar v3 et de
son point OAuth), sur le vrai magasin et ``agenda.sync``. Rien ne parle au vrai Google.

- se connecter : l'adresse de consentement (PKCE S256, ``access_type=offline``, ``prompt=consent``, un retour en
  boucle locale), puis l'adresse de retour collée — ou son code seul — ; le ``state`` et qui finit sont vérifiés, un
  refus et une case de l'agenda décochée se disent en mots ; sans application Google, rien ne commence ; une
  « Application Web » revient à l'origine HTTPS ; la connexion se garde à part, une connexion révoquée met le compte
  « à reconnecter » ;
- ses agendas (nom, couleur, droits, principal, son adresse) ; la première synchronisation (séries, exceptions,
  occurrences supprimées, invitations, journées entières, Meet, privé, rappels, HTML), puis le delta par
  ``syncToken``, page après page, un jeton périmé (``410``) qui fait tout relire ;
- écrire : créer (sa marque reste chez nous), les trois portées d'une série, « celui-ci et les suivants » défait si la
  coupe échoue, une invitation à laquelle on répond (la supprimer la refuse), un conflit (``412``) dit en mots.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

import httpx
import pytest

from mika.adapters.agenda import AgendaStore, GoogleApplication, GoogleProvider, GoogleSignIn, SignInNeeded
from mika.adapters.agenda.cloud import Api
from mika.adapters.agenda.oauth import GOOGLE_REVOKED, RETURN_PATH
from mika.plugins.agenda import AgendaParams
from mika.plugins.agenda.sync import reread, sync_account
from mika.ports.agenda import (
    ALL,
    BY_HER,
    EMAIL,
    FOLLOWING,
    MAYBE,
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
from tests.fixtures.google_calendar import CLIENT_ID, SECRET, FakeGoogle

PARIS = ZoneInfo("Europe/Paris")
NOW = us_of(datetime(2026, 11, 23, 15, tzinfo=PARIS))
MINUTE = 60 * US_PER_S
ME = "personne:user_1"
OWNER = "adrien.moreau@gmail.com"


def paris(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> int:
    return us_of(datetime(y, m, d, h, mi, tzinfo=PARIS))


def local(us: int) -> str:
    return at_us(us, PARIS).strftime("%d/%m %H:%M")


ESCALADE = {"id": "esc", "summary": "Escalade", "location": "Climb Up · Lille",
            "start": {"dateTime": "2026-11-26T19:00:00+01:00", "timeZone": "Europe/Paris"},
            "end": {"dateTime": "2026-11-26T21:00:00+01:00", "timeZone": "Europe/Paris"},
            "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=TH", "EXDATE;TZID=Europe/Paris:20261210T190000"],
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 10}]}}
LATE = {"id": "esc_20261203T180000Z", "recurringEventId": "esc", "summary": "Escalade (tard)",
        "originalStartTime": {"dateTime": "2026-12-03T19:00:00+01:00", "timeZone": "Europe/Paris"},
        "start": {"dateTime": "2026-12-03T20:00:00+01:00", "timeZone": "Europe/Paris"},
        "end": {"dateTime": "2026-12-03T22:00:00+01:00", "timeZone": "Europe/Paris"}}
SKIPPED = {"id": "esc_20261217T180000Z", "recurringEventId": "esc", "status": "cancelled",
           "originalStartTime": {"dateTime": "2026-12-17T19:00:00+01:00", "timeZone": "Europe/Paris"}}
RANDO = {"id": "rando", "summary": "Rando · boucle des Monts", "location": "Place du Concert, Lille",
         "start": {"dateTime": "2026-11-29T08:30:00+01:00", "timeZone": "Europe/Paris"},
         "end": {"dateTime": "2026-11-29T13:00:00+01:00", "timeZone": "Europe/Paris"},
         "organizer": {"email": "julien@example.org", "displayName": "Julien"},
         "attendees": [{"email": "julien@example.org", "displayName": "Julien", "organizer": True,
                        "responseStatus": "accepted"},
                       {"email": OWNER, "self": True, "responseStatus": "needsAction"},
                       {"email": "camille.petit@laposte.net", "displayName": "Camille Petit",
                        "responseStatus": "tentative", "optional": True},
                       {"email": "c_salle@resource.calendar.google.com", "resource": True,
                        "responseStatus": "accepted"}],
         "hangoutLink": "https://meet.google.com/abc-defg-hij", "guestsCanModify": False}
BIRTHDAY = {"id": "lea", "summary": "Anniversaire de Léa", "start": {"date": "2026-11-28"},
            "end": {"date": "2026-11-29"}, "recurrence": ["RRULE:FREQ=YEARLY"], "transparency": "transparent"}
DINNER = {"id": "diner", "summary": "Dîner avec Camille", "visibility": "private",
          "description": "<b>Réserver</b> chez Paul<br>avant jeudi",
          "start": {"dateTime": "2026-11-27T20:00:00+01:00", "timeZone": "Europe/Paris"},
          "end": {"dateTime": "2026-11-27T22:30:00+01:00", "timeZone": "Europe/Paris"}}
OFFICE = {"id": "bureau", "summary": "Bureau", "eventType": "workingLocation",
          "start": {"date": "2026-11-24"}, "end": {"date": "2026-11-25"}}
OLD = {"id": "vieux", "summary": "Il y a longtemps", "start": {"dateTime": "2026-01-05T10:00:00+01:00"},
       "end": {"dateTime": "2026-01-05T11:00:00+01:00"}}


class Vault:
    """Où les connexions se gardent (en vrai : les réglages, scellées)."""

    def __init__(self) -> None:
        self.grants: dict[str, tuple[object, str]] = {}

    def agenda_grant(self, account, kind):
        got = self.grants.get(account)
        return got[0] if got is not None and got[1] == kind else None

    async def save_agenda_grant(self, account, grant, kind) -> None:
        self.grants[account] = (grant, kind)


class World:
    def __init__(self, tmp, google: FakeGoogle | None = None, *, web: bool = False) -> None:
        self.google = google or FakeGoogle()
        self.vault = Vault()
        self.app: list[GoogleApplication | None] = [GoogleApplication.of(CLIENT_ID, SECRET, web=web)]
        self.clock = [NOW]
        self.signin = GoogleSignIn(self.vault, lambda: self.app[0], transport=self.google.transport(),
                                   now=lambda: self.clock[0], port=lambda: 53682)
        self.provider = GoogleProvider(self.signin, transport=self.google.transport(), now=lambda: self.clock[0])
        self.store = AgendaStore(backend.target(tmp, "agenda"), now=lambda: NOW)
        self.account = Connection("google", "google", owner=ME, label="Google")
        self.store.keep_account("google", "google", owner=ME)

    def connect(self) -> str:
        started = self.signin.start("google", who=ME)
        return asyncio.run(self.signin.finish(self.google.consent(started.url), key="google", who=ME))

    def sync(self, minutes: int = 0):
        self.clock[0] = NOW + minutes * MINUTE
        return asyncio.run(sync_account(self.store, self.provider, self.account, AgendaParams(), self.clock[0]))

    def cal(self, name: str = "Perso"):
        return next(c for c in self.store.calendars("google") if c.name == name)

    def shown(self, name: str = "Perso", start: int = 0, end: int = 0):
        start, end = start or paris(2026, 11, 1), end or paris(2027, 1, 1)
        return [(local(o.span.start), o.event.title) for o in self.store.period([self.cal(name).key], start, end)]

    def run(self, coro):
        return asyncio.run(coro)

    def reread(self, kept=(), name: str = "Perso"):
        return asyncio.run(reread(self.store, self.provider, self.account, self.cal(name).key, AgendaParams(),
                                  self.clock[0], kept))


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.store.close()


def _filled(world: World) -> World:
    for item in (ESCALADE, LATE, SKIPPED, RANDO, BIRTHDAY, DINNER, OFFICE, OLD):
        world.google.put(OWNER, item)
    world.google.put(OWNER, {"id": "parti", "summary": "x", "start": {"dateTime": "2026-11-30T10:00:00Z"},
                             "end": {"dateTime": "2026-11-30T11:00:00Z"}})
    world.google.remove(OWNER, "parti")
    world.connect()
    assert world.sync().error == ""
    return world


# ── se connecter ────────────────────────────────────────────────────────────


def test_signing_in_takes_the_pasted_return_address_and_keeps_the_connection_apart(world):
    assert world.signin.state("google").state == SIGNIN_NEEDED
    started = world.signin.start("google", who=ME, hint=OWNER)
    assert started.state == SIGNIN_PENDING and started.until == NOW + 15 * 60 * US_PER_S
    query = dict(parse_qsl(urlsplit(started.url).query))
    assert started.url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert query["redirect_uri"] == "http://127.0.0.1:53682/" and query["scope"] == \
        "https://www.googleapis.com/auth/calendar"
    assert query["code_challenge_method"] == "S256" and len(query["code_challenge"]) == 43
    assert query["access_type"] == "offline" and query["prompt"] == "consent" and query["login_hint"] == OWNER
    assert world.signin.state("google").state == SIGNIN_PENDING
    back = world.google.consent(started.url)  # la page de retour ne s'ouvre pas : on colle son adresse
    assert asyncio.run(world.signin.finish(back, key="google", who=ME)) == "google"
    assert world.signin.state("google").state == SIGNED_IN
    grant, kind = world.vault.grants["google"]
    assert kind == "google" and grant.client_id == CLIENT_ID and grant.refresh.startswith("1//renouv-")
    exchange = world.google.seen("POST", "/token")[-1].body
    assert exchange["grant_type"] == "authorization_code" and exchange["code_verifier"]
    assert exchange["redirect_uri"] == "http://127.0.0.1:53682/" and exchange["client_secret"] == SECRET
    # le code a servi : collé une seconde fois, rien ne repart
    with pytest.raises(AgendaError, match="ne vient pas d'une connexion commencée ici"):
        asyncio.run(world.signin.finish(back, key="google", who=ME))


def test_the_code_alone_finishes_the_one_waiting_and_a_foreign_state_or_person_is_refused(world):
    started = world.signin.start("google", who=ME)
    back = world.google.consent(started.url)
    code = dict(parse_qsl(urlsplit(back).query))["code"]
    with pytest.raises(AgendaError, match="ne vient pas d'une connexion commencée ici"):
        asyncio.run(world.signin.finish(back, key="google", who="personne:user_2"))  # quelqu'un d'autre
    with pytest.raises(AgendaError, match="ne vient pas"):
        asyncio.run(world.signin.finish(back.replace("state=", "state=x"), key="google", who=ME))
    assert asyncio.run(world.signin.finish(f"  {code}  ", key="google", who=ME)) == "google"
    assert world.signin.state("google").state == SIGNED_IN


def test_a_refusal_an_unticked_calendar_or_an_expired_start_is_said_in_words(world):
    started = world.signin.start("google", who=ME)
    with pytest.raises(AgendaError, match="refusée chez Google"):
        asyncio.run(world.signin.finish(world.google.consent(started.url, deny=True), key="google", who=ME))
    assert world.signin.state("google").error == "la connexion a été refusée chez Google"
    started = world.signin.start("google", who=ME)
    back = world.google.consent(started.url, scope="https://www.googleapis.com/auth/userinfo.email")
    with pytest.raises(AgendaError, match="accès à l'agenda"):
        asyncio.run(world.signin.finish(back, key="google", who=ME))
    assert "google" not in world.vault.grants
    started = world.signin.start("google", who=ME)
    back = world.google.consent(started.url)
    world.clock[0] = NOW + 16 * 60 * US_PER_S  # un quart d'heure est passé
    with pytest.raises(AgendaError, match="ou elle a expiré"):
        asyncio.run(world.signin.finish(back, key="google", who=ME))


def test_without_a_google_application_connecting_is_refused_in_words(world):
    world.app[0] = None
    with pytest.raises(AgendaError, match="aucune application Google sur ce serveur"):
        world.signin.start("google", who=ME)
    assert "aucune application Google" in world.signin.state("google").error
    assert "aucune application Google" in world.sync().error
    with pytest.raises(ValueError):
        GoogleApplication.of("pas-un-client", SECRET)
    with pytest.raises(ValueError):
        GoogleApplication.of(CLIENT_ID, "")
    assert SECRET not in repr(GoogleApplication.of(CLIENT_ID, SECRET))


def test_a_web_application_returns_to_the_https_origin_of_the_server(tmp_path):
    w = World(tmp_path, web=True)
    with pytest.raises(AgendaError, match="origine HTTPS"):
        w.signin.start("google", who=ME, origin="http://127.0.0.1:8001")
    started = w.signin.start("google", who=ME, origin="https://mika.example.org/")
    assert w.signin.direct()
    assert dict(parse_qsl(urlsplit(started.url).query))["redirect_uri"] == f"https://mika.example.org{RETURN_PATH}"
    back = w.google.consent(started.url)
    query = urlsplit(back).query  # la redirection directe : la route du lot 4 ne passe que sa requête
    assert w.run(w.signin.finish("?" + query, who=ME)) == "google"
    assert w.signin.state("google").state == SIGNED_IN
    w.store.close()


def test_a_revoked_connection_makes_the_account_to_reconnect(world):
    world.connect()
    assert world.sync().error == ""
    asked = len(world.google.seen("POST", "/token"))
    world.google.revoke_all()  # retirée depuis le compte Google
    state = world.sync(10)
    assert state.error == GOOGLE_REVOKED and state.failures == 1
    assert world.signin.state("google").state == SIGNIN_NEEDED and "à reconnecter" in world.signin.state("google").error
    assert len(world.google.seen("POST", "/token")) == asked + 1
    with pytest.raises(SignInNeeded):
        world.run(world.signin.token("google"))
    assert len(world.google.seen("POST", "/token")) == asked + 1  # pas représentée
    assert "1//renouv" not in state.error and "ya29" not in state.error
    world.connect()  # une connexion neuve la remplace
    assert world.sync(20).error == ""
    world.app[0] = GoogleApplication.of("999999999999-autreclient12345.apps.googleusercontent.com", SECRET)
    assert "application Google du serveur a changé" in world.sync(30).error


# ── lire ────────────────────────────────────────────────────────────────────


def test_the_calendars_carry_name_colour_role_and_the_primary_address(world):
    world.connect()
    world.sync()
    cals = {c.name: c for c in world.store.calendars("google")}
    assert set(cals) == {"Perso", "Famille", "Jours fériés en France"}
    assert cals["Perso"].primary and cals["Perso"].writable and cals["Perso"].color == "#7bd148"
    assert cals["Perso"].zone == "Europe/Paris" and cals["Perso"].remote == OWNER
    assert "@" not in cals["Perso"].key and cals["Perso"].key.startswith("google~h")
    assert cals["Famille"].writable and not cals["Jours fériés en France"].writable
    assert not cals["Jours fériés en France"].selected  # Google ne le coche pas : pas suivi
    assert world.run(world.provider.whoami(world.account)) == OWNER
    made = world.run(world.provider.create_calendar(world.account, "Sport"))
    assert made.name == "Sport" and made.writable and made.key.startswith("google~h")
    assert world.google.seen("POST", "/calendars")[-1].body == {"summary": "Sport"}
    world.sync(10)
    assert "Sport" in {c.name for c in world.store.calendars("google")}
    assert {r.host for r in world.google.requests} == {"oauth2.googleapis.com", "www.googleapis.com"}


def test_the_first_sync_reads_series_exceptions_invitations_and_whole_days(world):
    _filled(world)
    listed = world.google.seen("GET", "/events")[0].params
    assert listed["singleEvents"] == "false" and listed["showDeleted"] == "true" and listed["timeMin"]
    assert world.shown() == [
        ("26/11 19:00", "Escalade"), ("27/11 20:00", "Dîner avec Camille"), ("28/11 01:00", "Anniversaire de Léa"),
        ("29/11 08:30", "Rando · boucle des Monts"), ("03/12 20:00", "Escalade (tard)"), ("24/12 19:00", "Escalade"),
        ("31/12 19:00", "Escalade")]  # le 10 retiré (EXDATE), le 17 supprimé
    cal = world.cal().key
    series = world.store.find(cal, "esc")
    assert series.recurrence.rule == "FREQ=WEEKLY;BYDAY=TH" and series.recurrence.exdates == ("20261210T180000Z",)
    assert series.span.zone == "Europe/Paris" and series.reminders == (Alert(10),) and not series.reminders_default and series.remote == "esc"
    assert world.store.find(cal, "esc", "20261203T180000Z").remote == "esc_20261203T180000Z"
    rando = world.store.find(cal, "rando")
    assert rando.response == NEEDS and rando.conference == "https://meet.google.com/abc-defg-hij"
    assert rando.organizer.address == "julien@example.org" and not rando.organizer.me
    assert [(p.address, p.response, p.optional, p.me) for p in rando.participants] == [
        ("julien@example.org", YES, False, False), (OWNER, NEEDS, False, True),
        ("camille.petit@laposte.net", MAYBE, True, False)]  # la salle n'est pas une participante
    assert rando.reminders == () and rando.reminders_default  # il suit les rappels de son agenda…
    assert world.cal().reminders == (Alert(30),)  # …que la liste des agendas dit
    lea = world.store.find(cal, "lea")
    assert lea.span.all_day and lea.span.first_day == "2026-11-28" and not lea.busy
    dinner = world.store.find(cal, "diner")
    assert dinner.private and dinner.description == "Réserver chez Paul\navant jeudi"
    assert world.store.find(cal, "bureau") is None and world.store.find(cal, "parti") is None
    assert world.store.find(cal, "vieux") is None
    assert world.cal().cursor.startswith('{"s": "sync-')


def test_then_only_what_changed_page_by_page_and_a_dead_token_reads_all_again(tmp_path):
    w = _filled(World(tmp_path, FakeGoogle(page=2)))
    w.google.requests.clear()
    w.google.remove(OWNER, "diner")
    w.google.put(OWNER, {**RANDO, "summary": "Rando (annulée ?)"})
    w.google.put(OWNER, {"id": "esc_20261126T180000Z", "recurringEventId": "esc", "status": "cancelled",
                         "originalStartTime": {"dateTime": "2026-11-26T19:00:00+01:00"}})
    w.google.put(OWNER, {"id": "kine", "summary": "Kiné", "start": {"dateTime": "2026-11-25T18:00:00+01:00"},
                         "end": {"dateTime": "2026-11-25T18:30:00+01:00"}})
    assert w.sync(5).error == ""
    lists = [r.params for r in w.google.seen("GET", f"/calendars/{OWNER}/events")]
    assert all("syncToken" in p and "timeMin" not in p for p in lists) and len(lists) == 2  # deux pages de deux
    assert lists[1]["pageToken"] and lists[1]["syncToken"] == lists[0]["syncToken"]
    shown = w.shown()
    assert ("27/11 20:00", "Dîner avec Camille") not in shown and ("26/11 19:00", "Escalade") not in shown
    assert ("29/11 08:30", "Rando (annulée ?)") in shown and ("25/11 18:00", "Kiné") in shown
    w.google.expired_tokens.add(f"sync-{w.google.seq}")
    w.google.requests.clear()
    assert w.sync(10).error == ""  # 410 : tout relu
    lists = [r.params for r in w.google.seen("GET", f"/calendars/{OWNER}/events")]
    assert "syncToken" in lists[0] and "timeMin" in lists[1]
    assert ("25/11 18:00", "Kiné") in w.shown() and ("27/11 20:00", "Dîner avec Camille") not in w.shown()
    w.store.close()


# ── écrire ──────────────────────────────────────────────────────────────────


def test_creating_sends_only_to_google_and_keeps_her_mark_at_home(world):
    world.connect()
    world.sync()
    cal = world.cal()
    draft = EventDraft("Déjeuner avec Léa", Span(paris(2026, 12, 3, 12, 30), paris(2026, 12, 3, 14), "Europe/Paris"),
                       location="Chez Paul", conference="https://zoom.us/j/123456",
                       participants=(Participant("lea@example.org", "Léa"),), reminders=(Alert(15), Alert(1440, EMAIL)),
                       added=AddedBy(BY_HER, "fil:42", NOW))
    made = world.run(world.provider.create(world.account, cal, draft))
    sent = world.google.seen("POST", "/events")[-1]
    assert sent.params["sendUpdates"] == "all"
    assert sent.body["start"] == {"dateTime": "2026-12-03T12:30:00+01:00", "timeZone": "Europe/Paris"}
    assert sent.body["attendees"] == [{"email": "lea@example.org", "displayName": "Léa", "optional": False}]
    assert sent.body["reminders"] == {"useDefault": False, "overrides": [{"method": "popup", "minutes": 15},
                                                                      {"method": "email", "minutes": 1440}]}
    assert sent.body["description"] == "https://zoom.us/j/123456" and sent.body["location"] == "Chez Paul"
    assert "fil:42" not in str(sent.body) and "elle" not in str(sent.body).lower()  # sa marque ne part jamais
    assert made.added.ref == "fil:42" and made.organizer.me and made.conference == "https://zoom.us/j/123456"
    world.reread([made])
    assert world.store.find(cal.key, made.uid).added.by == BY_HER
    world.sync(10)  # Google le redit sans la marque : elle reste
    assert world.store.find(cal.key, made.uid).added.ref == "fil:42"


def test_changing_one_occurrence_the_following_or_all(world):
    _filled(world)
    cal = world.cal()
    series = world.store.find(cal.key, "esc")
    key = occurrence_key(paris(2026, 12, 24, 19), False)
    one = world.run(world.provider.edit(world.account, cal, series, key, EventChange(title="Escalade de Noël"), ONE))
    patch = world.google.seen("PATCH")[-1]
    assert patch.path.endswith("/events/esc_20261224T180000Z") and patch.body == {"summary": "Escalade de Noël"}
    assert patch.headers["if-match"] and patch.params["sendUpdates"] == "all"
    assert one.original == key and one.uid == "esc" and one.title == "Escalade de Noël"
    world.reread([one])
    assert ("24/12 19:00", "Escalade de Noël") in world.shown()
    # toute la série, depuis une occurrence : elle garde son premier jour et prend l'heure
    whole = world.run(world.provider.edit(world.account, cal, world.store.find(cal.key, "esc"), key, EventChange(
        span=Span(paris(2026, 12, 24, 18), paris(2026, 12, 24, 20), "Europe/Paris")), ALL))
    patch = world.google.seen("PATCH")[-1]
    assert patch.path.endswith("/events/esc")
    assert patch.body["start"] == {"dateTime": "2026-11-26T18:00:00+01:00", "timeZone": "Europe/Paris"}
    assert whole.span.start == paris(2026, 11, 26, 18)
    # celui-ci et les suivants : la suite créée d'abord, puis la série coupée la veille
    world.reread()
    key = occurrence_key(paris(2027, 1, 7, 18), False)
    after = world.run(world.provider.edit(world.account, cal, world.store.find(cal.key, "esc"), key,
                                          EventChange(location="Arkose Lille"), FOLLOWING))
    created, cut = world.google.seen("POST", "/events")[-1], world.google.seen("PATCH")[-1]
    assert world.google.requests.index(created) < world.google.requests.index(cut)
    assert created.body["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=TH"] and created.body["location"] == "Arkose Lille"
    assert created.body["start"]["dateTime"] == "2027-01-07T18:00:00+01:00"
    assert cut.body["recurrence"][0] == "RRULE:FREQ=WEEKLY;BYDAY=TH;UNTIL=20270107T165959Z"
    assert cut.body["recurrence"][1].startswith("EXDATE")
    assert after.recurrence.rule == "FREQ=WEEKLY;BYDAY=TH" and after.uid != "esc"
    world.reread()
    shown = world.shown(end=paris(2027, 1, 20))
    assert ("31/12 18:00", "Escalade") in shown and ("07/01 18:00", "Escalade") in shown
    assert world.store.find(cal.key, after.uid).location == "Arkose Lille"


def test_following_is_undone_when_cutting_the_series_fails(world):
    _filled(world)
    cal = world.cal()
    world.google.fail[("PATCH", "/calendar/v3/calendars/" + OWNER + "/events/esc")] = \
        lambda: httpx.Response(500, json={"error": {"code": 500, "message": "Backend Error"}})
    key = occurrence_key(paris(2026, 12, 24, 19), False)
    with pytest.raises(AgendaError, match="Google est en panne"):
        world.run(world.provider.edit(world.account, cal, world.store.find(cal.key, "esc"), key,
                                      EventChange(title="Escalade du soir"), FOLLOWING))
    made = [gid for gid in world.google.events[OWNER] if gid.startswith("new")]
    assert len(made) == 1 and world.google.seen("DELETE")[-1].path.endswith(f"/events/{made[0]}")
    assert world.google.events[OWNER][made[0]]["status"] == "cancelled"  # la suite retirée
    assert world.google.events[OWNER]["esc"]["recurrence"][0] == "RRULE:FREQ=WEEKLY;BYDAY=TH"  # la série intacte


def test_deleting_one_following_or_all(world):
    _filled(world)
    cal = world.cal()
    key = occurrence_key(paris(2026, 12, 24, 19), False)
    assert world.run(world.provider.delete(world.account, cal, world.store.find(cal.key, "esc"), key, ONE)) == 1
    assert world.google.seen("DELETE")[-1].path.endswith("/events/esc_20261224T180000Z")
    world.reread()
    assert ("24/12 19:00", "Escalade") not in world.shown() and ("31/12 19:00", "Escalade") in world.shown()
    key = occurrence_key(paris(2026, 12, 31, 19), False)
    world.run(world.provider.delete(world.account, cal, world.store.find(cal.key, "esc"), key, FOLLOWING))
    assert world.google.seen("PATCH")[-1].body["recurrence"][0] == "RRULE:FREQ=WEEKLY;BYDAY=TH;UNTIL=20261231T175959Z"
    world.reread()
    assert ("31/12 19:00", "Escalade") not in world.shown(end=paris(2027, 2, 1))
    world.run(world.provider.delete(world.account, cal, world.store.find(cal.key, "esc"), "", ALL))
    world.reread()
    assert not [s for s in world.shown() if s[1].startswith("Escalade")]
    assert world.store.series(cal.key, "esc") == []


def test_an_invitation_is_answered_not_changed_and_deleting_it_declines(world):
    _filled(world)
    cal = world.cal()
    rando = world.store.find(cal.key, "rando")
    with pytest.raises(AgendaError, match="se modifie chez qui l'organise"):
        world.run(world.provider.edit(world.account, cal, rando, "", EventChange(title="Autre"), ALL))
    world.run(world.provider.edit(world.account, cal, rando, "", EventChange(reminders=(Alert(60),)), ALL))  # à soi
    out = world.run(world.provider.respond(world.account, cal, rando, "", YES, ALL, "Je prends les sandwichs"))
    patch = world.google.seen("PATCH")[-1]
    me = next(a for a in patch.body["attendees"] if a.get("self"))
    assert me["responseStatus"] == "accepted" and me["comment"] == "Je prends les sandwichs"
    assert patch.params["sendUpdates"] == "all" and out.response == YES
    assert len(patch.body["attendees"]) == 4  # les autres invités, la salle comprise, restent tels quels
    assert world.run(world.provider.delete(world.account, cal, world.store.find(cal.key, "rando"), "", ALL)) == 1
    me = next(a for a in world.google.seen("PATCH")[-1].body["attendees"] if a.get("self"))
    assert me["responseStatus"] == "declined" and not world.google.seen("DELETE")
    world.reread()
    assert world.store.find(cal.key, "rando").response == NO
    assert ("29/11 08:30", "Rando · boucle des Monts") not in world.shown()  # refusé : caché
    with pytest.raises(AgendaError, match="rien à répondre"):
        world.run(world.provider.respond(world.account, cal, world.store.find(cal.key, "diner"), "", YES))


def test_a_conflict_is_said_and_the_copy_reread(world):
    _filled(world)
    cal = world.cal()
    diner = world.store.find(cal.key, "diner")
    world.google.fail[("PATCH", f"/calendar/v3/calendars/{OWNER}/events/diner")] = lambda: httpx.Response(
        412, json={"error": {"code": 412, "message": "Precondition Failed",
                             "errors": [{"reason": "conditionNotMet"}]}})
    with pytest.raises(AgendaError, match="a changé chez Google pendant qu'on l'écrivait"):
        world.run(world.provider.edit(world.account, cal, diner, "", EventChange(title="Dîner chez Paul"), ALL))
    del world.google.fail[("PATCH", f"/calendar/v3/calendars/{OWNER}/events/diner")]
    world.google.remove(OWNER, "diner")
    with pytest.raises(AgendaError, match="n'existe plus chez Google"):
        world.run(world.provider.edit(world.account, cal, diner, "", EventChange(title="Dîner chez Paul"), ALL))
    world.reread()
    assert world.store.find(cal.key, "diner") is None


def test_a_read_only_calendar_refuses_and_nothing_goes_elsewhere(world):
    world.connect()
    world.sync()
    feries = world.cal("Jours fériés en France")
    with pytest.raises(AgendaError, match="lecture seule"):
        world.run(world.provider.create(world.account, feries, EventDraft("x", Span(NOW, NOW + MINUTE))))
    api = Api("Google", ("www.googleapis.com",))
    assert api.allowed("https://www.googleapis.com/calendar/v3/x")
    assert not api.allowed("http://www.googleapis.com/calendar/v3/x") and not api.allowed("https://evil.example/x")
    assert not api.allowed("https://www.googleapis.com:8443/x")

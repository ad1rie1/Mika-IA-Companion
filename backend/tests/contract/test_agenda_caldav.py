"""CalDAV (ADR 0309, lot 1), ``adapters/agenda/caldav.py`` : un serveur d'agendas, joint par un faux serveur en
mémoire (``tests/fixtures/caldav_server.py``, un transport ``httpx`` factice), sur le vrai magasin et ``agenda.sync``.

- la découverte passe par ``/.well-known/caldav``, le principal (ses adresses : qui est le compte parmi les invités)
  et la maison ; seuls les agendas d'événements se listent (pas une liste de tâches), avec leur nom, leur couleur et
  s'ils s'écrivent ; le principal est celui où les invitations arrivent ; une adresse qui est un agenda (DavMail) est
  cet agenda seul ;
- la première synchronisation relit tout (un lot complet), les suivantes par ``sync-collection`` : ce qui change, ce
  qui part, une exception qu'une ressource n'a plus ; un jeton périmé fait tout relire ; sans ``sync-collection``,
  les ETag se comparent, et rien ne se demande quand le ``getctag`` n'a pas bougé ;
- créer, modifier (cet événement, celui-ci et les suivants, tous) et supprimer passent chez le serveur avec leur ETag ;
  une invitation ne se modifie que chez qui l'organise et, supprimée, est refusée ; répondre pose le PARTSTAT du compte
  quand le serveur le transmet, et le refuse en mots sinon ;
- un conflit (412) et un événement disparu se disent en mots, et la copie relue (``reread``) suit le serveur ; ce que
  Mika a ajouté reste marqué ;
- un mot de passe refusé, un serveur injoignable, une adresse qui n'est pas un serveur CalDAV se disent en mots ; le
  mot de passe part chez un hôte du même domaine (iCloud), jamais ailleurs ; une adresse qui mène à une machine privée
  est refusée.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from mika.adapters.agenda import AgendaStore, CalDavProvider, Web
from mika.plugins.agenda import AgendaParams
from mika.plugins.agenda.sync import reread, sync_account
from mika.ports.agenda import (
    ALL,
    BY_HER,
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
from tests.fixtures import backend
from tests.fixtures.caldav_server import FakeCalDav

PARIS = ZoneInfo("Europe/Paris")
NOW = us_of(datetime(2026, 11, 23, 15, tzinfo=PARIS))
HOUR = 3600 * US_PER_S
MINUTE = 60 * US_PER_S


def paris(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> int:
    return us_of(datetime(y, m, d, h, mi, tzinfo=PARIS))


def local(us: int) -> str:
    return at_us(us, PARIS).strftime("%d/%m %H:%M")


SERIES = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Apple Inc.//iOS 18.0//EN
BEGIN:VEVENT
UID:serie@example.org
DTSTART;TZID=Europe/Paris:20261130T100000
DTEND;TZID=Europe/Paris:20261130T110000
RRULE:FREQ=WEEKLY;COUNT=5
SUMMARY:Yoga
LOCATION:Salle B
END:VEVENT
BEGIN:VEVENT
UID:serie@example.org
RECURRENCE-ID;TZID=Europe/Paris:20261207T100000
DTSTART;TZID=Europe/Paris:20261207T180000
DTEND;TZID=Europe/Paris:20261207T190000
SUMMARY:Yoga (le soir)
END:VEVENT
END:VCALENDAR
"""

INVITE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example//Mail//EN
BEGIN:VEVENT
UID:invite@example.com
DTSTART:20261202T130000Z
DTEND:20261202T140000Z
SUMMARY:Revue du devis
ORGANIZER;CN=Sophie:mailto:sophie@example.com
ATTENDEE;CN=Sophie;PARTSTAT=ACCEPTED:mailto:sophie@example.com
ATTENDEE;CN=Adrien;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:adrien@example.org
END:VEVENT
END:VCALENDAR
"""


DENTIST = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Apple Inc.//iOS 18.0//EN
BEGIN:VEVENT
UID:dent@example.org
DTSTART;TZID=Europe/Paris:20261201T100000
DTEND;TZID=Europe/Paris:20261201T103000
SUMMARY:Dentiste
END:VEVENT
END:VCALENDAR
"""


class World:
    def __init__(self, tmp, server: FakeCalDav, *, url: str = "https://caldav.example.org/", **web) -> None:
        self.server = server
        self.store = AgendaStore(backend.target(tmp, "agenda"), now=lambda: NOW)
        self.clock = [NOW]
        self.ids = iter(f"id{i:04d}" for i in range(1000))
        self.provider = CalDavProvider(Web(transport=server.transport(), **web), now=lambda: self.clock[0],
                                       new_id=lambda: next(self.ids))
        self.account = Connection("pro", "caldav", url=url, username="adrien", secret="secret",
                                  address="adrien@example.org", label="Adrien")
        self.store.keep_account("pro", "caldav", address="adrien@example.org")

    def sync(self, minutes: int = 0):
        self.clock[0] = NOW + minutes * MINUTE
        return asyncio.run(sync_account(self.store, self.provider, self.account, AgendaParams(), self.clock[0]))

    def cal(self, name: str = "Perso"):
        return next(c for c in self.store.calendars("pro") if c.name == name)

    def shown(self, start: int = 0, end: int = 0, name: str = "Perso") -> list[tuple[str, str]]:
        start = start or paris(2026, 11, 1)
        end = end or paris(2027, 3, 1)
        return [(local(o.span.start), o.event.title) for o in self.store.period([self.cal(name).key], start, end)]

    def run(self, coro):
        return asyncio.run(coro)

    def reread(self, kept=()):
        return asyncio.run(reread(self.store, self.provider, self.account, self.cal().key, AgendaParams(),
                                  self.clock[0], kept))


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path, FakeCalDav())
    yield w
    w.store.close()


def test_discovery_lists_the_event_calendars_with_their_name_colour_and_rights(world):
    state = world.sync()
    assert state.error == ""
    cals = {c.name: c for c in world.store.calendars("pro")}
    assert set(cals) == {"Perso", "Fériés"}  # « Tâches » ne porte que des VTODO
    assert cals["Perso"].primary and not cals["Fériés"].primary  # celui où ses invitations arrivent
    assert cals["Perso"].color == "#3366cc" and cals["Fériés"].color == "#ff2968"
    assert cals["Perso"].writable and not cals["Fériés"].writable
    assert cals["Perso"].remote == "https://caldav.example.org/dav/calendars/adrien/perso/"
    assert cals["Perso"].key.startswith("pro~h") and "/" not in cals["Perso"].key  # jamais une adresse
    paths = [r.path for r in world.server.requests]
    assert "/.well-known/caldav" in paths and "/dav/principals/adrien/" in paths
    assert world.provider.abilities(world.account).invite


def test_an_address_that_is_a_calendar_is_that_calendar_alone(tmp_path):
    w = World(tmp_path, FakeCalDav(), url="https://caldav.example.org/dav/calendars/adrien/perso/")
    assert w.sync().error == ""
    assert [c.name for c in w.store.calendars("pro")] == ["Perso"] and w.cal().primary
    w.store.close()


def test_the_first_sync_reads_everything_then_only_what_changed(world):
    world.server.put("perso", "yoga.ics", SERIES)
    world.sync()
    assert world.shown() == [("30/11 10:00", "Yoga"), ("07/12 18:00", "Yoga (le soir)"), ("14/12 10:00", "Yoga"),
                             ("21/12 10:00", "Yoga"), ("28/12 10:00", "Yoga")]
    assert world.cal().cursor.startswith("token:tok-")
    world.server.put("perso", "yoga.ics", SERIES.split("BEGIN:VEVENT\nUID:serie@example.org\nRECURRENCE-ID")[0]
                     + "END:VCALENDAR\n")  # l'exception part de la ressource
    world.server.put("perso", "dentiste.ics", DENTIST)
    world.server.requests.clear()
    world.sync(10)
    reports = [r.body for r in world.server.seen("REPORT")]
    assert any(b"sync-collection" in b for b in reports) and not any(b"calendar-query" in b for b in reports)
    assert ("07/12 10:00", "Yoga") in world.shown() and ("01/12 10:00", "Dentiste") in world.shown()
    assert ("07/12 18:00", "Yoga (le soir)") not in world.shown()
    world.server.remove("perso", "dentiste.ics")
    world.sync(20)
    assert ("01/12 10:00", "Dentiste") not in world.shown()


def test_an_expired_token_reads_everything_again(world):
    world.server.put("perso", "yoga.ics", SERIES)
    world.sync()
    cal = world.cal()
    world.store.set_cursor(cal.key, "token:tok-999")
    world.server.requests.clear()
    assert world.sync(10).error == ""
    assert any(b"calendar-query" in r.body for r in world.server.seen("REPORT"))
    assert world.cal().cursor == f"token:tok-{world.server.token}" and len(world.shown()) == 5


def test_without_sync_collection_the_etags_are_compared(tmp_path):
    w = World(tmp_path, FakeCalDav(sync=False))
    w.server.put("perso", "yoga.ics", SERIES)
    w.sync()
    assert w.cal().cursor.startswith("etags:") and len(w.shown()) == 5
    w.server.requests.clear()
    w.sync(10)  # rien n'a bougé : le getctag le dit, rien ne se demande
    assert w.server.seen("REPORT") == []
    w.server.put("perso", "yoga.ics", SERIES.replace("Salle B", "Salle C"))
    w.sync(20)
    multiget = [r.body for r in w.server.seen("REPORT") if b"calendar-multiget" in r.body]
    assert len(multiget) == 1 and b"yoga.ics" in multiget[0]
    assert w.store.period([w.cal().key], paris(2026, 11, 30), paris(2026, 12, 1))[0].event.location == "Salle C"
    w.server.remove("perso", "yoga.ics")
    w.sync(30)
    assert w.shown() == []
    w.store.close()


def _series(world):
    world.server.put("perso", "yoga.ics", SERIES)
    world.sync()
    return world.store.find(world.cal().key, "serie@example.org")


def test_creating_an_event_puts_a_new_resource_and_keeps_her_mark(world):
    world.sync()
    cal = world.cal()
    draft = EventDraft("Déjeuner avec Léa", Span(paris(2026, 12, 3, 12, 30), paris(2026, 12, 3, 14), "Europe/Paris"),
                       location="Chez Paul", participants=(Participant("lea@example.org", "Léa"),),
                       reminders=(Alert(15),), added=AddedBy(BY_HER, "fil:42", NOW))
    made = world.run(world.provider.create(world.account, cal, draft))
    put = world.server.seen("PUT")[-1]
    assert put.headers["if-none-match"] == "*" and put.path == "/dav/calendars/adrien/perso/id0000.ics"
    assert made.uid == "id0000@mika" and made.etag and made.added.ref == "fil:42"
    assert made.organizer.me and [(p.address, p.response) for p in made.participants] == [("lea@example.org", NEEDS)]
    world.reread([made])
    row = world.store.find(cal.key, made.uid)
    assert row.added is not None and row.added.by == BY_HER and row.location == "Chez Paul"
    world.sync(10)  # le serveur le redit sans la marque : elle reste
    assert world.store.find(cal.key, made.uid).added.ref == "fil:42"


def test_changing_one_occurrence_writes_an_exception(world):
    master = _series(world)
    key = occurrence_key(paris(2026, 12, 14, 10), False)
    out = world.run(world.provider.edit(world.account, world.cal(), master, key,
                                        EventChange(title="Yoga (dehors)", location="Parc"), ONE))
    assert out.original == key and out.title == "Yoga (dehors)"
    assert world.server.seen("PUT")[-1].headers["if-match"]
    assert "RECURRENCE-ID;TZID=Europe/Paris:20261214T100000" in world.server.text("perso", "yoga.ics")
    world.reread()
    assert ("14/12 10:00", "Yoga (dehors)") in world.shown() and ("21/12 10:00", "Yoga") in world.shown()


def test_changing_all_from_an_occurrence_keeps_the_first_day_and_moves_the_exceptions(world):
    master = _series(world)
    key = occurrence_key(paris(2026, 12, 14, 10), False)
    world.run(world.provider.edit(world.account, world.cal(), master, key, EventChange(
        span=Span(paris(2026, 12, 14, 11), paris(2026, 12, 14, 12), "Europe/Paris"), title="Yoga doux"), ALL))
    world.reread()
    assert world.shown() == [("30/11 11:00", "Yoga doux"), ("07/12 18:00", "Yoga (le soir)"),
                             ("14/12 11:00", "Yoga doux"), ("21/12 11:00", "Yoga doux"), ("28/12 11:00", "Yoga doux")]
    assert "RECURRENCE-ID;TZID=Europe/Paris:20261207T110000" in world.server.text("perso", "yoga.ics")


def test_changing_this_and_the_following_splits_the_series(world):
    master = _series(world)
    key = occurrence_key(paris(2026, 12, 14, 10), False)
    out = world.run(world.provider.edit(world.account, world.cal(), master, key,
                                        EventChange(title="Yoga (nouveau prof)"), FOLLOWING))
    assert out.uid == "id0000@mika" and out.recurrence.rule == "FREQ=WEEKLY;COUNT=3"
    puts = world.server.seen("PUT")
    assert puts[-2].headers["if-none-match"] == "*" and puts[-1].headers["if-match"]  # la suite d'abord
    world.reread()
    assert world.shown() == [("30/11 10:00", "Yoga"), ("07/12 18:00", "Yoga (le soir)"),
                             ("14/12 10:00", "Yoga (nouveau prof)"), ("21/12 10:00", "Yoga (nouveau prof)"),
                             ("28/12 10:00", "Yoga (nouveau prof)")]


def test_a_failed_cut_takes_back_the_new_series(world):
    master = _series(world)
    world.server.fail[("PUT", "/dav/calendars/adrien/perso/yoga.ics")] = lambda: httpx.Response(412)
    with pytest.raises(AgendaError, match="a changé chez le fournisseur"):
        world.run(world.provider.edit(world.account, world.cal(), master,
                                      occurrence_key(paris(2026, 12, 14, 10), False), EventChange(title="x"),
                                      FOLLOWING))
    assert set(world.server.collections["perso"].items) == {"yoga.ics"}


def test_deleting_one_following_or_all(world):
    master = _series(world)
    n = world.run(world.provider.delete(world.account, world.cal(), master,
                                        occurrence_key(paris(2026, 11, 30, 10), False), ONE))
    world.reread()
    assert n == 1 and world.shown()[0] == ("07/12 18:00", "Yoga (le soir)")
    master = world.store.find(world.cal().key, "serie@example.org")
    world.run(world.provider.delete(world.account, world.cal(), master,
                                    occurrence_key(paris(2026, 12, 21, 10), False), FOLLOWING))
    world.reread()
    assert world.shown() == [("07/12 18:00", "Yoga (le soir)"), ("14/12 10:00", "Yoga")]
    master = world.store.find(world.cal().key, "serie@example.org")
    world.run(world.provider.delete(world.account, world.cal(), master, "", ALL))
    assert world.server.seen("DELETE")[-1].headers["if-match"] and world.server.collections["perso"].items == {}
    world.reread()
    assert world.shown() == []


def test_an_invitation_is_answered_and_not_edited_and_deleting_it_declines_it(world):
    world.server.put("perso", "invite.ics", INVITE)
    world.sync()
    invite = world.store.find(world.cal().key, "invite@example.com")
    assert invite.response == NEEDS and world.store.invitations([world.cal().key])[0].uid == invite.uid
    with pytest.raises(AgendaError, match="chez qui l'organise"):
        world.run(world.provider.edit(world.account, world.cal(), invite, "", EventChange(title="Autre")))
    world.run(world.provider.edit(world.account, world.cal(), invite, "", EventChange(reminders=(Alert(30, EMAIL),))))
    assert "ACTION:EMAIL" in world.server.text("perso", "invite.ics")  # ses rappels sont à elle
    out = world.run(world.provider.respond(world.account, world.cal(), invite, "", YES, comment="J'y serai"))
    assert out.response == YES
    text = world.server.text("perso", "invite.ics")
    assert "PARTSTAT=ACCEPTED" in text.split("mailto:adrien@example.org")[0].rsplit("ATTENDEE", 1)[1]
    assert "COMMENT:J'y serai" in text and "RSVP=TRUE" not in text
    world.run(world.provider.delete(world.account, world.cal(), out, "", ALL))
    assert "invite.ics" in world.server.collections["perso"].items  # gardée, refusée
    world.reread()
    assert world.store.find(world.cal().key, "invite@example.com").response == NO
    assert world.shown() == []  # refusée : elle ne se montre plus


def test_answering_is_offered_only_once_the_server_is_known_to_tell_the_organizer(world):
    assert not world.provider.abilities(world.account).invite  # pas encore découvert : rien ne dit qu'elle aboutirait
    world.sync()
    assert world.provider.abilities(world.account).invite


def test_answering_where_the_server_tells_nobody_is_refused_in_words(tmp_path):
    w = World(tmp_path, FakeCalDav(schedules=False))
    w.server.put("perso", "invite.ics", INVITE)
    w.sync()
    invite = w.store.find(w.cal().key, "invite@example.com")
    with pytest.raises(AgendaError, match="ne transmet pas les réponses"):
        w.run(w.provider.respond(w.account, w.cal(), invite, "", YES))
    assert not w.provider.abilities(w.account).invite
    w.store.close()


def test_a_conflict_and_a_vanished_event_are_said_and_the_copy_follows(world):
    master = _series(world)
    world.server.fail[("PUT", "/dav/calendars/adrien/perso/yoga.ics")] = lambda: httpx.Response(412)
    with pytest.raises(AgendaError, match="« Yoga » a changé chez le fournisseur"):
        world.run(world.provider.edit(world.account, world.cal(), master, "", EventChange(location="Salle Z")))
    world.server.put("perso", "yoga.ics", SERIES.replace("SUMMARY:Yoga\n", "SUMMARY:Yoga (changé ailleurs)\n"))
    world.reread()
    assert world.shown()[0] == ("30/11 10:00", "Yoga (changé ailleurs)")
    world.server.remove("perso", "yoga.ics")
    with pytest.raises(AgendaError, match="n'existe plus chez le fournisseur"):
        world.run(world.provider.edit(world.account, world.cal(), master, "", EventChange(location="Salle Z")))
    world.reread()
    assert world.shown() == []


def test_a_read_only_calendar_refuses_writing_in_words(world):
    world.sync()
    with pytest.raises(AgendaError, match="lecture seule"):
        world.run(world.provider.create(world.account, world.cal("Fériés"), EventDraft("x", Span(NOW, NOW + HOUR))))


def test_a_refused_password_an_unreachable_server_and_a_non_caldav_address_are_said_in_words(tmp_path):
    w = World(tmp_path, FakeCalDav(password="autre"))
    assert w.sync().error == "identifiant ou mot de passe refusé par caldav.example.org"
    w.store.close()

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    w = World(tmp_path / "b", FakeCalDav())
    w.provider = CalDavProvider(Web(transport=httpx.MockTransport(down)), now=lambda: NOW)
    assert w.sync().error == "le serveur CalDAV est injoignable (caldav.example.org)"
    w.store.close()
    w = World(tmp_path / "c", FakeCalDav(), url="https://ailleurs.example.net/")
    w.provider = CalDavProvider(Web(transport=httpx.MockTransport(lambda r: httpx.Response(404))), now=lambda: NOW)
    assert "n'est pas un serveur CalDAV" in w.sync().error
    w.store.close()


async def _public(host: str, port: int) -> list[str]:
    return ["93.184.216.34"]


async def _private(host: str, port: int) -> list[str]:
    return ["10.0.0.5"]


def test_the_password_goes_to_a_host_of_the_same_domain_only(tmp_path):
    server = FakeCalDav(home_host="p07-caldav.example.org")
    w = World(tmp_path, server, resolve=_public, local=())
    assert w.sync().error == ""
    sibling = [r for r in server.requests if r.host == "p07-caldav.example.org"]
    assert sibling and all("authorization" in r.headers for r in sibling)
    w.store.close()
    foreign = FakeCalDav(home_host="collecte.example.net")
    w = World(tmp_path / "b", foreign, resolve=_public, local=())
    w.sync()
    assert all("authorization" not in r.headers for r in foreign.requests if r.host == "collecte.example.net")
    w.store.close()


def test_an_address_given_by_the_server_that_leads_to_a_private_machine_is_refused(tmp_path):
    server = FakeCalDav(home_host="intranet.example.org")
    w = World(tmp_path, server, resolve=_private, local=())
    state = w.sync()
    assert "intranet.example.org" in state.error and "machine privée ou locale" in state.error
    assert not any(r.host == "intranet.example.org" for r in server.requests)
    w.store.close()

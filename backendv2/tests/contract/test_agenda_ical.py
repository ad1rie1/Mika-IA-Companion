"""L'abonnement iCal (ADR 0309, lot 1), ``adapters/agenda/ical.py`` : une adresse ``.ics`` en lecture seule, relue
par ``agenda.sync`` sur le vrai magasin, contre un faux serveur (un transport ``httpx`` factice).

- ``webcal://`` se lit ``https://`` ; un agenda par adresse, nommé comme le fichier le dit, en lecture seule ; ni son
  adresse dans la base ni dans une erreur (seul son hôte) ;
- un passage ne télécharge le fichier qu'une fois (``calendars`` puis ``sync``) ; relu, il est redemandé avec
  ``If-None-Match`` et ``If-Modified-Since`` : un 304, ou le même contenu, ne réécrit rien ; changé, la copie suit
  (ce qu'il ne dit plus part) ;
- un fichier trop gros n'est pas lu et la copie d'avant reste, en le disant ; une page web, une adresse refusée, un
  serveur injoignable se disent en mots sur le compte ;
- une redirection vers une machine privée est refusée ;
- écrire est refusé en mots.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from mika.adapters.agenda import AgendaStore, IcalProvider, Providers, Web
from mika.adapters.agenda.ical import ICAL_CALENDAR, ICS_MAX
from mika.plugins.agenda import AgendaParams
from mika.plugins.agenda.sync import sync_account
from mika.ports.agenda import (
    US_PER_S,
    AgendaError,
    Connection,
    EventDraft,
    Span,
    calendar_key,
    day_at,
    us_of,
)
from tests.fixtures import backend

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "agenda"
PARIS = ZoneInfo("Europe/Paris")
NOW = us_of(datetime(2026, 11, 23, 15, tzinfo=PARIS))
HOUR = 3600 * US_PER_S
SECRET = "https://calendar.example.com/calendar/ical/secret-0123456789abcdef/basic.ics"


def paris(y: int, m: int, d: int, h: int = 0) -> int:
    return us_of(datetime(y, m, d, h, tzinfo=PARIS))


class Feed:
    """Un serveur d'abonnement : un fichier, son ETag et sa date ; il répond 304 quand on les lui redit."""

    def __init__(self, body: bytes, *, status: int = 200) -> None:
        self.body, self.status = body, status
        self.etag, self.modified = '"v1"', "Mon, 23 Nov 2026 10:00:00 GMT"
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, text="<html>non</html>")
        if request.headers.get("if-none-match") == self.etag:
            return httpx.Response(304)
        return httpx.Response(200, content=self.body, headers={"ETag": self.etag, "Last-Modified": self.modified,
                                                               "Content-Type": "text/calendar"})


class World:
    def __init__(self, tmp: Path, feed: Feed, *, url: str = SECRET) -> None:
        self.store = AgendaStore(backend.target(tmp, "agenda"), now=lambda: NOW)
        self.feed = feed
        self.clock = [NOW]
        self.provider = IcalProvider(Web(transport=httpx.MockTransport(feed.handle)), now=lambda: self.clock[0])
        self.account = Connection("feries", "ical", label="Jours fériés", url=url)
        self.providers = Providers(self.store, lambda: [self.account])
        self.providers.add(self.provider)
        self.store.keep_account("feries", "ical")

    def sync(self, at: int = NOW):
        self.clock[0] = at
        return asyncio.run(sync_account(self.store, self.provider, self.account, AgendaParams(), at))

    @property
    def calendar(self) -> str:
        return calendar_key("feries", ICAL_CALENDAR)

    def shown(self, start: int, end: int) -> list[str]:
        return [o.event.title for o in self.store.period([self.calendar], start, end)]


@pytest.fixture
def holidays(tmp_path):
    w = World(tmp_path, Feed((FIXTURES / "feries-france-google.ics").read_bytes()),
              url=SECRET.replace("https://", "webcal://"))
    yield w
    w.store.close()


def test_a_webcal_address_reads_as_one_read_only_calendar_named_by_its_file(holidays):
    state = holidays.sync()
    assert state.error == "" and state.synced_at == NOW
    assert holidays.feed.requests[0].url.scheme == "https"
    [cal] = holidays.store.calendars("feries")
    assert (cal.key, cal.name, cal.writable, cal.primary) == (
        holidays.calendar, "Jours fériés et autres fêtes en France", False, True)
    assert cal.remote == ""  # l'adresse, secrète, ne se range pas dans la base
    assert holidays.shown(paris(2026, 12, 20), paris(2027, 1, 5)) == [
        "La veille de Noël", "Noël", "la Saint-Sylvestre", "Jour de l'an"]
    # ce qui a fini avant la fenêtre (90 jours derrière) n'est pas rangé
    assert holidays.shown(paris(2021, 1, 1), paris(2026, 1, 1)) == []


def test_a_pass_downloads_once_and_a_reread_asks_with_its_validators(holidays):
    holidays.sync()
    assert len(holidays.feed.requests) == 1  # calendars puis sync : un seul téléchargement
    before = holidays.store.calendar(holidays.calendar).cursor
    holidays.sync(NOW + 2 * HOUR)
    again = holidays.feed.requests[-1]
    assert again.headers["if-none-match"] == '"v1"'
    assert again.headers["if-modified-since"] == "Mon, 23 Nov 2026 10:00:00 GMT"
    assert holidays.store.calendar(holidays.calendar).cursor == before
    assert "Noël" in holidays.shown(paris(2026, 12, 20), paris(2026, 12, 31))


def test_after_a_restart_the_same_file_rewrites_nothing(holidays, tmp_path):
    holidays.sync()
    changed: list[object] = []
    holidays.store.on_change(changed.append)
    fresh = IcalProvider(Web(transport=httpx.MockTransport(holidays.feed.handle)), now=lambda: NOW + HOUR)
    asyncio.run(sync_account(holidays.store, fresh, holidays.account, AgendaParams(), NOW + HOUR))
    assert not any(getattr(c, "keys", ()) and holidays.calendar in c.keys for c in changed)


def test_a_changed_file_replaces_the_copy(holidays):
    holidays.sync()
    text = holidays.feed.body.decode()
    holidays.feed.body = text.replace("SUMMARY:Noël", "SUMMARY:Noël (férié)").encode()
    holidays.feed.etag = '"v2"'
    holidays.sync(NOW + 2 * HOUR)
    assert holidays.shown(day_at("2026-12-25"), day_at("2026-12-27")) == ["Noël (férié)"]
    start = text.index("BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20270101")
    holidays.feed.body = (text[:start] + text[text.index("END:VEVENT", start) + len("END:VEVENT\r\n"):]).encode()
    holidays.feed.etag = '"v3"'
    holidays.sync(NOW + 4 * HOUR)
    assert holidays.shown(day_at("2027-01-01"), day_at("2027-01-02")) == []


def test_a_file_too_big_is_not_read_and_the_old_copy_stays(holidays):
    holidays.sync()
    holidays.feed.body = b"BEGIN:VCALENDAR\r\n" + b"X" * (ICS_MAX + 10)
    holidays.feed.etag = '"gros"'
    state = holidays.sync(NOW + 2 * HOUR)
    assert "pèse plus de 10 Mo" in state.error and "la copie d'avant reste" in state.error
    assert "Noël" in holidays.shown(paris(2026, 12, 20), paris(2026, 12, 31))


@pytest.mark.parametrize(("status", "body", "words"), [
    (200, b"<!doctype html><html>Connexion</html>", "ne donne pas un agenda"),
    (401, b"", "refuse cette adresse"),
    (404, b"", "introuvable"),
    (503, b"", "en panne"),
])
def test_what_goes_wrong_is_said_in_words_without_the_secret_address(tmp_path, status, body, words):
    feed = Feed(body, status=status)
    w = World(tmp_path, feed)
    state = w.sync()
    assert words in state.error and "calendar.example.com" in state.error
    assert "secret-0123456789abcdef" not in state.error
    w.store.close()


def test_an_unreachable_server_is_said_in_words(tmp_path):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    w = World(tmp_path, Feed(b""))
    w.provider = IcalProvider(Web(transport=httpx.MockTransport(down)), now=lambda: NOW)
    state = w.sync()
    assert state.error == "l'abonnement est injoignable (calendar.example.com)"
    w.store.close()


def test_a_redirect_to_a_private_machine_is_refused(tmp_path):
    def moved(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://intranet.lan/agenda.ics"})

    async def lan(host: str, port: int) -> list[str]:
        return ["192.168.1.10"]

    w = World(tmp_path, Feed(b""))
    w.provider = IcalProvider(Web(transport=httpx.MockTransport(moved), resolve=lan, local=()), now=lambda: NOW)
    state = w.sync()
    assert "intranet.lan" in state.error and "machine privée ou locale" in state.error
    w.store.close()


def test_an_account_on_internet_only_rechecks_its_own_host_at_each_connection(tmp_path):
    answers = iter([["93.184.216.34"], ["127.0.0.1"]])  # publique à la première synchro, puis la machine (rebinding)

    async def rebinding(host: str, port: int) -> list[str]:
        return next(answers)

    feed = Feed((FIXTURES / "feries-france-google.ics").read_bytes())
    w = World(tmp_path, feed)
    w.provider = IcalProvider(Web(transport=httpx.MockTransport(feed.handle), resolve=rebinding, local=()),
                              now=lambda: NOW)
    w.account = replace(w.account, internet=True)  # réglé par une personne qui n'est pas opératrice
    assert w.sync().error == ""
    assert feed.requests[-1].url.host == "93.184.216.34"  # l'adresse vérifiée, épinglée
    assert feed.requests[-1].headers["host"] == "calendar.example.com"
    state = w.sync(NOW + 3600 * US_PER_S)
    assert "calendar.example.com" in state.error and "machine privée ou locale" in state.error
    assert len(feed.requests) == 1  # rien n'est parti vers la machine
    w.store.close()


def test_an_operators_account_joins_its_own_host_as_she_chose(tmp_path):
    async def unasked(host: str, port: int) -> list[str]:
        raise AssertionError("l'hôte d'une opératrice n'est pas résolu par Mika")

    feed = Feed((FIXTURES / "feries-france-google.ics").read_bytes())
    w = World(tmp_path, feed)
    w.provider = IcalProvider(Web(transport=httpx.MockTransport(feed.handle), resolve=unasked, local=()),
                              now=lambda: NOW)
    assert w.sync().error == "" and feed.requests[-1].url.host == "calendar.example.com"
    w.store.close()


def test_writing_to_a_subscription_is_refused_in_words(holidays):
    holidays.sync()
    cal = holidays.store.calendar(holidays.calendar)
    with pytest.raises(AgendaError, match="se lit seulement"):
        asyncio.run(holidays.provider.create(holidays.account, cal, EventDraft("x", Span(NOW, NOW + HOUR))))
    assert holidays.provider.abilities(holidays.account).write is False

"""CalDAV contre un vrai serveur (ADR 0309, lot 1) : Radicale, lancé à part (jamais par la suite) et désigné par
``MIKA_TEST_RADICALE`` (``http://<identifiant>:<mot de passe>@127.0.0.1:<port>/``) ; sans elle, sauté.

Sur un agenda neuf, créé pour l'essai et retiré après : la découverte, une série créée, changée pour cet événement,
pour tous depuis une occurrence, puis à partir d'une occurrence (la série coupée), une occurrence et un événement
supprimés, la copie relue par ``sync-collection`` (RFC 6578) ; répondre refusé en mots (Radicale ne transmet pas les
réponses, RFC 6638) ; un vrai conflit (412 : un autre client écrit entre la lecture et l'écriture) dit en mots, la
copie relue ensuite.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx
import pytest

from mika.adapters.agenda import AgendaStore, CalDavProvider, Web
from mika.plugins.agenda import AgendaParams
from mika.plugins.agenda.sync import reread, sync_account
from mika.ports.agenda import (
    ALL,
    EMAIL,
    FOLLOWING,
    ONE,
    US_PER_S,
    YES,
    AgendaError,
    Alert,
    Connection,
    EventChange,
    EventDraft,
    Span,
    at_us,
    occurrence_key,
    us_of,
)
from tests.fixtures import backend

RADICALE = os.environ.get("MIKA_TEST_RADICALE", "")
pytestmark = pytest.mark.skipif(not RADICALE, reason="MIKA_TEST_RADICALE : un Radicale lancé à part")

PARIS = ZoneInfo("Europe/Paris")
MINUTE = 60 * US_PER_S


def paris(y: int, m: int, d: int, h: int = 0) -> int:
    return us_of(datetime(y, m, d, h, tzinfo=PARIS))


class Intruder(httpx.AsyncBaseTransport):
    """Le vrai réseau ; ``armed`` : au prochain PUT avec ``If-Match``, un autre client réécrit d'abord la ressource."""

    def __init__(self, auth: tuple[str, str]) -> None:
        self.inner = httpx.AsyncHTTPTransport()
        self.auth = auth
        self.armed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.armed and request.method == "PUT" and "if-match" in request.headers:
            self.armed = False
            async with httpx.AsyncClient(auth=self.auth) as other:
                got = await other.get(str(request.url))
                await other.put(str(request.url), content=got.text.replace("SUMMARY:", "SUMMARY:(ailleurs) "),
                                headers={"Content-Type": "text/calendar"})
        return await self.inner.handle_async_request(request)


@pytest.fixture
def radicale(tmp_path):
    parts = urlsplit(RADICALE)
    user, password = parts.username or "", parts.password or ""
    base = urlunsplit((parts.scheme, f"{parts.hostname}:{parts.port}", "/", "", ""))
    name = f"essai-{uuid.uuid4().hex[:8]}"
    home = f"{base}{user}/{name}/"
    body = ('<?xml version="1.0" encoding="utf-8"?><C:mkcalendar xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav"><D:set><D:prop><D:displayname>Essai</D:displayname>'
            '<C:supported-calendar-component-set><C:comp name="VEVENT"/></C:supported-calendar-component-set>'
            "</D:prop></D:set></C:mkcalendar>")
    made = httpx.request("MKCALENDAR", home, auth=(user, password), content=body,
                         headers={"Content-Type": "application/xml"})
    assert made.status_code == 201, made.text
    store = AgendaStore(backend.target(tmp_path, "agenda"))
    intruder = Intruder((user, password))
    provider = CalDavProvider(Web(transport=intruder))
    account = Connection("radicale", "caldav", url=home, username=user, secret=password,
                         address=f"{user}@example.org")
    store.keep_account("radicale", "caldav", address=account.address)
    yield store, provider, account, intruder
    httpx.request("DELETE", home, auth=(user, password))
    store.close()


def test_a_real_radicale_creates_changes_deletes_and_syncs_by_token(radicale):
    store, provider, account, intruder = radicale
    now = us_of(datetime(2026, 11, 23, 15, tzinfo=PARIS))

    def sync(minutes: int):
        state = asyncio.run(sync_account(store, provider, account, AgendaParams(), now + minutes * MINUTE))
        assert state.error == ""
        return store.calendars("radicale")[0]

    def shown(cal):
        return [(at_us(o.span.start, PARIS).strftime("%d/%m %H:%M"), o.event.title)
                for o in store.period([cal.key], paris(2026, 11, 1), paris(2027, 3, 1))]

    cal = sync(0)
    assert cal.name == "Essai" and cal.writable and cal.cursor.startswith("token:")
    made = asyncio.run(provider.create(account, cal, EventDraft(
        "Point hebdo", Span(paris(2026, 11, 30, 10), paris(2026, 11, 30, 11), "Europe/Paris"),
        rule="FREQ=WEEKLY;COUNT=5", location="Salle 2")))
    cal = sync(1)
    assert [t for _d, t in shown(cal)] == ["Point hebdo"] * 5
    master = store.find(cal.key, made.uid)
    asyncio.run(provider.edit(account, cal, master, occurrence_key(paris(2026, 12, 7, 10), False),
                              EventChange(title="Point (déplacé)", span=Span(paris(2026, 12, 7, 14),
                                                                             paris(2026, 12, 7, 15), "Europe/Paris")),
                              ONE))
    master = store.find(cal.key, made.uid)
    asyncio.run(provider.edit(account, cal, master, occurrence_key(paris(2026, 12, 14, 10), False),
                              EventChange(span=Span(paris(2026, 12, 14, 11), paris(2026, 12, 14, 12),
                                                    "Europe/Paris")), ALL))
    cal = sync(2)
    master = store.find(cal.key, made.uid)
    asyncio.run(provider.edit(account, cal, master, occurrence_key(paris(2026, 12, 21, 11), False),
                              EventChange(title="Point (nouvelle formule)"), FOLLOWING))
    cal = sync(3)
    assert shown(cal) == [("30/11 11:00", "Point hebdo"), ("07/12 14:00", "Point (déplacé)"),
                          ("14/12 11:00", "Point hebdo"), ("21/12 11:00", "Point (nouvelle formule)"),
                          ("28/12 11:00", "Point (nouvelle formule)")]
    master = store.find(cal.key, made.uid)
    asyncio.run(provider.delete(account, cal, master, occurrence_key(paris(2026, 11, 30, 11), False), ONE))
    cal = sync(4)
    assert shown(cal)[0] == ("07/12 14:00", "Point (déplacé)")
    with pytest.raises(AgendaError, match="ne transmet pas les réponses"):
        asyncio.run(provider.respond(account, cal, store.find(cal.key, made.uid), "", YES))
    # un autre client écrit entre la lecture et l'écriture : le serveur répond 412, dit en mots ; la copie suit
    intruder.armed = True
    with pytest.raises(AgendaError, match="a changé chez le fournisseur"):
        asyncio.run(provider.edit(account, cal, store.find(cal.key, made.uid), "", EventChange(location="Salle 9")))
    asyncio.run(reread(store, provider, account, cal.key, AgendaParams(), now + 5 * MINUTE))
    assert store.find(cal.key, made.uid).title == "(ailleurs) Point hebdo"
    asyncio.run(provider.delete(account, cal, store.find(cal.key, made.uid), "", ALL))
    cal = sync(6)
    assert [t for _d, t in shown(cal)] == ["Point (nouvelle formule)"] * 2


def test_a_real_radicale_keeps_the_providers_reminders_a_notification_and_an_email(radicale):
    store, provider, account, _intruder = radicale
    now = us_of(datetime(2026, 11, 23, 15, tzinfo=PARIS))
    asyncio.run(sync_account(store, provider, account, AgendaParams(), now))
    cal = store.calendars("radicale")[0]
    made = asyncio.run(provider.create(account, cal, EventDraft(
        "Dentiste", Span(paris(2026, 12, 2, 17), paris(2026, 12, 2, 18), "Europe/Paris"),
        reminders=(Alert(1440, EMAIL), Alert(30)))))
    assert asyncio.run(sync_account(store, provider, account, AgendaParams(), now + MINUTE)).error == ""
    kept = store.find(cal.key, made.uid)
    assert kept.reminders == (Alert(30), Alert(1440, EMAIL)) and not kept.reminders_default
    asyncio.run(provider.edit(account, cal, kept, "", EventChange(reminders=(Alert(10),))))
    asyncio.run(sync_account(store, provider, account, AgendaParams(), now + 2 * MINUTE))
    assert store.find(cal.key, made.uid).reminders == (Alert(10),)
    asyncio.run(provider.edit(account, cal, store.find(cal.key, made.uid), "", EventChange(reminders=())))
    asyncio.run(sync_account(store, provider, account, AgendaParams(), now + 3 * MINUTE))
    assert store.find(cal.key, made.uid).reminders == ()

"""L'abonnement iCal (ADR 0309, lot 1) : une adresse ``.ics`` (des jours fériés, l'adresse secrète d'un agenda
Google ou Outlook), en lecture seule.

- **Un agenda par adresse** : le compte n'en porte qu'un (``ICAL_CALENDAR``, une clé fixe : changer d'adresse — une
  adresse secrète réinitialisée — garde ses réglages), nommé comme le fichier le dit (X-WR-CALNAME), sinon comme le
  compte. Son adresse, qui ouvre l'agenda à qui la connaît, est scellée dans les réglages et ne se range nulle part
  ailleurs : ni dans la base (``Calendar.remote`` reste vide), ni dans une erreur (seul son hôte s'y dit).
- **Relu selon sa cadence** (une heure par défaut, ``plugins/agenda``) avec ``If-None-Match`` et
  ``If-Modified-Since`` : un fichier inchangé (304, ou le même contenu) ne réécrit rien. Ce qui sert à le redemander
  (son ETag, sa date, l'empreinte de son contenu) est le curseur de l'agenda.
- **Lu en entier** par ``ics.read`` (hors de la boucle) : un lot complet, que la base range en retirant ce que le
  fichier ne dit plus ; ce qui a fini avant la fenêtre n'est pas rangé.
- **Une taille bornée** (``ICS_MAX`` : 10 Mo) : au-delà, le fichier n'est pas lu — la copie d'avant reste, et le
  compte le dit (« l'abonnement pèse plus de 10 Mo »). Une adresse qui ne donne pas un agenda (une page web, une
  page de connexion) le dit aussi.
- **Écrire** est refusé en mots : un abonnement se lit seulement.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from mika.adapters.agenda import ics
from mika.adapters.agenda.http import TooBig, Web, server_host, server_url, status_words
from mika.ports.agenda import (
    ALL,
    ICAL,
    Abilities,
    AgendaError,
    Calendar,
    Connection,
    Event,
    EventChange,
    EventDraft,
    SyncBatch,
    Window,
    at_us,
    calendar_key,
    key_instant,
    series_end,
)

#: la clé courte de l'agenda d'un abonnement (un seul par adresse)
ICAL_CALENDAR = "abonnement"
#: un abonnement plus gros n'est pas lu
ICS_MAX = 10_000_000
#: ce qu'un fichier relu vaut pour le passage en cours (``calendars`` puis ``sync`` ne le demandent qu'une fois)
FRESH_US = 300 * 1_000_000
READ_ONLY = "un abonnement se lit seulement : on n'y écrit pas"


def _now_us() -> int:
    return time.time_ns() // 1000


@dataclass(frozen=True, slots=True)
class _Fetched:
    """Ce qu'un relevé a donné : quand, ses validateurs, l'empreinte du contenu, le fichier lu (``None`` : inchangé,
    304)."""

    at: int
    url: str
    etag: str
    modified: str
    digest: str
    feed: ics.Feed | None


def _cursor(etag: str, modified: str, digest: str) -> str:
    return json.dumps({"etag": etag, "modified": modified, "digest": digest}, sort_keys=True)


def _validators(cursor: str) -> tuple[str, str, str]:
    try:
        got = json.loads(cursor) if cursor else {}
    except ValueError:
        got = {}
    if not isinstance(got, dict):
        got = {}
    return str(got.get("etag", "")), str(got.get("modified", "")), str(got.get("digest", ""))


def _kept(event: Event, window: Window) -> bool:
    """Ce qui touche encore la fenêtre (ou qui vient après) : ce qui a fini avant n'est pas rangé."""
    if event.original:
        return event.span.end > window.start or key_instant(event.original) > window.start
    return series_end(event) > window.start


class IcalProvider:
    """Un ``CalendarProvider`` pour une adresse ``.ics`` (``web`` : les requêtes ; les tests en posent un faux)."""

    kind = ICAL

    def __init__(self, web: Web | None = None, *, now: Callable[[], int] = _now_us) -> None:
        self._web = web or Web()
        self._now = now
        #: le dernier relevé de chaque compte, pour son nom et pour le passage en cours
        self._fetched: dict[str, _Fetched] = {}

    def abilities(self, account: Connection) -> Abilities:
        return Abilities()

    def _calendar(self, account: Connection, fetched: _Fetched | None) -> Calendar:
        feed = fetched.feed if fetched is not None else None
        name = (feed.name if feed is not None else "") or account.label or server_host(account.url) or account.key
        return Calendar(calendar_key(account.key, ICAL_CALENDAR), account.key, "", name=name[:200],
                        color=feed.color if feed is not None else "", writable=False,
                        zone=feed.zone if feed is not None else "", primary=True, selected=True)

    async def calendars(self, account: Connection) -> list[Calendar]:
        """Son agenda : le fichier est relu (le passage qui suit s'en sert), pour son nom et pour dire tout de suite
        une adresse qui ne donne pas un agenda."""
        known = self._fetched.get(account.key)
        same = known is not None and known.url == server_url(account.url) and known.feed is not None
        fetched = self._remember(account, await self._fetch(account, known.etag if same else "",
                                                            known.modified if same else ""))
        return [self._calendar(account, fetched)]

    def _remember(self, account: Connection, fetched: _Fetched) -> _Fetched:
        """Le relevé gardé pour ce compte : inchangé (304), le fichier d'avant reste le sien."""
        known = self._fetched.get(account.key)
        if fetched.feed is None and known is not None and known.feed is not None and known.url == fetched.url:
            fetched = replace(fetched, feed=known.feed, digest=known.digest,
                              etag=fetched.etag or known.etag, modified=fetched.modified or known.modified)
        self._fetched[account.key] = fetched
        return fetched

    async def create_calendar(self, account: Connection, name: str) -> Calendar:
        raise AgendaError(READ_ONLY)

    async def sync(self, account: Connection, calendar: Calendar, cursor: str, window: Window) -> SyncBatch:
        """Le fichier relu (ou celui que ``calendars`` vient de relire) : un lot complet s'il a changé depuis le
        curseur, rien sinon."""
        etag, modified, digest = _validators(cursor)
        fetched = self._fetched.get(account.key)
        if fetched is None or fetched.url != server_url(account.url) or self._now() - fetched.at >= FRESH_US:
            fetched = self._remember(account, await self._fetch(account, etag, modified))
        if fetched.feed is None or fetched.digest == digest:  # inchangé : rien à réécrire
            return SyncBatch(cursor=_cursor(fetched.etag or etag, fetched.modified or modified,
                                            fetched.digest or digest))
        events = tuple(replace(e, calendar=calendar.key) for e in fetched.feed.events if _kept(e, window))
        return SyncBatch(events=events, cursor=_cursor(fetched.etag, fetched.modified, fetched.digest),
                         complete=True)

    async def _fetch(self, account: Connection, etag: str, modified: str) -> _Fetched:
        """Le fichier demandé (avec ses validateurs : un 304 rend ``feed=None``), lu hors de la boucle."""
        url = server_url(account.url)
        if not url:
            raise AgendaError("l'abonnement n'a pas d'adresse")
        host = server_host(url)
        headers = {"Accept": "text/calendar, text/plain;q=0.8, */*;q=0.5"}
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
        async with self._web.session(url, what="l'abonnement", internet=account.internet) as web:
            try:
                reply = await web.send("GET", url, headers=headers, limit=ICS_MAX)
            except TooBig:
                raise AgendaError(f"l'abonnement pèse plus de {ICS_MAX // 1_000_000} Mo : il n'est pas relu "
                                  "(la copie d'avant reste)") from None
        now = self._now()
        if reply.status == 304:
            return _Fetched(now, url, etag, modified, "", None)
        if reply.status in (401, 403):
            raise AgendaError(f"{host} refuse cette adresse (privée ? une adresse secrète réinitialisée ?)")
        if not reply.ok:
            raise AgendaError(status_words(reply.status, host, "l'agenda"))
        digest = hashlib.sha256(reply.body).hexdigest()
        known = self._fetched.get(account.key)
        if known is not None and known.digest == digest and known.feed is not None:
            feed = known.feed  # le même fichier : déjà lu
        else:
            mine = {a for a in (account.address.strip().lower(),) if a}
            try:
                feed = await asyncio.to_thread(ics.read, reply.body, mine=mine, year=at_us(now).year,
                                               calendar=calendar_key(account.key, ICAL_CALENDAR))
            except AgendaError as exc:
                raise AgendaError(f"l'adresse de l'abonnement ({host}) ne donne pas un agenda : {exc}") from None
        return _Fetched(now, url, reply.headers.get("etag", ""), reply.headers.get("last-modified", ""), digest, feed)

    async def create(self, account: Connection, calendar: Calendar, draft: EventDraft) -> Event:
        raise AgendaError(READ_ONLY)

    async def edit(self, account: Connection, calendar: Calendar, event: Event, occurrence: str, change: EventChange,
                   scope: str = ALL) -> Event:
        raise AgendaError(READ_ONLY)

    async def delete(self, account: Connection, calendar: Calendar, event: Event, occurrence: str,
                     scope: str = ALL) -> int:
        raise AgendaError(READ_ONLY)

    async def respond(self, account: Connection, calendar: Calendar, event: Event, occurrence: str, response: str,
                      scope: str = ALL, comment: str = "") -> Event:
        raise AgendaError("un abonnement se lit seulement : on répond à l'invitation là où elle est arrivée")


__all__ = ["ICAL_CALENDAR", "ICS_MAX", "READ_ONLY", "IcalProvider"]

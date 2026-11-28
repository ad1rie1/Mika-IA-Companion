"""CalDAV (ADR 0309, lot 1 ; RFC 4791, 6578, 6638) : un serveur d'agendas — Outlook pro par DavMail, iCloud,
Nextcloud, Fastmail, Radicale… —, une adresse, un identifiant et un mot de passe d'application (scellé dans les
réglages).

- **Découvrir** (``calendars``) : l'adresse donnée, puis ``/.well-known/caldav`` ; le principal de l'identifiant
  (``current-user-principal``), ses adresses (``calendar-user-address-set`` : qui il est parmi les invités) et sa
  maison d'agendas (``calendar-home-set``) ; chaque agenda qui porte des VEVENT (ni une liste de tâches, ni une boîte
  de réception) avec son nom, sa couleur, s'il s'écrit (``current-user-privilege-set``), son fuseau, et de quoi le
  resynchroniser (``sync-token``, ``getctag``). Une adresse qui est déjà un agenda (celle de DavMail) est cet agenda
  seul. Si le serveur transmet les réponses aux invitations (``calendar-auto-schedule``, RFC 6638) se lit dans son
  en-tête ``DAV``. La découverte se garde un jour ; chaque passage relit les agendas (une requête).
- **Synchroniser** (``sync``) : la première fois, ce qui touche la fenêtre et vient après (``calendar-query`` sur un
  intervalle ouvert vers l'avenir, puis ``calendar-multiget`` par paquets) — un lot complet ; ensuite, par
  ``sync-collection`` (RFC 6578) depuis le jeton gardé dans le curseur quand le serveur le sait (un jeton périmé :
  tout relu), sinon par la même requête et la comparaison des ETag gardés dans le curseur (rien à demander quand le
  ``getctag`` n'a pas bougé). Chaque ressource changée est redonnée en entière (``SyncBatch.replaced``) : une
  exception qu'elle n'a plus part.
- **Écrire** : chaque écriture relit d'abord la ressource chez le serveur (jamais une copie périmée), y pose le
  changement — ce qui est demandé seulement — et la renvoie (``PUT`` avec ``If-Match`` sur l'ETag lu, ``If-None-Match:
  *`` pour une ressource neuve ; ``DELETE`` avec ``If-Match``), puis la relit pour rendre l'événement tel que le
  serveur le garde. Une série se change pour cet événement (une exception), à partir de lui (la série coupée : la
  suite dans une ressource neuve, sous un nouvel UID, ses exceptions avec elle ; la neuve écrite d'abord, retirée si
  la coupe échoue) ou en entier (depuis une occurrence, elle garde son premier jour et prend l'heure ; ses exceptions
  suivent ce qu'elles tenaient d'elle). Une invitation ne se modifie que chez qui l'organise (ses rappels et
  « occupé » restent à soi) ; la supprimer de son agenda, c'est la refuser.
- **Répondre** (``respond``) : le PARTSTAT de sa ligne d'invitée (de la série, ou d'une occurrence), que le serveur
  transmet à l'organisateur (RFC 6638 ; DavMail le transmet comme la réponse d'Outlook). Un serveur qui ne transmet
  rien (Radicale) le dit : répondre là ne préviendrait personne.
- **Un conflit** (412 : la ressource a changé entre la lecture et l'écriture) **ou un événement disparu** se dit en
  mots ; celui qui écrit relit alors la copie (``plugins/agenda/sync.py::reread``).
- ``SERVICES`` : les aides par service que les écrans proposent (l'adresse à donner, ce qu'est l'identifiant).
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, fields, replace
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlsplit
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from mika.adapters.agenda import ics
from mika.adapters.agenda.http import Reply, Session, Web, server_host, server_url, status_words
from mika.ports.agenda import (
    ALL,
    CALDAV,
    FOLLOWING,
    MAYBE,
    NO,
    ONE,
    YES,
    Abilities,
    AgendaError,
    Calendar,
    Connection,
    Event,
    EventChange,
    EventDraft,
    Participant,
    Span,
    SyncBatch,
    Window,
    at_us,
    calendar_key,
    key_instant,
    local_key,
    occurrence_key,
    occurrences,
    split_rule,
)

log = logging.getLogger("mika.agenda")

D, C, CS, IC = "DAV:", "urn:ietf:params:xml:ns:caldav", "http://calendarserver.org/ns/", "http://apple.com/ns/ical/"
_XMLNS = f'xmlns:d="{D}" xmlns:c="{C}" xmlns:cs="{CS}" xmlns:ic="{IC}"'
#: ce que la découverte demande de chaque collection
_PROPS = ("<d:resourcetype/><d:displayname/><d:current-user-principal/><c:calendar-home-set/>"
          "<c:calendar-user-address-set/><c:schedule-inbox-URL/><ic:calendar-color/><d:current-user-privilege-set/>"
          "<c:supported-calendar-component-set/><c:calendar-timezone/><d:sync-token/><cs:getctag/>"
          "<d:supported-report-set/>")
PROPFIND = f'<?xml version="1.0" encoding="utf-8"?><d:propfind {_XMLNS}><d:prop>{_PROPS}</d:prop></d:propfind>'
#: au plus tant de ressources par ``calendar-multiget``
MULTIGET_MAX = 50
#: la découverte (principal, maison, planification) se garde tant (µs) ; les agendas se relisent à chaque passage
FOUND_US = 86_400 * 1_000_000
#: les droits qui permettent d'écrire dans un agenda
_WRITE = {f"{{{D}}}write", f"{{{D}}}write-content", f"{{{D}}}bind", f"{{{D}}}all"}
#: ce qu'un changement fait par une invitée garde à elle (le reste est à qui organise)
_GUEST_FIELDS = ("reminders", "busy", "added")
TOKEN, ETAGS = "token:", "etags:"
#: les rappels (VALARM) qu'un événement reçoit d'ici : une liste courte, une notification ou un e-mail (un serveur qui
#: n'envoie pas d'e-mail le garde quand même : un autre client le lira)
REMINDERS_OFFERED = 5


@dataclass(frozen=True, slots=True)
class CalDavService:
    """Une aide pour brancher un service : son nom, l'adresse à donner (``<adresse>``, ``<hôte>`` : à remplacer), ce
    qu'il faut savoir."""

    key: str
    name: str
    url: str
    help: str


SERVICES = (
    CalDavService("davmail", "Outlook pro (DavMail)", "http://localhost:1080/users/<adresse>/calendar/",
                  "DavMail sur cette machine, en mode O365Graph (son port CalDAV : 1080 par défaut) ; l'identifiant "
                  "est ton adresse pro, le mot de passe celui que DavMail demande."),
    CalDavService("icloud", "iCloud", "https://caldav.icloud.com",
                  "L'identifiant est ton identifiant Apple ; le mot de passe, un mot de passe pour app "
                  "(compte Apple › Connexion et sécurité)."),
    CalDavService("nextcloud", "Nextcloud", "https://<hôte>/remote.php/dav",
                  "L'identifiant est ton nom d'utilisateur Nextcloud ; le mot de passe, un mot de passe "
                  "d'application (Paramètres personnels › Sécurité)."),
    CalDavService("fastmail", "Fastmail", "https://caldav.fastmail.com",
                  "L'identifiant est ton adresse Fastmail ; le mot de passe, un mot de passe d'application avec "
                  "l'accès CalDAV (Paramètres › Confidentialité et sécurité)."),
)


def _now_us() -> int:
    return time.time_ns() // 1000


def _new_id() -> str:
    return uuid.uuid4().hex


# ── le XML de WebDAV ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Response:
    """Une ``d:response`` d'un multistatus : son adresse, son état (celui de la réponse, sinon 200), ses propriétés
    trouvées (200)."""

    href: str
    status: int
    props: dict[str, ElementTree.Element]

    def text(self, name: str) -> str:
        found = self.props.get(name)
        return (found.text or "").strip() if found is not None else ""

    def hrefs(self, name: str) -> list[str]:
        found = self.props.get(name)
        if found is None:
            return []
        return [(h.text or "").strip() for h in found.iter(f"{{{D}}}href") if (h.text or "").strip()]

    def children(self, name: str) -> list[ElementTree.Element]:
        found = self.props.get(name)
        return list(found) if found is not None else []


def _status(text: str | None) -> int:
    parts = (text or "").split()
    try:
        return int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return 0


def multistatus(body: bytes) -> tuple[list[_Response], str]:
    """Les réponses d'un multistatus, et son ``sync-token`` (vide s'il n'en a pas) ; ``AgendaError`` s'il ne se lit
    pas."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        raise AgendaError("le serveur renvoie une réponse WebDAV illisible") from None
    out = []
    for resp in root.iter(f"{{{D}}}response"):
        href = (resp.findtext(f"{{{D}}}href") or "").strip()
        status = _status(resp.findtext(f"{{{D}}}status"))
        props: dict[str, ElementTree.Element] = {}
        for propstat in resp.findall(f"{{{D}}}propstat"):
            if _status(propstat.findtext(f"{{{D}}}status")) // 100 != 2:
                continue
            prop = propstat.find(f"{{{D}}}prop")
            for child in prop if prop is not None else ():
                props[child.tag] = child
        out.append(_Response(href, status or 200, props))
    return out, (root.findtext(f"{{{D}}}sync-token") or "").strip()


def _norm(href: str, base: str) -> str:
    """L'adresse d'une ressource telle qu'on la range et la compare (``Event.remote``) : son chemin, décodé."""
    return unquote(urlsplit(urljoin(base, href)).path)


def _quoted(path: str) -> str:
    return quote(path, safe="/:@!$&'()*+,;=~")


def _same(a: str, b: str) -> bool:
    return a.rstrip("/") == b.rstrip("/")


def _etag(value: str) -> str:
    return value.strip()


# ── ce qu'on sait d'un compte ───────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Collection:
    """Un agenda trouvé : son adresse entière, ce qu'il dit de lui et de quoi le resynchroniser."""

    url: str
    name: str = ""
    color: str = ""
    writable: bool = True
    zone: str = ""
    token: str = ""
    ctag: str = ""
    sync: bool = False


@dataclass(frozen=True, slots=True)
class _Found:
    """Ce qu'une découverte a trouvé pour un compte (``signature`` : son adresse, son identifiant, son mot de passe —
    un compte changé se redécouvre)."""

    signature: str
    at: int
    #: l'adresse des agendas : la maison, ou l'agenda donné seul
    home: str
    single: bool
    addresses: frozenset[str] = frozenset()
    schedules: bool = False
    default: str = ""
    collections: tuple[_Collection, ...] = field(default_factory=tuple)

    def collection(self, url: str) -> _Collection | None:
        return next((c for c in self.collections if _same(c.url, url)), None)


def _signature(account: Connection) -> str:
    seed = f"{server_url(account.url)}\x00{account.username}\x00{account.secret}"
    return hashlib.sha256(seed.encode("utf-8", "surrogatepass")).hexdigest()


def _collection(resp: _Response, base: str) -> _Collection | None:
    """Un agenda d'événements d'après sa réponse (``None`` : ce n'en est pas un)."""
    kinds = {c.tag for c in resp.children(f"{{{D}}}resourcetype")}
    if f"{{{C}}}calendar" not in kinds:
        return None
    comps = {(c.get("name") or "").upper() for c in resp.children(f"{{{C}}}supported-calendar-component-set")}
    if comps and "VEVENT" not in comps:
        return None
    privileges = resp.props.get(f"{{{D}}}current-user-privilege-set")
    if privileges is not None:
        held = {p.tag for priv in privileges.iter(f"{{{D}}}privilege") for p in priv}
        writable = bool(held & _WRITE)
    else:
        writable = True
    url = urljoin(base, resp.href)
    tz = resp.text(f"{{{C}}}calendar-timezone")
    name = resp.text(f"{{{D}}}displayname") or unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
    return _Collection(url=url, name=name[:200], color=ics.color_of(resp.text(f"{{{IC}}}calendar-color")),
                       writable=writable, zone=ics.zone_of_vtimezone(tz) if tz else "",
                       token=resp.text(f"{{{D}}}sync-token"), ctag=resp.text(f"{{{CS}}}getctag"),
                       sync=bool(resp.text(f"{{{D}}}sync-token")))


def _xml_hrefs(hrefs: Sequence[str]) -> str:
    return "".join(f"<d:href>{escape(h)}</d:href>" for h in hrefs)


def _chunks(values: Sequence[str], size: int = MULTIGET_MAX) -> Iterator[Sequence[str]]:
    for i in range(0, len(values), size):
        yield values[i:i + size]


def _utc(us: int) -> str:
    return at_us(us).strftime("%Y%m%dT%H%M%SZ")


# ── le fournisseur ──────────────────────────────────────────────────────────


class CalDavProvider:
    """Un ``CalendarProvider`` pour un serveur CalDAV (``web`` : les requêtes ; les tests en posent un faux)."""

    kind = CALDAV

    def __init__(self, web: Web | None = None, *, now: Callable[[], int] = _now_us,
                 new_id: Callable[[], str] = _new_id) -> None:
        self._web = web or Web()
        self._now = now
        self._new_id = new_id
        self._found: dict[str, _Found] = {}
        #: une découverte à la fois par compte
        self._locks: dict[str, asyncio.Lock] = {}
        #: les agendas dont le serveur refuse ``sync-collection`` : (compte, adresse)
        self._unsynced: set[tuple[str, str]] = set()

    def abilities(self, account: Connection) -> Abilities:
        """Répondre (``invite``) : seulement quand la découverte a vu le serveur transmettre les réponses (RFC 6638) ;
        avant elle, rien ne dit qu'une réponse aboutirait, et un écran n'offre pas ce qui échouerait."""
        found = self._found.get(account.key)
        return Abilities(write=True, invite=found is not None and found.schedules, incremental=True,
                         reminders=REMINDERS_OFFERED, email_reminders=True)

    @asynccontextmanager
    async def _session(self, account: Connection) -> Any:
        url = server_url(account.url)
        if not url:
            raise AgendaError("le compte CalDAV n'a pas d'adresse de serveur")
        async with self._web.session(url, username=account.username, password=account.secret,
                                     what="le serveur CalDAV", internet=account.internet) as web:
            yield web

    def _mine(self, account: Connection) -> frozenset[str]:
        """Qui est ce compte parmi les invités : son adresse, son identifiant s'il en est une, celles du principal."""
        found = self._found.get(account.key)
        own = {ics.user_address(a) for a in (account.address, account.username) if "@" in (a or "")}
        return frozenset(own | (set(found.addresses) if found is not None else set()))

    def _organizer(self, account: Connection) -> Participant | None:
        for a in [account.address, *sorted(self._mine(account)), account.username]:
            if a and "@" in a and ":" not in a and "/" not in a:
                return Participant(address=a.strip().lower(), name=account.label)
        return None

    # ── découvrir ──
    async def _propfind(self, web: Session, url: str, depth: str) -> Reply:
        return await web.send("PROPFIND", url, headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"},
                              body=PROPFIND.encode())

    async def _discover(self, web: Session, account: Connection) -> _Found:
        start = server_url(account.url)
        host = server_host(start)
        first = await self._propfind(web, start, "0")
        if first.status == 401:
            raise AgendaError(status_words(401, host, "l'agenda"))
        responses: list[_Response] = []
        if first.status == 207:
            responses, _token = multistatus(first.body)
        own = next((r for r in responses if _same(_norm(r.href, first.url), unquote(urlsplit(first.url).path))), None) \
            or (responses[0] if responses else None)
        if own is not None and (single := _collection(own, first.url)) is not None:  # l'adresse est un agenda
            principal = own.hrefs(f"{{{D}}}current-user-principal")
            addresses, _inbox, _homes = await self._principal(web, principal[0], first.url) if principal \
                else (set(), "", [])
            return _Found(_signature(account), self._now(), single.url, True, frozenset(addresses),
                          await self._schedules(web, single.url), single.url, (single,))
        principal_href = own.hrefs(f"{{{D}}}current-user-principal") if own is not None else []
        home_href = own.hrefs(f"{{{C}}}calendar-home-set") if own is not None else []
        base = first.url
        if not principal_href and not home_href:  # l'adresse ne dit rien : celle que le serveur réserve à CalDAV
            parts = urlsplit(start)
            known = await self._propfind(web, f"{parts.scheme}://{parts.netloc}/.well-known/caldav", "0")
            if known.status == 401:
                raise AgendaError(status_words(401, host, "l'agenda"))
            if known.status == 207:
                found, _token = multistatus(known.body)
                principal_href = next((r.hrefs(f"{{{D}}}current-user-principal") for r in found
                                       if r.hrefs(f"{{{D}}}current-user-principal")), [])
                home_href = next((r.hrefs(f"{{{C}}}calendar-home-set") for r in found
                                  if r.hrefs(f"{{{C}}}calendar-home-set")), [])
                base = known.url
        if not principal_href and not home_href:
            if first.status not in (207, 404, 405, 400, 501):
                raise AgendaError(status_words(first.status, host, "le serveur CalDAV"))
            raise AgendaError(f"cette adresse n'est pas un serveur CalDAV ({host} : ni agenda, ni compte trouvé)")
        addresses: set[str] = set()
        inbox = ""
        if principal_href:
            addresses, inbox, homes = await self._principal(web, principal_href[0], base)
            home_href = home_href or homes
        if not home_href:
            raise AgendaError(f"{host} ne dit pas où sont les agendas de ce compte (pas de calendar-home-set)")
        home = urljoin(base, home_href[0])
        collections = await self._collections(web, home)
        if not collections:
            raise AgendaError(f"aucun agenda d'événements sur ce compte ({host})")
        default = await self._default(web, inbox) if inbox else ""
        return _Found(_signature(account), self._now(), home, False, frozenset(addresses),
                      await self._schedules(web, home), default, tuple(collections))

    async def _principal(self, web: Session, href: str, base: str) -> tuple[set[str], str, list[str]]:
        """Ses adresses (``calendar-user-address-set``), sa boîte de réception, sa maison d'agendas."""
        reply = await self._propfind(web, urljoin(base, href), "0")
        if reply.status != 207:
            return set(), "", []
        found, _token = multistatus(reply.body)
        if not found:
            return set(), "", []
        me = found[0]
        addresses = {ics.user_address(a) for a in me.hrefs(f"{{{C}}}calendar-user-address-set")}
        inbox = [urljoin(reply.url, h) for h in me.hrefs(f"{{{C}}}schedule-inbox-URL")]
        return addresses, inbox[0] if inbox else "", [urljoin(reply.url, h) for h in me.hrefs(f"{{{C}}}calendar-home-set")]

    async def _collections(self, web: Session, home: str) -> list[_Collection]:
        reply = await self._propfind(web, home, "1")
        if reply.status == 401:
            raise AgendaError(status_words(401, web.host, "l'agenda"))
        if reply.status != 207:
            raise AgendaError(status_words(reply.status, web.host, "la liste des agendas"))
        found, _token = multistatus(reply.body)
        return [c for r in found if (c := _collection(r, reply.url)) is not None]

    async def _schedules(self, web: Session, url: str) -> bool:
        """Le serveur transmet-il les réponses aux invitations (RFC 6638 : ``calendar-auto-schedule`` dans ``DAV``) ?"""
        try:
            reply = await web.send("OPTIONS", url)
        except AgendaError:
            return False
        dav = ",".join(reply.headers.get_list("dav")).lower()
        return "calendar-auto-schedule" in dav or "calendar-schedule" in dav

    async def _default(self, web: Session, inbox: str) -> str:
        """L'agenda où ses invitations arrivent (``schedule-default-calendar-URL``), son principal."""
        body = (f'<?xml version="1.0" encoding="utf-8"?><d:propfind {_XMLNS}><d:prop>'
                "<c:schedule-default-calendar-URL/></d:prop></d:propfind>")
        try:
            reply = await web.send("PROPFIND", inbox, headers={"Depth": "0", "Content-Type": "application/xml"},
                                   body=body.encode())
        except AgendaError:
            return ""
        if reply.status != 207:
            return ""
        found, _token = multistatus(reply.body)
        hrefs = found[0].hrefs(f"{{{C}}}schedule-default-calendar-URL") if found else []
        return urljoin(reply.url, hrefs[0]) if hrefs else ""

    async def _refresh(self, web: Session, account: Connection) -> _Found:
        """Ce qu'on sait du compte : redécouvert s'il a changé ou si c'est vieux, sinon ses agendas relus."""
        lock = self._locks.setdefault(account.key, asyncio.Lock())
        async with lock:
            known = self._found.get(account.key)
            if known is None or known.signature != _signature(account) or self._now() - known.at >= FOUND_US:
                found = await self._discover(web, account)
            elif known.single:
                reply = await self._propfind(web, known.home, "0")
                if reply.status != 207:
                    raise AgendaError(status_words(reply.status, web.host, "l'agenda"))
                listed, _token = multistatus(reply.body)
                fresh = next((c for r in listed if (c := _collection(r, reply.url)) is not None), None)
                if fresh is None:
                    raise AgendaError(f"cette adresse n'est plus un agenda ({web.host})")
                found = replace(known, collections=(fresh,))
            else:
                found = replace(known, collections=tuple(await self._collections(web, known.home)))
            self._found[account.key] = found
            return found

    async def calendars(self, account: Connection) -> list[Calendar]:
        async with self._session(account) as web:
            found = await self._refresh(web, account)
        default = found.default or (found.collections[0].url if found.collections else "")
        out = []
        for c in found.collections:
            local = local_key(urlsplit(c.url).path.rstrip("/") or c.url)
            out.append(Calendar(calendar_key(account.key, local), account.key, c.url, name=c.name, color=c.color,
                                writable=c.writable, zone=c.zone, primary=_same(c.url, default), selected=True))
        return out

    async def create_calendar(self, account: Connection, name: str) -> Calendar:
        raise AgendaError("un agenda CalDAV se crée chez le fournisseur ; il apparaît ici à la synchronisation suivante")

    # ── synchroniser ──
    async def sync(self, account: Connection, calendar: Calendar, cursor: str, window: Window) -> SyncBatch:
        async with self._session(account) as web:
            if account.key not in self._found:
                await self._refresh(web, account)
            coll = self._collection_of(account, calendar) or _Collection(calendar.remote, zone=calendar.zone)
            if cursor.startswith(TOKEN) and coll.sync:
                batch = await self._changes(web, account, calendar, cursor[len(TOKEN):], window)
                if batch is not None:
                    return batch
                coll = self._collection_of(account, calendar) or coll
            elif cursor.startswith(ETAGS) and not coll.sync:
                return await self._compared(web, account, calendar, coll, cursor[len(ETAGS):], window)
            return await self._whole(web, account, calendar, coll, window)

    async def _query(self, web: Session, calendar: Calendar, window: Window) -> dict[str, tuple[str, str]]:
        """Les ressources qui touchent la fenêtre ou viennent après (``calendar-query`` : leur ETag), par chemin :
        (adresse telle que le serveur la donne, ETag)."""
        body = (f'<?xml version="1.0" encoding="utf-8"?><c:calendar-query {_XMLNS}><d:prop><d:getetag/></d:prop>'
                '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
                f'<c:time-range start="{_utc(window.start)}"/></c:comp-filter></c:comp-filter></c:filter>'
                "</c:calendar-query>")
        reply = await web.send("REPORT", calendar.remote, headers={"Depth": "1", "Content-Type": "application/xml"},
                               body=body.encode())
        if reply.status != 207:
            raise AgendaError(status_words(reply.status, web.host, f"l'agenda « {calendar.name} »"))
        found, _token = multistatus(reply.body)
        base = urlsplit(reply.url).path
        out = {}
        for r in found:
            path = _norm(r.href, reply.url)
            if r.status // 100 == 2 and not _same(path, unquote(base)) and not path.endswith("/"):
                out[path] = (r.href, _etag(r.text(f"{{{D}}}getetag")))
        return out

    async def _multiget(self, web: Session, account: Connection, calendar: Calendar, hrefs: Sequence[str]
                        ) -> tuple[list[Event], set[str]]:
        """Ces ressources lues (``calendar-multiget`` par paquets) : leurs lignes, et les chemins lus (une ressource
        illisible n'y est pas : sa copie reste)."""
        events: list[Event] = []
        read: set[str] = set()
        mine = self._mine(account)
        year = at_us(self._now()).year
        for chunk in _chunks(list(hrefs)):
            body = (f'<?xml version="1.0" encoding="utf-8"?><c:calendar-multiget {_XMLNS}><d:prop><d:getetag/>'
                    f"<c:calendar-data/></d:prop>{_xml_hrefs(chunk)}</c:calendar-multiget>")
            reply = await web.send("REPORT", calendar.remote,
                                   headers={"Depth": "1", "Content-Type": "application/xml"}, body=body.encode())
            if reply.status != 207:
                raise AgendaError(status_words(reply.status, web.host, f"l'agenda « {calendar.name} »"))
            found, _token = multistatus(reply.body)
            for r in found:
                path = _norm(r.href, reply.url)
                data = r.text(f"{{{C}}}calendar-data")
                if r.status == 404:
                    read.add(path)
                    continue
                if not data:
                    continue
                try:
                    rows = ics.Resource(data, hint=calendar.zone, year=year).events(
                        calendar=calendar.key, mine=mine, remote=path, etag=_etag(r.text(f"{{{D}}}getetag")))
                except AgendaError as exc:
                    log.info("agenda : une ressource CalDAV illisible (%s) : %s", path[-60:], exc)
                    continue
                events.extend(rows)
                read.add(path)
        return events, read

    async def _whole(self, web: Session, account: Connection, calendar: Calendar, coll: _Collection,
                     window: Window) -> SyncBatch:
        """Tout relu : ce qui touche la fenêtre et vient après, un lot complet ; le curseur est le jeton lu avant
        (ce qui change entre les deux revient au passage suivant) ou les ETag."""
        token = coll.token if coll.sync else ""
        listed = await self._query(web, calendar, window)
        events, read = await self._multiget(web, account, calendar, [h for h, _e in listed.values()])
        if token:
            cursor = TOKEN + token
        else:
            cursor = ETAGS + json.dumps({"ctag": coll.ctag, "etags": {p: e for p, (_h, e) in listed.items()
                                                                      if p in read}}, sort_keys=True)
        return SyncBatch(events=tuple(events), replaced=tuple(sorted(read)), cursor=cursor, complete=True)

    async def _changes(self, web: Session, account: Connection, calendar: Calendar, token: str,
                       window: Window) -> SyncBatch | None:
        """Ce qui a changé depuis ce jeton (``sync-collection``, RFC 6578) ; ``None`` : le jeton n'est plus bon, ou
        le serveur ne le sait plus — tout se relit."""
        body = (f'<?xml version="1.0" encoding="utf-8"?><d:sync-collection {_XMLNS}>'
                f"<d:sync-token>{escape(token)}</d:sync-token><d:sync-level>1</d:sync-level>"
                "<d:prop><d:getetag/></d:prop></d:sync-collection>")
        reply = await web.send("REPORT", calendar.remote, headers={"Depth": "0", "Content-Type": "application/xml"},
                               body=body.encode())
        if reply.status in (400, 403, 409, 412, 501, 405):
            if b"valid-sync-token" not in reply.body:
                self._no_sync(account, calendar.remote)
            return None
        if reply.status != 207:
            raise AgendaError(status_words(reply.status, web.host, f"l'agenda « {calendar.name} »"))
        found, new_token = multistatus(reply.body)
        base = unquote(urlsplit(reply.url).path)
        changed: list[str] = []
        gone: list[str] = []
        more = False
        for r in found:
            path = _norm(r.href, reply.url)
            if _same(path, base):
                more = more or r.status == 507
                continue
            if r.status == 404:
                gone.append(path)
            elif r.status // 100 == 2 and not path.endswith("/"):
                changed.append(r.href)
        events, read = await self._multiget(web, account, calendar, changed)
        return SyncBatch(events=tuple(events), replaced=tuple(sorted(read | set(gone))),
                         cursor=TOKEN + (new_token or token), more=more and bool(new_token))

    def _collection_of(self, account: Connection, calendar: Calendar) -> _Collection | None:
        found = self._found.get(account.key)
        coll = found.collection(calendar.remote) if found is not None else None
        if coll is not None and (account.key, coll.url.rstrip("/")) in self._unsynced:
            coll = replace(coll, sync=False, token="")
        return coll

    def _no_sync(self, account: Connection, url: str) -> None:
        """Ce serveur ne sait pas ``sync-collection`` sur cet agenda (il le refuse autrement que pour un jeton
        périmé) : la comparaison des ETag le remplace, jusqu'au redémarrage."""
        self._unsynced.add((account.key, url.rstrip("/")))

    async def _compared(self, web: Session, account: Connection, calendar: Calendar, coll: _Collection,
                        cursor: str, window: Window) -> SyncBatch:
        """Sans ``sync-collection`` : ce que la requête liste comparé aux ETag gardés (rien à demander quand le
        ``getctag`` de l'agenda n'a pas bougé)."""
        try:
            before = json.loads(cursor)
        except ValueError:
            before = {}
        etags = dict(before.get("etags") or {}) if isinstance(before, dict) else {}
        if coll.ctag and isinstance(before, dict) and before.get("ctag") == coll.ctag:
            return SyncBatch(cursor=ETAGS + cursor)
        listed = await self._query(web, calendar, window)
        changed = [href for path, (href, etag) in listed.items() if not etag or etags.get(path) != etag]
        gone = [path for path in etags if path not in listed]
        events, read = await self._multiget(web, account, calendar, changed)
        kept = {p: e for p, (_h, e) in listed.items() if p in read or (p in etags and etags[p] == e)}
        cursor = ETAGS + json.dumps({"ctag": coll.ctag, "etags": kept}, sort_keys=True)
        return SyncBatch(events=tuple(events), replaced=tuple(sorted(read | set(gone))), cursor=cursor)

    # ── écrire ──
    async def _resource(self, web: Session, url: str, title: str, hint: str) -> tuple[ics.Resource, str]:
        """La ressource telle que le serveur la garde maintenant, et son ETag."""
        reply = await web.send("GET", url, headers={"Accept": "text/calendar"})
        if reply.status in (404, 410):
            raise AgendaError(f"« {title} » n'existe plus chez le fournisseur (supprimé ailleurs ?) : la copie est "
                              "relue")
        if not reply.ok:
            raise AgendaError(status_words(reply.status, web.host, f"« {title} »"))
        try:
            res = ics.Resource(reply.body, hint=hint, year=at_us(self._now()).year)
        except AgendaError as exc:
            raise AgendaError(f"« {title} » ne se relit pas chez le fournisseur : {exc}") from None
        return res, _etag(reply.headers.get("etag", ""))

    async def _put(self, web: Session, url: str, body: bytes, *, etag: str | None, title: str) -> None:
        """La ressource écrite : ``etag`` : celle qu'on a lue (``If-Match``) ; ``None`` : une neuve
        (``If-None-Match: *``)."""
        headers = {"Content-Type": "text/calendar; charset=utf-8"}
        if etag:
            headers["If-Match"] = etag
        elif etag is None:
            headers["If-None-Match"] = "*"
        reply = await web.send("PUT", url, headers=headers, body=body)
        if reply.ok:
            return
        raise AgendaError(self._refused(reply, web.host, title, new=etag is None))

    @staticmethod
    def _refused(reply: Reply, host: str, title: str, *, new: bool) -> str:
        if reply.status == 412:
            if new:
                return f"« {title} » existe déjà chez le fournisseur"
            return (f"« {title} » a changé chez le fournisseur pendant qu'on l'écrivait : la copie est relue, "
                    "redis ce que tu voulais y changer")
        if reply.status in (404, 410):
            return f"« {title} » n'existe plus chez le fournisseur (supprimé ailleurs ?) : la copie est relue"
        if b"no-uid-conflict" in reply.body:
            return f"un autre événement porte déjà l'identifiant de « {title} » chez le fournisseur"
        if reply.status == 403:
            return f"{host} refuse d'écrire dans cet agenda (en lecture seule ?)"
        if reply.status == 507:
            return f"{host} n'a plus de place pour « {title} »"
        if reply.status in (400, 409, 415, 422):
            return f"{host} refuse « {title} » tel qu'il est écrit (réponse {reply.status})"
        return status_words(reply.status, host, f"« {title} »")

    async def _delete(self, web: Session, url: str, etag: str, title: str) -> None:
        reply = await web.send("DELETE", url, headers={"If-Match": etag} if etag else {})
        if reply.ok or reply.status in (404, 410):
            return
        raise AgendaError(self._refused(reply, web.host, title, new=False))

    async def _returned(self, web: Session, account: Connection, calendar: Calendar, url: str, uid: str,
                        original: str, fallback: ics.Resource) -> Event:
        """L'événement tel que le serveur le garde après l'écriture (relu ; sinon tel qu'on l'a écrit)."""
        path = _norm(url, url)
        try:
            res, etag = await self._resource(web, url, "l'événement", calendar.zone)
        except AgendaError:
            res, etag = fallback, ""
        rows = res.events(calendar=calendar.key, mine=self._mine(account), remote=path, etag=etag)
        found = next((r for r in rows if r.uid == uid and r.original == original), None) \
            or next((r for r in rows if r.uid == uid and not r.original), None) or (rows[0] if rows else None)
        if found is None:
            raise AgendaError("l'événement n'a pas été gardé par le fournisseur")
        return found

    def _writable(self, account: Connection, calendar: Calendar) -> None:
        if calendar.account != account.key:
            raise AgendaError("cet agenda n'est pas de ce compte")
        if not calendar.writable:
            raise AgendaError(f"« {calendar.name} » est en lecture seule chez le fournisseur")

    def _url(self, calendar: Calendar, event: Event) -> str:
        if not event.remote:
            raise AgendaError("cet événement n'a pas d'adresse chez le fournisseur : la copie doit être relue")
        return urljoin(calendar.remote, _quoted(event.remote))

    async def create(self, account: Connection, calendar: Calendar, draft: EventDraft) -> Event:
        self._writable(account, calendar)
        name = self._new_id()
        uid = f"{name}@mika"
        url = calendar.remote.rstrip("/") + f"/{name}.ics"
        vevent = ics.draft_vevent(draft, uid=uid, now=self._now(), organizer=self._organizer(account))
        res = ics.Resource(ics.new_resource([vevent]), hint=calendar.zone)
        async with self._session(account) as web:
            await self._put(web, url, res.to_bytes(), etag=None, title=draft.title)
            made = await self._returned(web, account, calendar, url, uid, "", res)
        return replace(made, added=draft.added)

    async def edit(self, account: Connection, calendar: Calendar, event: Event, occurrence: str, change: EventChange,
                   scope: str = ALL) -> Event:
        self._writable(account, calendar)
        url = self._url(calendar, event)
        now = self._now()
        async with self._session(account) as web:
            res, etag = await self._resource(web, url, event.title or "l'événement", calendar.zone)
            mine = self._mine(account)
            master = res.master()
            master_event = res.event(master) if master is not None else None
            key = occurrence or event.original
            guard = master if master is not None else res.override(event.original)
            if guard is None:
                raise AgendaError(f"« {event.title} » n'existe plus chez le fournisseur : la copie est relue")
            if not ics.organizes(guard, mine) and any(
                    getattr(change, f.name) is not None for f in fields(EventChange) if f.name not in _GUEST_FIELDS):
                raise AgendaError("une invitation se modifie chez qui l'organise : on y répond")
            organizer = self._organizer(account)
            if master_event is None or not master_event.recurring:
                one = res.override(event.original) if event.original else master
                if one is None:
                    raise AgendaError(f"« {event.title} » n'existe plus chez le fournisseur : la copie est relue")
                ics.apply_change(one, replace(change, rule=None) if event.original else change, now=now,
                                 organizer=organizer)
                await self._put(web, url, res.to_bytes(), etag=etag, title=event.title)
                out_key = event.original
            elif scope == ONE and key:
                self._occurs(res, master_event, key, event.title)
                ics.apply_change(res.instance(key), replace(change, rule=None), now=now, organizer=organizer)
                await self._put(web, url, res.to_bytes(), etag=etag, title=event.title)
                out_key = key
            elif scope == FOLLOWING and key and key != _first_key(master_event):
                self._occurs(res, master_event, key, event.title)
                return await self._split(web, account, calendar, res, etag, url, master_event, key, change, now)
            else:
                self._whole_change(res, master, master_event, key, change, now, organizer)
                await self._put(web, url, res.to_bytes(), etag=etag, title=event.title)
                out_key = ""
            made = await self._returned(web, account, calendar, url, event.uid, out_key, res)
        return replace(made, added=change.added or event.added)

    @staticmethod
    def _occurs(res: ics.Resource, master: Event, key: str, title: str) -> None:
        """Cette occurrence existe-t-elle encore dans la série telle que le serveur la garde ?"""
        at = key_instant(key)
        if res.override(key) is None and not any(o.key == key for o in occurrences(master, at, at + 1)):
            raise AgendaError(f"cette occurrence de « {title} » n'existe plus chez le fournisseur (la série a "
                              "changé) : la copie est relue")

    @staticmethod
    def _whole_change(res: ics.Resource, master: Any, master_event: Event, key: str, change: EventChange, now: int,
                      organizer: Participant | None) -> None:
        """Toute la série : depuis une occurrence, elle garde son premier jour et prend l'heure ; ses exceptions
        suivent ce qu'elles tenaient d'elle ; sa règle retirée, ses exceptions partent."""
        if change.span is not None and key:
            moved = change.span.start - key_instant(key)
            length = change.span.end - change.span.start
            start = master_event.span.start + moved
            change = replace(change, span=Span(start, start + length, change.span.zone, change.span.all_day))
        before = copy.deepcopy(master)
        ics.apply_change(master, change, now=now, organizer=organizer)
        after = res.event(master)
        if change.rule == "":
            for v in [v for v in res.vevents if v.get("RECURRENCE-ID") is not None]:
                res.cal.subcomponents.remove(v)
            return
        delta = (after.span.start - master_event.span.start) if after is not None else 0
        res.inherit(before, change, now=now)
        res.shift(delta)

    async def _split(self, web: Session, account: Connection, calendar: Calendar, res: ics.Resource, etag: str,
                     url: str, master: Event, key: str, change: EventChange, now: int) -> Event:
        """Celui-ci et les suivants : la suite dans une ressource neuve (écrite d'abord), la série d'avant coupée
        juste avant (retirée, la neuve, si la coupe échoue)."""
        before_rule, after_rule = split_rule(master, key)
        name = self._new_id()
        uid = f"{name}@mika"
        new_url = calendar.remote.rstrip("/") + f"/{name}.ics"
        new = res.split(key, after_rule, uid)
        moved = res.truncate(key, before_rule)
        old_master = res.master()
        if old_master is not None:
            ics.stamp(old_master, now, bump=True)
        head = new.master()
        assert head is not None
        before = copy.deepcopy(head)
        ics.apply_change(head, change, now=now, organizer=self._organizer(account))
        after = new.event(head)
        delta = (after.span.start - key_instant(key)) if after is not None else 0
        new.adopt(moved, uid, delta)
        new.inherit(before, change, now=now)
        await self._put(web, new_url, new.to_bytes(), etag=None, title=master.title)
        try:
            await self._put(web, url, res.to_bytes(), etag=etag, title=master.title)
        except AgendaError:
            try:
                await self._delete(web, new_url, "", master.title)
            except AgendaError as exc:
                log.warning("agenda : la suite d'une série coupée n'a pas pu être retirée : %s", exc)
            raise
        made = await self._returned(web, account, calendar, new_url, uid, "", new)
        return replace(made, added=change.added or master.added)

    async def delete(self, account: Connection, calendar: Calendar, event: Event, occurrence: str,
                     scope: str = ALL) -> int:
        self._writable(account, calendar)
        url = self._url(calendar, event)
        now = self._now()
        async with self._session(account) as web:
            res, etag = await self._resource(web, url, event.title or "l'événement", calendar.zone)
            mine = self._mine(account)
            master = res.master()
            guard = master if master is not None else res.override(event.original)
            found = self._found.get(account.key)
            if guard is not None and not ics.organizes(guard, mine) and found is not None and found.schedules:
                # une invitation retirée de son agenda : refusée (l'organisateur le sait)
                await self._answer(web, account, calendar, res, etag, url, event, occurrence, NO,
                                   ONE if scope == ONE else ALL, "", now)
                return 1
            master_event = res.event(master) if master is not None else None
            key = occurrence or event.original
            if master_event is None or not master_event.recurring:
                if event.original and master is None:
                    lone = res.override(event.original)
                    if lone is not None:
                        res.cal.subcomponents.remove(lone)
                    if res.vevents:
                        await self._put(web, url, res.to_bytes(), etag=etag, title=event.title)
                        return 1
                await self._delete(web, url, etag, event.title)
                return max(1, len(res.vevents))
            if scope == ALL or not key or (scope == FOLLOWING and key == _first_key(master_event)):
                n = len(res.vevents)
                await self._delete(web, url, etag, event.title)
                return n
            if scope == ONE:
                res.exclude(key)
                gone = 1
            else:
                before_rule, _after = split_rule(master_event, key)
                gone = 1 + len(res.truncate(key, before_rule))
            ics.stamp(master, now, bump=True)
            await self._put(web, url, res.to_bytes(), etag=etag, title=event.title)
            return gone

    async def respond(self, account: Connection, calendar: Calendar, event: Event, occurrence: str, response: str,
                      scope: str = ALL, comment: str = "") -> Event:
        if response not in (YES, MAYBE, NO):
            raise AgendaError("une réponse est oui, peut-être ou non")
        if scope == FOLLOWING:
            raise AgendaError("une réponse vaut pour cet événement ou pour toute la série")
        if calendar.account != account.key:
            raise AgendaError("cet agenda n'est pas de ce compte")
        url = self._url(calendar, event)
        async with self._session(account) as web:
            found = self._found.get(account.key) or await self._refresh(web, account)
            if not found.schedules:
                raise AgendaError(f"{web.host} ne transmet pas les réponses aux invitations (pas de planification "
                                  "CalDAV, RFC 6638) : réponds depuis ta messagerie")
            res, etag = await self._resource(web, url, event.title or "l'invitation", calendar.zone)
            key = await self._answer(web, account, calendar, res, etag, url, event, occurrence, response, scope,
                                     comment, self._now())
            return await self._returned(web, account, calendar, url, event.uid, key, res)

    async def _answer(self, web: Session, account: Connection, calendar: Calendar, res: ics.Resource, etag: str,
                      url: str, event: Event, occurrence: str, response: str, scope: str, comment: str,
                      now: int) -> str:
        """Sa réponse posée (sur la série et chaque exception où elle est invitée, ou sur une occurrence) et
        écrite ; rend la clé de l'occurrence répondue (vide : la série)."""
        mine = self._mine(account)
        master = res.master()
        master_event = res.event(master) if master is not None else None
        key = occurrence or event.original
        guard = master if master is not None else res.override(event.original)
        if guard is not None and ics.organizes(guard, mine):
            raise AgendaError("ce compte organise cet événement : il n'y a rien à répondre")
        if master_event is not None and master_event.recurring and scope == ONE and key:
            self._occurs(res, master_event, key, event.title)
            res.answer(res.instance(key), response, mine, comment=comment, now=now)
            out = key
        elif master is None:
            lone = res.override(event.original) if event.original else None
            if lone is None:
                raise AgendaError(f"« {event.title} » n'existe plus chez le fournisseur : la copie est relue")
            res.answer(lone, response, mine, comment=comment, now=now)
            out = event.original
        else:
            res.answer(master, response, mine, comment=comment, now=now)
            for v in res.vevents:
                if v is not master and any(p.me for p in (res.event(v, mine=mine).participants
                                                          if res.event(v, mine=mine) else ())):
                    res.answer(v, response, mine, comment=comment, now=now)
            out = ""
        await self._put(web, url, res.to_bytes(), etag=etag, title=event.title)
        return out


def _first_key(master: Event) -> str:
    first = occurrences(master, master.span.start, master.span.start + 1)
    return first[0].key if first else occurrence_key(master.span.start, master.span.all_day)


__all__ = ["SERVICES", "CalDavProvider", "CalDavService", "multistatus"]

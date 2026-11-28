"""Un petit serveur CalDAV en mémoire (ADR 0309, lot 1), servi par un transport ``httpx`` factice : ce que les tests
du fournisseur CalDAV joignent, sans réseau.

Il sait ce que le fournisseur demande : ``/.well-known/caldav`` (redirigé), le principal (ses adresses, sa boîte de
réception), la maison d'agendas et ses agendas (nom, couleur, droits, composants, ``sync-token``, ``getctag``),
``calendar-query``, ``calendar-multiget``, ``sync-collection`` (RFC 6578, un jeton périmé refusé), ``GET``, ``PUT``
et ``DELETE`` avec leurs ETag (``If-Match``, ``If-None-Match``), ``OPTIONS`` (son en-tête ``DAV`` dit s'il transmet
les réponses aux invitations). Il route par l'en-tête ``Host`` : un hôte voisin (iCloud répond d'un autre nom) se
sert pareil. Chaque requête est notée (``requests``) ; ``fail`` en fait échouer une à la demande.
"""

from __future__ import annotations

import base64
import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import httpx

D, C, CS, IC = "DAV:", "urn:ietf:params:xml:ns:caldav", "http://calendarserver.org/ns/", "http://apple.com/ns/ical/"
NS = f'xmlns:d="{D}" xmlns:c="{C}" xmlns:cs="{CS}" xmlns:ic="{IC}"'


@dataclass
class Collection:
    name: str
    color: str = "#3366CCFF"
    comps: tuple[str, ...] = ("VEVENT",)
    writable: bool = True
    #: nom de la ressource → (ETag, texte)
    items: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: (numéro du jeton, ressource, supprimée)
    log: list[tuple[int, str, bool]] = field(default_factory=list)


@dataclass
class Seen:
    method: str
    host: str
    path: str
    headers: httpx.Headers
    body: bytes


class FakeCalDav:
    def __init__(self, *, host: str = "caldav.example.org", user: str = "adrien", password: str = "secret",
                 schedules: bool = True, sync: bool = True, ctag: bool = True,
                 addresses: tuple[str, ...] = ("mailto:adrien@example.org",), home_host: str = "",
                 default: str = "perso") -> None:
        self.host = host
        self.home_host = home_host or host
        self.user, self.password = user, password
        self.schedules, self.sync, self.ctag = schedules, sync, ctag
        self.addresses = addresses
        self.default = default
        self.home = f"/dav/calendars/{user}/"
        self.principal = f"/dav/principals/{user}/"
        self.collections: dict[str, Collection] = {"perso": Collection("Perso"), "taches": Collection(
            "Tâches", comps=("VTODO",)), "feries": Collection("Fériés", color="#FF2968FF", writable=False)}
        self._tokens = itertools.count(1)
        self.token = next(self._tokens)
        self._etags = itertools.count(1)
        self.requests: list[Seen] = []
        #: une panne à la demande : (méthode, chemin) → réponse
        self.fail: dict[tuple[str, str], Callable[[], httpx.Response]] = {}

    # ── ce que les tests posent ──
    def put(self, coll: str, name: str, text: str) -> str:
        """Une ressource écrite par quelqu'un d'autre (un téléphone, une autre appli)."""
        etag = f'"e{next(self._etags)}"'
        self.collections[coll].items[name] = (etag, text.replace("\r\n", "\n").replace("\n", "\r\n"))
        self.token = next(self._tokens)
        self.collections[coll].log.append((self.token, name, False))
        return etag

    def remove(self, coll: str, name: str) -> None:
        self.collections[coll].items.pop(name, None)
        self.token = next(self._tokens)
        self.collections[coll].log.append((self.token, name, True))

    def text(self, coll: str, name: str) -> str:
        return self.collections[coll].items[name][1]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def seen(self, method: str) -> list[Seen]:
        return [r for r in self.requests if r.method == method]

    # ── le serveur ──
    def handle(self, request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host", request.url.host).split(":")[0]
        path = unquote(request.url.path)
        body = request.content
        self.requests.append(Seen(request.method, host, path, request.headers, body))
        if (request.method, path) in self.fail:
            return self.fail.pop((request.method, path))()
        if host not in (self.host, self.home_host):
            return httpx.Response(404)
        if path == "/.well-known/caldav":
            return httpx.Response(301, headers={"Location": "/dav/"})
        expected = "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        if request.headers.get("authorization") != expected:
            return httpx.Response(401, headers={"WWW-Authenticate": 'Basic realm="dav"'})
        if request.method == "OPTIONS":
            dav = "1, 2, 3, calendar-access" + (", calendar-auto-schedule" if self.schedules else "")
            return httpx.Response(200, headers={"DAV": dav})
        if request.method == "PROPFIND":
            return self._propfind(path, request.headers.get("depth", "0"))
        coll, name = self._split(path)
        if request.method == "REPORT" and coll is not None and not name:
            return self._report(coll, body)
        if coll is None:
            return httpx.Response(404)
        c = self.collections[coll]
        if request.method == "GET":
            if name not in c.items:
                return httpx.Response(404)
            etag, text = c.items[name]
            return httpx.Response(200, headers={"ETag": etag, "Content-Type": "text/calendar"}, text=text)
        if request.method == "PUT":
            if not c.writable:
                return httpx.Response(403)
            if request.headers.get("if-none-match") == "*" and name in c.items:
                return httpx.Response(412)
            match = request.headers.get("if-match")
            if match and (name not in c.items or c.items[name][0] != match):
                return httpx.Response(412)
            created = name not in c.items
            etag = self.put(coll, name, body.decode())
            return httpx.Response(201 if created else 204, headers={"ETag": etag})
        if request.method == "DELETE":
            if name not in c.items:
                return httpx.Response(404)
            match = request.headers.get("if-match")
            if match and c.items[name][0] != match:
                return httpx.Response(412)
            self.remove(coll, name)
            return httpx.Response(204)
        return httpx.Response(405)

    def _split(self, path: str) -> tuple[str | None, str]:
        if not path.startswith(self.home):
            return None, ""
        rest = path[len(self.home):].strip("/").split("/")
        if not rest or rest[0] not in self.collections:
            return None, ""
        return rest[0], rest[1] if len(rest) > 1 else ""

    def _props(self, coll: str) -> str:
        c = self.collections[coll]
        privileges = "<d:privilege><d:read/></d:privilege>" + (
            "<d:privilege><d:write/></d:privilege>" if c.writable else "")
        comps = "".join(f'<c:comp name="{x}"/>' for x in c.comps)
        sync = f"<d:sync-token>tok-{self.token}</d:sync-token>" if self.sync else ""
        reports = ("<d:supported-report-set><d:supported-report><d:report><d:sync-collection/></d:report>"
                   "</d:supported-report></d:supported-report-set>") if self.sync else ""
        ctag = f"<cs:getctag>{len(c.log)}-{sum(1 for _ in c.items)}</cs:getctag>" if self.ctag else ""
        return (f"<d:resourcetype><d:collection/><c:calendar/></d:resourcetype><d:displayname>{escape(c.name)}"
                f"</d:displayname><ic:calendar-color>{c.color}</ic:calendar-color><d:current-user-privilege-set>"
                f"{privileges}</d:current-user-privilege-set><c:supported-calendar-component-set>{comps}"
                f"</c:supported-calendar-component-set>{sync}{ctag}{reports}")

    @staticmethod
    def _ok(href: str, props: str) -> str:
        return (f"<d:response><d:href>{escape(href)}</d:href><d:propstat><d:prop>{props}</d:prop>"
                "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>")

    def _multistatus(self, inner: str, token: str = "") -> httpx.Response:
        tok = f"<d:sync-token>{token}</d:sync-token>" if token else ""
        return httpx.Response(207, headers={"Content-Type": "application/xml"},
                              text=f'<?xml version="1.0"?><d:multistatus {NS}>{inner}{tok}</d:multistatus>')

    def _propfind(self, path: str, depth: str) -> httpx.Response:
        principal = f"<d:current-user-principal><d:href>{self.principal}</d:href></d:current-user-principal>"
        home_url = f"https://{self.home_host}{self.home}" if self.home_host != self.host else self.home
        if path == "/dav/":  # sa racine WebDAV ; « / » n'en est pas une (comme Nextcloud) : il faut .well-known
            return self._multistatus(self._ok(path, principal))
        if path == self.principal:
            addresses = "".join(f"<d:href>{a}</d:href>" for a in self.addresses)
            return self._multistatus(self._ok(path, (
                f"{principal}<c:calendar-home-set><d:href>{home_url}</d:href></c:calendar-home-set>"
                f"<c:calendar-user-address-set>{addresses}</c:calendar-user-address-set>"
                f"<c:schedule-inbox-URL><d:href>{self.home}inbox/</d:href></c:schedule-inbox-URL>")))
        if path == f"{self.home}inbox/":
            return self._multistatus(self._ok(path, (
                "<d:resourcetype><d:collection/><c:schedule-inbox/></d:resourcetype><c:schedule-default-calendar-URL>"
                f"<d:href>{self.home}{self.default}/</d:href></c:schedule-default-calendar-URL>")))
        if path == self.home:
            inner = self._ok(path, "<d:resourcetype><d:collection/></d:resourcetype>")
            if depth == "1":
                inner += self._ok(f"{self.home}inbox/",
                                  "<d:resourcetype><d:collection/><c:schedule-inbox/></d:resourcetype>")
                inner += "".join(self._ok(f"{self.home}{k}/", self._props(k)) for k in self.collections)
            return self._multistatus(inner)
        coll, name = self._split(path)
        if coll is not None and not name:
            return self._multistatus(self._ok(path, self._props(coll) + principal))
        return httpx.Response(404)

    def _report(self, coll: str, body: bytes) -> httpx.Response:
        root = ElementTree.fromstring(body)
        c = self.collections[coll]
        base = f"{self.home}{coll}/"
        if root.tag == f"{{{C}}}calendar-query":
            inner = "".join(self._ok(base + n, f"<d:getetag>{e}</d:getetag>") for n, (e, _t) in c.items.items())
            return self._multistatus(inner)
        if root.tag == f"{{{C}}}calendar-multiget":
            inner = ""
            for h in root.iter(f"{{{D}}}href"):
                name = unquote(urlsplit(h.text or "").path).rstrip("/").rsplit("/", 1)[-1]
                if name in c.items:
                    etag, text = c.items[name]
                    inner += self._ok(base + name, f"<d:getetag>{etag}</d:getetag><c:calendar-data>"
                                                   f"{escape(text)}</c:calendar-data>")
                else:
                    inner += (f"<d:response><d:href>{base + name}</d:href><d:status>HTTP/1.1 404 Not Found"
                              "</d:status></d:response>")
            return self._multistatus(inner)
        if root.tag == f"{{{D}}}sync-collection":
            if not self.sync:
                return httpx.Response(501)
            given = (root.findtext(f"{{{D}}}sync-token") or "").strip()
            since = int(given.removeprefix("tok-")) if given.startswith("tok-") and given[4:].isdigit() else -1
            if given and (since < 0 or since > self.token):
                return httpx.Response(403, text=f'<?xml version="1.0"?><d:error {NS}><d:valid-sync-token/></d:error>')
            changed: dict[str, bool] = {}
            for n, name, deleted in c.log:
                if n > since:
                    changed[name] = deleted
            inner = ""
            for name, deleted in changed.items():
                if deleted or name not in c.items:
                    inner += (f"<d:response><d:href>{base + name}</d:href><d:status>HTTP/1.1 404 Not Found"
                              "</d:status></d:response>")
                else:
                    inner += self._ok(base + name, f"<d:getetag>{c.items[name][0]}</d:getetag>")
            return self._multistatus(inner, token=f"tok-{self.token}")
        return httpx.Response(400)


__all__ = ["Collection", "FakeCalDav", "Seen"]

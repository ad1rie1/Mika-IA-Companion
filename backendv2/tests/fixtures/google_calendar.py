"""Un faux Google (ADR 0309, lot 2), servi par un transport ``httpx`` factice : son point OAuth (``oauth2.googleapis.com``
: le code d'une autorisation avec PKCE, le renouvellement, la révocation) et l'API Calendar v3
(``www.googleapis.com``), sans réseau.

Il suit les formes que dit la documentation de Google : ``calendarList`` (``accessRole``, ``primary``, ``selected``,
``backgroundColor``, ``defaultReminders``) ; ``events.list`` avec ``maxResults``, ``pageToken``, ``showDeleted``,
``singleEvents``, ``timeMin`` et ``syncToken`` (``nextPageToken`` sur chaque page sauf la dernière, ``nextSyncToken``
sur la dernière ; un jeton périmé : ``410`` et la raison ``fullSyncRequired``) ; un événement supprimé ne porte que
son identifiant et ``status: cancelled`` ; une occurrence supprimée garde ``recurringEventId`` et
``originalStartTime`` ; ``events.instances`` (``originalStart``) ; ``insert``, ``patch`` (``If-Match`` : ``412``),
``delete`` ; les erreurs au format ``{"error": {"code", "message", "errors": [{"reason"}], "status"}}``. Un jeton
d'accès inconnu : ``401``. Chaque requête est notée (``requests``) ; ``fail`` en fait échouer une à la demande.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import itertools
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit
from zoneinfo import ZoneInfo

import httpx

from mika.ports.agenda import Event, Recurrence, Span, at_us, day_at, occurrence_key, occurrences, us_of

API = "/calendar/v3"
CLIENT_ID = "123456789012-abcdefgh12345678.apps.googleusercontent.com"
SECRET = "GOCSPX-secret-du-client-42"
SCOPE = "https://www.googleapis.com/auth/calendar"


@dataclass
class Seen:
    method: str
    host: str
    path: str
    params: dict[str, str]
    headers: httpx.Headers
    body: Any


def _error(status: int, reason: str, message: str, state: str = "") -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": status, "message": message, "errors": [
        {"domain": "global", "reason": reason, "message": message}], "status": state or reason.upper()}})


def instant(item_time: dict[str, Any]) -> tuple[int, bool]:
    if "date" in item_time and item_time["date"]:
        return day_at(item_time["date"]), True
    return us_of(datetime.fromisoformat(item_time["dateTime"].replace("Z", "+00:00"))), False


def when(us: int, all_day: bool, zone: str) -> dict[str, Any]:
    if all_day:
        return {"date": at_us(us).strftime("%Y-%m-%d")}
    return {"dateTime": at_us(us, ZoneInfo(zone)).isoformat(timespec="seconds"), "timeZone": zone}


class FakeGoogle:
    def __init__(self, *, owner: str = "adrien.moreau@gmail.com", page: int = 2500) -> None:
        self.owner = owner
        self.page = page
        self.client_id, self.secret = CLIENT_ID, SECRET
        self.calendars: dict[str, dict[str, Any]] = {
            owner: {"id": owner, "summary": owner, "summaryOverride": "Perso", "accessRole": "owner", "primary": True,
                    "selected": True, "backgroundColor": "#7BD148", "timeZone": "Europe/Paris",
                    "defaultReminders": [{"method": "popup", "minutes": 30}]},
            "famille123@group.calendar.google.com": {
                "id": "famille123@group.calendar.google.com", "summary": "Famille", "accessRole": "writer",
                "selected": True, "backgroundColor": "#FF887C", "timeZone": "Europe/Paris", "defaultReminders": []},
            "fr.french#holiday@group.v.calendar.google.com": {
                "id": "fr.french#holiday@group.v.calendar.google.com", "summary": "Jours fériés en France",
                "accessRole": "reader", "backgroundColor": "#16A765", "timeZone": "Europe/Paris"},
        }
        self.events: dict[str, dict[str, dict[str, Any]]] = {c: {} for c in self.calendars}
        self._seq = itertools.count(1)
        self.seq = 0
        self._ids = itertools.count(1)
        self.expired_tokens: set[str] = set()
        #: les codes d'autorisation délivrés : code → (défi PKCE, redirection, portée)
        self.codes: dict[str, tuple[str, str, str]] = {}
        self.refresh: dict[str, bool] = {}
        self.access: set[str] = set()
        self._tokens = itertools.count(1)
        self.requests: list[Seen] = []
        self.fail: dict[tuple[str, str], Callable[[], httpx.Response]] = {}

    # ── ce que les tests posent ──
    def _stamp(self, item: dict[str, Any]) -> None:
        self.seq = next(self._seq)
        item["_seq"] = self.seq
        item["etag"] = f'"e{self.seq}"'
        item["updated"] = f"2026-11-23T10:{self.seq % 60:02d}:00.000Z"

    def put(self, calendar: str, item: dict[str, Any]) -> dict[str, Any]:
        """Un événement écrit ailleurs (sur le téléphone, par un autre) : rangé tel quel, daté d'une version."""
        item = copy.deepcopy(item)
        item.setdefault("id", f"ev{next(self._ids)}")
        item.setdefault("status", "confirmed")
        item.setdefault("iCalUID", f"{item['id']}@google.com")
        item.setdefault("organizer", {"email": self.owner, "self": True})
        item.setdefault("created", "2026-11-01T09:00:00.000Z")
        self._stamp(item)
        self.events[calendar][item["id"]] = item
        return item

    def remove(self, calendar: str, gid: str) -> None:
        """Un événement supprimé ailleurs : Google ne garde que son identifiant et son état."""
        self.events[calendar][gid] = {"id": gid, "status": "cancelled"}
        self._stamp(self.events[calendar][gid])

    def consent(self, url: str, *, scope: str = SCOPE, deny: bool = False) -> str:
        """La personne consent chez Google : l'adresse de la page de retour (qui ne s'ouvre pas), avec son code."""
        query = dict(parse_qsl(urlsplit(url).query))
        assert query["client_id"] == self.client_id and query["response_type"] == "code"
        assert query["code_challenge_method"] == "S256" and query["access_type"] == "offline"
        assert query["prompt"] == "consent"
        if deny:
            return f"{query['redirect_uri']}?{urlencode({'error': 'access_denied', 'state': query['state']})}"
        code = f"4/0A{next(self._tokens)}-code"
        self.codes[code] = (query["code_challenge"], query["redirect_uri"], scope)
        return f"{query['redirect_uri']}?{urlencode({'state': query['state'], 'code': code, 'scope': scope})}"

    def revoke_all(self) -> None:
        for token in self.refresh:
            self.refresh[token] = False
        self.access.clear()

    def seen(self, method: str, contains: str = "") -> list[Seen]:
        return [r for r in self.requests if r.method == method and contains in r.path]

    # ── le transport ──
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        params = dict(parse_qsl(url.query.decode()))
        raw = request.content.decode() if request.content else ""
        if url.host == "oauth2.googleapis.com":
            body: Any = dict(parse_qsl(raw))
        else:
            body = json.loads(raw) if raw else None
        path = unquote(url.raw_path.decode().split("?", 1)[0])
        self.requests.append(Seen(request.method, url.host, path, params, request.headers, body))
        failing = self.fail.get((request.method, path))
        if failing is not None:
            return failing()
        if url.host == "oauth2.googleapis.com":
            return self._oauth(path, body)
        assert url.host == "www.googleapis.com", url.host
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] not in self.access:
            return _error(401, "authError", "Request had invalid authentication credentials.", "UNAUTHENTICATED")
        return self._api(request.method, path.removeprefix(API), params, body, request.headers)

    def _oauth(self, path: str, data: dict[str, str]) -> httpx.Response:
        if path == "/revoke":
            if data.get("token") in self.refresh:
                self.refresh[data["token"]] = False
                return httpx.Response(200)
            return httpx.Response(400, json={"error": "invalid_token", "error_description": "Bad Request"})
        assert path == "/token"
        if data.get("client_id") != self.client_id or data.get("client_secret") != self.secret:
            return httpx.Response(401, json={"error": "invalid_client", "error_description": "Unauthorized"})
        if data.get("grant_type") == "authorization_code":
            got = self.codes.pop(data.get("code", ""), None)
            if got is None:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Bad Request"})
            challenge, redirect, scope = got
            verifier = data.get("code_verifier", "")
            digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            if digest != challenge or data.get("redirect_uri") != redirect:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Bad Request"})
            refresh = f"1//renouv-{next(self._tokens)}"
            self.refresh[refresh] = True
            return self._issue(scope, refresh)
        if data.get("grant_type") == "refresh_token":
            if not self.refresh.get(data.get("refresh_token", "")):
                return httpx.Response(400, json={"error": "invalid_grant",
                                                 "error_description": "Token has been expired or revoked."})
            return self._issue(SCOPE, None)
        return httpx.Response(400, json={"error": "unsupported_grant_type"})

    def _issue(self, scope: str, refresh: str | None) -> httpx.Response:
        access = f"ya29.acces-{next(self._tokens)}"
        self.access.add(access)
        body = {"access_token": access, "expires_in": 3599, "scope": scope, "token_type": "Bearer"}
        if refresh:
            body["refresh_token"] = refresh
        return httpx.Response(200, json=body)

    # ── l'API ──
    def _api(self, method: str, path: str, params: dict[str, str], body: Any, headers: httpx.Headers
             ) -> httpx.Response:
        parts = [p for p in path.split("/") if p]
        if parts == ["users", "me", "calendarList"] and method == "GET":
            items = [{k: v for k, v in c.items()} for c in self.calendars.values()]
            return self._paged(items, params, {"kind": "calendar#calendarList"}, sync=False)
        if parts == ["calendars"] and method == "POST":
            cid = f"cal{next(self._ids)}@group.calendar.google.com"
            self.calendars[cid] = {"id": cid, "summary": body["summary"], "accessRole": "owner",
                                   "timeZone": "Europe/Paris"}
            self.events[cid] = {}
            return httpx.Response(200, json={"id": cid, "summary": body["summary"], "timeZone": "Europe/Paris"})
        if len(parts) < 3 or parts[0] != "calendars" or parts[2] != "events":
            return _error(404, "notFound", "Not Found")
        cal = parts[1]
        if cal not in self.events:
            return _error(404, "notFound", "Not Found")
        if len(parts) == 3:
            if method == "GET":
                return self._list(cal, params)
            if method == "POST":
                return self._insert(cal, body, params)
        if len(parts) == 4:
            if method == "GET":
                item = self._find(cal, parts[3])
                return httpx.Response(200, json=self._public(item)) if item else _error(404, "notFound", "Not Found")
            if method == "PATCH":
                return self._patch(cal, parts[3], body, headers, params)
            if method == "DELETE":
                return self._delete(cal, parts[3], headers, params)
        if len(parts) == 5 and parts[4] == "instances" and method == "GET":
            return self._instances(cal, parts[3], params)
        return _error(404, "notFound", "Not Found")

    @staticmethod
    def _public(item: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in item.items() if not k.startswith("_")}

    def _paged(self, items: list[dict[str, Any]], params: dict[str, str], top: dict[str, Any], *,
               sync: bool) -> httpx.Response:
        size = min(int(params.get("maxResults") or 250), self.page)
        offset = int(params.get("pageToken", "p0")[1:].split("|")[0])
        page = items[offset:offset + size]
        out = {**top, "items": page}
        if offset + size < len(items):
            out["nextPageToken"] = f"p{offset + size}|{self.seq}"
        elif sync:
            out["nextSyncToken"] = f"sync-{self.seq}"
        return httpx.Response(200, json=out)

    def _list(self, cal: str, params: dict[str, str]) -> httpx.Response:
        assert params.get("singleEvents") == "false" and params.get("showDeleted") == "true"
        token = params.get("syncToken")
        rows = list(self.events[cal].values())
        if token:
            assert "timeMin" not in params
            if token in self.expired_tokens or not token.startswith("sync-"):
                return _error(410, "fullSyncRequired", "Sync token is no longer valid, a full sync is required.",
                              "GONE")
            since = int(token.split("-", 1)[1])
            upto = int(params["pageToken"].split("|")[1]) if params.get("pageToken") else self.seq
            rows = [r for r in rows if since < r["_seq"] <= upto]
        elif params.get("timeMin"):
            floor = us_of(datetime.fromisoformat(params["timeMin"].replace("Z", "+00:00")))
            rows = [r for r in rows if "end" not in r or r.get("recurrence") or instant(r["end"])[0] > floor]
        rows.sort(key=lambda r: r["_seq"])
        top = {"kind": "calendar#events", "timeZone": self.calendars[cal].get("timeZone", "UTC"),
               "defaultReminders": self.calendars[cal].get("defaultReminders", []), "accessRole": "owner"}
        return self._paged([self._public(r) for r in rows], params, top, sync=True)

    def _insert(self, cal: str, body: dict[str, Any], params: dict[str, str]) -> httpx.Response:
        item = copy.deepcopy(body)
        gid = f"new{next(self._ids)}"
        item.update(id=gid, iCalUID=f"{gid}@google.com", organizer={"email": self.owner, "self": True},
                    creator={"email": self.owner, "self": True}, created="2026-11-23T14:20:00.000Z",
                    _sent=params.get("sendUpdates", ""))
        item.setdefault("status", "confirmed")
        for a in item.get("attendees") or []:
            a.setdefault("responseStatus", "needsAction")
        self._stamp(item)
        self.events[cal][gid] = item
        return httpx.Response(200, json=self._public(item))

    # ── les séries ──
    def _series(self, master: dict[str, Any]) -> Event:
        start, all_day = instant(master["start"])
        end = instant(master["end"])[0]
        rule = next((line[6:] for line in master.get("recurrence") or [] if line.startswith("RRULE:")), "")
        zone = master["start"].get("timeZone", "")
        return Event(calendar="x", uid=master["id"], span=Span(start, end, zone, all_day),
                     recurrence=Recurrence(rule) if rule else None)

    def _instance(self, cal: str, master: dict[str, Any], key: str) -> dict[str, Any] | None:
        stored = next((e for e in self.events[cal].values() if e.get("recurringEventId") == master["id"]
                       and occurrence_key(*instant(e["originalStartTime"])) == key), None)
        if stored is not None:
            return stored
        series = self._series(master)
        at = day_at(key) if "T" not in key else us_of(datetime.strptime(key, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=ZoneInfo("UTC")))
        if not any(o.key == key for o in occurrences(series, at, at + 1)):
            return None
        duration = series.span.end - series.span.start
        zone = master["start"].get("timeZone", "UTC")
        item = {k: copy.deepcopy(v) for k, v in master.items() if k not in ("recurrence", "id", "_seq")}
        item.update(id=f"{master['id']}_{key}", recurringEventId=master["id"],
                    originalStartTime=when(at, series.span.all_day, zone), start=when(at, series.span.all_day, zone),
                    end=when(at + duration, series.span.all_day, zone), _virtual=True)
        return item

    def _find(self, cal: str, gid: str) -> dict[str, Any] | None:
        item = self.events[cal].get(gid)
        if item is not None:
            return item
        master_id, _sep, key = gid.rpartition("_")
        master = self.events[cal].get(master_id)
        return self._instance(cal, master, key) if master and master.get("recurrence") else None

    def _instances(self, cal: str, gid: str, params: dict[str, str]) -> httpx.Response:
        master = self.events[cal].get(gid)
        if master is None or not master.get("recurrence"):
            return _error(404, "notFound", "Not Found")
        wanted = params.get("originalStart", "")
        key = wanted.replace("-", "") if "T" not in wanted else occurrence_key(
            us_of(datetime.fromisoformat(wanted.replace("Z", "+00:00"))), False)
        item = self._instance(cal, master, key)
        items = [] if item is None or (item.get("status") == "cancelled" and params.get("showDeleted") != "true") \
            else [self._public(item)]
        return httpx.Response(200, json={"kind": "calendar#events", "items": items})

    def _patch(self, cal: str, gid: str, body: dict[str, Any], headers: httpx.Headers,
               params: dict[str, str]) -> httpx.Response:
        item = self._find(cal, gid)
        if item is None or item.get("status") == "cancelled" and not item.get("recurringEventId"):
            return _error(404, "notFound", "Not Found")
        if headers.get("if-match") and headers["if-match"] != item.get("etag"):
            return _error(412, "conditionNotMet", "Precondition Failed", "FAILED_PRECONDITION")
        item = self.events[cal].setdefault(item["id"], item)
        item.pop("_virtual", None)
        for k, v in body.items():
            if isinstance(v, dict):
                merged = {**(item.get(k) or {}), **v}
                item[k] = {kk: vv for kk, vv in merged.items() if vv is not None}
            else:
                item[k] = copy.deepcopy(v)
        item["_sent"] = params.get("sendUpdates", "")
        self._stamp(item)
        return httpx.Response(200, json=self._public(item))

    def _delete(self, cal: str, gid: str, headers: httpx.Headers, params: dict[str, str]) -> httpx.Response:
        item = self._find(cal, gid)
        if item is None or item.get("status") == "cancelled":
            return _error(410, "deleted", "Resource has been deleted")
        if headers.get("if-match") and headers["if-match"] != item.get("etag"):
            return _error(412, "conditionNotMet", "Precondition Failed", "FAILED_PRECONDITION")
        if item.get("recurringEventId"):
            gone = {"id": item["id"], "status": "cancelled", "recurringEventId": item["recurringEventId"],
                    "originalStartTime": item["originalStartTime"]}
        else:
            gone = {"id": item["id"], "status": "cancelled"}
        self._stamp(gone)
        self.events[cal][item["id"]] = gone
        return httpx.Response(204)


__all__ = ["CLIENT_ID", "SCOPE", "SECRET", "FakeGoogle", "Seen", "instant", "when"]

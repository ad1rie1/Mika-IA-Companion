"""Un faux Microsoft (ADR 0309, lot 2), servi par un transport ``httpx`` factice : son point OAuth2
(``login.microsoftonline.com`` : le code d'appareil, les jetons, leurs refus ``AADSTS…``) et les agendas de Microsoft
Graph v1.0 (``graph.microsoft.com``), sans réseau.

Il suit les formes que dit la documentation de Graph : ``/me/calendars`` (``hexColor``, ``color``, ``canEdit``,
``isDefaultCalendar``, ``owner``) ; ``calendarView/delta`` sur un intervalle — les occurrences d'une série, jamais la
série, chacune avec son ``seriesMasterId`` et son ``originalStart`` ; des pages (``Prefer: odata.maxpagesize``) liées
par ``@odata.nextLink`` (``$skiptoken``), la dernière portant ``@odata.deltaLink`` (``$deltatoken``) ; ce qui part
(``@removed``) ne porte que son identifiant ; un état perdu : ``410`` et ``SyncStateNotFound`` ; les heures en UTC
(``Prefer: outlook.timezone``), une journée entière à minuit de son fuseau, lu en UTC (la veille au soir à Paris) ;
``events`` (créer, ``PATCH`` avec ``If-Match`` : ``412`` ``ErrorIrresolvableConflict``, ``DELETE``), ``instances``,
``accept``, ``tentativelyAccept``, ``decline`` (``202``) ; les erreurs ``{"error": {"code", "message"}}``. Un jeton
d'accès inconnu : ``401``. Chaque requête est notée (``requests``) ; ``fail`` en fait échouer une à la demande.
"""

from __future__ import annotations

import copy
import itertools
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, quote, unquote
from zoneinfo import ZoneInfo

import httpx
from icalendar.timezone.windows_to_olson import WINDOWS_TO_OLSON

from mika.ports.agenda import DAY_US, Event, Recurrence, Span, at_us, occurrences, us_of

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
CAL, BIRTHDAYS = "AAMkAGI2TGuLAAA=", "AAMkAGI2TGuLAAB="
_DAYS = {"monday": "MO", "tuesday": "TU", "wednesday": "WE", "thursday": "TH", "friday": "FR", "saturday": "SA",
         "sunday": "SU"}


@dataclass
class Seen:
    method: str
    host: str
    path: str
    params: dict[str, str]
    headers: httpx.Headers
    body: Any


def _error(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": message,
                                                  "innerError": {"request-id": "r-1", "date": "2026-11-23T14:00:00"}}})


def utc(us: int) -> dict[str, str]:
    return {"dateTime": at_us(us).strftime("%Y-%m-%dT%H:%M:%S.0000000"), "timeZone": "UTC"}


def zone_of_graph(name: str) -> str:
    return WINDOWS_TO_OLSON.get(name, name) if name and name != "UTC" else "UTC"


def local_us(value: dict[str, str]) -> int:
    moment = datetime.fromisoformat(value["dateTime"][:19])
    return us_of(moment.replace(tzinfo=ZoneInfo(zone_of_graph(value.get("timeZone", "UTC")))))


def key_at(key: str) -> int:
    if "T" in key:
        return us_of(datetime.strptime(key, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC))
    return us_of(datetime.strptime(key, "%Y%m%d").replace(tzinfo=UTC))


def rule_of(recurrence: dict[str, Any] | None) -> str:
    """Une RRULE pour développer ce que le faux garde (son propre lecteur, plus court que celui du fournisseur :
    chaque jour, chaque semaine, chaque mois à date fixe)."""
    if not recurrence:
        return ""
    pattern, rng = recurrence["pattern"], recurrence["range"]
    parts = {"daily": ["FREQ=DAILY"], "weekly": ["FREQ=WEEKLY", "BYDAY=" + ",".join(
        _DAYS[d] for d in pattern.get("daysOfWeek", []))], "absoluteMonthly": [
        "FREQ=MONTHLY", f"BYMONTHDAY={pattern.get('dayOfMonth')}"]}[pattern["type"]]
    if int(pattern.get("interval", 1)) > 1:
        parts.append(f"INTERVAL={pattern['interval']}")
    if rng.get("type") == "numbered":
        parts.append(f"COUNT={rng['numberOfOccurrences']}")
    elif rng.get("type") == "endDate":
        parts.append("UNTIL=" + rng["endDate"].replace("-", ""))
    return ";".join(parts)


class FakeGraph:
    def __init__(self, *, owner: str = "adrien.moreau@outlook.fr", pending: int = 1) -> None:
        self.owner = owner
        self.calendars: dict[str, dict[str, Any]] = {
            CAL: {"id": CAL, "name": "Calendrier", "color": "auto", "hexColor": "#8764b8", "canEdit": True,
                  "isDefaultCalendar": True, "owner": {"name": "Adrien Moreau", "address": owner}},
            BIRTHDAYS: {"id": BIRTHDAYS, "name": "Anniversaires", "color": "lightGreen", "hexColor": "",
                        "canEdit": False, "isDefaultCalendar": False, "owner": {"name": "Adrien Moreau",
                                                                                "address": owner}},
        }
        #: les séries et les événements simples (leurs heures en µs UTC, leur fuseau IANA, leur règle à développer)
        self.items: dict[str, dict[str, Any]] = {}
        #: les occurrences changées d'une série : (série, clé) → ce qui change, ou ``{"_cancelled": True}``
        self.exceptions: dict[tuple[str, str], dict[str, Any]] = {}
        self._ids = itertools.count(1)
        self._versions = itertools.count(1)
        self.tokens: dict[str, dict[str, Any]] = {}
        self.pages: dict[str, dict[str, Any]] = {}
        self._tokens = itertools.count(1)
        self.requests: list[Seen] = []
        self.fail: dict[tuple[str, str], Callable[[], httpx.Response]] = {}
        self.answers: list[tuple[str, str, dict[str, Any]]] = []
        # OAuth
        self.pending = pending
        self.refresh: dict[str, bool] = {}
        self.access: set[str] = set()
        self.refused = ""  # le code AADSTS d'un refus du renouvellement, à la demande
        self.oauth: list[tuple[str, str, dict[str, str]]] = []

    # ── ce que les tests posent ──
    def put(self, calendar: str, subject: str, start: int, end: int, *, zone: str = "Europe/Paris",
            all_day: bool = False, rule: dict[str, Any] | None = None, gid: str = "", **more: Any) -> dict[str, Any]:
        """Un événement écrit ailleurs (sur le téléphone, dans Outlook), ou une série (``rule`` : sa
        ``patternedRecurrence``)."""
        gid = gid or f"AAMkEv{next(self._ids)}="
        item = {"id": gid, "subject": subject, "_cal": calendar, "_start": start, "_end": end, "_zone": zone,
                "isAllDay": all_day, "recurrence": rule, "type": "seriesMaster" if rule else "singleInstance",
                "iCalUId": f"040000008200E00074C5B7101A82E008{gid}", "isOrganizer": True, "isCancelled": False,
                "showAs": "free" if all_day else "busy", "sensitivity": "normal", "isReminderOn": True,
                "reminderMinutesBeforeStart": 15, "responseRequested": True,
                "responseStatus": {"response": "organizer", "time": "0001-01-01T00:00:00Z"},
                "organizer": {"emailAddress": {"name": "Adrien Moreau", "address": self.owner}}, "attendees": [],
                "body": {"contentType": "text", "content": ""}, "location": {"displayName": ""},
                "createdDateTime": "2026-11-01T09:00:00Z"}
        item.update(copy.deepcopy(more))
        self._bump(item)
        self.items[gid] = item
        return item

    def change(self, gid: str, **fields: Any) -> None:
        self.items[gid].update(fields)
        self._bump(self.items[gid])

    def cancel(self, master: str, key: str) -> None:
        self.exceptions[(master, key)] = {"_cancelled": True}

    def move(self, master: str, key: str, start: int, end: int, **fields: Any) -> None:
        self.exceptions[(master, key)] = {"_start": start, "_end": end, **fields, "_v": next(self._versions)}

    def drop(self, gid: str) -> None:
        self.items.pop(gid, None)
        for k in [k for k in self.exceptions if k[0] == gid]:
            del self.exceptions[k]

    def expire_tokens(self) -> None:
        self.tokens.clear()

    def seen(self, method: str, contains: str = "") -> list[Seen]:
        return [r for r in self.requests if r.method == method and contains in r.path]

    def _bump(self, item: dict[str, Any]) -> None:
        item["_v"] = next(self._versions)
        item["lastModifiedDateTime"] = "2026-11-23T10:00:00Z"

    # ── les occurrences ──
    def _series(self, item: dict[str, Any]) -> Event:
        rule = rule_of(item.get("recurrence"))
        return Event(calendar="x", uid=item["id"], span=Span(item["_start"], item["_end"], item["_zone"],
                                                             bool(item.get("isAllDay"))),
                     recurrence=Recurrence(rule) if rule else None)

    def _public(self, item: dict[str, Any]) -> dict[str, Any]:
        out = {k: copy.deepcopy(v) for k, v in item.items() if not k.startswith("_")}
        out["start"], out["end"] = utc(item["_start"]), utc(item["_end"])
        windows = next((w for w, o in WINDOWS_TO_OLSON.items() if o == item["_zone"]), item["_zone"])
        out["originalStartTimeZone"] = out["originalEndTimeZone"] = windows
        out["@odata.etag"] = f'W/"v{item["_v"]}"'
        if item.get("type") != "seriesMaster":
            out.pop("recurrence", None)
        return out

    def instances(self, gid: str, start: int, end: int) -> list[dict[str, Any]]:
        master = self.items[gid]
        series = self._series(master)
        duration = master["_end"] - master["_start"]
        out = []
        for o in occurrences(series, start - 30 * DAY_US, end + 30 * DAY_US):
            got = self._instance(master, o.key, o.span.start, duration)
            if got is not None and got["_start"] < end and max(got["_end"], got["_start"] + 1) > start:
                out.append(got)
        return out

    def _instance(self, master: dict[str, Any], key: str, at: int, duration: int) -> dict[str, Any] | None:
        changed = self.exceptions.get((master["id"], key))
        if changed is not None and changed.get("_cancelled"):
            return None
        item = {k: copy.deepcopy(v) for k, v in master.items() if k != "recurrence"}
        item.update(id=f"{master['id']}OID{key}", type="exception" if changed else "occurrence",
                    seriesMasterId=master["id"], originalStart=at_us(at).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    _start=at, _end=at + duration)
        if changed:
            item.update({k: copy.deepcopy(v) for k, v in changed.items()})
            item["_v"] = master["_v"] * 1000 + changed["_v"]
        return item

    def _find(self, gid: str) -> dict[str, Any] | None:
        if gid in self.items:
            return self.items[gid]
        master_id, sep, key = gid.partition("OID")
        master = self.items.get(master_id)
        if not sep or master is None or master.get("type") != "seriesMaster":
            return None
        at = key_at(key)
        series = self._series(master)
        if not any(o.key == key for o in occurrences(series, at, at + 1)):
            return None
        return self._instance(master, key, at, master["_end"] - master["_start"])

    def view(self, calendar: str, start: int, end: int) -> list[dict[str, Any]]:
        out = []
        for item in self.items.values():
            if item["_cal"] != calendar:
                continue
            if item.get("type") == "seriesMaster":
                out.extend(self.instances(item["id"], start, end))
            elif item["_start"] < end and max(item["_end"], item["_start"] + 1) > start:
                out.append(item)
        return out

    # ── le transport ──
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        raw = request.content.decode() if request.content else ""
        if url.host == "login.microsoftonline.com":
            data = dict(parse_qsl(raw))
            parts = url.path.strip("/").split("/")
            self.oauth.append((parts[0], parts[-1], data))
            return self._login(parts[-1], data)
        assert url.host == "graph.microsoft.com", url.host
        params = dict(parse_qsl(url.query.decode()))
        path = unquote(url.raw_path.decode().split("?", 1)[0])
        body = json.loads(raw) if raw else None
        self.requests.append(Seen(request.method, url.host, path, params, request.headers, body))
        failing = self.fail.get((request.method, path))
        if failing is not None:
            return failing()
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] not in self.access:
            return _error(401, "InvalidAuthenticationToken", "Access token has expired or is not yet valid.")
        assert 'outlook.timezone="UTC"' in request.headers.get("prefer", "")
        return self._graph(request.method, path.removeprefix("/v1.0"), params, body, request.headers)

    def _login(self, endpoint: str, data: dict[str, str]) -> httpx.Response:
        if endpoint == "devicecode":
            assert "Calendars.ReadWrite" in data["scope"] and "offline_access" in data["scope"]
            return httpx.Response(200, json={"device_code": "appareil-1", "user_code": "GRPH-CODE", "expires_in": 900,
                                             "interval": 5, "verification_uri": "https://microsoft.com/devicelogin"})
        if data.get("grant_type") == DEVICE_GRANT:
            if self.pending:
                self.pending -= 1
                return httpx.Response(400, json={"error": "authorization_pending",
                                                 "error_description": "AADSTS70016: OAuth 2.0 device flow error."})
            return self._issue(data)
        assert "Calendars.ReadWrite" in data.get("scope", "")
        if self.refused or not self.refresh.get(data.get("refresh_token", "")):
            code = self.refused or "AADSTS70000"
            return httpx.Response(400, json={"error": "invalid_grant", "error_description":
                                             f"{code}: The provided grant has expired due to it being revoked."})
        return self._issue(data)

    def _issue(self, data: dict[str, str]) -> httpx.Response:
        n = next(self._tokens)
        access, refresh = f"eyJ0eXAi-acces-{n}", f"M.C5-renouv-{n}"
        self.access.add(access)
        self.refresh[refresh] = True
        return httpx.Response(200, json={"access_token": access, "refresh_token": refresh, "expires_in": 3599,
                                         "token_type": "Bearer", "scope": "Calendars.ReadWrite"})

    def revoke_all(self) -> None:
        for token in self.refresh:
            self.refresh[token] = False
        self.access.clear()

    # ── Graph ──
    def _graph(self, method: str, path: str, params: dict[str, str], body: Any, headers: httpx.Headers
               ) -> httpx.Response:
        parts = [p for p in path.split("/") if p]
        if parts == ["me", "calendars"]:
            if method == "GET":
                return httpx.Response(200, json={"value": list(self.calendars.values())})
            cid = f"AAMkCal{next(self._ids)}="
            self.calendars[cid] = {"id": cid, "name": body["name"], "color": "auto", "hexColor": "", "canEdit": True,
                                   "isDefaultCalendar": False, "owner": {"name": "Adrien Moreau",
                                                                         "address": self.owner}}
            return httpx.Response(201, json=self.calendars[cid])
        if len(parts) == 5 and parts[:2] == ["me", "calendars"] and parts[3:] == ["calendarView", "delta"]:
            return self._delta(parts[2], params, headers)
        if len(parts) == 4 and parts[:2] == ["me", "calendars"] and parts[3] == "events" and method == "POST":
            return self._create(parts[2], body)
        if len(parts) >= 3 and parts[:2] == ["me", "events"]:
            gid = parts[2]
            if len(parts) == 4 and parts[3] == "instances":
                if gid not in self.items:
                    return _error(404, "ErrorItemNotFound", "The specified object was not found in the store.")
                start = us_of(datetime.fromisoformat(params["startDateTime"].replace("Z", "+00:00")))
                end = us_of(datetime.fromisoformat(params["endDateTime"].replace("Z", "+00:00")))
                return httpx.Response(200, json={"value": [self._public(i) for i in self.instances(gid, start, end)]})
            if len(parts) == 4 and parts[3] in ("accept", "tentativelyAccept", "decline"):
                return self._answer(gid, parts[3], body)
            item = self._find(gid)
            if item is None:
                return _error(404, "ErrorItemNotFound", "The specified object was not found in the store.")
            if method == "GET":
                return httpx.Response(200, json=self._public(item))
            if headers.get("if-match") and headers["if-match"] != f'W/"v{item["_v"]}"':
                return _error(412, "ErrorIrresolvableConflict",
                              "The send or update operation could not be performed because the change key passed in "
                              "the request does not match the current change key for the item.")
            if method == "PATCH":
                return self._patch(item, body)
            if method == "DELETE":
                if item.get("seriesMasterId"):
                    self.cancel(item["seriesMasterId"], gid.partition("OID")[2])
                else:
                    self.drop(gid)
                return httpx.Response(204)
        return _error(400, "BadRequest", "Resource not found for the segment.")

    def _fields(self, target: dict[str, Any], body: dict[str, Any]) -> None:
        for k, v in body.items():
            if k in ("start", "end"):
                target["_" + k] = local_us(v)
                target["_zone"] = zone_of_graph(v.get("timeZone", "UTC"))
            elif k == "recurrence":
                target["recurrence"] = v
                target["type"] = "seriesMaster" if v else "singleInstance"
            else:
                target[k] = copy.deepcopy(v)

    def _create(self, calendar: str, body: dict[str, Any]) -> httpx.Response:
        if not self.calendars[calendar]["canEdit"]:
            return _error(403, "ErrorAccessDenied", "Access is denied. Check credentials and try again.")
        item = self.put(calendar, body.get("subject", ""), 0, 0)
        self._fields(item, {k: v for k, v in body.items()})
        for a in item.get("attendees") or []:
            a.setdefault("status", {"response": "none", "time": "0001-01-01T00:00:00Z"})
        self._bump(item)
        return httpx.Response(201, json=self._public(item))

    def _patch(self, item: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
        if item.get("seriesMasterId"):
            key = item["id"].partition("OID")[2]
            changed = self.exceptions.setdefault((item["seriesMasterId"], key), {})
            self._fields(changed, body)
            changed["_v"] = next(self._versions)
            master = self.items[item["seriesMasterId"]]
            return httpx.Response(200, json=self._public(self._instance(
                master, key, key_at(key), master["_end"] - master["_start"])))
        self._fields(item, body)
        self._bump(item)
        return httpx.Response(200, json=self._public(item))

    def _answer(self, gid: str, action: str, body: dict[str, Any]) -> httpx.Response:
        item = self._find(gid)
        if item is None:
            return _error(404, "ErrorItemNotFound", "The specified object was not found in the store.")
        response = {"accept": "accepted", "tentativelyAccept": "tentativelyAccepted", "decline": "declined"}[action]
        self.answers.append((gid, action, body))
        status = {"response": response, "time": "2026-11-23T14:00:00Z"}
        attendees = [dict(a, status=status) if (a.get("emailAddress") or {}).get("address") == self.owner else a
                     for a in item.get("attendees") or []]
        if item.get("seriesMasterId"):
            key = gid.partition("OID")[2]
            changed = self.exceptions.setdefault((item["seriesMasterId"], key), {})
            changed.update(responseStatus=status, attendees=attendees, _v=next(self._versions))
        else:
            item.update(responseStatus=status, attendees=attendees)
            self._bump(item)
        return httpx.Response(202)

    # ── le delta ──
    def _link(self, calendar: str, name: str, token: str) -> str:
        return f"https://graph.microsoft.com/v1.0/me/calendars/{quote(calendar, safe='')}/calendarView/delta?" \
               f"${name}={token}"

    def _delta(self, calendar: str, params: dict[str, str], headers: httpx.Headers) -> httpx.Response:
        size = int(re.search(r"odata\.maxpagesize=(\d+)", headers.get("prefer", "")).group(1))
        if "$skiptoken" in params:
            page = self.pages.pop(params["$skiptoken"], None)
            if page is None:
                return _error(410, "SyncStateNotFound", "The sync state generation is not found.")
            return self._pages(calendar, page["rows"], page["state"], size)
        if "$deltatoken" in params:
            state = self.tokens.get(params["$deltatoken"])
            if state is None:
                return _error(410, "SyncStateNotFound", "The sync state generation is not found.")
            start, end, before = state["start"], state["end"], state["snap"]
        else:
            start = us_of(datetime.fromisoformat(params["startDateTime"].replace("Z", "+00:00")))
            end = us_of(datetime.fromisoformat(params["endDateTime"].replace("Z", "+00:00")))
            before = None
        now = {i["id"]: i for i in self.view(calendar, start, end)}
        snap = {gid: i["_v"] for gid, i in now.items()}
        if before is None:
            rows = [self._public(i) for i in now.values()]
        else:
            rows = [self._public(i) for gid, i in now.items() if before.get(gid) != i["_v"]]
            rows += [{"@odata.type": "#microsoft.graph.event", "id": gid, "@removed": {"reason": "deleted"}}
                     for gid in before if gid not in now]
        return self._pages(calendar, rows, {"start": start, "end": end, "snap": snap}, size)

    def _pages(self, calendar: str, rows: list[dict[str, Any]], state: dict[str, Any], size: int) -> httpx.Response:
        page, rest = rows[:size], rows[size:]
        out: dict[str, Any] = {"@odata.context": "https://graph.microsoft.com/v1.0/$metadata#Collection(event)",
                               "value": page}
        if rest:
            skip = f"skip{next(self._tokens)}"
            self.pages[skip] = {"rows": rest, "state": state}
            out["@odata.nextLink"] = self._link(calendar, "skiptoken", skip)
        else:
            token = f"delta{next(self._tokens)}"
            self.tokens[token] = state
            out["@odata.deltaLink"] = self._link(calendar, "deltatoken", token)
        return httpx.Response(200, json=out)


__all__ = ["BIRTHDAYS", "CAL", "DEVICE_GRANT", "FakeGraph", "Seen", "local_us", "rule_of", "utc"]

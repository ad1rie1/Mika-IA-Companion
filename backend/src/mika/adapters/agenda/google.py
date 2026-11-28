"""Google Agenda (ADR 0309, lot 2) : l'API Calendar v3 de Google, par la connexion du compte (le parcours du
cadre, ``adapters/signin/google.py::GoogleSignIn``, à la portée de l'agenda :
``adapters/agenda/oauth.py::google_signin``), vers ``www.googleapis.com`` seulement.

- **Ses agendas** (``calendarList``) : nom (celui que la personne a donné, sinon le sien), couleur, ce qu'on peut y
  faire (``accessRole`` : ``owner`` et ``writer`` écrivent), fuseau, le principal (son identifiant est l'adresse du
  compte : ``whoami``), ceux que Google coche, ses rappels par défaut.
- **Synchroniser** (``events.list``, ``singleEvents=false``, ``showDeleted=true``) : la première fois, tout ce qui
  finit après le début de la fenêtre (``timeMin``, sans borne devant), page après page, un lot complet et son
  ``nextSyncToken`` ; ensuite, depuis ce jeton, ce qui a changé (page après page : le curseur garde la page) ; un
  jeton périmé (``410 Gone``) fait tout relire. Une série est une ligne (sa règle, ses EXDATE : les lignes
  ``recurrence`` de Google sont de la RFC 5545, lues par ``ics``) ; une occurrence changée, une exception
  (``recurringEventId``, ``originalStartTime``) ; une occurrence supprimée, une exception annulée ; un événement
  supprimé ne porte que son identifiant : sa série entière part.
- **Les identifiants** : ``Event.uid`` est l'identifiant de Google de la série (celui de l'événement, ou le
  ``recurringEventId`` d'une exception), ``Event.remote`` celui de la ligne — un événement supprimé ne dit que lui.
  L'``iCalUID`` n'est pas gardé.
- **Écrire** : chaque écriture relit d'abord l'événement chez Google (jamais une copie périmée) et n'envoie que ce
  qui change (``PATCH`` avec ``If-Match`` sur l'ETag lu : un conflit est un 412, dit en mots), ``sendUpdates=all``
  (les invités le savent). Une série se change pour cet événement (l'occurrence, trouvée par ``instances``), à partir
  de lui (la suite créée d'abord, une série neuve, puis la série d'avant coupée par UNTIL ; la neuve retirée si la
  coupe échoue — les exceptions d'après la coupe ne suivent pas) ou en entier (depuis une occurrence, elle garde son
  premier jour et prend l'heure). Une invitation ne se modifie que chez qui l'organise, sauf si l'organisateur le
  permet (``guestsCanModify``) ; ses rappels et « occupé » restent à soi ; la supprimer de son agenda, c'est la
  refuser. Un lien de visio donné (``conference``) va dans la description : Google ne crée que ses liens Meet.
- **Répondre** : le ``responseStatus`` de sa ligne d'invitée (``self``), avec un mot (``comment``), pour la série ou
  une occurrence ; Google prévient l'organisateur.
- **Lire** : titre, lieu, description (un texte : le HTML de Google est rendu en texte), lien de visio (Meet par
  ``hangoutLink`` et ``conferenceData``, sinon un lien connu du lieu ou de la description), participants (pas les
  salles) et leurs réponses, organisateur, le compte parmi eux (``self``), rappels (ceux de l'événement, ou les
  défauts de l'agenda), occupé (``transparency``), privé (``visibility``), état ; une « adresse de travail » de
  Google (``workingLocation``) n'est pas un rendez-vous : sautée.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from mika.adapters.agenda import ics
from mika.adapters.agenda.cloud import Answer, Api, Session, SignInNeeded, refused_words
from mika.adapters.signin.google import GoogleSignIn
from mika.ports.agenda import (
    ALL,
    CANCELLED,
    CONFIRMED,
    DAY_US,
    EMAIL,
    FOLLOWING,
    GOOGLE,
    MAYBE,
    NEEDS,
    NO,
    NOTIFY,
    ONE,
    TENTATIVE,
    YES,
    Abilities,
    AgendaError,
    Alert,
    Calendar,
    Connection,
    Event,
    EventChange,
    EventDraft,
    Participant,
    Span,
    SyncBatch,
    Window,
    alerts_of,
    at_us,
    calendar_key,
    day_at,
    day_of,
    key_instant,
    local_key,
    occurrence_key,
    occurrences,
    rule_parts,
    rule_text,
    series_end,
    split_rule,
    us_of,
    zone_of,
)
from mika.ports.preprocess import html_text

log = logging.getLogger("mika.agenda")

API = "https://www.googleapis.com/calendar/v3"
HOSTS = ("www.googleapis.com",)
#: des événements par page (le plus que Google rend) ; des agendas par page
PAGE, CALENDARS_PAGE = 2500, 250
#: une relecture entière de plus de tant de pages est refusée en mots (un agenda de plus de 100 000 événements)
FULL_PAGES_MAX = 40
#: au plus tant de rappels par événement (Google n'en garde pas plus)
REMINDERS_MAX = 5
_WRITERS = frozenset({"owner", "writer"})
_RESPONSE = {"needsAction": NEEDS, "accepted": YES, "tentative": MAYBE, "declined": NO}
_RESPONSE_OF = {YES: "accepted", MAYBE: "tentative", NO: "declined", NEEDS: "needsAction"}
_STATUS = {"confirmed": CONFIRMED, "tentative": TENTATIVE, "cancelled": CANCELLED}
_STATUS_OF = {CONFIRMED: "confirmed", TENTATIVE: "tentative", CANCELLED: "cancelled"}
#: ce qu'on ne range pas : une « adresse de travail » n'est pas un rendez-vous
_SKIPPED = frozenset({"workingLocation"})
#: les lignes de récurrence de Google (RFC 5545) qu'on lit
_RECURRENCE = re.compile(r"^(RRULE|RDATE|EXDATE)[;:]", re.IGNORECASE)
#: ce qu'un changement fait par une invitée garde à elle (le reste est à qui organise)
_GUEST_FIELDS = ("reminders", "busy", "added")
#: ce qu'une série neuve reprend de celle qu'on coupe
_COPIED = ("summary", "description", "location", "transparency", "visibility", "colorId", "reminders",
           "guestsCanModify", "guestsCanInviteOthers", "guestsCanSeeOtherGuests", "status")
_TAG = re.compile(r"<[a-zA-Z/!][^>]*>")


def _now_us() -> int:
    return time.time_ns() // 1000


# ── lire ce que Google dit ──────────────────────────────────────────────────


def _instant(text: str) -> int:
    """Un instant RFC 3339 de Google (avec son décalage), en µs UTC ; ``ValueError`` s'il ne se lit pas."""
    return us_of(datetime.fromisoformat(text.strip().replace("Z", "+00:00")))


def _when(value: Any) -> tuple[int, bool] | None:
    """(instant µs UTC, journée entière) d'un ``start``, ``end`` ou ``originalStartTime`` ; ``None`` s'il n'y en a
    pas."""
    if not isinstance(value, dict):
        return None
    try:
        if value.get("date"):
            return day_at(str(value["date"])), True
        if value.get("dateTime"):
            return _instant(str(value["dateTime"])), False
    except ValueError:
        return None
    return None


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _description(value: Any) -> str:
    """La description en texte : Google la garde en HTML quand elle a été écrite sur son site."""
    text = str(value or "")
    if _TAG.search(text):
        text = html_text(text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n"))
    return text.strip()[:ics.DESCRIPTION_MAX]


def _conference(item: Mapping[str, Any], location: str, description: str) -> str:
    """Le lien de visio : celui de Meet (``hangoutLink``, l'entrée vidéo de ``conferenceData``), sinon un lien connu
    du lieu ou de la description."""
    link = str(item.get("hangoutLink") or "")
    if link.startswith("https://"):
        return link[:2000]
    data = item.get("conferenceData")
    for entry in (data.get("entryPoints") or []) if isinstance(data, dict) else []:
        if isinstance(entry, dict) and entry.get("entryPointType") == "video":
            uri = str(entry.get("uri") or "")
            if uri.startswith("https://"):
                return uri[:2000]
    return ics.meeting_link(location, description)


def _who(person: Any) -> Participant | None:
    if not isinstance(person, dict):
        return None
    return Participant(address=str(person.get("email") or "").strip().lower()[:320],
                       name=_text(person.get("displayName"), 200),
                       response=_RESPONSE.get(str(person.get("responseStatus") or ""), NEEDS),
                       optional=bool(person.get("optional")), me=bool(person.get("self")))


def _alert(raw: Any) -> Alert | None:
    """Un rappel de Google (``{"method": "popup" | "email", "minutes": n}``) ; illisible : ``None``."""
    if not isinstance(raw, dict):
        return None
    try:
        minutes = int(raw.get("minutes"))
    except (TypeError, ValueError):
        return None
    return Alert(minutes, EMAIL if str(raw.get("method") or "") == "email" else NOTIFY)


def alerts_in(raw: Any) -> tuple[Alert, ...]:
    """Des rappels de Google (une liste d'``overrides`` ou de ``defaultReminders``), rangés."""
    return alerts_of(a for a in (_alert(x) for x in raw or ()) if a is not None) if isinstance(raw, list) else ()


def _reminders(item: Mapping[str, Any]) -> tuple[tuple[Alert, ...], bool]:
    """Les rappels de l'événement, et s'il suit ceux de son agenda (``useDefault`` : ils sont alors dans
    ``Calendar.reminders``)."""
    got = item.get("reminders")
    if not isinstance(got, dict) or got.get("useDefault", True):
        return (), True
    return alerts_in(got.get("overrides")), False


def _start_line(first: int, all_day: bool, zone: str) -> str:
    if all_day:
        return f"DTSTART;VALUE=DATE:{day_of(first).replace('-', '')}"
    if zone:
        return f"DTSTART;TZID={zone}:{at_us(first, zone_of(zone)).strftime('%Y%m%dT%H%M%S')}"
    return f"DTSTART:{at_us(first).strftime('%Y%m%dT%H%M%SZ')}"


def recurrence_of(lines: Iterable[Any], first: int, all_day: bool, zone: str) -> Any:
    """La règle d'une série (``ports.agenda.Recurrence``) d'après ses lignes ``recurrence`` (RRULE, EXDATE, RDATE de
    la RFC 5545), lues par ``ics`` sur son début ; ``None`` si elle n'en a pas de lisible."""
    kept = [str(line).strip() for line in lines if isinstance(line, str) and _RECURRENCE.match(line.strip())
            and "\n" not in line and "\r" not in line]
    if not kept:
        return None
    text = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{ics.PRODID}", "BEGIN:VEVENT",
                        "UID:google", _start_line(first, all_day, zone), *kept, "END:VEVENT", "END:VCALENDAR", ""])
    try:
        feed = ics.read(text, calendar="google", zone=zone)
    except AgendaError:
        return None
    return feed.events[0].recurrence if feed.events else None


def event_of(item: Mapping[str, Any], calendar: str, *, zone: str = "") -> Event | None:
    """Un événement de Google devenu une ligne du port ; ``None`` : ce n'est pas un rendez-vous, ou il ne se lit pas
    (un événement supprimé, qui ne porte que son identifiant, se traite à part : ``deleted``)."""
    if str(item.get("eventType") or "") in _SKIPPED:
        return None
    gid = str(item.get("id") or "")
    if not gid:
        return None
    series = str(item.get("recurringEventId") or "")
    original = ""
    if series:
        moment = _when(item.get("originalStartTime"))
        if moment is None:
            return None
        original = occurrence_key(*moment)
    status = _STATUS.get(str(item.get("status") or "confirmed"), CONFIRMED)
    start, end = _when(item.get("start")), _when(item.get("end"))
    if start is None:
        if status != CANCELLED or not original:
            return None
        at = key_instant(original)  # une occurrence supprimée : son créneau d'origine, qui ne se montre pas
        start, end = (at, "T" not in original), (at, "T" not in original)
    all_day = start[1]
    stop = end[0] if end is not None and not item.get("endTimeUnspecified") else start[0]
    stop = max(stop, start[0] + (DAY_US if all_day else 0))
    named = ics.iana(str((item.get("start") or {}).get("timeZone") or "")) or ics.iana(zone)
    tz = "" if all_day or named == "UTC" else named
    location = _text(item.get("location"), ics.LOCATION_MAX)
    description = _description(item.get("description"))
    recurrence = None
    if not series and item.get("recurrence"):
        recurrence = recurrence_of(item.get("recurrence") or (), start[0], all_day, tz)
    organizer = _who(item.get("organizer"))
    if organizer is not None:
        organizer = replace(organizer, response="", optional=False)
    people = [a for a in item.get("attendees") or [] if isinstance(a, dict) and not a.get("resource")]
    participants = tuple(p for p in (_who(a) for a in people[:ics.PARTICIPANTS_MAX]) if p is not None)
    me = next((p for p in participants if p.me), None)
    response = me.response if me is not None and not (organizer is not None and organizer.me) else ""
    created = updated = 0
    try:
        created = _instant(str(item["created"])) if item.get("created") else 0
        updated = _instant(str(item["updated"])) if item.get("updated") else 0
    except ValueError:
        pass
    try:
        sequence = max(0, int(item.get("sequence") or 0))
    except (TypeError, ValueError):
        sequence = 0
    alerts, by_default = _reminders(item)
    return Event(
        calendar=calendar, uid=(series or gid)[:400], original=original, span=Span(start[0], stop, tz, all_day),
        title=_text(item.get("summary"), ics.TITLE_MAX), location=location, description=description,
        conference=_conference(item, location, description), recurrence=recurrence, status=status,
        busy=str(item.get("transparency") or "opaque") != "transparent",
        private=str(item.get("visibility") or "default") in ("private", "confidential"),
        organizer=organizer, participants=participants, response=response,
        reminders=alerts, reminders_default=by_default, remote=gid[:400], etag=str(item.get("etag") or ""), sequence=sequence,
        created=created, updated=updated)


def deleted(item: Mapping[str, Any]) -> bool:
    """Un événement supprimé (pas une occurrence annulée d'une série : elle a son ``recurringEventId``)."""
    return str(item.get("status") or "") == "cancelled" and not item.get("recurringEventId")


def _kept(event: Event, window: Window) -> bool:
    """Ce qui touche encore la fenêtre (ou vient après)."""
    if event.original:
        return event.span.end > window.start or key_instant(event.original) > window.start
    return series_end(event) > window.start


# ── écrire ce que Google lira ───────────────────────────────────────────────


def _rfc3339(us: int) -> str:
    return at_us(us).strftime("%Y-%m-%dT%H:%M:%SZ")


def times(span: Span, zone: str, *, clear: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """Le ``start`` et le ``end`` de Google d'une période : une date (la fin exclue) pour une journée entière ; sinon
    l'heure de son fuseau et son nom (Google le demande pour une série). ``clear`` : l'autre forme effacée (un
    changement qui passe d'une journée entière à une heure, ou l'inverse)."""
    if span.all_day:
        start: dict[str, Any] = {"date": day_of(span.start)}
        end: dict[str, Any] = {"date": day_of(max(span.end, span.start + DAY_US))}
        if clear:
            start["dateTime"] = end["dateTime"] = None
        return start, end
    name = ics.iana(span.zone or zone)
    name = name if name and name != "UTC" else "UTC"
    tz = zone_of(name)
    start = {"dateTime": at_us(span.start, tz).isoformat(timespec="seconds"), "timeZone": name}
    end = {"dateTime": at_us(max(span.end, span.start), tz).isoformat(timespec="seconds"), "timeZone": name}
    if clear:
        start["date"] = end["date"] = None
    return start, end


def google_rule(rule: str, span: Span, zone: str) -> str:
    """Une RRULE telle que Google la prend : son UNTIL en UTC pour un événement à l'heure (une date y vaut la fin de
    ce jour dans son fuseau), une date pour une journée entière."""
    parts = []
    for name, value in rule_parts(rule):
        if name == "UNTIL":
            raw = value.upper()
            if span.all_day:
                value = raw[:8]
            elif "T" not in raw:
                last = datetime.strptime(raw[:8] + "235959", "%Y%m%d%H%M%S").replace(tzinfo=zone_of(span.zone or zone))
                value = occurrence_key(us_of(last), False)
            elif not raw.endswith("Z"):
                local = datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=zone_of(span.zone or zone))
                value = occurrence_key(us_of(local), False)
        parts.append((name, value))
    return rule_text(parts)


def attendees(participants: Sequence[Participant], kept: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """Les invités de Google : ceux qui y étaient gardent ce que Google sait d'eux (leur réponse), les neufs
    attendent la leur ; une participante sans adresse n'y va pas."""
    known = {str(a.get("email") or "").lower(): a for a in kept if isinstance(a, dict) and a.get("email")}
    out = []
    for p in participants:
        address = p.address.strip().lower()
        if not address or "@" not in address:
            continue
        row = dict(known.get(address) or {"email": address})
        if p.name:
            row["displayName"] = p.name
        row["optional"] = bool(p.optional)
        out.append(row)
    return out


def _reminders_body(alerts: Sequence[Alert]) -> dict[str, Any]:
    """Les rappels d'un événement, écrits pour Google : cinq au plus (sa limite), une notification ou un e-mail."""
    return {"useDefault": False, "overrides": [{"method": "email" if a.method == EMAIL else "popup",
                                                "minutes": a.minutes}
                                               for a in alerts_of(alerts)[:REMINDERS_MAX]]}


def _with_link(description: str, conference: str, location: str) -> str:
    """La description, et le lien de visio donné s'il n'y est pas déjà (ni dans le lieu)."""
    if not conference or conference in description or conference in location:
        return description
    return f"{description}\n\n{conference}" if description.strip() else conference


def draft_body(draft: EventDraft, zone: str) -> dict[str, Any]:
    start, end = times(draft.span, zone)
    body: dict[str, Any] = {"summary": draft.title, "start": start, "end": end,
                            "transparency": "opaque" if draft.busy else "transparent",
                            "visibility": "private" if draft.private else "default",
                            "status": _STATUS_OF.get(draft.status, "confirmed")}
    description = _with_link(draft.description, draft.conference, draft.location)
    if description:
        body["description"] = description
    if draft.location:
        body["location"] = draft.location
    if draft.rule:
        body["recurrence"] = ["RRULE:" + google_rule(draft.rule, draft.span, zone)]
    people = attendees(draft.participants)
    if people:
        body["attendees"] = people
    body["reminders"] = _reminders_body(draft.reminders) if draft.reminders is not None else {"useDefault": True}
    return body


def _span_of(item: Mapping[str, Any], zone: str) -> Span:
    """La période d'un événement de Google telle qu'il la dit (pour écrire sa règle)."""
    start, end = _when(item.get("start")), _when(item.get("end"))
    first = start[0] if start else 0
    all_day = bool(start and start[1])
    return Span(first, end[0] if end else first, str((item.get("start") or {}).get("timeZone") or zone), all_day)


def change_body(item: Mapping[str, Any], change: EventChange, zone: str, *, span: Span | None = None) -> dict[str, Any]:
    """Ce qu'un changement envoie à Google (``PATCH``) : seulement ce qui change ; ``span`` : la période déjà
    calculée (toute une série déplacée depuis une occurrence)."""
    body: dict[str, Any] = {}
    if change.title is not None:
        body["summary"] = change.title
    if change.location is not None:
        body["location"] = change.location
    if change.description is not None or change.conference:
        description = change.description if change.description is not None else _description(item.get("description"))
        location = change.location if change.location is not None else str(item.get("location") or "")
        body["description"] = _with_link(description, change.conference or "", location)
    when = span or change.span
    if when is not None:
        was_day = bool((item.get("start") or {}).get("date"))
        body["start"], body["end"] = times(when, zone, clear=was_day != when.all_day)
    if change.rule is not None:
        kept = [line for line in item.get("recurrence") or [] if not str(line).upper().startswith("RRULE")]
        body["recurrence"] = (["RRULE:" + google_rule(change.rule, when or _span_of(item, zone), zone), *kept]
                              if change.rule else [])
    if change.participants is not None:
        body["attendees"] = attendees(change.participants, item.get("attendees") or ())
    if change.busy is not None:
        body["transparency"] = "opaque" if change.busy else "transparent"
    if change.private is not None:
        body["visibility"] = "private" if change.private else "default"
    if change.status is not None:
        body["status"] = _STATUS_OF.get(change.status, "confirmed")
    if change.reminders is not None:
        body["reminders"] = _reminders_body(change.reminders)
    return body


# ── le fournisseur ──────────────────────────────────────────────────────────


def _cursor(cursor: str) -> dict[str, str]:
    try:
        got = json.loads(cursor) if cursor else {}
    except ValueError:
        got = {}
    return {k: str(v) for k, v in got.items() if k in ("s", "p") and v} if isinstance(got, dict) else {}


def _refused(answer: Answer, what: str) -> str:
    """Un refus de l'API de Google, en mots."""
    code, message = answer.error()
    if answer.status == 403:
        if code in ("rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"):
            return "Google demande d'attendre (trop de requêtes)"
        if code in ("insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT") or "scope" in message.lower():
            raise SignInNeeded("à reconnecter : Google n'a pas donné l'accès à l'agenda (sa case n'était pas cochée)")
        if code == "forbiddenForNonOrganizer":
            return f"{what} : seul son organisateur peut changer cela chez Google"
        if code == "requiredAccessLevel":
            return f"{what} : ce compte ne peut pas y écrire chez Google (en lecture seule)"
        return f"Google refuse l'accès à {what}"
    common = refused_words("Google", answer, what)
    if common:
        return common
    if answer.status == 400:
        return f"Google refuse {what} tel qu'il est écrit : {message[:200]}" if message else \
            f"Google refuse {what} tel qu'il est écrit"
    return f"Google répond {answer.status} pour {what}"


def _q(value: str) -> str:
    return quote(value, safe="")


class GoogleProvider:
    """Un ``CalendarProvider`` pour Google Agenda (``signin`` : les connexions ; ``transport`` : les tests en posent
    un faux)."""

    kind = GOOGLE

    def __init__(self, signin: GoogleSignIn, *, transport: httpx.AsyncBaseTransport | None = None,
                 now: Callable[[], int] = _now_us, page: int = PAGE) -> None:
        self.signin = signin
        self._api = Api("Google", HOSTS, transport=transport)
        self._now = now
        self._page = max(1, min(page, PAGE))

    def abilities(self, account: Connection) -> Abilities:
        return Abilities(write=True, invite=True, incremental=True, calendars=True, reminders=REMINDERS_MAX,
                         email_reminders=True)

    @asynccontextmanager
    async def _session(self, account: Connection) -> AsyncIterator[Session]:
        async def token(force: bool) -> str:
            if force:
                self.signin.drop(account.key)
            return await self.signin.token(account.key)

        async with self._api.session(token) as s:
            yield s

    async def _json(self, s: Session, method: str, url: str, what: str, *, params: Mapping[str, Any] | None = None,
                    body: Any = None, etag: str = "", ok: Sequence[int] = ()) -> Any:
        headers = {"If-Match": etag} if etag else None
        answer = await s.send(method, url, params=params, body=body, headers=headers)
        if answer.ok or answer.status in ok:
            return answer.data if isinstance(answer.data, dict) else {}
        raise AgendaError(_refused(answer, what))

    # ── ses agendas ──
    async def _list(self, s: Session) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        token = ""
        for _ in range(FULL_PAGES_MAX):
            params: dict[str, Any] = {"maxResults": CALENDARS_PAGE}
            if token:
                params["pageToken"] = token
            got = await self._json(s, "GET", f"{API}/users/me/calendarList", "la liste des agendas", params=params)
            items.extend(i for i in got.get("items") or [] if isinstance(i, dict))
            token = str(got.get("nextPageToken") or "")
            if not token:
                break
        return items

    async def calendars(self, account: Connection) -> list[Calendar]:
        async with self._session(account) as s:
            listed = await self._list(s)
        out = []
        for c in listed:
            remote = str(c.get("id") or "")
            role = str(c.get("accessRole") or "")
            if not remote or c.get("deleted") or role in ("", "none"):
                continue
            name = _text(c.get("summaryOverride") or c.get("summary") or remote, 200)
            zone = ics.iana(str(c.get("timeZone") or ""))
            out.append(Calendar(calendar_key(account.key, local_key(remote)), account.key, remote, name=name,
                                color=ics.color_of(str(c.get("backgroundColor") or "")), writable=role in _WRITERS,
                                zone="" if zone == "UTC" else zone, primary=bool(c.get("primary")),
                                selected=bool(c.get("selected")) or bool(c.get("primary")),
                                reminders=alerts_in(c.get("defaultReminders"))))
        return out

    async def whoami(self, account: Connection) -> str:
        """L'adresse du compte Google (l'identifiant de son agenda principal) ; vide si Google ne la dit pas."""
        async with self._session(account) as s:
            listed = await self._list(s)
        primary = next((c for c in listed if c.get("primary")), None)
        found = str(primary.get("id") or "") if primary is not None else ""
        return found.lower() if "@" in found else ""

    async def create_calendar(self, account: Connection, name: str) -> Calendar:
        name = name.strip()[:200]
        if not name:
            raise AgendaError("un agenda a un nom")
        async with self._session(account) as s:
            got = await self._json(s, "POST", f"{API}/calendars", f"l'agenda « {name} »", body={"summary": name})
        remote = str(got.get("id") or "")
        if not remote:
            raise AgendaError("Google n'a pas rendu l'agenda créé")
        zone = ics.iana(str(got.get("timeZone") or ""))
        return Calendar(calendar_key(account.key, local_key(remote)), account.key, remote,
                        name=_text(got.get("summary") or name, 200), writable=True,
                        zone="" if zone == "UTC" else zone, selected=True)

    # ── synchroniser ──
    def _events_url(self, calendar: Calendar) -> str:
        if not calendar.remote:
            raise AgendaError("cet agenda n'a pas d'identifiant chez Google : la liste des agendas doit être relue")
        return f"{API}/calendars/{_q(calendar.remote)}/events"

    async def sync(self, account: Connection, calendar: Calendar, cursor: str, window: Window) -> SyncBatch:
        state = _cursor(cursor)
        async with self._session(account) as s:
            if state.get("s"):
                batch = await self._changes(s, account, calendar, state, window)
                if batch is not None:
                    return batch
            return await self._whole(s, account, calendar, window)

    def _rows(self, account: Connection, calendar: Calendar, items: Iterable[Any], zone: str,
              window: Window, *, removing: bool) -> tuple[list[Event], list[tuple[str, str]]]:
        events: list[Event] = []
        removed: list[tuple[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if deleted(item):
                if removing and item.get("id"):
                    removed.append((str(item["id"])[:400], ""))
                continue
            try:
                e = event_of(item, calendar.key, zone=zone or calendar.zone)
            except (ValueError, TypeError, KeyError) as exc:
                log.info("agenda : un événement de Google illisible (%s) : %s", str(item.get("id"))[:40], exc)
                continue
            if e is None:
                if removing and item.get("id") and str(item.get("eventType") or "") in _SKIPPED:
                    removed.append((str(item["id"])[:400], ""))
                continue
            if _kept(e, window):
                events.append(e)
        return events, removed

    async def _whole(self, s: Session, account: Connection, calendar: Calendar, window: Window) -> SyncBatch:
        """Tout relu (ce qui finit après le début de la fenêtre), page après page : un lot complet, et son jeton."""
        url = self._events_url(calendar)
        events: list[Event] = []
        page, token = "", ""
        for _ in range(FULL_PAGES_MAX):
            params: dict[str, Any] = {"maxResults": self._page, "showDeleted": "true", "singleEvents": "false",
                                      "timeMin": _rfc3339(window.start)}
            if page:
                params["pageToken"] = page
            got = await self._json(s, "GET", url, f"l'agenda « {calendar.name} »", params=params)
            rows, _gone = self._rows(account, calendar, got.get("items") or [], str(got.get("timeZone") or ""),
                                     window, removing=False)
            events.extend(rows)
            page = str(got.get("nextPageToken") or "")
            if not page:
                token = str(got.get("nextSyncToken") or "")
                break
        else:
            raise AgendaError(f"l'agenda « {calendar.name} » a trop d'événements pour être relu en entier")
        return SyncBatch(events=tuple(events), cursor=json.dumps({"s": token}) if token else "", complete=True)

    async def _changes(self, s: Session, account: Connection, calendar: Calendar, state: dict[str, str],
                       window: Window) -> SyncBatch | None:
        """Une page de ce qui a changé depuis le jeton ; ``None`` : le jeton ne vaut plus (``410``), tout se relit."""
        params: dict[str, Any] = {"maxResults": self._page, "showDeleted": "true", "singleEvents": "false",
                                  "syncToken": state["s"]}
        if state.get("p"):
            params["pageToken"] = state["p"]
        answer = await s.send("GET", self._events_url(calendar), params=params)
        if answer.status == 410:
            log.info("agenda : le jeton de synchronisation de Google ne vaut plus (%s) : tout est relu",
                     calendar.key)
            return None
        if not answer.ok:
            raise AgendaError(_refused(answer, f"l'agenda « {calendar.name} »"))
        got = answer.data if isinstance(answer.data, dict) else {}
        events, removed = self._rows(account, calendar, got.get("items") or [], str(got.get("timeZone") or ""),
                                     window, removing=True)
        page = str(got.get("nextPageToken") or "")
        if page:
            return SyncBatch(events=tuple(events), removed=tuple(removed),
                             cursor=json.dumps({"s": state["s"], "p": page}), more=True)
        token = str(got.get("nextSyncToken") or "") or state["s"]
        return SyncBatch(events=tuple(events), removed=tuple(removed), cursor=json.dumps({"s": token}))

    # ── écrire ──
    def _writable(self, account: Connection, calendar: Calendar) -> None:
        if calendar.account != account.key:
            raise AgendaError("cet agenda n'est pas de ce compte")
        if not calendar.writable:
            raise AgendaError(f"« {calendar.name} » est en lecture seule chez Google")

    def _event(self, account: Connection, calendar: Calendar, item: Mapping[str, Any]) -> Event:
        made = event_of(item, calendar.key, zone=calendar.zone)
        if made is None:
            raise AgendaError("l'événement n'a pas été gardé par Google")
        return made

    async def _get(self, s: Session, calendar: Calendar, gid: str, title: str) -> dict[str, Any]:
        if not gid:
            raise AgendaError("cet événement n'a pas d'identifiant chez Google : la copie doit être relue")
        return dict(await self._json(s, "GET", f"{self._events_url(calendar)}/{_q(gid)}", f"« {title} »"))

    async def _instance(self, s: Session, calendar: Calendar, series: str, key: str, event: Event,
                        master: Mapping[str, Any]) -> dict[str, Any]:
        """L'occurrence ``key`` d'une série telle que Google la garde (l'exception rangée, sinon trouvée par
        ``instances``)."""
        if event.original == key and event.remote and event.remote != series:
            return await self._get(s, calendar, event.remote, event.title)
        all_day = "T" not in key
        start = day_of(key_instant(key)) if all_day else _rfc3339(key_instant(key))
        got = await self._json(s, "GET", f"{self._events_url(calendar)}/{_q(series)}/instances",
                               f"« {event.title} »", params={"originalStart": start, "showDeleted": "true",
                                                             "maxResults": 25})
        for item in got.get("items") or []:
            moment = _when(item.get("originalStartTime")) if isinstance(item, dict) else None
            if moment is not None and occurrence_key(*moment) == key:
                if item.get("status") == "cancelled":
                    break
                return dict(item)
        raise AgendaError(f"cette occurrence de « {event.title} » n'existe plus chez Google (la série a changé) : "
                          "la copie est relue")

    @staticmethod
    def _organizes(item: Mapping[str, Any]) -> bool:
        organizer = item.get("organizer")
        return not isinstance(organizer, dict) or bool(organizer.get("self"))

    def _guard(self, item: Mapping[str, Any], change: EventChange) -> None:
        if self._organizes(item) or item.get("guestsCanModify"):
            return
        if any(getattr(change, name) is not None for name in EventChange.__dataclass_fields__
               if name not in _GUEST_FIELDS):
            raise AgendaError("une invitation se modifie chez qui l'organise : on y répond")

    async def _patch(self, s: Session, calendar: Calendar, item: Mapping[str, Any], body: Mapping[str, Any],
                     title: str) -> dict[str, Any]:
        if not body:
            return dict(item)
        return dict(await self._json(s, "PATCH", f"{self._events_url(calendar)}/{_q(str(item.get('id')))}",
                                     f"« {title} »", params={"sendUpdates": "all"}, body=dict(body),
                                     etag=str(item.get("etag") or "")))

    async def create(self, account: Connection, calendar: Calendar, draft: EventDraft) -> Event:
        self._writable(account, calendar)
        async with self._session(account) as s:
            got = await self._json(s, "POST", self._events_url(calendar), f"« {draft.title} »",
                                   params={"sendUpdates": "all"}, body=draft_body(draft, calendar.zone))
        return replace(self._event(account, calendar, got), added=draft.added)

    async def edit(self, account: Connection, calendar: Calendar, event: Event, occurrence: str, change: EventChange,
                   scope: str = ALL) -> Event:
        self._writable(account, calendar)
        key = occurrence or event.original
        series = event.uid if event.original else event.remote
        async with self._session(account) as s:
            master = await self._get(s, calendar, series, event.title or "l'événement")
            self._guard(master, change)
            if not master.get("recurrence"):
                target = master if not event.original else await self._get(s, calendar, event.remote, event.title)
                done = await self._patch(s, calendar, target, change_body(target, change, calendar.zone),
                                         event.title)
            elif scope == ONE and key:
                target = await self._instance(s, calendar, series, key, event, master)
                done = await self._patch(s, calendar, target,
                                         change_body(target, replace(change, rule=None), calendar.zone), event.title)
            elif scope == FOLLOWING and key and key != _first_key(self._event(account, calendar, master)):
                return await self._split(s, account, calendar, master, key, change)
            else:
                span = None
                if change.span is not None and key:
                    first = _when(master.get("start"))
                    moved = change.span.start - key_instant(key)
                    begin = (first[0] if first else key_instant(key)) + moved
                    span = Span(begin, begin + (change.span.end - change.span.start), change.span.zone,
                                change.span.all_day)
                done = await self._patch(s, calendar, master, change_body(master, change, calendar.zone, span=span),
                                         event.title)
        return replace(self._event(account, calendar, done), added=change.added or event.added)

    async def _split(self, s: Session, account: Connection, calendar: Calendar, master: dict[str, Any], key: str,
                     change: EventChange) -> Event:
        """Celui-ci et les suivants : la suite, une série neuve, créée d'abord ; la série d'avant coupée juste avant
        (la neuve retirée si la coupe échoue)."""
        before_event = self._event(account, calendar, master)
        title = before_event.title
        self._occurs(before_event, key)
        before_rule, after_rule = split_rule(before_event, key)
        at = key_instant(key)
        duration = before_event.span.end - before_event.span.start
        span = change.span or Span(at, at + duration, before_event.span.zone, before_event.span.all_day)
        body = {k: master[k] for k in _COPIED if k in master}
        body["attendees"] = attendees(before_event.participants)
        body["start"], body["end"] = times(span, calendar.zone)
        rule = after_rule if change.rule is None else change.rule
        body["recurrence"] = ["RRULE:" + google_rule(rule, span, calendar.zone)] if rule else []
        body.update(change_body(body, replace(change, span=None, rule=None), calendar.zone))
        if not body["attendees"]:
            del body["attendees"]
        made = await self._json(s, "POST", self._events_url(calendar), f"« {title} »",
                                params={"sendUpdates": "all"}, body=body)
        kept = [line for line in master.get("recurrence") or [] if not str(line).upper().startswith("RRULE")]
        cut = {"recurrence": ["RRULE:" + google_rule(before_rule, before_event.span, calendar.zone), *kept]}
        try:
            await self._patch(s, calendar, master, cut, title)
        except AgendaError:
            try:
                await self._json(s, "DELETE", f"{self._events_url(calendar)}/{_q(str(made.get('id')))}",
                                 f"« {title} »", params={"sendUpdates": "none"}, ok=(404, 410))
            except AgendaError as exc:
                log.warning("agenda : la suite d'une série coupée n'a pas pu être retirée de Google : %s", exc)
            raise
        return replace(self._event(account, calendar, made), added=change.added or before_event.added)

    @staticmethod
    def _occurs(master: Event, key: str) -> None:
        at = key_instant(key)
        if not any(o.key == key for o in occurrences(master, at, at + 1)):
            raise AgendaError(f"cette occurrence de « {master.title} » n'existe plus chez Google (la série a changé) : "
                              "la copie est relue")

    async def delete(self, account: Connection, calendar: Calendar, event: Event, occurrence: str,
                     scope: str = ALL) -> int:
        self._writable(account, calendar)
        key = occurrence or event.original
        series = event.uid if event.original else event.remote
        async with self._session(account) as s:
            answer = await s.send("GET", f"{self._events_url(calendar)}/{_q(series)}")
            if answer.status in (404, 410):
                return 0  # déjà parti chez Google
            if not answer.ok:
                raise AgendaError(_refused(answer, f"« {event.title} »"))
            master = dict(answer.data or {})
            if not self._organizes(master):  # une invitation retirée de son agenda : refusée
                await self._answer(s, account, calendar, master, series, event, key, NO,
                                   ONE if scope == ONE else ALL, "")
                return 1
            url = self._events_url(calendar)
            if not master.get("recurrence") or scope == ALL or not key or \
                    (scope == FOLLOWING and key == _first_key(self._event(account, calendar, master))):
                gone = master if not (event.original and not master.get("recurrence")) else \
                    await self._get(s, calendar, event.remote, event.title)
                await self._json(s, "DELETE", f"{url}/{_q(str(gone.get('id')))}", f"« {event.title} »",
                                 params={"sendUpdates": "all"}, etag=str(gone.get("etag") or ""), ok=(404, 410))
                return 1
            if scope == ONE:
                target = await self._instance(s, calendar, series, key, event, master)
                await self._json(s, "DELETE", f"{url}/{_q(str(target.get('id')))}", f"« {event.title} »",
                                 params={"sendUpdates": "all"}, etag=str(target.get("etag") or ""), ok=(404, 410))
                return 1
            before_event = self._event(account, calendar, master)
            before_rule, _after = split_rule(before_event, key)
            kept = [line for line in master.get("recurrence") or [] if not str(line).upper().startswith("RRULE")]
            await self._patch(s, calendar, master, {"recurrence": [
                "RRULE:" + google_rule(before_rule, before_event.span, calendar.zone), *kept]}, event.title)
            return 1

    async def respond(self, account: Connection, calendar: Calendar, event: Event, occurrence: str, response: str,
                      scope: str = ALL, comment: str = "") -> Event:
        if response not in (YES, MAYBE, NO):
            raise AgendaError("une réponse est oui, peut-être ou non")
        if scope == FOLLOWING:
            raise AgendaError("une réponse vaut pour cet événement ou pour toute la série")
        if calendar.account != account.key:
            raise AgendaError("cet agenda n'est pas de ce compte")
        key = occurrence or event.original
        series = event.uid if event.original else event.remote
        async with self._session(account) as s:
            master = await self._get(s, calendar, series, event.title or "l'invitation")
            done = await self._answer(s, account, calendar, master, series, event, key, response, scope, comment)
        return self._event(account, calendar, done)

    async def _answer(self, s: Session, account: Connection, calendar: Calendar, master: dict[str, Any], series: str,
                      event: Event, key: str, response: str, scope: str, comment: str) -> dict[str, Any]:
        """Sa réponse posée sur sa ligne d'invitée (``self``), de la série ou d'une occurrence, et envoyée."""
        if self._organizes(master):
            raise AgendaError("ce compte organise cet événement : il n'y a rien à répondre")
        if master.get("recurrence") and scope == ONE and key:
            target = await self._instance(s, calendar, series, key, event, master)
        elif event.original and not master.get("recurrence"):
            target = await self._get(s, calendar, event.remote, event.title)
        else:
            target = master
        people = [dict(a) for a in target.get("attendees") or [] if isinstance(a, dict)]
        me = next((a for a in people if a.get("self")), None)
        if me is None:
            raise AgendaError(f"ce compte n'est pas parmi les invités de « {event.title} » chez Google")
        me["responseStatus"] = _RESPONSE_OF[response]
        if comment.strip():
            me["comment"] = comment.strip()[:1000]
        return await self._patch(s, calendar, target, {"attendees": people}, event.title)


def _first_key(master: Event) -> str:
    first = occurrences(master, master.span.start, master.span.start + 1)
    return first[0].key if first else occurrence_key(master.span.start, master.span.all_day)


__all__ = ["API", "HOSTS", "GoogleProvider", "attendees", "change_body", "deleted", "draft_body", "event_of",
           "google_rule", "recurrence_of", "times"]

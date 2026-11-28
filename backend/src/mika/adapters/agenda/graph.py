"""Outlook.com / Microsoft 365 (ADR 0309, lot 2) : Microsoft Graph, par la connexion du compte (le code d'appareil du
cadre, ``adapters/signin/microsoft.py``, à la portée de l'agenda : ``adapters/agenda/oauth.py::microsoft_signin``), vers
``graph.microsoft.com`` seulement.

- **Ses agendas** (``/me/calendars``) : nom, couleur (``hexColor``, sinon sa couleur nommée), si on peut y écrire
  (``canEdit``), le principal (``isDefaultCalendar``), son propriétaire (l'adresse du compte : ``whoami``, et qui il
  est parmi les invités).
- **Synchroniser** : le delta de la vue d'un agenda (``calendarView/delta``) sur la fenêtre, et un mois de plus devant
  (``AHEAD_US``) : la première fois, toutes ses pages jusqu'au ``@odata.deltaLink``, un lot complet ; ensuite, depuis
  ce lien, ce qui a changé, page après page (le curseur garde le ``@odata.nextLink``) ; un lien que Graph invalide
  (``410``, ``syncStateNotFound``) fait tout relire, et la vue se redemande quand la fenêtre a glissé au-delà de sa fin.
  Les liens que Graph rend ne mènent que chez lui (``cloud.Api``).
- **Ce que la copie garde** : une vue rend chaque occurrence d'une série, jamais la série. La copie garde donc chaque
  occurrence comme une ligne à elle (``Event.original`` : son ``originalStart`` ; ``Event.uid`` : la série,
  ``seriesMasterId``), un événement simple comme une ligne (``uid`` : son ``iCalUId``) ; ``Event.remote`` est
  l'identifiant de Graph de chaque ligne — ce qui part (``@removed``) ne dit que lui (``SyncBatch.replaced``). La
  règle d'une série (``patternedRecurrence`` ↔ RRULE : ``pattern_rule``, ``rule_pattern``) se lit sur la série quand
  on l'écrit.
- **Écrire** : chaque écriture relit d'abord l'événement chez Graph (jamais une copie périmée) et n'envoie que ce qui
  change (``PATCH`` avec ``If-Match`` sur l'ETag lu : un conflit est un 412, dit en mots). Une série se change pour
  cet événement (l'occurrence), à partir de lui (la suite, une série neuve, créée d'abord ; la série d'avant finie la
  veille — ``range.endDate`` ; la neuve retirée si la coupe échoue) ou en entier (depuis une occurrence, elle garde
  son premier jour et prend l'heure). Une invitation ne se modifie que chez qui l'organise (``isOrganizer``) ; ses
  rappels et « occupé » restent à soi ; la supprimer de son agenda, c'est la refuser. Un lien de visio donné va dans
  la description : Graph ne pose que les siens. Graph ne garde qu'un rappel : le plus tôt.
- **Répondre** : ``accept``, ``tentativelyAccept``, ``decline``, avec un mot, ``sendResponse`` (sauf si l'organisateur
  n'en demande pas, ``responseRequested``) ; pour la série ou une occurrence.
- **Lire** : titre, lieu, description (en texte : ``outlook.body-content-type``), lien de visio (Teams :
  ``onlineMeeting.joinUrl``, sinon un lien connu), participants (pas les salles) et leurs réponses, organisateur, la
  réponse du compte, son rappel, occupé (``showAs``), privé (``sensitivity``), annulé ; les heures en UTC
  (``outlook.timezone``), le fuseau de l'événement par son ``originalStartTimeZone`` (un nom Windows, lu IANA) ; une
  journée entière par ses dates.
"""

from __future__ import annotations

import copy
import functools
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx
from icalendar.timezone.windows_to_olson import WINDOWS_TO_OLSON

from mika.adapters.agenda import ics
from mika.adapters.agenda.cloud import Answer, Api, Session, SignInNeeded, refused_words
from mika.adapters.signin.microsoft import MicrosoftSignIn, OAuthError, Unreachable
from mika.ports.agenda import (
    ALL,
    CANCELLED,
    CONFIRMED,
    DAY_US,
    FOLLOWING,
    MAYBE,
    MICROSOFT,
    NEEDS,
    NO,
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
    Recurrence,
    Span,
    SyncBatch,
    Window,
    alerts_of,
    at_us,
    calendar_key,
    day_of,
    key_instant,
    local_key,
    occurrence_key,
    occurrences,
    rule_parts,
    rule_text,
    split_rule,
    us_of,
    zone_of,
)
from mika.ports.preprocess import html_text

log = logging.getLogger("mika.agenda")

GRAPH = "https://graph.microsoft.com/v1.0"
HOSTS = ("graph.microsoft.com",)
#: des événements par page (``odata.maxpagesize``)
PAGE = 100
#: une relecture entière de plus de tant de pages est refusée en mots
FULL_PAGES_MAX = 200
#: la vue se demande jusqu'à tant après la fin de la fenêtre : elle se redemande quand la fenêtre l'a rattrapée
AHEAD_US = 30 * DAY_US
#: les heures en UTC, les descriptions en texte
PREFER = 'outlook.timezone="UTC", outlook.body-content-type="text"'
#: une occurrence se cherche à tant de jours de son heure d'origine (une exception déplacée)
INSTANCE_DAYS = 14

_RESPONSE = {"none": NEEDS, "notResponded": NEEDS, "accepted": YES, "tentativelyAccepted": MAYBE, "declined": NO,
             "organizer": ""}
_ANSWER = {YES: "accept", MAYBE: "tentativelyAccept", NO: "decline"}
#: les couleurs nommées d'un agenda, quand il ne dit pas la sienne (``hexColor``)
_COLORS = {"lightBlue": "#a6d1f5", "lightGreen": "#87d28e", "lightOrange": "#fcab73", "lightGray": "#c0c0c0",
           "lightYellow": "#f4d07a", "lightTeal": "#6dd2d2", "lightPink": "#f08cc0", "lightBrown": "#cba287",
           "lightRed": "#f89b9b"}
_DAYS = {"MO": "monday", "TU": "tuesday", "WE": "wednesday", "TH": "thursday", "FR": "friday", "SA": "saturday",
         "SU": "sunday"}
_DAY_OF = {v: k for k, v in _DAYS.items()}
_WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
_INDEX = {1: "first", 2: "second", 3: "third", 4: "fourth", -1: "last"}
_INDEX_OF = {v: k for k, v in _INDEX.items()}
#: ce qu'une RRULE peut dire pour qu'Outlook la sache
_RULE_PARTS = frozenset({"FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "BYMONTH", "BYSETPOS", "COUNT", "UNTIL", "WKST"})
_BYDAY = re.compile(r"^([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)$")
_GUEST_FIELDS = ("reminders", "busy", "added")
#: ce qu'une série neuve reprend de celle qu'on coupe
_COPIED = ("subject", "body", "location", "showAs", "sensitivity", "isReminderOn", "reminderMinutesBeforeStart",
           "categories", "importance", "responseRequested")
_FRACTION = re.compile(r"(\.\d{6})\d+")


def _now_us() -> int:
    return time.time_ns() // 1000


# ── les fuseaux et les heures ───────────────────────────────────────────────


@functools.cache
def _windows_names() -> dict[str, str]:
    out: dict[str, str] = {}
    for windows, olson in WINDOWS_TO_OLSON.items():
        out.setdefault(olson, windows)
    return out


def windows_zone(name: str) -> str:
    """Le nom d'un fuseau tel que Graph le prend : son nom Windows (« Romance Standard Time »), sinon son nom IANA
    s'il en a un, sinon ``UTC``."""
    found = ics.iana(name)
    if not found or found == "UTC":
        return "UTC"
    return _windows_names().get(found, found)


def iana_zone(name: str) -> str:
    """Le fuseau IANA d'un nom de Graph (Windows, IANA, ``tzone://Microsoft/…``) ; vide pour UTC ou un inconnu."""
    name = (name or "").strip()
    if not name or name.lower().startswith("tzone://"):
        return ""
    found = ics.iana(name)
    return "" if found == "UTC" else found


def _clock(value: str) -> datetime:
    text = _FRACTION.sub(r"\1", value.strip()).replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def instant_of(value: Any) -> int | None:
    """L'instant (µs UTC) d'un ``dateTimeTimeZone`` de Graph, ou d'un ``DateTimeOffset`` (``originalStart``)."""
    try:
        if isinstance(value, str):
            moment = _clock(value)
            return us_of(moment if moment.tzinfo else moment.replace(tzinfo=UTC))
        if not isinstance(value, dict) or not value.get("dateTime"):
            return None
        moment = _clock(str(value["dateTime"]))
        if moment.tzinfo is None:
            tz = iana_zone(str(value.get("timeZone") or "UTC"))
            moment = moment.replace(tzinfo=zone_of(tz) if tz else UTC)
        return us_of(moment)
    except ValueError:
        return None


def nearest_day(us: int) -> int:
    """Minuit UTC le plus proche d'un instant : le jour d'une journée entière, que Graph donne à minuit d'un fuseau
    (lu en UTC, il tombe la veille au soir ou le matin même)."""
    return ((us + DAY_US // 2) // DAY_US) * DAY_US


def times(span: Span, zone: str) -> tuple[dict[str, str], dict[str, str]]:
    """Le ``start`` et le ``end`` de Graph d'une période : l'heure de son fuseau et son nom ; une journée entière à
    minuit de ses dates."""
    name = span.zone or zone
    win = windows_zone(name)
    if span.all_day:
        return ({"dateTime": f"{day_of(span.start)}T00:00:00", "timeZone": win},
                {"dateTime": f"{day_of(max(span.end, span.start + DAY_US))}T00:00:00", "timeZone": win})
    tz = zone_of(ics.iana(name) if ics.iana(name) not in ("", "UTC") else "")
    fmt = "%Y-%m-%dT%H:%M:%S"
    return ({"dateTime": at_us(span.start, tz).strftime(fmt), "timeZone": win},
            {"dateTime": at_us(max(span.end, span.start), tz).strftime(fmt), "timeZone": win})


# ── la récurrence : patternedRecurrence ↔ RRULE ─────────────────────────────


def pattern_rule(recurrence: Any) -> str:
    """La RRULE d'une ``patternedRecurrence`` de Graph (vide : il n'en a pas, ou elle ne se lit pas). Sa fin datée
    (``range.endDate``) devient un UNTIL daté : la fin de ce jour dans le fuseau de la série."""
    if not isinstance(recurrence, dict):
        return ""
    pattern, span = recurrence.get("pattern") or {}, recurrence.get("range") or {}
    kind = str(pattern.get("type") or "")
    try:
        interval = max(1, int(pattern.get("interval") or 1))
        days = ",".join(_DAY_OF[d] for d in pattern.get("daysOfWeek") or [] if d in _DAY_OF)
        index = str(_INDEX_OF.get(str(pattern.get("index") or "first"), 1))
        month, day = int(pattern.get("month") or 0), int(pattern.get("dayOfMonth") or 0)
    except (TypeError, ValueError):
        return ""
    if kind == "daily":
        parts = [("FREQ", "DAILY")]
    elif kind == "weekly" and days:
        parts = [("FREQ", "WEEKLY"), ("BYDAY", days)]
        if interval > 1:
            parts.append(("WKST", _DAY_OF.get(str(pattern.get("firstDayOfWeek") or "sunday"), "SU")))
    elif kind == "absoluteMonthly" and day:
        parts = [("FREQ", "MONTHLY"), ("BYMONTHDAY", str(day))]
    elif kind == "relativeMonthly" and days:
        parts = [("FREQ", "MONTHLY"), ("BYDAY", days), ("BYSETPOS", index)]
    elif kind == "absoluteYearly" and day and month:
        parts = [("FREQ", "YEARLY"), ("BYMONTH", str(month)), ("BYMONTHDAY", str(day))]
    elif kind == "relativeYearly" and days and month:
        parts = [("FREQ", "YEARLY"), ("BYMONTH", str(month)), ("BYDAY", days), ("BYSETPOS", index)]
    else:
        return ""
    if interval > 1:
        parts.insert(1, ("INTERVAL", str(interval)))
    end = str(span.get("type") or "")
    if end == "numbered" and int(span.get("numberOfOccurrences") or 0) > 0:
        parts.append(("COUNT", str(int(span["numberOfOccurrences"]))))
    elif end == "endDate" and span.get("endDate"):
        parts.append(("UNTIL", str(span["endDate"]).replace("-", "")[:8]))
    return rule_text(parts)


def _last_date(value: str, first: datetime) -> date:
    """La date de la dernière occurrence qu'un UNTIL permet (``range.endDate``, comprise) : une date telle quelle ;
    un instant, le jour où il tombe dans le fuseau de la série — la veille si l'occurrence de ce jour viendrait après
    lui."""
    raw = value.upper()
    if "T" not in raw:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    tz = first.tzinfo or UTC
    if raw.endswith("Z"):
        limit = datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    else:
        limit = datetime.strptime(raw[:15], "%Y%m%dT%H%M%S").replace(tzinfo=tz)
    local = limit.astimezone(tz)
    same = datetime.combine(local.date(), first.timetz().replace(tzinfo=None)).replace(tzinfo=tz)
    return local.date() - timedelta(days=1) if same > limit else local.date()


def rule_pattern(rule: str, start: int, zone: str, all_day: bool) -> dict[str, Any]:
    """La ``patternedRecurrence`` de Graph d'une RRULE, sur le début de la série (``start``, dans ``zone``).
    ``AgendaError`` pour une règle qu'Outlook ne sait pas (toutes les heures, plusieurs jours du mois…)."""
    parts = rule_parts(rule)
    said = dict(parts)
    if {k for k, _ in parts} - _RULE_PARTS or "FREQ" not in said:
        raise AgendaError("Outlook ne sait pas cette récurrence : choisis-en une plus simple (chaque jour, semaine, "
                          "mois ou année)")
    tz = UTC if all_day else zone_of(ics.iana(zone) if ics.iana(zone) not in ("", "UTC") else "")
    first = at_us(start, tz)
    try:
        interval = max(1, int(said.get("INTERVAL") or 1))
        byday = [_BYDAY.match(d.strip().upper()) for d in said.get("BYDAY", "").split(",") if d.strip()]
        if any(m is None for m in byday):
            raise ValueError
        days = [_DAYS[m.group(2)] for m in byday if m is not None]
        ordinals = {int(m.group(1)) for m in byday if m is not None and m.group(1)}
        setpos = {int(p) for p in said.get("BYSETPOS", "").split(",") if p.strip()}
        monthdays = [int(d) for d in said.get("BYMONTHDAY", "").split(",") if d.strip()]
        months = [int(m) for m in said.get("BYMONTH", "").split(",") if m.strip()]
    except ValueError:
        raise AgendaError("cette récurrence ne se lit pas : choisis-en une plus simple") from None
    positions = ordinals | setpos
    if len(positions) > 1 or (positions and next(iter(positions)) not in _INDEX) or len(monthdays) > 1 \
            or len(months) > 1 or (monthdays and monthdays[0] <= 0):
        raise AgendaError("Outlook ne sait pas cette récurrence (plusieurs positions ou jours du mois) : choisis-en "
                          "une plus simple")
    index = _INDEX[next(iter(positions))] if positions else "first"
    freq = said["FREQ"].upper()
    pattern: dict[str, Any]
    if freq == "DAILY" and not days:
        pattern = {"type": "daily", "interval": interval}
    elif freq in ("DAILY", "WEEKLY"):
        pattern = {"type": "weekly", "interval": interval,
                   "daysOfWeek": days or [_DAYS[_WEEKDAYS[first.weekday()]]],
                   "firstDayOfWeek": _DAYS.get(said.get("WKST", "MO").upper(), "monday")}
    elif freq == "MONTHLY":
        if days and not monthdays:
            pattern = {"type": "relativeMonthly", "interval": interval, "daysOfWeek": days, "index": index}
        else:
            pattern = {"type": "absoluteMonthly", "interval": interval,
                       "dayOfMonth": monthdays[0] if monthdays else first.day}
    elif freq == "YEARLY":
        month = months[0] if months else first.month
        if days and not monthdays:
            pattern = {"type": "relativeYearly", "interval": interval, "month": month, "daysOfWeek": days,
                       "index": index}
        else:
            pattern = {"type": "absoluteYearly", "interval": interval, "month": month,
                       "dayOfMonth": monthdays[0] if monthdays else first.day}
    else:
        raise AgendaError("Outlook ne sait pas cette récurrence (plus souvent que chaque jour) : choisis-en une plus "
                          "simple")
    rng: dict[str, Any] = {"startDate": first.date().isoformat(), "recurrenceTimeZone": windows_zone(zone)}
    if said.get("COUNT", "").isdigit():
        rng.update(type="numbered", numberOfOccurrences=int(said["COUNT"]))
    elif said.get("UNTIL"):
        try:
            rng.update(type="endDate", endDate=_last_date(said["UNTIL"], first).isoformat())
        except ValueError:
            raise AgendaError("la fin de cette récurrence ne se lit pas") from None
    else:
        rng["type"] = "noEnd"
    return {"pattern": pattern, "range": rng}


# ── lire ce que Graph dit ───────────────────────────────────────────────────


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _address(value: Any) -> tuple[str, str]:
    mail = value.get("emailAddress") if isinstance(value, dict) else None
    if not isinstance(mail, dict):
        return "", ""
    return str(mail.get("address") or "").strip().lower()[:320], _text(mail.get("name"), 200)


def _location(item: Mapping[str, Any]) -> str:
    place = item.get("location")
    name = _text(place.get("displayName") if isinstance(place, dict) else "", ics.LOCATION_MAX)
    if name:
        return name
    names = [_text(p.get("displayName"), 300) for p in item.get("locations") or [] if isinstance(p, dict)]
    return "; ".join(n for n in names if n)[:ics.LOCATION_MAX]


def _description(item: Mapping[str, Any]) -> str:
    body = item.get("body")
    if not isinstance(body, dict):
        return _text(item.get("bodyPreview"), ics.DESCRIPTION_MAX)
    content = str(body.get("content") or "")
    if str(body.get("contentType") or "text").lower() == "html":
        content = html_text(content)
    return content.strip()[:ics.DESCRIPTION_MAX]


def event_of(item: Mapping[str, Any], calendar: str, *, mine: Iterable[str] = (), zone: str = "") -> Event | None:
    """Un événement de Graph devenu une ligne du port : une occurrence d'une série (``original`` : son
    ``originalStart`` ; ``uid`` : sa série), un événement simple, ou la série elle-même (``seriesMaster``, sa règle :
    ce que l'on relit pour l'écrire, jamais rangé). ``None`` : ce qui est parti (``@removed``), ou illisible."""
    if "@removed" in item or not item.get("id"):
        return None
    gid = str(item["id"])
    kind = str(item.get("type") or "singleInstance")
    start, end = instant_of(item.get("start")), instant_of(item.get("end"))
    if start is None:
        return None
    all_day = bool(item.get("isAllDay"))
    named = iana_zone(str(item.get("originalStartTimeZone") or "")) or zone
    if all_day:
        first = nearest_day(start)
        span = Span(first, max(nearest_day(end if end is not None else start), first + DAY_US), "", True)
    else:
        span = Span(start, max(end if end is not None else start, start), named, False)
    series = str(item.get("seriesMasterId") or "") if kind in ("occurrence", "exception") else ""
    original = ""
    if series:
        was = instant_of(item.get("originalStart"))
        was = start if was is None else was
        original = occurrence_key(nearest_day(was) if all_day else was, all_day)
    recurrence = None
    if kind == "seriesMaster":
        rule = pattern_rule(item.get("recurrence"))
        recurrence = Recurrence(rule) if rule else None
    own = {a.strip().lower() for a in mine if a}
    organizer_address, organizer_name = _address(item.get("organizer"))
    organizes = bool(item.get("isOrganizer"))
    organizer = Participant(address=organizer_address, name=organizer_name, me=organizes) \
        if organizer_address or organizer_name else None
    participants = []
    for a in (item.get("attendees") or [])[:ics.PARTICIPANTS_MAX]:
        if not isinstance(a, dict) or str(a.get("type") or "") == "resource":
            continue
        address, name = _address(a)
        status = a.get("status") if isinstance(a.get("status"), dict) else {}
        participants.append(Participant(address=address, name=name,
                                        response=_RESPONSE.get(str(status.get("response") or "none"), NEEDS) or YES,
                                        optional=str(a.get("type") or "") == "optional", me=bool(own) and address in own))
    response = ""
    said = item.get("responseStatus") if isinstance(item.get("responseStatus"), dict) else {}
    answer = _RESPONSE.get(str(said.get("response") or "none"), NEEDS)
    if not organizes and answer:
        invited = any(p.me for p in participants) if own else bool(participants)
        if answer != NEEDS:
            response = answer
        elif invited and item.get("responseRequested", True) is not False:
            response = NEEDS
    location = _location(item)
    description = _description(item)
    meeting = item.get("onlineMeeting") if isinstance(item.get("onlineMeeting"), dict) else {}
    conference = str(meeting.get("joinUrl") or item.get("onlineMeetingUrl") or "")
    if not conference.startswith("https://"):
        conference = ics.meeting_link(location, description)
    reminders: tuple[Alert, ...] = ()
    if item.get("isReminderOn"):
        try:
            minutes = int(item.get("reminderMinutesBeforeStart") or 0)
        except (TypeError, ValueError):
            minutes = -1
        reminders = alerts_of((Alert(minutes),))
    created = instant_of(item.get("createdDateTime")) or 0
    updated = instant_of(item.get("lastModifiedDateTime")) or 0
    uid = series or (gid if kind == "seriesMaster" else str(item.get("iCalUId") or gid))
    return Event(
        calendar=calendar, uid=uid[:400], original=original, span=span, title=_text(item.get("subject"), ics.TITLE_MAX),
        location=location, description=description, conference=conference[:2000], recurrence=recurrence,
        status=CANCELLED if item.get("isCancelled") else CONFIRMED,
        busy=str(item.get("showAs") or "busy") not in ("free", "workingElsewhere"),
        private=str(item.get("sensitivity") or "normal") in ("private", "confidential"),
        organizer=organizer, participants=tuple(participants), response=response, reminders=reminders,
        remote=gid[:400], etag=str(item.get("@odata.etag") or ""), created=created, updated=updated)


# ── écrire ce que Graph lira ────────────────────────────────────────────────


def _people(participants: Sequence[Participant]) -> list[dict[str, Any]]:
    out = []
    for p in participants:
        address = p.address.strip().lower()
        if address and "@" in address:
            out.append({"emailAddress": {"address": address, **({"name": p.name} if p.name else {})},
                        "type": "optional" if p.optional else "required"})
    return out


def _with_link(description: str, conference: str, location: str) -> str:
    if not conference or conference in description or conference in location:
        return description
    return f"{description}\n\n{conference}" if description.strip() else conference


def _reminder(body: dict[str, Any], alerts: Sequence[Alert]) -> None:
    """Le rappel d'un événement, écrit pour Graph : il n'en garde qu'un, une notification — de plusieurs, le plus tôt
    (le plus de minutes avant : rien ne vient plus tard que demandé) ; un e-mail y devient une notification."""
    kept = alerts_of(alerts)
    if kept:
        body["isReminderOn"] = True
        body["reminderMinutesBeforeStart"] = max(a.minutes for a in kept)
    else:
        body["isReminderOn"] = False


def _show_as(busy: bool, status: str) -> str:
    if not busy:
        return "free"
    return "tentative" if status == TENTATIVE else "busy"


def draft_body(draft: EventDraft, zone: str) -> dict[str, Any]:
    start, end = times(draft.span, zone)
    body: dict[str, Any] = {"subject": draft.title, "start": start, "end": end, "isAllDay": draft.span.all_day,
                            "showAs": _show_as(draft.busy, draft.status),
                            "sensitivity": "private" if draft.private else "normal"}
    description = _with_link(draft.description, draft.conference, draft.location)
    if description:
        body["body"] = {"contentType": "text", "content": description}
    if draft.location:
        body["location"] = {"displayName": draft.location}
    people = _people(draft.participants)
    if people:
        body["attendees"] = people
    if draft.reminders is not None:
        _reminder(body, draft.reminders)
    if draft.rule:
        body["recurrence"] = rule_pattern(draft.rule, draft.span.start, draft.span.zone or zone, draft.span.all_day)
    return body


def change_body(item: Mapping[str, Any], change: EventChange, zone: str, *, span: Span | None = None) -> dict[str, Any]:
    """Ce qu'un changement envoie à Graph (``PATCH``) : seulement ce qui change."""
    body: dict[str, Any] = {}
    if change.title is not None:
        body["subject"] = change.title
    if change.location is not None:
        body["location"] = {"displayName": change.location}
    if change.description is not None or change.conference:
        description = change.description if change.description is not None else _description(item)
        location = change.location if change.location is not None else _location(item)
        body["body"] = {"contentType": "text", "content": _with_link(description, change.conference or "", location)}
    when = span or change.span
    if when is not None:
        body["start"], body["end"] = times(when, zone)
        body["isAllDay"] = when.all_day
    if change.rule is not None:
        if change.rule:
            first = when or Span(instant_of(item.get("start")) or 0, 0,
                                 iana_zone(str(item.get("originalStartTimeZone") or "")) or zone,
                                 bool(item.get("isAllDay")))
            body["recurrence"] = rule_pattern(change.rule, first.start, first.zone or zone, first.all_day)
        else:
            body["recurrence"] = None
    if change.participants is not None:
        body["attendees"] = _people(change.participants)
    if change.busy is not None or change.status is not None:
        busy = change.busy if change.busy is not None else str(item.get("showAs") or "busy") != "free"
        body["showAs"] = _show_as(busy, change.status or CONFIRMED)
    if change.private is not None:
        body["sensitivity"] = "private" if change.private else "normal"
    if change.reminders is not None:
        _reminder(body, change.reminders)
    return body


# ── le fournisseur ──────────────────────────────────────────────────────────


def _cursor(cursor: str) -> dict[str, Any]:
    try:
        got = json.loads(cursor) if cursor else {}
    except ValueError:
        got = {}
    return got if isinstance(got, dict) else {}


def _stale(answer: Answer) -> bool:
    """Graph ne sait plus ce lien de delta (``410``, ou une erreur ``syncStateNotFound``) : tout se relit."""
    if answer.status == 410:
        return True
    code, _message = answer.error()
    return answer.status in (400, 404) and ("syncstate" in code.lower() or "resync" in code.lower())


def _refused(answer: Answer, what: str) -> str:
    """Un refus de Graph, en mots."""
    code, message = answer.error()
    if code in ("MailboxNotEnabledForRESTAPI", "MailboxNotSupportedForRESTAPI"):
        return "ce compte Microsoft n'a pas de boîte en ligne que Graph sache joindre (l'agenda n'y est pas)"
    if answer.status == 403:
        if "scope" in message.lower() or code == "ErrorAccessDenied" and "token" in message.lower():
            raise SignInNeeded("à reconnecter : Microsoft n'a pas donné l'accès à l'agenda (Calendars.ReadWrite)")
        return f"Microsoft refuse l'accès à {what} (en lecture seule ?)"
    common = refused_words("Microsoft", answer, what)
    if common:
        return common
    if answer.status == 400:
        return f"Microsoft refuse {what} tel qu'il est écrit : {message[:200]}" if message else \
            f"Microsoft refuse {what} tel qu'il est écrit"
    return f"Microsoft répond {answer.status} pour {what}"


def _q(value: str) -> str:
    return quote(value, safe="")


def _iso(us: int) -> str:
    return at_us(us).strftime("%Y-%m-%dT%H:%M:%SZ")


class MicrosoftProvider:
    """Un ``CalendarProvider`` pour Outlook.com / Microsoft 365 par Graph (``signin`` : les connexions ;
    ``transport`` : les tests en posent un faux)."""

    kind = MICROSOFT

    def __init__(self, signin: MicrosoftSignIn, *, transport: httpx.AsyncBaseTransport | None = None,
                 now: Callable[[], int] = _now_us, page: int = PAGE) -> None:
        self.signin = signin
        self._api = Api("Microsoft", HOSTS, transport=transport)
        self._now = now
        self._page = max(1, page)
        #: par compte : l'adresse du propriétaire de son agenda principal (qui il est parmi les invités)
        self._owners: dict[str, str] = {}

    def abilities(self, account: Connection) -> Abilities:
        return Abilities(write=True, invite=True, incremental=True, calendars=True, reminders=1)

    async def _token(self, account: Connection, force: bool) -> str:
        if force:
            self.signin.drop(account.key)
        try:
            return await self.signin.token(account.key, account)
        except Unreachable as exc:
            raise AgendaError(str(exc)) from None
        except OAuthError as exc:
            raise SignInNeeded(str(exc)) from None

    @asynccontextmanager
    async def _session(self, account: Connection) -> AsyncIterator[Session]:
        async with self._api.session(lambda force: self._token(account, force)) as s:
            yield s

    def _mine(self, account: Connection) -> set[str]:
        return {a for a in (account.address.strip().lower(), self._owners.get(account.key, "")) if a}

    async def _json(self, s: Session, method: str, url: str, what: str, *, params: Mapping[str, Any] | None = None,
                    body: Any = None, etag: str = "", ok: Sequence[int] = (), prefer: str = PREFER) -> Any:
        headers = {"Prefer": prefer}
        if etag:
            headers["If-Match"] = etag
        answer = await s.send(method, url, params=params, body=body, headers=headers)
        if answer.ok or answer.status in ok:
            return answer.data if isinstance(answer.data, dict) else {}
        raise AgendaError(_refused(answer, what))

    async def _pages(self, s: Session, url: str, what: str, params: Mapping[str, Any] | None = None
                     ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for _ in range(FULL_PAGES_MAX):
            got = await self._json(s, "GET", url, what, params=params)
            out.extend(v for v in got.get("value") or [] if isinstance(v, dict))
            url, params = str(got.get("@odata.nextLink") or ""), None
            if not url:
                return out
        raise AgendaError(f"{what} : trop de pages chez Microsoft")

    # ── ses agendas ──
    async def calendars(self, account: Connection) -> list[Calendar]:
        async with self._session(account) as s:
            listed = await self._pages(s, f"{GRAPH}/me/calendars", "la liste des agendas", {"$top": 100})
        out = []
        for c in listed:
            remote = str(c.get("id") or "")
            if not remote:
                continue
            owner, _name = _address({"emailAddress": c.get("owner")}) if isinstance(c.get("owner"), dict) else ("", "")
            if c.get("isDefaultCalendar") and owner:
                self._owners[account.key] = owner
            color = ics.color_of(str(c.get("hexColor") or "")) or _COLORS.get(str(c.get("color") or ""), "")
            out.append(Calendar(calendar_key(account.key, local_key(remote)), account.key, remote,
                                name=_text(c.get("name") or remote, 200), color=color, writable=bool(c.get("canEdit")),
                                primary=bool(c.get("isDefaultCalendar")), selected=True))
        return out

    async def whoami(self, account: Connection) -> str:
        """L'adresse du compte Microsoft (le propriétaire de son agenda principal) ; vide si Graph ne la dit pas."""
        await self.calendars(account)
        return self._owners.get(account.key, "")

    async def create_calendar(self, account: Connection, name: str) -> Calendar:
        name = name.strip()[:200]
        if not name:
            raise AgendaError("un agenda a un nom")
        async with self._session(account) as s:
            got = await self._json(s, "POST", f"{GRAPH}/me/calendars", f"l'agenda « {name} »", body={"name": name})
        remote = str(got.get("id") or "")
        if not remote:
            raise AgendaError("Microsoft n'a pas rendu l'agenda créé")
        return Calendar(calendar_key(account.key, local_key(remote)), account.key, remote,
                        name=_text(got.get("name") or name, 200),
                        color=ics.color_of(str(got.get("hexColor") or "")), writable=True, selected=True)

    # ── synchroniser ──
    async def sync(self, account: Connection, calendar: Calendar, cursor: str, window: Window) -> SyncBatch:
        if not calendar.remote:
            raise AgendaError("cet agenda n'a pas d'identifiant chez Microsoft : la liste des agendas doit être relue")
        state = _cursor(cursor)
        async with self._session(account) as s:
            if state.get("link") and int(state.get("end") or 0) >= window.end:
                batch = await self._changes(s, account, calendar, state)
                if batch is not None:
                    return batch
            return await self._whole(s, account, calendar, window)

    def _prefer(self) -> str:
        return f"{PREFER}, odata.maxpagesize={self._page}"

    def _rows(self, account: Connection, calendar: Calendar, values: Iterable[Any]) -> tuple[list[Event], list[str]]:
        events, seen = [], []
        mine = self._mine(account)
        for item in values:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            seen.append(str(item["id"])[:400])
            if "@removed" in item:
                continue
            e = event_of(item, calendar.key, mine=mine, zone=calendar.zone)
            if e is not None and e.recurrence is None:
                events.append(e)
        return events, seen

    async def _whole(self, s: Session, account: Connection, calendar: Calendar, window: Window) -> SyncBatch:
        """La vue entière, de la fenêtre et d'un mois de plus, toutes ses pages : un lot complet, et son lien."""
        end = window.end + AHEAD_US
        url = f"{GRAPH}/me/calendars/{_q(calendar.remote)}/calendarView/delta"
        params: dict[str, Any] | None = {"startDateTime": _iso(window.start), "endDateTime": _iso(end)}
        events: list[Event] = []
        what = f"l'agenda « {calendar.name} »"
        for _ in range(FULL_PAGES_MAX):
            got = await self._json(s, "GET", url, what, params=params, prefer=self._prefer())
            rows, _seen = self._rows(account, calendar, got.get("value") or [])
            events.extend(rows)
            url, params = str(got.get("@odata.nextLink") or ""), None
            if not url:
                delta = str(got.get("@odata.deltaLink") or "")
                cursor = json.dumps({"link": delta, "end": end}) if delta else ""
                return SyncBatch(events=tuple(events), cursor=cursor, complete=True)
        raise AgendaError(f"{what} a trop d'événements pour être relu en entier")

    async def _changes(self, s: Session, account: Connection, calendar: Calendar,
                       state: Mapping[str, Any]) -> SyncBatch | None:
        """Une page de ce qui a changé depuis le lien gardé ; ``None`` : Graph ne le sait plus, tout se relit."""
        answer = await s.send("GET", str(state["link"]), headers={"Prefer": self._prefer()})
        if _stale(answer):
            log.info("agenda : le lien de delta de Microsoft ne vaut plus (%s) : tout est relu", calendar.key)
            return None
        if not answer.ok:
            raise AgendaError(_refused(answer, f"l'agenda « {calendar.name} »"))
        got = answer.data if isinstance(answer.data, dict) else {}
        events, seen = self._rows(account, calendar, got.get("value") or [])
        more = str(got.get("@odata.nextLink") or "")
        link = more or str(got.get("@odata.deltaLink") or "") or str(state["link"])
        return SyncBatch(events=tuple(events), replaced=tuple(dict.fromkeys(seen)),
                         cursor=json.dumps({"link": link, "end": int(state.get("end") or 0)}), more=bool(more))

    # ── écrire ──
    def _writable(self, account: Connection, calendar: Calendar) -> None:
        if calendar.account != account.key:
            raise AgendaError("cet agenda n'est pas de ce compte")
        if not calendar.writable:
            raise AgendaError(f"« {calendar.name} » est en lecture seule chez Microsoft")

    def _event(self, account: Connection, calendar: Calendar, item: Mapping[str, Any]) -> Event:
        made = event_of(item, calendar.key, mine=self._mine(account), zone=calendar.zone)
        if made is None:
            raise AgendaError("l'événement n'a pas été gardé par Microsoft")
        return made

    async def _get(self, s: Session, gid: str, title: str) -> dict[str, Any]:
        if not gid:
            raise AgendaError("cet événement n'a pas d'identifiant chez Microsoft : la copie doit être relue")
        return dict(await self._json(s, "GET", f"{GRAPH}/me/events/{_q(gid)}", f"« {title} »"))

    async def _patch(self, s: Session, item: Mapping[str, Any], body: Mapping[str, Any], title: str) -> dict[str, Any]:
        if not body:
            return dict(item)
        return dict(await self._json(s, "PATCH", f"{GRAPH}/me/events/{_q(str(item.get('id')))}", f"« {title} »",
                                     body=dict(body), etag=str(item.get("@odata.etag") or "")))

    async def _instances(self, s: Session, series: str, start: int, end: int, title: str) -> list[dict[str, Any]]:
        return await self._pages(s, f"{GRAPH}/me/events/{_q(series)}/instances", f"« {title} »",
                                 {"startDateTime": _iso(start), "endDateTime": _iso(end)})

    async def _instance(self, s: Session, series: str, key: str, event: Event) -> dict[str, Any]:
        """L'occurrence ``key`` d'une série telle que Graph la garde (la ligne rangée, sinon cherchée autour de son
        heure d'origine)."""
        if event.original == key and event.remote:
            return await self._get(s, event.remote, event.title)
        at = key_instant(key)
        for item in await self._instances(s, series, at - INSTANCE_DAYS * DAY_US, at + INSTANCE_DAYS * DAY_US,
                                          event.title):
            all_day = bool(item.get("isAllDay"))
            was = instant_of(item.get("originalStart"))
            if was is not None and occurrence_key(nearest_day(was) if all_day else was, all_day) == key:
                return item
        raise AgendaError(f"cette occurrence de « {event.title} » n'existe plus chez Microsoft (la série a changé) : "
                          "la copie est relue")

    async def _shown(self, s: Session, account: Connection, calendar: Calendar, item: Mapping[str, Any],
                     near: int | None = None) -> Event:
        """L'événement tel que la copie le range : lui-même, ou, pour une série, son occurrence la plus proche de
        ``near`` (sa première, sinon)."""
        if str(item.get("type") or "") != "seriesMaster":
            return self._event(account, calendar, item)
        start = instant_of(item.get("start")) or 0
        at = start if near is None else near
        try:
            found = await self._instances(s, str(item.get("id")), at - DAY_US, at + 32 * DAY_US,
                                          str(item.get("subject") or ""))
        except AgendaError:
            found = []
        rows = [e for e in (event_of(i, calendar.key, mine=self._mine(account), zone=calendar.zone) for i in found)
                if e is not None]
        if rows:
            return min(rows, key=lambda e: (abs(e.span.start - at), e.span.start))
        master = self._event(account, calendar, item)
        return replace(master, recurrence=None, original=occurrence_key(master.span.start, master.span.all_day),
                       remote="")

    @staticmethod
    def _guard(item: Mapping[str, Any], change: EventChange) -> None:
        if item.get("isOrganizer", True):
            return
        if any(getattr(change, name) is not None for name in EventChange.__dataclass_fields__
               if name not in _GUEST_FIELDS):
            raise AgendaError("une invitation se modifie chez qui l'organise : on y répond")

    def _series_event(self, account: Connection, calendar: Calendar, master: Mapping[str, Any]) -> Event:
        made = self._event(account, calendar, master)
        if made.recurrence is None:
            raise AgendaError(f"la série « {made.title} » ne dit pas sa règle chez Microsoft")
        return made

    def _zone(self, master: Mapping[str, Any], calendar: Calendar) -> str:
        rng = (master.get("recurrence") or {}).get("range") or {}
        return iana_zone(str(rng.get("recurrenceTimeZone") or "")) or \
            iana_zone(str(master.get("originalStartTimeZone") or "")) or calendar.zone

    async def create(self, account: Connection, calendar: Calendar, draft: EventDraft) -> Event:
        self._writable(account, calendar)
        async with self._session(account) as s:
            got = await self._json(s, "POST", f"{GRAPH}/me/calendars/{_q(calendar.remote)}/events",
                                   f"« {draft.title} »", body=draft_body(draft, calendar.zone))
            made = await self._shown(s, account, calendar, got)
        return replace(made, added=draft.added)

    async def edit(self, account: Connection, calendar: Calendar, event: Event, occurrence: str, change: EventChange,
                   scope: str = ALL) -> Event:
        self._writable(account, calendar)
        key = occurrence or event.original
        async with self._session(account) as s:
            if not event.original:  # un événement simple
                item = await self._get(s, event.remote, event.title or "l'événement")
                self._guard(item, change)
                done = await self._patch(s, item, change_body(item, change, calendar.zone), event.title)
                return replace(await self._shown(s, account, calendar, done), added=change.added or event.added)
            series = event.uid
            if scope == ONE:
                target = await self._instance(s, series, key, event)
                self._guard(target, change)
                done = await self._patch(s, target, change_body(target, replace(change, rule=None), calendar.zone),
                                         event.title)
                return replace(self._event(account, calendar, done), added=change.added or event.added)
            master = await self._get(s, series, event.title)
            self._guard(master, change)
            whole = self._series_event(account, calendar, master)
            if scope == FOLLOWING and key and key != _first_key(whole):
                return await self._split(s, account, calendar, master, whole, key, change)
            span = None
            near = key_instant(key) if key else None
            if change.span is not None and key:
                moved = change.span.start - key_instant(key)
                begin = whole.span.start + moved
                span = Span(begin, begin + (change.span.end - change.span.start), change.span.zone or whole.span.zone,
                            change.span.all_day)
                near = change.span.start
            body = change_body(master, change, self._zone(master, calendar), span=span)
            if span is not None and "recurrence" not in body and isinstance(master.get("recurrence"), dict):
                moved_rec = copy.deepcopy(master["recurrence"])
                tz = UTC if span.all_day else zone_of(span.zone)
                moved_rec.setdefault("range", {})["startDate"] = at_us(span.start, tz).date().isoformat()
                body["recurrence"] = moved_rec
            done = await self._patch(s, master, body, event.title)
            made = await self._shown(s, account, calendar, done, near)
        return replace(made, added=change.added or event.added)

    async def _split(self, s: Session, account: Connection, calendar: Calendar, master: dict[str, Any], whole: Event,
                     key: str, change: EventChange) -> Event:
        """Celui-ci et les suivants : la suite, une série neuve, créée d'abord ; la série d'avant finie la veille
        (la neuve retirée si la coupe échoue)."""
        title = whole.title
        at = key_instant(key)
        if not any(o.key == key for o in occurrences(whole, at, at + 1)):
            raise AgendaError(f"cette occurrence de « {title} » n'existe plus chez Microsoft (la série a changé) : la "
                              "copie est relue")
        zone = self._zone(master, calendar)
        rec = master.get("recurrence") or {}
        rng = dict(rec.get("range") or {})
        tz = UTC if whole.span.all_day else zone_of(zone)
        day_before = (at_us(at, tz).date() - timedelta(days=1)).isoformat()
        cut = {"pattern": rec.get("pattern"), "range": {**rng, "type": "endDate", "endDate": day_before}}
        cut["range"].pop("numberOfOccurrences", None)
        duration = whole.span.end - whole.span.start
        span = change.span or Span(at, at + duration, whole.span.zone, whole.span.all_day)
        body: dict[str, Any] = {k: copy.deepcopy(master[k]) for k in _COPIED if k in master and master[k] is not None}
        attendees = _people(whole.participants)
        if attendees:
            body["attendees"] = attendees
        body["start"], body["end"] = times(span, zone)
        body["isAllDay"] = span.all_day
        start_day = at_us(span.start, UTC if span.all_day else zone_of(span.zone or zone)).date().isoformat()
        if change.rule is None:
            _before, after = split_rule(whole, key)
            count = dict(rule_parts(after)).get("COUNT", "")
            after_range: dict[str, Any] = {**rng, "startDate": start_day}
            if rng.get("type") == "numbered" and count.isdigit():
                after_range["numberOfOccurrences"] = int(count)
            body["recurrence"] = {"pattern": rec.get("pattern"), "range": after_range}
        elif change.rule:
            body["recurrence"] = rule_pattern(change.rule, span.start, span.zone or zone, span.all_day)
        body.update(change_body(body, replace(change, span=None, rule=None), zone))
        made = await self._json(s, "POST", f"{GRAPH}/me/calendars/{_q(calendar.remote)}/events", f"« {title} »",
                                body=body)
        try:
            await self._patch(s, master, {"recurrence": cut}, title)
        except AgendaError:
            try:
                await self._json(s, "DELETE", f"{GRAPH}/me/events/{_q(str(made.get('id')))}", f"« {title} »",
                                 ok=(404,))
            except AgendaError as exc:
                log.warning("agenda : la suite d'une série coupée n'a pas pu être retirée de Microsoft : %s", exc)
            raise
        shown = await self._shown(s, account, calendar, made, span.start)
        return replace(shown, added=change.added or whole.added)

    async def delete(self, account: Connection, calendar: Calendar, event: Event, occurrence: str,
                     scope: str = ALL) -> int:
        self._writable(account, calendar)
        key = occurrence or event.original
        async with self._session(account) as s:
            if event.original and scope == ONE:
                try:
                    target = await self._instance(s, event.uid, key, event)
                except AgendaError:
                    return 0  # déjà partie chez Microsoft
            else:
                answer = await s.send("GET", f"{GRAPH}/me/events/{_q(event.uid if event.original else event.remote)}",
                                      headers={"Prefer": PREFER})
                if answer.status in (404, 410):
                    return 0
                if not answer.ok:
                    raise AgendaError(_refused(answer, f"« {event.title} »"))
                target = dict(answer.data or {})
            if not target.get("isOrganizer", True):  # une invitation retirée de son agenda : refusée
                await self._answer(s, target, NO, "", event.title)
                return 1
            if event.original and scope == FOLLOWING and key:
                whole = self._series_event(account, calendar, target)
                if key != _first_key(whole):
                    rec = target.get("recurrence") or {}
                    tz = UTC if whole.span.all_day else zone_of(self._zone(target, calendar))
                    day_before = (at_us(key_instant(key), tz).date() - timedelta(days=1)).isoformat()
                    rng = {**(rec.get("range") or {}), "type": "endDate", "endDate": day_before}
                    rng.pop("numberOfOccurrences", None)
                    await self._patch(s, target, {"recurrence": {"pattern": rec.get("pattern"), "range": rng}},
                                      event.title)
                    return 1
            await self._json(s, "DELETE", f"{GRAPH}/me/events/{_q(str(target.get('id')))}", f"« {event.title} »",
                             etag=str(target.get("@odata.etag") or ""), ok=(404,))
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
        async with self._session(account) as s:
            if event.original and scope == ONE:
                target = await self._instance(s, event.uid, key, event)
            else:
                target = await self._get(s, event.uid if event.original else event.remote, event.title or "l'invitation")
            await self._answer(s, target, response, comment, event.title)
            fresh = await self._get(s, event.remote if event.original and event.remote else str(target.get("id")),
                                    event.title)
            return await self._shown(s, account, calendar, fresh, key_instant(key) if key else None)

    async def _answer(self, s: Session, target: Mapping[str, Any], response: str, comment: str, title: str) -> None:
        if target.get("isOrganizer"):
            raise AgendaError("ce compte organise cet événement : il n'y a rien à répondre")
        body = {"comment": comment.strip()[:1000], "sendResponse": target.get("responseRequested", True) is not False}
        await self._json(s, "POST", f"{GRAPH}/me/events/{_q(str(target.get('id')))}/{_ANSWER[response]}",
                         f"« {title} »", body=body)


def _first_key(master: Event) -> str:
    first = occurrences(master, master.span.start, master.span.start + 1)
    return first[0].key if first else occurrence_key(master.span.start, master.span.all_day)


__all__ = ["GRAPH", "HOSTS", "MicrosoftProvider", "change_body", "draft_body", "event_of", "iana_zone", "instant_of",
           "nearest_day", "pattern_rule", "rule_pattern", "times", "windows_zone"]

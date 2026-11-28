"""Le format iCalendar (RFC 5545) de l'agenda (ADR 0309, lot 1) : une seule lecture et une seule écriture, partagées
par l'abonnement iCal et CalDAV, sur la bibliothèque ``icalendar``.

- **Lire** (``read``, ``Resource.events``) : un VCALENDAR entier — ses VEVENT (une série et ses exceptions, un
  événement simple), leur récurrence (RRULE, RDATE, EXDATE, RECURRENCE-ID), leurs fuseaux (``Zones``), les journées
  entières et les événements sur plusieurs jours, ce qui est annulé — devient les types du port, sans rien perdre de
  ce que les écrans montrent : titre, lieu, description, lien de réunion (``conference_of``), participants et leurs
  réponses, organisateur, rappels (VALARM), occupé ou disponible (TRANSP), privé (CLASS), état. Un VEVENT illisible
  est sauté et compté, le reste se lit.
- **Les fuseaux** : un TZID qui nomme un fuseau IANA, un nom Windows d'Outlook (« Romance Standard Time ») ou un
  identifiant « globalement unique » (``/mozilla.org/…/Europe/Paris``) se lit par ce fuseau ; un VTIMEZONE propre au
  fichier se lit par ses règles, propres à ce fichier (jamais celles d'un autre VTIMEZONE du même nom ailleurs), et
  reçoit le fuseau IANA qui lui ressemble (les mêmes décalages sur trois ans), que la récurrence suit. Une heure
  « flottante » se lit dans le fuseau de l'agenda (X-WR-TIMEZONE, ou ce que le serveur en dit). Les instants du port
  sont en UTC, une journée entière reste une date.
- **Écrire** (``Resource``, ``new_resource``) : un événement neuf, ou une ressource relue chez le fournisseur que
  l'on change sur place — un champ, une occurrence devenue exception (``instance``), une occurrence retirée
  (``exclude``), une série coupée (``truncate``, ``split``), une réponse à une invitation (``answer``) — en gardant
  tout ce qu'on n'y touche pas (ses propriétés inconnues, ses VTIMEZONE, ses paramètres). Une RECURRENCE-ID et une
  EXDATE s'écrivent comme le DTSTART de leur série (une date, un instant UTC, ou l'heure de son TZID).
- **Rien de ce qu'il dit n'est gardé tel quel** (``Event.raw`` reste vide) : une adresse oubliée ne survit pas dans
  un texte brut ; une écriture relit la ressource chez le fournisseur.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import logging
import re
import warnings
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, available_timezones

from icalendar import Alarm, vCalAddress, vDDDTypes, vRecur
from icalendar import Calendar as VCalendar
from icalendar import Event as VEvent
from icalendar.timezone import tzp
from icalendar.timezone.windows_to_olson import WINDOWS_TO_OLSON

from mika.ports.agenda import (
    CANCELLED,
    CONFIRMED,
    DATES_MAX,
    DAY_US,
    MAYBE,
    NEEDS,
    NO,
    TENTATIVE,
    US_PER_S,
    YES,
    AgendaError,
    Event,
    EventChange,
    EventDraft,
    Participant,
    Recurrence,
    Span,
    alerts_of,
    at_us,
    day_at,
    key_instant,
    occurrence_key,
    us_of,
)
from mika.ports.agenda import EMAIL as BY_EMAIL
from mika.ports.agenda import NOTIFY as BY_NOTICE
from mika.ports.agenda import Alert as Reminder

log = logging.getLogger("mika.agenda")

PRODID = "-//Mika//Agenda//FR"
#: au plus tant de caractères d'un titre, d'un lieu ; d'une description (un texte venu du dehors)
TITLE_MAX, LOCATION_MAX, DESCRIPTION_MAX = 1000, 1000, 50_000
#: au plus tant de rappels par événement, de participants (une liste de diffusion entière n'entre pas)
REMINDERS_MAX, PARTICIPANTS_MAX = 10, 500

#: PARTSTAT (RFC 5545 § 3.2.12) ↔ la réponse du port ; « déléguée » compte comme un refus
_PARTSTAT = {"NEEDS-ACTION": NEEDS, "ACCEPTED": YES, "TENTATIVE": MAYBE, "DECLINED": NO, "DELEGATED": NO}
PARTSTAT_OF = {NEEDS: "NEEDS-ACTION", YES: "ACCEPTED", MAYBE: "TENTATIVE", NO: "DECLINED"}
_STATUS = {"CONFIRMED": CONFIRMED, "TENTATIVE": TENTATIVE, "CANCELLED": CANCELLED}
_STATUS_OF = {v: k for k, v in _STATUS.items()}
_UTC_NAMES = frozenset({"UTC", "Z", "GMT", "ETC/UTC", "ETC/GMT", "UT", "ZULU", "UNIVERSAL", "COORDINATED UNIVERSAL TIME"})

#: les liens de réunion qu'on reconnaît dans un lieu ou une description, quand l'événement n'en déclare pas
_MEETING = re.compile(
    r"https://(?:[a-z0-9-]+\.)*(?:meet\.google\.com|teams\.microsoft\.com|teams\.live\.com|zoom\.us|zoom\.com|"
    r"webex\.com|whereby\.com|meet\.jit\.si|gotomeet(?:ing)?\.com|bluejeans\.com|chime\.aws|facetime\.apple\.com)"
    r"/[^\s<>\"')\]]*", re.IGNORECASE)
#: les propriétés qui déclarent un lien de réunion, dans l'ordre : RFC 7986, Google, Microsoft
_CONFERENCE_PROPS = ("CONFERENCE", "X-GOOGLE-CONFERENCE", "X-MICROSOFT-SKYPETEAMSMEETINGURL")
#: ce qu'une exception reprend de sa série quand elle en avait la valeur (``inherit``)
_INHERITED = ("SUMMARY", "LOCATION", "DESCRIPTION", "TRANSP", "CLASS", "STATUS", "CONFERENCE")


# ── les fuseaux ─────────────────────────────────────────────────────────────


@functools.cache
def _iana_names() -> frozenset[str]:
    return frozenset(available_timezones())


def iana(tzid: str) -> str:
    """Le fuseau IANA qu'un TZID nomme (lui-même, un nom Windows, un identifiant « globalement unique ») ; ``"UTC"``
    pour UTC ; vide s'il n'en nomme aucun."""
    name = (tzid or "").strip().strip('"')
    if not name:
        return ""
    if name.upper() in _UTC_NAMES:
        return "UTC"
    if name in _iana_names():
        return name
    if (olson := WINDOWS_TO_OLSON.get(name)) and olson in _iana_names():
        return olson
    with warnings.catch_warnings():  # un identifiant « globalement unique » : deviné, ce qu'on veut
        warnings.simplefilter("ignore")
        try:
            found = tzp.timezone(name)
        except (ValueError, KeyError, OSError):
            found = None
    key = getattr(found, "key", None)
    return key if isinstance(key, str) and key in _iana_names() else ""


def _signature(tz: tzinfo, year: int) -> tuple[int, ...]:
    """Les décalages d'un fuseau (en minutes), le 1er et le 15 de chaque mois de trois années autour de ``year``."""
    out = []
    for y in (year - 1, year, year + 1):
        for m in range(1, 13):
            for d in (1, 15):
                off = datetime(y, m, d, 12, tzinfo=UTC).astimezone(tz).utcoffset()
                out.append(int(off.total_seconds() // 60) if off is not None else 0)
    return tuple(out)


@functools.lru_cache(maxsize=4096)
def _zone_signature(name: str, year: int) -> tuple[int, ...]:
    return _signature(ZoneInfo(name), year)


@functools.lru_cache(maxsize=512)
def _lookalike(signature: tuple[int, ...], year: int, hint: str, words: tuple[str, ...]) -> str:
    """Le fuseau IANA qui a ces décalages : celui de l'agenda d'abord, puis ceux dont la ville est dans le TZID, puis
    le premier par nom ; vide s'il n'y en a pas."""
    names = sorted(n for n in _iana_names() if "/" in n and not n.startswith(("posix/", "right/")))
    named = [n for n in names if n.rsplit("/", 1)[-1].replace("_", " ").lower() in words]
    for name in ([hint] if hint in _iana_names() else []) + named + names:
        try:
            if _zone_signature(name, year) == signature:
                return name
        except (ValueError, OSError):
            continue
    return ""


class Zones:
    """Les fuseaux d'un VCALENDAR : ceux que ses VTIMEZONE définissent (leurs règles à eux, ou celles du fuseau IANA
    qu'ils nomment), ceux que ses TZID nomment sans VTIMEZONE, et celui de l'agenda pour une heure flottante. Chacun :
    le fuseau qui convertit, et son nom IANA (vide : UTC)."""

    def __init__(self, cals: Iterable[VCalendar], *, hint: str = "", year: int = 2026) -> None:
        self.year = year
        name = iana(hint)
        self.hint = "" if name == "UTC" else name
        self.default: tuple[tzinfo, str] = (ZoneInfo(self.hint), self.hint) if self.hint else (UTC, "")
        self._by_id: dict[str, tuple[tzinfo, str]] = {}
        for cal in cals:
            for vtz in cal.walk("VTIMEZONE"):
                tzid = str(vtz.get("TZID", "")).strip()
                if tzid and tzid not in self._by_id:
                    self._by_id[tzid] = self._defined(vtz, tzid)

    def _defined(self, vtz: Any, tzid: str) -> tuple[tzinfo, str]:
        known = iana(tzid)
        if known:
            return (UTC, "") if known == "UTC" else (ZoneInfo(known), known)
        try:
            own = tzp.create_timezone(vtz)  # ses règles à lui, jamais gardées pour un autre fichier
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
            log.info("agenda : un VTIMEZONE illisible (%s) : %s", tzid[:60], type(exc).__name__)
            return self.default
        tokens = re.findall(r"[a-zà-ÿ]+", tzid.lower())
        words = tuple(dict.fromkeys([*tokens, *(" ".join(pair) for pair in zip(tokens, tokens[1:], strict=False))]))
        try:
            name = _lookalike(_signature(own, self.year), self.year, self.hint, words)
        except (ValueError, OverflowError, TypeError):
            name = ""
        return own, name

    def get(self, tzid: str) -> tuple[tzinfo, str]:
        tzid = (tzid or "").strip()
        if not tzid:
            return self.default
        found = self._by_id.get(tzid)
        if found is None:
            known = iana(tzid)
            found = (UTC, "") if known in ("", "UTC") else (ZoneInfo(known), known)
            if not known:
                log.info("agenda : fuseau inconnu « %s », lu en UTC", tzid[:60])
            self._by_id[tzid] = found
        return found


# ── lire ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Feed:
    """Un VCALENDAR lu : son nom, sa couleur, son fuseau (tels qu'il les dit), ses lignes, et combien de VEVENT
    illisibles ont été sautés."""

    name: str = ""
    color: str = ""
    zone: str = ""
    events: tuple[Event, ...] = ()
    skipped: int = 0


def _text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value).replace("\r\n", "\n").strip()[:limit]


def _decode(data: str | bytes) -> str:
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    return text.lstrip("﻿")


def parse(data: str | bytes) -> list[VCalendar]:
    """Les VCALENDAR d'un texte ; ``AgendaError`` s'il n'en est pas un."""
    text = _decode(data)
    if "BEGIN:VCALENDAR" not in text[:4096].upper():
        raise AgendaError("ce n'est pas un agenda iCalendar (pas de BEGIN:VCALENDAR) — une page web ? vérifie l'adresse")
    try:
        cals = VCalendar.from_ical(text, multiple=True)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AgendaError(f"l'agenda ne se lit pas ({str(exc)[:120]})") from None
    if not cals:
        raise AgendaError("l'agenda est vide (aucun VCALENDAR)")
    return list(cals)


def _prop(component: Any, name: str) -> Any:
    value = component.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _dt(prop: Any) -> Any:
    """La valeur d'une propriété de date (``None`` si elle est illisible)."""
    if not isinstance(prop, vDDDTypes):
        return None
    value = prop.dt
    if isinstance(value, tuple):  # une PERIOD : son début
        value = value[0]
    return value if isinstance(value, date) else None


def _instant(value: date, params: Any, zones: Zones) -> tuple[int, bool, str]:
    """(instant en µs UTC, journée entière, nom du fuseau) d'une valeur de date lue."""
    if not isinstance(value, datetime):
        return day_at(value.isoformat()), True, ""
    tzid = str(params.get("TZID", "")) if params is not None else ""
    if tzid:
        tz, name = zones.get(tzid)
    elif value.tzinfo is not None:  # « Z » : UTC
        tz, name = UTC, ""
    else:  # flottante : le fuseau de l'agenda
        tz, name = zones.default
    return us_of(value.replace(tzinfo=None).replace(tzinfo=tz)), False, name


def _key(value: date, params: Any, zones: Zones, *, all_day: bool, at: time | None, zone: tzinfo) -> str:
    """La clé d'occurrence d'une RECURRENCE-ID, d'une EXDATE ou d'une RDATE : une date pour une série de journées
    entières ; un instant UTC sinon (une date seule, pour une série à l'heure : à l'heure de son début, dans son
    fuseau)."""
    if all_day:
        day = value if not isinstance(value, datetime) else at_us(_instant(value, params, zones)[0], zone).date()
        return day.strftime("%Y%m%d")
    if not isinstance(value, datetime):
        local = datetime.combine(value, at or time()).replace(tzinfo=zone)
        return occurrence_key(us_of(local), False)
    return occurrence_key(_instant(value, params, zones)[0], False)


def _series_clock(first: date, prop: Any, zones: Zones) -> tuple[tzinfo, time | None]:
    """Le fuseau et l'heure du début d'une série : ce qui place une date seule (une EXDATE, une RECURRENCE-ID) sur
    l'occurrence de ce jour."""
    if not isinstance(first, datetime):
        return UTC, None
    tzid = str(prop.params.get("TZID", ""))
    if tzid:
        zone = zones.get(tzid)[0]
    else:
        zone = UTC if first.tzinfo is not None else zones.default[0]
    return zone, first.replace(tzinfo=None).time()


def _dates(component: Any, name: str) -> list[tuple[date, Any]]:
    """Les valeurs d'une EXDATE ou d'une RDATE (plusieurs lignes, plusieurs valeurs chacune), avec leurs paramètres :
    ``DATES_MAX`` au plus (un fichier hostile n'en fait pas relire des centaines de milliers à chaque période)."""
    found = component.get(name)
    if found is None:
        return []
    out = []
    for line in found if isinstance(found, list) else [found]:
        for item in getattr(line, "dts", ()):
            value = _dt(item)
            if value is not None:
                params = item.params if item.params.get("TZID") else getattr(line, "params", item.params)
                out.append((value, params))
                if len(out) >= DATES_MAX:
                    return out
    return out


def user_address(value: Any) -> str:
    """Une adresse d'agenda telle qu'on la compare (RFC 6638, ``calendar-user-address-set``) : une adresse e-mail
    sans « mailto: », sinon l'URI entière (``urn:uuid:…``, le chemin d'un principal), en minuscules."""
    text = str(value or "").strip()
    return (text[7:] if text.lower().startswith("mailto:") else text).strip().lower()


def _address(prop: Any) -> str:
    """L'adresse e-mail d'une ligne ORGANIZER ou ATTENDEE (vide : ce n'en est pas une)."""
    text = str(prop or "").strip()
    if text.lower().startswith("mailto:"):
        return text[7:].strip().lower()
    return "" if ":" in text or "/" in text else text.lower()


def _who(prop: Any, mine: Collection[str]) -> Participant:
    params = getattr(prop, "params", {}) or {}
    me = user_address(prop)
    return Participant(address=_address(prop), name=_text(params.get("CN"), 200),
                       response=_PARTSTAT.get(str(params.get("PARTSTAT", "NEEDS-ACTION")).upper(), NEEDS),
                       optional=str(params.get("ROLE", "")).upper() in ("OPT-PARTICIPANT", "NON-PARTICIPANT"),
                       me=bool(me) and me in mine)


def conference_of(vevent: Any, location: str, description: str) -> str:
    """Le lien de réunion : celui qu'il déclare (CONFERENCE, puis ceux de Google et de Microsoft), sinon un lien de
    visio connu dans son lieu ou sa description."""
    for name in _CONFERENCE_PROPS:
        for value in (vevent.get(name) if isinstance(vevent.get(name), list) else [vevent.get(name)]):
            text = str(value or "").strip()
            if text.lower().startswith(("https://", "http://")):
                return text[:2000]
    return meeting_link(location, description)


def meeting_link(*texts: str) -> str:
    """Un lien de visio connu (Meet, Teams, Zoom…) dans ces textes (un lieu, une description), le premier ; vide sinon
    — ce que Google et Microsoft lisent aussi quand l'événement ne déclare pas le sien."""
    for text in texts:
        found = _MEETING.search(text or "")
        if found:
            return found.group(0)[:2000]
    return ""


def _reminders(vevent: Any, start: int, end: int) -> tuple[Reminder, ...]:
    """Les rappels du fournisseur (VALARM), en minutes avant le début (ceux d'après le début ne comptent pas) : un
    e-mail (ACTION:EMAIL), sinon une notification (DISPLAY, AUDIO)."""
    out: list[Reminder] = []
    for alarm in vevent.walk("VALARM"):
        action = str(alarm.get("ACTION", "")).upper()
        if action == "NONE":
            continue
        trigger = alarm.get("TRIGGER")
        value = getattr(trigger, "dt", None)
        if isinstance(value, timedelta):
            base = end if str(trigger.params.get("RELATED", "START")).upper() == "END" else start
            before = (start - (base + value // timedelta(microseconds=1))) // (60 * US_PER_S)
        elif isinstance(value, datetime):
            at = us_of(value if value.tzinfo else value.replace(tzinfo=UTC))
            before = (start - at) // (60 * US_PER_S)
        else:
            continue
        out.append(Reminder(int(before), BY_EMAIL if action == "EMAIL" else BY_NOTICE))
    return alerts_of(out)[:REMINDERS_MAX]


def _moment(component: Any, name: str) -> int:
    value = _dt(_prop(component, name))
    if isinstance(value, datetime):
        return us_of(value if value.tzinfo else value.replace(tzinfo=UTC))
    return 0


def _uid(vevent: Any) -> str:
    uid = str(vevent.get("UID") or "").strip()
    if uid:
        return uid[:400]
    seed = f"{vevent.get('DTSTART').to_ical() if vevent.get('DTSTART') else b''!r}|{vevent.get('SUMMARY')}"
    return "h" + hashlib.sha256(seed.encode("utf-8", "replace")).hexdigest()[:24] + "@ics"


def event_of(vevent: Any, zones: Zones, *, calendar: str, mine: Collection[str] = (), remote: str = "",
             etag: str = "") -> Event | None:
    """Un VEVENT devenu une ligne du port (``None`` s'il n'a pas de début lisible)."""
    start_prop = _prop(vevent, "DTSTART")
    first = _dt(start_prop)
    if first is None:
        return None
    start, all_day, zone_name = _instant(first, start_prop.params, zones)
    end_value, end_prop = _dt(_prop(vevent, "DTEND")), _prop(vevent, "DTEND")
    duration = getattr(_prop(vevent, "DURATION"), "dt", None)
    if end_value is not None:
        end = day_at(end_value.isoformat()[:10]) if all_day else _instant(end_value, end_prop.params, zones)[0]
    elif isinstance(duration, timedelta):
        end = start + duration // timedelta(microseconds=1)
    else:
        end = start + DAY_US if all_day else start
    end = max(end, start + (DAY_US if all_day else 0))
    zone, at = _series_clock(first, start_prop, zones)
    rid = _prop(vevent, "RECURRENCE-ID")
    original = ""
    if rid is not None and _dt(rid) is not None:
        original = _key(_dt(rid), rid.params, zones, all_day=not isinstance(_dt(rid), datetime), at=at, zone=zone)
    recurrence = None
    if not original:
        rule_prop = _prop(vevent, "RRULE")
        rule = rule_prop.to_ical().decode("utf-8", "replace") if isinstance(rule_prop, vRecur) else ""
        exdates = tuple(dict.fromkeys(_key(v, p, zones, all_day=all_day, at=at, zone=zone)
                                      for v, p in _dates(vevent, "EXDATE")))
        rdates = tuple(dict.fromkeys(_key(v, p, zones, all_day=all_day, at=at, zone=zone)
                                     for v, p in _dates(vevent, "RDATE")))
        if rule or rdates:
            recurrence = Recurrence(rule, exdates, rdates)
    location = _text(vevent.get("LOCATION"), LOCATION_MAX)
    description = _text(vevent.get("DESCRIPTION"), DESCRIPTION_MAX)
    organizer_prop = _prop(vevent, "ORGANIZER")
    organizer = _who(organizer_prop, mine) if organizer_prop is not None else None
    if organizer is not None:
        organizer = replace(organizer, response="", optional=False)
    attendees = vevent.get("ATTENDEE")
    participants = tuple(_who(a, mine) for a in (attendees if isinstance(attendees, list) else
                                                  [attendees] if attendees is not None else []))[:PARTICIPANTS_MAX]
    me_invited = next((p for p in participants if p.me), None)
    response = me_invited.response if me_invited is not None and not (organizer and organizer.me) else ""
    transp = str(vevent.get("TRANSP", "OPAQUE")).upper()
    busy_status = str(vevent.get("X-MICROSOFT-CDO-BUSYSTATUS", "")).upper()
    sequence = vevent.get("SEQUENCE")
    try:
        seq = int(str(sequence)) if sequence is not None else 0
    except ValueError:
        seq = 0
    return Event(
        calendar=calendar, uid=_uid(vevent), original=original, span=Span(start, end, zone_name, all_day),
        title=_text(vevent.get("SUMMARY"), TITLE_MAX), location=location, description=description,
        conference=conference_of(vevent, location, description), recurrence=recurrence,
        status=_STATUS.get(str(vevent.get("STATUS", "CONFIRMED")).upper(), CONFIRMED),
        busy=transp != "TRANSPARENT" and busy_status != "FREE",
        private=str(vevent.get("CLASS", "PUBLIC")).upper() in ("PRIVATE", "CONFIDENTIAL"),
        organizer=organizer, participants=participants, response=response,
        reminders=_reminders(vevent, start, end), remote=remote, etag=etag, sequence=max(0, seq),
        created=_moment(vevent, "CREATED"), updated=_moment(vevent, "LAST-MODIFIED") or _moment(vevent, "DTSTAMP"))


def _meta(cals: Sequence[VCalendar]) -> tuple[str, str, str]:
    cal = cals[0]
    name = _text(cal.get("X-WR-CALNAME") or cal.get("NAME"), 200)
    color = color_of(str(cal.get("X-APPLE-CALENDAR-COLOR") or cal.get("COLOR") or ""))
    zone = iana(str(cal.get("X-WR-TIMEZONE") or ""))
    return name, color, "" if zone == "UTC" else zone


def color_of(value: str) -> str:
    """Une couleur ``#rrggbb`` (celle qu'Apple écrit en ``#rrggbbaa``) ; vide sinon."""
    found = re.fullmatch(r"\s*#([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?\s*", value or "")
    return f"#{found.group(1).lower()}" if found else ""


def read(data: str | bytes, *, calendar: str, mine: Collection[str] = (), zone: str = "", remote: str = "",
         etag: str = "", year: int = 2026) -> Feed:
    """Un VCALENDAR lu en entier : ses lignes (séries, exceptions, événements simples), et ce qu'il dit de lui.
    ``zone`` : le fuseau de l'agenda quand le fichier n'en dit pas (une heure flottante s'y lit) ; ``year`` : l'année
    autour de laquelle un VTIMEZONE propre au fichier se compare aux fuseaux IANA."""
    cals = parse(data)
    name, color, own_zone = _meta(cals)
    zones = Zones(cals, hint=own_zone or zone, year=year)
    out: list[Event] = []
    skipped = 0
    for cal in cals:
        for vevent in cal.walk("VEVENT"):
            try:
                found = event_of(vevent, zones, calendar=calendar, mine=mine, remote=remote, etag=etag)
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError, IndexError) as exc:
                log.info("agenda : un VEVENT illisible, sauté : %s", type(exc).__name__)
                found = None
            if found is None:
                skipped += 1
            else:
                out.append(found)
    return Feed(name=name, color=color, zone=zones.hint, events=tuple(out), skipped=skipped)


def zone_of_vtimezone(data: str | bytes) -> str:
    """Le fuseau IANA d'un VTIMEZONE seul (``calendar-timezone`` d'un agenda CalDAV) ; vide s'il ne se lit pas."""
    text = _decode(data)
    if "BEGIN:VCALENDAR" not in text.upper():
        text = f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:x\r\n{text.strip()}\r\nEND:VCALENDAR\r\n"
    try:
        cals = parse(text)
    except AgendaError:
        return ""
    for vtz in cals[0].walk("VTIMEZONE"):
        _tz, name = Zones(cals).get(str(vtz.get("TZID", "")))
        return name
    return ""


# ── écrire ──────────────────────────────────────────────────────────────────


def _utc(us: int) -> datetime:
    return at_us(us - us % US_PER_S)


def _set(component: Any, name: str, value: Any, parameters: dict[str, str] | None = None) -> None:
    """Une propriété remplacée (ou retirée : ``None``, ``""``)."""
    component.pop(name, None)
    if value is not None and value != "":
        component.add(name, value, parameters=parameters)


def _set_span(vevent: Any, span: Span) -> None:
    """DTSTART et DTEND d'une période (DURATION retirée) : des dates, l'heure de son fuseau IANA, ou UTC."""
    vevent.pop("DURATION", None)
    if span.all_day:
        first = at_us(span.start).date()
        last = at_us(max(span.end, span.start + DAY_US)).date()
        _set(vevent, "DTSTART", first)
        _set(vevent, "DTEND", last)
        return
    tz = ZoneInfo(span.zone) if span.zone and span.zone in _iana_names() else UTC
    _set(vevent, "DTSTART", _utc(span.start).astimezone(tz))
    _set(vevent, "DTEND", _utc(max(span.end, span.start)).astimezone(tz))


def stamp(vevent: Any, now: int, *, bump: bool) -> None:
    """DTSTAMP et LAST-MODIFIED à maintenant ; ``bump`` : SEQUENCE + 1 (un changement de qui organise)."""
    _set(vevent, "DTSTAMP", _utc(now))
    _set(vevent, "LAST-MODIFIED", _utc(now))
    if bump:
        try:
            seq = int(str(vevent.get("SEQUENCE", 0)))
        except ValueError:
            seq = 0
        _set(vevent, "SEQUENCE", seq + 1)


def _attendee(p: Participant, kept: Any | None = None) -> vCalAddress:
    """La ligne ATTENDEE d'une participante : la sienne si elle y était (sa réponse, ses paramètres), sinon une
    invitation en attente."""
    if kept is not None:
        out = copy.deepcopy(kept)
    else:
        out = vCalAddress(f"mailto:{p.address}")
        out.params["PARTSTAT"] = PARTSTAT_OF.get(p.response, "NEEDS-ACTION") if p.response else "NEEDS-ACTION"
        out.params["RSVP"] = "TRUE"
        out.params["CUTYPE"] = "INDIVIDUAL"
    out.params["ROLE"] = "OPT-PARTICIPANT" if p.optional else "REQ-PARTICIPANT"
    if p.name:
        out.params["CN"] = p.name
    return out


def _alarms(vevent: Any, reminders: Sequence[Reminder], title: str) -> None:
    """Les rappels du fournisseur d'un événement, remplacés : une notification (ACTION:DISPLAY) ou un e-mail
    (ACTION:EMAIL, à l'organisatrice quand le VEVENT la nomme : la RFC 5545 veut un destinataire)."""
    vevent.subcomponents = [c for c in vevent.subcomponents if c.name != "VALARM"]
    organizer = vevent.get("ORGANIZER")
    for r in alerts_of(reminders)[:REMINDERS_MAX]:
        alarm = Alarm()
        alarm.add("ACTION", "EMAIL" if r.method == BY_EMAIL else "DISPLAY")
        alarm.add("DESCRIPTION", title or "Rappel")
        if r.method == BY_EMAIL:
            alarm.add("SUMMARY", title or "Rappel")
            if organizer is not None:
                alarm.add("ATTENDEE", organizer)
        alarm.add("TRIGGER", timedelta(minutes=-r.minutes))
        vevent.add_component(alarm)


def set_participants(vevent: Any, participants: Sequence[Participant], organizer: Participant | None) -> None:
    """Les participantes d'un événement qu'on organise : chacune garde sa ligne (sa réponse) si elle y était ; une
    nouvelle est invitée. Une participante sans adresse ne se reçoit pas : refusée en mots."""
    nameless = [p for p in participants if not p.address.strip()]
    if nameless:
        who = nameless[0].name or nameless[0].person or "?"
        raise AgendaError(f"une invitée sans adresse ne reçoit pas l'invitation ({who[:60]})")
    before = vevent.get("ATTENDEE")
    kept = {_address(a): a for a in (before if isinstance(before, list) else [before] if before is not None else [])}
    vevent.pop("ATTENDEE", None)
    seen: set[str] = set()
    for p in participants[:PARTICIPANTS_MAX]:
        address = p.address.strip().lower()
        if address in seen:
            continue
        seen.add(address)
        vevent.add("ATTENDEE", _attendee(replace(p, address=address), kept.get(address)))
    if seen and organizer is not None and organizer.address and vevent.get("ORGANIZER") is None:
        org = vCalAddress(f"mailto:{organizer.address}")
        if organizer.name:
            org.params["CN"] = organizer.name
        vevent.add("ORGANIZER", org)


def apply_change(vevent: Any, change: EventChange, *, now: int, organizer: Participant | None = None) -> None:
    """Ce qu'un changement dit, posé sur un VEVENT (ce qu'il laisse à ``None`` reste tel quel ; sa règle seulement sur
    une série)."""
    if change.title is not None:
        if not change.title.strip():
            raise AgendaError("un événement a un titre")
        _set(vevent, "SUMMARY", change.title.strip()[:TITLE_MAX])
    if change.location is not None:
        _set(vevent, "LOCATION", change.location.strip()[:LOCATION_MAX])
    if change.description is not None:
        _set(vevent, "DESCRIPTION", change.description[:DESCRIPTION_MAX])
    if change.conference is not None:
        for name in _CONFERENCE_PROPS:
            vevent.pop(name, None)
        if change.conference.strip():
            vevent.add("CONFERENCE", change.conference.strip(), parameters={"VALUE": "URI", "FEATURE": "VIDEO"})
    if change.busy is not None:
        _set(vevent, "TRANSP", "OPAQUE" if change.busy else "TRANSPARENT")
        vevent.pop("X-MICROSOFT-CDO-BUSYSTATUS", None)
    if change.private is not None:
        _set(vevent, "CLASS", "PRIVATE" if change.private else "PUBLIC")
    if change.status is not None:
        _set(vevent, "STATUS", _STATUS_OF.get(change.status, "CONFIRMED"))
    if change.span is not None:
        if change.span.end < change.span.start:
            raise AgendaError("un événement finit après avoir commencé")
        _set_span(vevent, change.span)
    if change.rule is not None and vevent.get("RECURRENCE-ID") is None:
        if change.rule:
            _set(vevent, "RRULE", vRecur.from_ical(change.rule.removeprefix("RRULE:")))
        else:
            for name in ("RRULE", "RDATE", "EXDATE"):
                vevent.pop(name, None)
    if change.participants is not None:
        set_participants(vevent, change.participants, organizer)
    if change.reminders is not None:
        _alarms(vevent, change.reminders, str(vevent.get("SUMMARY", "")))
    stamp(vevent, now, bump=True)


def draft_vevent(draft: EventDraft, *, uid: str, now: int, organizer: Participant | None = None) -> VEvent:
    """Le VEVENT d'un événement à créer."""
    if not draft.title.strip():
        raise AgendaError("un événement a un titre")
    if draft.span.end < draft.span.start:
        raise AgendaError("un événement finit après avoir commencé")
    vevent = VEvent()
    vevent.add("UID", uid)
    _set(vevent, "DTSTAMP", _utc(now))
    _set(vevent, "CREATED", _utc(now))
    vevent.add("SEQUENCE", 0)
    _set_span(vevent, draft.span)
    if draft.rule:
        vevent.add("RRULE", vRecur.from_ical(draft.rule.removeprefix("RRULE:")))
    apply_change(vevent, EventChange(
        title=draft.title, location=draft.location or None, description=draft.description or None,
        conference=draft.conference or None, busy=draft.busy, private=draft.private, status=draft.status,
        participants=draft.participants or None, reminders=draft.reminders), now=now, organizer=organizer)
    _set(vevent, "SEQUENCE", 0)
    return vevent


def new_resource(vevents: Sequence[Any]) -> VCalendar:
    cal = VCalendar()
    cal.add("PRODID", PRODID)
    cal.add("VERSION", "2.0")
    cal.add("CALSCALE", "GREGORIAN")
    for vevent in vevents:
        cal.add_component(vevent)
    return cal


def to_bytes(cal: VCalendar) -> bytes:
    """Le texte d'un VCALENDAR, avec les VTIMEZONE des fuseaux IANA qu'il nomme sans les définir."""
    years = [d.year for v in cal.walk("VEVENT") if isinstance(d := _dt(_prop(v, "DTSTART")), datetime)]
    first = date(max(1970, min(years) - 1), 1, 1) if years else date(1970, 1, 1)
    try:
        cal.add_missing_timezones(first_date=first)
    except (ValueError, TypeError) as exc:  # un fuseau qu'on ne sait pas décrire : le serveur le connaît par son nom
        log.info("agenda : VTIMEZONE non ajouté (%s)", type(exc).__name__)
    return cal.to_ical()


class Resource:
    """Une ressource d'un fournisseur (un VCALENDAR : une série et ses exceptions, ou un événement simple), relue
    chez lui et changée sur place : ce qu'on n'y touche pas reste tel quel."""

    def __init__(self, data: str | bytes | VCalendar, *, hint: str = "", year: int = 2026) -> None:
        self.cal = data if isinstance(data, VCalendar) else parse(data)[0]
        self.zones = Zones([self.cal], hint=hint, year=year)

    @property
    def vevents(self) -> list[Any]:
        return [c for c in self.cal.subcomponents if c.name == "VEVENT"]

    def master(self) -> Any | None:
        return next((v for v in self.vevents if v.get("RECURRENCE-ID") is None), None)

    def key_of(self, vevent: Any) -> str:
        event = self.event(vevent)
        return event.original if event is not None else ""

    def override(self, key: str) -> Any | None:
        return next((v for v in self.vevents if v.get("RECURRENCE-ID") is not None and self.key_of(v) == key), None)

    def event(self, vevent: Any, *, calendar: str = "", mine: Collection[str] = ()) -> Event | None:
        return event_of(vevent, self.zones, calendar=calendar, mine=mine)

    def events(self, *, calendar: str, mine: Collection[str] = (), remote: str = "", etag: str = "") -> list[Event]:
        out = []
        for vevent in self.vevents:
            found = event_of(vevent, self.zones, calendar=calendar, mine=mine, remote=remote, etag=etag)
            if found is not None:
                out.append(found)
        return out

    # ── les occurrences d'une série ──
    def _form(self) -> tuple[bool, str, tzinfo]:
        """Comment le DTSTART de la série s'écrit : journée entière, son TZID (vide : UTC ou flottante), son fuseau."""
        master = self.master()
        prop = _prop(master, "DTSTART") if master is not None else None
        value = _dt(prop)
        if value is None or not isinstance(value, datetime):
            return value is not None, "", UTC
        tzid = str(prop.params.get("TZID", ""))
        if tzid:
            return False, tzid, self.zones.get(tzid)[0]
        return False, "", UTC if value.tzinfo is not None else self.zones.default[0]

    def _like_start(self, name: str, key: str) -> tuple[Any, dict[str, str] | None]:
        """Une valeur de RECURRENCE-ID ou d'EXDATE pour cette clé, écrite comme le DTSTART de la série."""
        all_day, tzid, tz = self._form()
        at = key_instant(key)
        if all_day:
            return at_us(at).date(), None
        if tzid:
            return at_us(at, tz).replace(tzinfo=None), {"TZID": tzid}
        return _utc(at), None

    def instance(self, key: str) -> Any:
        """L'exception de cette occurrence : la sienne si elle existe, sinon une copie de la série à cette occurrence
        (sans sa règle), ajoutée à la ressource."""
        found = self.override(key)
        if found is not None:
            return found
        master = self.master()
        if master is None:
            raise AgendaError("cette occurrence n'a pas de série")
        ev = self.event(master)
        assert ev is not None
        duration = max(0, ev.span.end - ev.span.start)
        out = copy.deepcopy(master)
        for name in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID"):
            out.pop(name, None)
        value, params = self._like_start("RECURRENCE-ID", key)
        out.add("RECURRENCE-ID", value, parameters=params)
        self._place(out, key_instant(key), duration)
        self.cal.add_component(out)
        return out

    def exclude(self, key: str) -> None:
        """Cette occurrence retirée de la série (une EXDATE), son exception avec elle."""
        master = self.master()
        found = self.override(key)
        if found is not None:
            self.cal.subcomponents.remove(found)
        if master is not None:
            value, params = self._like_start("EXDATE", key)
            master.add("EXDATE", value, parameters=params)

    def _write_dates(self, vevent: Any, name: str, keys: Sequence[str]) -> None:
        """Les EXDATE ou les RDATE d'une série réécrites d'après leurs clés, comme le DTSTART de la série."""
        vevent.pop(name, None)
        for k in dict.fromkeys(keys):
            value, params = self._like_start(name, k)
            vevent.add(name, value, parameters=params)

    def _dates_of(self, vevent: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """(EXDATE, RDATE) d'une série, par leurs clés."""
        ev = self.event(vevent)
        rec = ev.recurrence if ev is not None else None
        return (rec.exdates, rec.rdates) if rec is not None else ((), ())

    def _place(self, vevent: Any, at: int, duration: int) -> None:
        """DTSTART et DTEND d'une occurrence, écrits comme le DTSTART de la série."""
        all_day, tzid, tz = self._form()
        vevent.pop("DURATION", None)
        if all_day:
            _set(vevent, "DTSTART", at_us(at).date())
            _set(vevent, "DTEND", at_us(at + max(duration, DAY_US)).date())
        elif tzid:
            _set(vevent, "DTSTART", at_us(at, tz).replace(tzinfo=None), {"TZID": tzid})
            _set(vevent, "DTEND", at_us(at + duration, tz).replace(tzinfo=None), {"TZID": tzid})
        else:
            _set(vevent, "DTSTART", _utc(at))
            _set(vevent, "DTEND", _utc(at + duration))

    def truncate(self, key: str, rule: str) -> list[Any]:
        """La série finie juste avant cette occurrence (sa règle ``rule``, finie par UNTIL) ; ses EXDATE, RDATE et
        exceptions d'après partent — les exceptions rendues, pour une nouvelle série."""
        master = self.master()
        if master is None:
            raise AgendaError("cette occurrence n'a pas de série")
        at = key_instant(key)
        exdates, rdates = self._dates_of(master)
        _set(master, "RRULE", vRecur.from_ical(rule))
        self._write_dates(master, "EXDATE", [k for k in exdates if key_instant(k) < at])
        self._write_dates(master, "RDATE", [k for k in rdates if key_instant(k) < at])
        moved = [v for v in self.vevents if v.get("RECURRENCE-ID") is not None and key_instant(self.key_of(v)) >= at]
        for v in moved:
            self.cal.subcomponents.remove(v)
        return moved

    def split(self, key: str, rule: str, uid: str) -> Resource:
        """« Celui-ci et les suivants » : une nouvelle ressource, sous un nouvel UID, dont la série commence à cette
        occurrence (sa règle ``rule`` : le COUNT qui reste, ou le même UNTIL), avec les EXDATE et RDATE d'après, et
        les VTIMEZONE de celle-ci. Celle-ci ne change pas (``truncate`` la coupe)."""
        master = self.master()
        if master is None:
            raise AgendaError("cette occurrence n'a pas de série")
        ev = self.event(master)
        assert ev is not None
        at = key_instant(key)
        exdates, rdates = self._dates_of(master)
        out = copy.deepcopy(master)
        _set(out, "UID", uid)
        _set(out, "RRULE", vRecur.from_ical(rule))
        self._write_dates(out, "EXDATE", [k for k in exdates if key_instant(k) >= at])
        self._write_dates(out, "RDATE", [k for k in rdates if key_instant(k) >= at])
        self._place(out, at, max(0, ev.span.end - ev.span.start))
        _set(out, "SEQUENCE", 0)
        cal = new_resource([*(copy.deepcopy(z) for z in self.cal.walk("VTIMEZONE")), out])
        return Resource(cal, hint=self.zones.hint, year=self.zones.year)

    def adopt(self, overrides: Sequence[Any], uid: str, delta: int = 0) -> None:
        """Des exceptions d'une autre série, sous l'UID de celle-ci ; ``delta`` : la série a bougé d'autant, leur
        RECURRENCE-ID aussi (et leur heure, si elles étaient à celle de la série)."""
        for v in overrides:
            _set(v, "UID", uid)
            self.cal.add_component(v)
        self.shift(delta, overrides, exdates=False)

    def shift(self, delta: int, overrides: Sequence[Any] | None = None, *, exdates: bool = True) -> None:
        """La série a bougé de ``delta`` µs : les RECURRENCE-ID de ses exceptions (``overrides`` : celles-ci
        seulement) et ses EXDATE la suivent ; une exception restée à l'heure de la série bouge avec elle."""
        if not delta:
            return
        for v in self.vevents if overrides is None else list(overrides):
            key = self.key_of(v) if v.get("RECURRENCE-ID") is not None else ""
            ev = self.event(v)
            if not key or ev is None:
                continue
            new_key = occurrence_key(key_instant(key) + delta, "T" not in key)
            value, params = self._like_start("RECURRENCE-ID", new_key)
            _set(v, "RECURRENCE-ID", value, params)
            if ev.span.start == key_instant(key):  # restée à l'heure de la série : elle la suit
                _set_span(v, replace(ev.span, start=ev.span.start + delta, end=ev.span.end + delta))
        master = self.master()
        if master is not None and exdates:
            old, rdates = self._dates_of(master)
            self._write_dates(master, "EXDATE", [occurrence_key(key_instant(k) + delta, "T" not in k) for k in old])
            self._write_dates(master, "RDATE", [occurrence_key(key_instant(k) + delta, "T" not in k) for k in rdates])

    def inherit(self, before: Any, change: EventChange, *, now: int) -> None:
        """Ses exceptions reprennent ce qui change dans la série, là où elles en avaient encore la valeur
        (``before`` : la série telle qu'elle était)."""
        simple = EventChange(title=change.title, location=change.location, description=change.description,
                             conference=change.conference, busy=change.busy, private=change.private,
                             status=change.status)
        names = {"title": "SUMMARY", "location": "LOCATION", "description": "DESCRIPTION",
                 "conference": "CONFERENCE", "busy": "TRANSP", "private": "CLASS", "status": "STATUS"}
        for v in self.vevents:
            if v.get("RECURRENCE-ID") is None:
                continue
            fields = {f: getattr(simple, f) for f, prop in names.items()
                      if getattr(simple, f) is not None and str(v.get(prop, "")) == str(before.get(prop, ""))}
            if fields:
                apply_change(v, EventChange(**fields), now=now)

    def answer(self, vevent: Any, response: str, mine: Collection[str], *, comment: str = "", now: int) -> None:
        """La réponse du compte à cette invitation : le PARTSTAT de sa ligne (sans RSVP), un commentaire s'il y en a
        un — ce que le serveur transmet à l'organisateur (RFC 6638)."""
        attendees = vevent.get("ATTENDEE")
        lines = attendees if isinstance(attendees, list) else [attendees] if attendees is not None else []
        own = [a for a in lines if user_address(a) in mine]
        if not own:
            raise AgendaError("ce compte n'est pas parmi les invités de cet événement")
        for a in own:
            a.params["PARTSTAT"] = PARTSTAT_OF[response]
            a.params.pop("RSVP", None)
        vevent.pop("COMMENT", None)
        if comment.strip():
            vevent.add("COMMENT", comment.strip()[:2000])
        stamp(vevent, now, bump=False)

    def to_bytes(self) -> bytes:
        return to_bytes(self.cal)


def organizes(vevent: Any, mine: Collection[str]) -> bool:
    """Ce compte organise-t-il cet événement (ou personne ne l'organise : un événement à soi) ?"""
    org = _prop(vevent, "ORGANIZER")
    return org is None or user_address(org) in mine


__all__ = ["PARTSTAT_OF", "PRODID", "Feed", "Resource", "Zones", "apply_change", "color_of", "conference_of",
           "draft_vevent",
           "event_of", "iana", "meeting_link", "new_resource", "organizes", "parse", "read", "set_participants", "stamp",
           "to_bytes", "user_address", "zone_of_vtimezone"]

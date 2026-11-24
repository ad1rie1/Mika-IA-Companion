"""Agenda, pour qui est connecté (ADR 0309, lot 4) : ses agendas — les siens, ceux qu'on lui partage, ses abonnements,
« L'agenda de Mika » vu par elle —, une période, un événement, chercher, ses invitations et ce que Mika propose ;
écrire, répondre, décider ; ses comptes d'agenda (Paramètres › Agendas), les partager, leur tableau de droits.

Un agenda est à elle quand son compte l'est (son compte du système ``moi:<sa clé>`` ; un compte branché à son nom, ou
« à toi » si elle est une de ses propriétaires : la règle de ``vocab.ownership``, ADR 0185) ; un agenda qu'on lui
partage s'y ajoute, à son niveau (``plugins/agenda/actions.py::level_of``) — masqué par son propriétaire, ou sous un
compte décoché, il ne l'est plus. Un événement, une proposition sont à l'agenda qu'ils désignent : hors de ses agendas,
rien n'existe (404). Un événement privé d'une autre personne se lit « Occupé ».

Ce qui s'écrit passe par les actions du plugin (``agenda.creer``, ``modifier``, ``supprimer``, ``dupliquer``,
``repondre``, ``rappel``, ``nouvel_agenda``, ``synchroniser``, ``accepter``, ``refuser``, ``ajouter_modifie``), au nom
de la personne, auditées ``moi.agenda.<action>`` ; ce qui se règle (un compte, un agenda, un partage, un tableau) dans
les réglages, sous leur verrou, audité ``moi.<geste>``. Le contrat : ``docs/protocole-moi.md``, § 13.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta
from html import escape
from typing import Any

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from mika.adapters.agenda import SERVICES, AgendaAccount, AgendaConfig, server_host
from mika.adapters.agenda.config import ACCOUNT_KEY, COLORS
from mika.adapters.web.session import account_of
from mika.app.her_agenda import her_agenda, title_of
from mika.app.me.api import (
    NO_STORE,
    OWN_MAX,
    Call,
    Denied,
    MeApiBase,
    done,
    form,
    missing,
    refused,
)
from mika.app.me.common import millis, own_room, settings_of
from mika.app.me.hosts import public_only
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.kernel.clock import instant, local
from mika.plugins.agenda import CREATE, RESPOND, WAITING, AgendaState, owner, params_of, reminder
from mika.plugins.agenda.actions import KEEP, account_level, handles_of, level_of
from mika.plugins.agenda.rights import table_of
from mika.plugins.agenda.tools import busy_summary
from mika.plugins.agenda.watch import invitation_key
from mika.ports.agenda import (
    ALERT_METHODS,
    ALERTS_MAX,
    CALDAV,
    DAY_US,
    GOOGLE,
    ICAL,
    KIND_WORDS,
    MICROSOFT,
    NEEDS,
    REMINDERS,
    SYSTEM,
    AgendaError,
    Alert,
    Calendar,
    Connection,
    Event,
    Occurrence,
    Participant,
    instance,
    masked,
    occurrences,
    readable_key,
    split_calendar_key,
    system_account,
    system_person,
)
from mika.ports.mail import SIGNED_IN
from mika.runtime import decisions
from mika.runtime.operations import audit
from mika.runtime.state import RUNTIME
from mika.vocab.access import (
    KEEP_WORDS,
    PERSON,
    SHARE_PREPARE,
    SHARE_USE,
    WRITE_WORDS,
    AgendaRule,
    Table,
    canal_words,
    reaches,
    when_words,
    who_words,
)
from mika.vocab.ownership import OWNED
from mika.vocab.rights import rights_of
from mika.vocab.words import fold

#: « L'agenda de Mika » parmi ses agendas : sa mémoire, montrée comme un agenda (lecture seule)
HER = "mika"
#: au plus tant de jours d'une période ; une recherche lit la fenêtre de la synchro (90 jours derrière, un an devant)
PERIOD_DAYS, SEARCH_PAST, SEARCH_AHEAD, SEARCH_MAX = 100, 90, 366, 50
#: ce qu'on dit d'une sorte qui se branche ici (le système existe sans rien faire)
PLUGGABLE = (GOOGLE, MICROSOFT, CALDAV, ICAL)
#: ce qu'une personne règle d'un compte
ACCOUNT_FIELDS = ("label", "enabled", "url", "username", "password", "address", "oauth_client_id", "oauth_tenant")
TOO_LOW = {"lire": "Cet agenda t'est partagé en lecture : tu le lis, sans y écrire.",
           "preparer": "Cet agenda t'est partagé en lecture et préparation : elle peut t'y préparer un ajout, que son "
                       "propriétaire approuve ; tu n'y écris pas toi-même."}
ONLY_OWNER = "Seul son propriétaire règle cet agenda."
NO_GOOGLE_APP = "L'application Google de ce serveur n'est pas réglée : demande-le à qui s'occupe d'elle."


# ── à qui ──


def _ports(call: Call) -> tuple[Any, Any]:
    store, providers = call.port("agenda"), call.port("agenda_providers")
    if store is None or providers is None:
        raise Denied(503, "L'agenda n'est pas branché sur ce serveur.")
    return store, providers


def mine(call: Call) -> dict[str, tuple[Calendar, str]]:
    """Ses agendas, par clé : l'agenda et son niveau — les siens (« Mon agenda » né au besoin), puis ceux qu'on lui
    partage."""
    store, providers = _ports(call)
    system = getattr(providers, "system", None)
    if system is not None:
        system.ensure(system_account(call.me.person))
    p, frame = params_of(call.frame), call.frame
    out: dict[str, tuple[Calendar, str]] = {}
    for cal in store.calendars():
        level = level_of(p, frame, call.me.person, cal.key)
        if level:
            out[cal.key] = (cal, level)
    return out


def _one(call: Call, key: str) -> tuple[Calendar, str]:
    found = mine(call).get(key)
    if found is None:
        raise missing()
    return found


def _owned(call: Call, key: str) -> Calendar:
    cal, level = _one(call, key)
    if level != OWNED:
        raise Denied(403, ONLY_OWNER)
    return cal


def _usable(level: str) -> bool:
    return level == OWNED or reaches(level, SHARE_USE)


def _account_mine(call: Call, key: str) -> None:
    """Un compte à elle (son compte du système, ou un compte branché à elle) ; un compte d'une autre n'existe pas."""
    if account_level(params_of(call.frame), call.frame, call.me.person, key) != OWNED:
        raise missing()
    if not system_person(key) and key not in settings_of(call).agenda().accounts:
        raise missing()


def _name(call: Call, person: str) -> str:
    return identity_c.person_name(call.frame, person) or str(
        getattr(call.frame.get(identity_c.IDENTITY(person)), "name", "") or person)


def _owner_name(call: Call, account: str) -> str:
    holder = owner(params_of(call.frame), account)
    return _name(call, holder[len(PERSON):]) if holder.startswith(PERSON) else identity_c.keepers(call.frame)


def _kind_of(call: Call, account: str) -> str:
    if system_person(account):
        return SYSTEM
    p = params_of(call.frame)
    if account in p.kinds:
        return p.kinds[account]
    state = call.port("agenda").account(account) if call.port("agenda") is not None else None
    return state.kind if state is not None else ""


def _writable(call: Call, cal: Calendar, level: str) -> bool:
    """Peut-elle écrire dans cet agenda d'ici : le sien ou « s'en servir », un agenda que son fournisseur laisse
    écrire, sous un compte actif."""
    if not _usable(level) or not cal.writable:
        return False
    _store, providers = _ports(call)
    conn = providers.connection(cal.account)
    provider = providers.of(conn.kind) if conn is not None else None
    return bool(conn is not None and provider is not None and conn.enabled
                and cal.account not in params_of(call.frame).accounts_off and provider.abilities(conn).write)


#: pourquoi elle ne répond pas d'ici à une invitation (une ligne sous ses boutons, que l'écran cache alors)
NO_ANSWER_SHARED = "Cet agenda t'est partagé sans t'en servir : seul son propriétaire répond à ses invitations."
NO_ANSWER_PRIVATE = "Cette invitation est privée : seul son propriétaire y répond."
NO_ANSWER_READ_ONLY = "Cet agenda ne s'écrit pas d'ici (en lecture seule, ou son compte est coupé) : réponds depuis " \
    "son application."
NO_ANSWER_TOLD = "Son serveur ne transmet pas les réponses aux invitations (pas de planification CalDAV) : réponds " \
    "depuis ta messagerie."


def _answers_reach(call: Call, calendar: str) -> bool:
    """Une réponse d'ici atteint-elle l'organisatrice : le fournisseur de cet agenda la transmet-il (un serveur CalDAV
    sans planification, RFC 6638, ne la transmet pas ; avant de l'avoir découvert, on ne le sait pas) ?"""
    _store, providers = _ports(call)
    conn = providers.connection(split_calendar_key(calendar)[0])
    provider = providers.of(conn.kind) if conn is not None else None
    return bool(conn is not None and provider is not None and provider.abilities(conn).invite)


def _setting(cfg: AgendaConfig, calendar: str) -> Any:
    account, local_ = split_calendar_key(calendar)
    found = cfg.account(account)
    return found.setting(local_) if found is not None else None


def alerts_json(alerts: Iterable[Alert]) -> list[dict[str, Any]]:
    """Des rappels du fournisseur : ``method`` (``notification``, ``email``) et ``minutes`` avant."""
    return [{"method": a.method, "minutes": a.minutes} for a in alerts]


def _abilities(call: Call, account: str) -> Any:
    _store, providers = _ports(call)
    conn = providers.connection(account)
    provider = providers.of(conn.kind) if conn is not None else None
    return provider.abilities(conn) if provider is not None and conn is not None else None


def _calendar_json(call: Call, cal: Calendar, level: str, cfg: AgendaConfig | None = None) -> dict[str, Any]:
    p = params_of(call.frame)
    kind = _kind_of(call, cal.account)
    owned = level == OWNED
    setting = _setting(cfg, cal.key) if cfg is not None else None
    state = call.port("agenda").account(cal.account)
    writable = _writable(call, cal, level)
    abilities = _abilities(call, cal.account)
    out: dict[str, Any] = {
        "key": cal.key, "account": cal.account, "name": cal.name or split_calendar_key(cal.key)[1],
        "provider_name": cal.provider_name, "kind": kind,
        "kind_label": KIND_WORDS.get(kind, kind), "level": level, "owner_name": "" if owned else _owner_name(
            call, cal.account),
        "group": ("subscriptions" if kind == ICAL else "mine") if owned else "shared",
        "color": setting.color if setting is not None else "", "provider_color": cal.color, "primary": cal.primary,
        "hidden": cal.key in p.hidden, "enabled": cal.account not in p.accounts_off,
        "reminder": reminder(p, cal.key, kind), "reminder_set": p.reminders.get(cal.key, ""),
        "writable": writable, "read_only": not cal.writable,
        "can": {"write": writable, "respond": writable and bool(abilities is not None and abilities.invite),
                "settings": owned, "share": owned, "rights": owned,
                "remind": owned, "rename": owned},
        "synced_at": millis(cal.synced_at or (state.synced_at if state is not None else 0)),
        "provider_reminders": {"max": abilities.reminders if abilities is not None and cal.writable else 0,
                               "email": bool(abilities is not None and abilities.email_reminders),
                               "defaults": alerts_json(cal.reminders)},
    }
    if owned:
        out["error"] = state.error if state is not None else ""
        shares = setting.shares if setting is not None else p.shares.get(cal.key, {})
        out["shares"] = [{"person": who[len(PERSON):], "name": _name(call, who[len(PERSON):]), "level": lv}
                         for who, lv in sorted(shares.items())]
    return out


def _her_json(call: Call) -> dict[str, Any]:
    return {"key": HER, "account": "", "name": title_of(call.kernel), "kind": HER, "kind_label": "", "level": "lire",
            "owner_name": "", "group": HER, "color": "rose", "provider_color": "", "primary": False, "hidden": False,
            "enabled": True, "reminder": "non", "reminder_set": "", "writable": False, "read_only": True,
            "can": {"write": False, "respond": False, "settings": False, "share": False, "rights": False,
                    "remind": False, "rename": False}, "synced_at": 0, "provider_name": "",
            "provider_reminders": {"max": 0, "email": False, "defaults": []}}


async def calendars(call: Call) -> dict[str, Any]:
    """Ses agendas, les siens d'abord (le principal en tête), puis ceux qu'on lui partage, et l'agenda de Mika."""
    settings = call.api.settings
    cfg = settings.agenda() if settings is not None else None
    held = mine(call)
    rank = {"mine": 0, "subscriptions": 1, "shared": 2}
    items = [_calendar_json(call, cal, level, cfg) for cal, level in held.values()]
    items.sort(key=lambda c: (rank.get(c["group"], 3), not c["primary"], fold(c["name"])))
    return {"plugged": True, "zone": _zone_name(call), "calendars": [*items, _her_json(call)],
            "colors": [{"code": c, "label": w} for c, w in COLORS],
            "reminders": [{"code": c, "label": w} for c, w in REMINDERS]}


# ── une période ──


def _tz(call: Call) -> Any:
    return call.frame.env.tz_of(call.frame.root)


def _zone_name(call: Call) -> str:
    return str(getattr(_tz(call), "key", "") or "")


def _day(call: Call, name: str, default: date) -> date:
    raw = call.arg(name, limit=10)
    if not raw:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise Denied(400, f"« {name} » : une date AAAA-MM-JJ.", {name: "AAAA-MM-JJ"}) from None


def _bounds(call: Call, days: int = PERIOD_DAYS) -> tuple[date, date, int, int]:
    """La période demandée : ``start`` et ``end`` (le dernier jour compris), à l'heure du serveur ; par défaut, la
    semaine qui commence aujourd'hui."""
    tz = _tz(call)
    today = local(call.frame.now, tz).date()
    first = _day(call, "start", today)
    last = _day(call, "end", first + timedelta(days=6))
    if last < first:
        raise Denied(400, "« end » vient avant « start ».", {"end": "après start"})
    if (last - first).days >= days:
        raise Denied(400, f"Une période de {days} jours au plus.", {"end": f"{days} jours au plus"})
    lo = instant(datetime.combine(first, time(), tzinfo=tz))
    hi = instant(datetime.combine(last + timedelta(days=1), time(), tzinfo=tz))
    return first, last, lo, hi


def _chosen(call: Call, held: Mapping[str, tuple[Calendar, str]]) -> tuple[list[str], bool]:
    """Les agendas demandés (``calendars`` : leurs clés, séparées par des virgules ; ``mika`` : l'agenda de Mika) ;
    vide : tous ceux qu'elle voit, sauf les masqués. Un agenda qui n'est pas à elle : introuvable."""
    raw = call.arg("calendars", limit=4000)
    p = params_of(call.frame)
    if not raw:
        return [k for k, (cal, _lv) in held.items() if k not in p.hidden], True
    wanted = [k.strip() for k in raw.split(",") if k.strip()]
    if any(k not in held and k != HER for k in wanted):
        raise missing()
    return [k for k in dict.fromkeys(wanted) if k != HER], HER in wanted


def _person_json(x: Participant | None) -> dict[str, Any] | None:
    if x is None:
        return None
    return {"address": x.address, "name": x.name, "person": x.person, "response": x.response,
            "optional": x.optional, "me": x.me}


def _invited(e: Event) -> bool:
    return bool(e.origin) or (e.organizer is not None and not e.organizer.me and bool(e.response))


def event_json(call: Call, o: Occurrence, level: str, writable: bool,
               defaults: Iterable[Alert] = ()) -> dict[str, Any]:
    """Une occurrence : un événement privé d'une autre personne se lit « Occupé » (son créneau seul). Ses rappels du
    fournisseur : les siens, ou ceux de son agenda (``defaults``) quand il les suit."""
    e, span = o.event, o.span
    owned = level == OWNED
    hidden_words = e.private and not owned
    shown = masked(e) if hidden_words else e
    added = e.added if e.added is not None and not hidden_words else None
    why = ""
    if e.response:
        why = (NO_ANSWER_SHARED if not _usable(level) else NO_ANSWER_READ_ONLY) if not writable \
            else NO_ANSWER_PRIVATE if hidden_words else "" if _answers_reach(call, e.calendar) else NO_ANSWER_TOLD
    return {
        "event": e.id, "occurrence": o.key, "uid": e.uid, "calendar": e.calendar, "title": shown.title,
        "masked": hidden_words, "start": millis(span.start), "end": millis(span.end), "all_day": span.all_day,
        "first_day": span.first_day, "last_day": span.last_day, "zone": span.zone, "location": shown.location,
        "description": shown.description, "conference": shown.conference, "status": e.status, "busy": e.busy,
        "private": e.private, "recurring": e.recurring or bool(e.original),
        "rule": e.recurrence.rule if e.recurrence is not None and not e.original else "",
        "organizer": _person_json(shown.organizer), "participants": [_person_json(x) for x in shown.participants],
        "response": e.response, "invitation": e.response == NEEDS, "organized": not _invited(e),
        "added": {"by": added.by, "conversation": added.ref, "at": millis(added.at)} if added is not None else None,
        "remind": e.remind, "forgotten": e.forgotten,
        "reminders": [] if hidden_words else alerts_json(defaults if e.reminders_default else e.reminders),
        "reminders_default": e.reminders_default and not hidden_words,
        "can": {"edit": writable and not hidden_words and not _invited(e),
                "delete": writable and not hidden_words, "respond": bool(e.response) and not why,
                "duplicate": True, "remind": owned},
        "respond_why": why,
    }


def her_json(call: Call, d: Any) -> dict[str, Any]:
    """Une date de l'agenda de Mika : sa mémoire, en lecture seule — d'où ça vient, et la conversation."""
    return {"ref": d.ref, "calendar": HER, "kind": d.kind, "title": d.title, "start": millis(d.start),
            "end": millis(d.end), "all_day": d.all_day, "day": d.day, "source": d.source,
            "conversation": d.conversation, "said_at": millis(d.said_at)}


def _waiting(call: Call) -> list[Any]:
    return [w for w in call.frame.state("agenda").writes.values() if w.status == WAITING and w.approval]


def _args(call: Call, proposal: int) -> dict[str, Any]:
    """Les arguments d'une proposition qui attend, tels que le runtime les garde."""
    pending = call.frame.state(RUNTIME.name).effects.get(proposal)
    return rt.proposal_args(pending.args_json) if pending is not None else {}


async def period(call: Call) -> dict[str, Any]:
    """Les occurrences d'une période sur les agendas choisis, et ce que Mika propose d'y ajouter."""
    store, _providers = _ports(call)
    held = mine(call)
    first, last, lo, hi = _bounds(call)
    keys, with_her = _chosen(call, held)
    writable = {k: _writable(call, held[k][0], held[k][1]) for k in keys}
    items = [event_json(call, o, held[o.event.calendar][1], writable[o.event.calendar],
                        held[o.event.calendar][0].reminders) for o in store.period(keys, lo, hi, zone=_tz(call))]
    her = [her_json(call, d) for d in her_agenda(call.kernel, person=call.me.person, since=lo, until=hi)] \
        if with_her else []
    shown = set(keys)
    proposed = [x for x in await _proposals(call, held) if x["op"] == CREATE and x["calendar"] in shown
                and x["draft"] and x["draft"]["end"] > millis(lo) and x["draft"]["start"] < millis(hi)]
    return {"start": first.isoformat(), "end": last.isoformat(), "zone": _zone_name(call), "items": items,
            "her": her, "proposals": proposed}


def _event_of(call: Call) -> tuple[Event, str, Calendar, str]:
    store, _providers = _ports(call)
    raw = call.arg("event", limit=20)
    if not raw.isdigit():
        raise missing()
    e = store.event(int(raw))
    if e is None:
        raise missing()
    cal, level = _one(call, e.calendar)
    key = call.arg("occurrence", limit=20)
    if key and not readable_key(key):
        raise Denied(400, "« occurrence » ne se lit pas.", {"occurrence": "la clé d'une occurrence de la série"})
    return e, key, cal, level


async def event(call: Call) -> dict[str, Any]:
    """Un événement (une occurrence d'une série, par sa clé), avec ce qui l'attend : l'invitation et la réponse que
    Mika a préparée, ce qu'elle propose d'y changer. Une série demandée sans occurrence (la fiche qu'un client ouvre
    après l'avoir créée) désigne sa première : ce qu'on en supprime ou change demande alors sa portée."""
    e, key, cal, level = _event_of(call)
    if e.original:
        o = Occurrence(e, e.original, e.span)
    elif key and e.recurring:
        o = Occurrence(e, key, instance(e, key).span)
    else:
        first = occurrences(e, e.span.start, e.span.start + 400 * DAY_US, limit=1) if e.recurring else []
        o = first[0] if first else Occurrence(e, "", e.span)
    out = event_json(call, o, level, _writable(call, cal, level), cal.reminders)
    proposals = [x for x in await _proposals(call, mine(call)) if x["target"] and x["target"]["uid"] == e.uid
                 and x["calendar"] == e.calendar]
    out["proposals"] = proposals
    out["prepared"] = next((x for x in proposals if x["op"] == RESPOND and x["invitation"]), None)
    out["calendar_name"] = cal.name
    return out


def _matches(e: Event, words: str) -> bool:
    hay = " ".join([e.title, e.location, e.description, *(x.name for x in e.participants),
                    *(x.address for x in e.participants)])
    return words in fold(hay)


async def search(call: Call) -> dict[str, Any]:
    """Chercher dans ses agendas (un titre, un lieu, une description, une personne), sur la fenêtre de la synchro :
    les plus proches d'aujourd'hui d'abord, ``SEARCH_MAX`` au plus. Un événement privé d'une autre ne se cherche
    pas."""
    store, _providers = _ports(call)
    q = call.arg("q", limit=120).strip()
    if len(q) < 2:
        raise Denied(400, "« q » : deux caractères au moins.", {"q": "deux caractères au moins"})
    words = fold(q)
    held = mine(call)
    keys, with_her = _chosen(call, held)
    now = call.frame.now
    lo, hi = now - SEARCH_PAST * DAY_US, now + SEARCH_AHEAD * DAY_US
    found = [o for o in store.period(keys, lo, hi)
             if not (o.event.private and held[o.event.calendar][1] != OWNED) and _matches(o.event, words)]
    found.sort(key=lambda o: abs(o.span.start - now))
    writable = {k: _writable(call, held[k][0], held[k][1]) for k in keys}
    items = [event_json(call, o, held[o.event.calendar][1], writable[o.event.calendar],
                        held[o.event.calendar][0].reminders) for o in found[:SEARCH_MAX]]
    her = [her_json(call, d) for d in her_agenda(call.kernel, person=call.me.person, since=lo, until=hi)
           if words in fold(d.title)] if with_her else []
    return {"q": q, "items": sorted(items, key=lambda x: x["start"]), "her": her[:SEARCH_MAX],
            "more": len(found) > SEARCH_MAX}


# ── ce qui attend ──


async def _proposals(call: Call, held: Mapping[str, tuple[Calendar, str]]) -> list[dict[str, Any]]:
    """Ce que Mika propose d'écrire dans ses agendas et qui attend un accord : dans un agenda à elle, ou qu'on lui
    partage pour préparer ou s'en servir, ou dont elle décide. ``decides`` : c'est elle qui décide (son adresse est
    celle de la proposition) ; sinon elle attend l'accord d'un autre (le propriétaire, la console). Une réponse
    d'invitation à laquelle elle a répondu elle-même entre-temps n'y est plus. Sur un événement privé, qui n'en est
    ni propriétaire ni ne décide lit « Occupé » : ni son titre dans le résumé, ni ce qui changerait, ni la réponse
    préparée, ni le mot à l'organisatrice."""
    store = call.port("agenda")
    mine_ = handles_of(call.frame, call.me.handle)
    out = []
    texts = _texts(call, [w.summary_ref for w in _waiting(call)])
    for w in sorted(_waiting(call), key=lambda w: w.proposal):
        decides = bool(w.decider) and w.decider in mine_
        cal, level = held.get(w.calendar, (None, ""))
        if not decides and not (level == OWNED or reaches(level, SHARE_PREPARE)):
            continue
        args = _args(call, w.proposal)
        row = store.find(w.calendar, w.uid, w.original) if w.uid and store is not None else None
        if w.op == RESPOND and row is not None and row.response != NEEDS:
            continue  # elle a répondu elle-même : la proposition tombe (``agenda.watch``)
        veiled = bool(w.uid) and not decides and level != OWNED and (row is None or row.private)
        if veiled and (row is None or cal is None):
            continue  # l'événement visé n'est plus là : rien à en dire à qui ne décide pas (elle tombera)
        summary = busy_summary(w.op, row, w.occurrence, cal.name or w.calendar, _tz(call)) if veiled \
            else texts.get(w.summary_ref, "")
        draft = args.get("draft") or {}
        span = draft.get("span") or {}
        shown = await decisions.preview(call.kernel.mind, call.kernel.ports, "agenda.write",
                                        _json(args)) if decides else None
        out.append({
            "id": w.proposal, "op": w.op, "calendar": w.calendar, "summary": summary,
            "at": millis(w.at), "starts": millis(w.starts), "decides": decides,
            "conversation": str(args.get("ref") or ""), "invitation": w.invitation,
            "target": {"event": row.id if row is not None else 0, "uid": w.uid, "occurrence": w.occurrence}
            if w.uid else None,
            "draft": {"title": str(draft.get("title") or ""), "start": millis(int(span.get("start") or 0)),
                      "end": millis(int(span.get("end") or 0)), "all_day": bool(span.get("all_day")),
                      "zone": str(span.get("zone") or ""), "location": str(draft.get("location") or ""),
                      "description": str(draft.get("description") or ""), "rule": str(draft.get("rule") or ""),
                      "invite": [str(x.get("address") or "") for x in draft.get("invite") or []
                                 if isinstance(x, dict)]} if w.op == CREATE else None,
            "change": None if veiled else args.get("change") or None, "scope": str(args.get("scope") or ""),
            "answer": "" if veiled else str(args.get("response") or ""),
            "comment": "" if veiled else str(args.get("comment") or ""),
            "why": str(args.get("why") or "") if decides else "",
            "remind": args.get("remind"),
            "preview": {"text": shown.text, "digest": shown.digest, "blocked": shown.blocked}
            if shown is not None else None,
        })
    return out


def _json(args: Mapping[str, Any]) -> str:
    return json.dumps(dict(args), ensure_ascii=False, sort_keys=True)


def _texts(call: Call, refs: Iterable[str]) -> dict[str, str]:
    wanted = [r for r in dict.fromkeys(refs) if r]
    store = call.port("store")
    return dict(store.content(wanted)) if wanted and store is not None else {}


async def proposals(call: Call) -> dict[str, Any]:
    return {"items": await _proposals(call, mine(call))}


def _answerable(held: Mapping[str, tuple[Calendar, str]]) -> list[str]:
    return [k for k, (_cal, level) in held.items() if _usable(level)]


async def invitations(call: Call) -> dict[str, Any]:
    """Les invitations qui attendent sa réponse, dans ses agendas (et ceux qu'on lui partage pour s'en servir), la
    plus proche d'abord, chacune avec la réponse que Mika a préparée (son accord à elle)."""
    store, _providers = _ports(call)
    held = mine(call)
    s: AgendaState = call.frame.state("agenda")
    prepared = {x["invitation"]: x for x in await _proposals(call, held) if x["op"] == RESPOND and x["invitation"]}
    now = call.frame.now
    out = []
    for e in store.invitations(_answerable(held)):
        cal, level = held[e.calendar]
        nxt = occurrences(e, now, now + 400 * DAY_US, limit=1) if e.recurring and not e.original else []
        o = nxt[0] if nxt else Occurrence(e, e.original, e.span)
        item = event_json(call, o, level, _writable(call, cal, level), cal.reminders)
        inv = s.invitations.get(invitation_key(e))
        item["prepared"] = prepared.get(inv.key) if inv is not None else None
        item["calendar_name"] = cal.name
        out.append(item)
    return {"items": out}


def count(call: Call) -> int:
    """Pour la barre du haut : ses invitations en attente, et ce que Mika propose dont elle décide."""
    store = call.port("agenda")
    if store is None or call.port("agenda_providers") is None:
        return 0
    p, frame = params_of(call.frame), call.frame
    keys = [c.key for c in store.calendars() if _usable(level_of(p, frame, call.me.person, c.key))]
    mine_ = handles_of(frame, call.me.handle)
    decided = sum(1 for w in _waiting(call) if w.decider and w.decider in mine_)
    return len(store.invitations(keys)) + decided


# ── écrire ──


def _fields(call: Call, names: Iterable[str], *, keep: bool = False) -> dict[str, Any]:
    """Les champs d'un événement présents dans le corps, tels que l'action les lit ; ``keep`` : une modification (ce
    qui manque reste tel quel)."""
    out: dict[str, Any] = {}
    for name in names:
        if name not in call.data:
            continue
        raw = call.data[name]
        if name == "invite":
            if raw is not None and not (isinstance(raw, list) and all(isinstance(x, str) for x in raw)):
                raise Denied(400, "« invite » : une liste d'adresses.", {"invite": "une liste d'adresses"})
            if raw is None and not keep:
                continue
            out[name] = list(raw or [])
        elif name == "reminders":
            if raw is None:
                continue  # ceux de l'agenda chez son fournisseur (une création), tels quels (une modification)
            out[name] = _alerts_in(raw)
        elif name in ("all_day", "free", "private") and not keep:
            out[name] = raw is True
        elif name in ("all_day", "free", "private"):
            out[name] = "" if raw is None else ("oui" if raw is True else "non" if raw is False else str(raw))
        else:
            out[name] = call.arg(name, limit=8000)
    return out


EVENT_FIELDS = ("title", "start", "end", "all_day", "zone", "location", "description", "conference", "rule",
                "invite", "free", "private", "remind", "reminders")


def _alerts_in(raw: Any) -> list[str]:
    """Les rappels du fournisseur d'un corps (``[{"method": "notification", "minutes": 10}, …]``), tels que l'action
    les lit (« notification:10 »)."""
    bad = Denied(400, "« reminders » : une liste de {method, minutes}.", {"reminders": "une liste de {method, minutes}"})
    if not isinstance(raw, list) or len(raw) > ALERTS_MAX:
        raise bad
    out = []
    for x in raw:
        if not isinstance(x, dict) or x.get("method") not in ALERT_METHODS or not isinstance(x.get("minutes"), int) \
                or isinstance(x.get("minutes"), bool):
            raise bad
        out.append(f"{x['method']}:{x['minutes']}")
    return out


def _with_show(outcome: Any) -> dict[str, Any]:
    made = next((x for x in outcome.show if isinstance(x, dict)), None) if outcome.ok else None
    return done(outcome, **({"made": made} if made else {}))


def _target(call: Call, need_write: bool = True) -> tuple[Event, str, Calendar, str]:
    e, key, cal, level = _event_of(call)
    if need_write and not _usable(level):
        raise Denied(403, TOO_LOW.get(level, "Cet agenda ne t'est pas ouvert pour cela."))
    return e, key, cal, level


async def create(call: Call) -> dict[str, Any]:
    key = call.arg("calendar", limit=200)
    _cal, level = _one(call, key)
    if not _usable(level):
        raise Denied(403, TOO_LOW.get(level, "Cet agenda ne t'est pas ouvert pour cela."))
    values = _fields(call, EVENT_FIELDS)
    return _with_show(await call.act("agenda.creer", form(fixed={"calendar": key}, **values)))


async def edit(call: Call) -> dict[str, Any]:
    e, key, cal, _level = _target(call)
    values = _fields(call, (*EVENT_FIELDS, "scope"), keep=True)
    for name in ("title", "start", "end", "zone", "location", "description", "conference", "rule", "remind"):
        if name in values and call.data.get(name) is None:
            values[name] = KEEP
    return done(await call.act("agenda.modifier", form(fixed={"calendar": cal.key, "event": e.id,
                                                               "occurrence": key}, **values)))


async def delete(call: Call) -> dict[str, Any]:
    e, key, cal, _level = _target(call)
    return done(await call.act("agenda.supprimer", form(fixed={"calendar": cal.key, "event": e.id, "occurrence": key},
                                                        scope=call.arg("scope", "un", limit=10))))


async def duplicate(call: Call) -> dict[str, Any]:
    e, key, cal, _level = _target(call, need_write=False)
    to = call.arg("to", limit=200)
    if to:
        _one(call, to)
    return _with_show(await call.act("agenda.dupliquer", form(fixed={"calendar": cal.key, "event": e.id,
                                                                      "occurrence": key}, to=to)))


async def respond(call: Call) -> dict[str, Any]:
    e, key, cal, _level = _target(call)
    return done(await call.act("agenda.repondre", form(
        fixed={"calendar": cal.key, "event": e.id, "occurrence": key}, answer=call.arg("answer", limit=4),
        comment=call.arg("comment", limit=500), scope=call.arg("scope", "tous", limit=10))))


async def remind(call: Call) -> dict[str, Any]:
    e, _key, cal, level = _event_of(call)
    if level != OWNED:
        raise Denied(403, ONLY_OWNER)
    return done(await call.act("agenda.rappel", form(fixed={"calendar": cal.key, "event": e.id},
                                                     value=call.arg("value", limit=10))))


def _proposal(call: Call) -> Any:
    raw = call.arg("proposal", limit=20)
    w = call.frame.state("agenda").writes.get(int(raw)) if raw.isdigit() else None
    if w is None or w.status != WAITING:
        raise missing()
    held = mine(call)
    level = held.get(w.calendar, (None, ""))[1]
    decides = bool(w.decider) and w.decider in handles_of(call.frame, call.me.handle)
    if not decides:
        if level == OWNED or reaches(level, SHARE_PREPARE):
            raise Denied(403, "Cette proposition attend l'accord d'un autre que toi.")
        raise missing()
    return w


async def proposal_accept(call: Call) -> dict[str, Any]:
    w = _proposal(call)
    return done(await call.act("agenda.accepter", form(fixed={"proposal": w.proposal,
                                                              "seen": call.arg("seen", limit=100)})))


async def proposal_refuse(call: Call) -> dict[str, Any]:
    w = _proposal(call)
    return done(await call.act("agenda.refuser", form(fixed={"proposal": w.proposal},
                                                      note=call.arg("note", limit=500))))


async def proposal_edit(call: Call) -> dict[str, Any]:
    """« Modifier » ce que Mika propose d'ajouter, puis « Ajouter » : sa version s'écrit, marquée « ajouté par Mika »
    ; la proposition est retirée, et Mika l'apprend."""
    w = _proposal(call)
    if w.op != CREATE:
        raise Denied(409, "Seule une proposition d'ajout se modifie : accepte-la ou refuse-la.")
    key = call.arg("calendar", limit=200) or w.calendar
    _cal, level = _one(call, key)
    if not _usable(level):
        raise Denied(403, TOO_LOW.get(level, "Cet agenda ne t'est pas ouvert pour cela."))
    values = _fields(call, EVENT_FIELDS)
    conversation = str(_args(call, w.proposal).get("ref") or "")
    return _with_show(await call.act("agenda.ajouter_modifie", form(
        fixed={"calendar": key, "proposal": w.proposal, "conversation": conversation}, **values)))


# ── ses comptes (Paramètres › Agendas) ──


def _signin(call: Call, key: str, kind: str, conn: Connection | None) -> dict[str, Any] | None:
    _store, providers = _ports(call)
    provider = providers.of(kind)
    signin = getattr(provider, "signin", None)
    if signin is None:
        return None
    got = signin.state(key) if kind == GOOGLE else signin.state(key, conn) if conn is not None else None
    if got is None:
        return None
    return {"state": got.state, "code": got.code, "url": got.url, "until": millis(got.until), "error": got.error}


def _account_json(call: Call, key: str, a: AgendaAccount, held: Mapping[str, tuple[Calendar, str]],
                  cfg: AgendaConfig) -> dict[str, Any]:
    store, providers = _ports(call)
    state = store.account(key)
    conn = providers.connection(key)
    provider = providers.of(a.kind)
    abilities = provider.abilities(conn) if provider is not None and conn is not None else None
    cals = [_calendar_json(call, cal, lv, cfg) for cal, lv in held.values() if cal.account == key]
    cals.sort(key=lambda c: (not c["primary"], fold(c["name"])))
    system = bool(system_person(key))
    return {"key": key, "kind": a.kind, "kind_label": KIND_WORDS.get(a.kind, a.kind),
            "label": a.label or ("Ce serveur" if system else key), "system": system, "address": a.address,
            "enabled": a.enabled, "url": a.url if a.kind == CALDAV else "",
            "url_set": bool(a.url) if a.kind == ICAL else False, "username": a.username,
            "secrets": {"password": bool(a.password)}, "oauth_client_id": a.oauth_client_id,
            "oauth_tenant": a.oauth_tenant if a.kind == MICROSOFT else "",
            "synced_at": millis(state.synced_at) if state is not None else 0,
            "tried_at": millis(state.tried_at) if state is not None else 0,
            "failures": state.failures if state is not None else 0,
            "error": state.error if state is not None and not system else "",
            "signin": _signin(call, key, a.kind, conn) if a.kind in (GOOGLE, MICROSOFT) else None,
            "abilities": {"write": bool(abilities and abilities.write),
                          "calendars": bool(abilities and abilities.calendars)},
            "calendars": cals}


async def accounts(call: Call) -> dict[str, Any]:
    """Ses comptes d'agenda : son compte du système d'abord, puis ceux qu'elle a branchés ; ce que le serveur sait
    brancher (l'application Google, celle de Microsoft, les aides CalDAV) et les bornes."""
    settings = settings_of(call)
    cfg = settings.agenda()
    held = mine(call)
    p = params_of(call.frame)
    own = system_account(call.me.person)
    keys = [own, *sorted(k for k in cfg.accounts if not system_person(k)
                         and account_level(p, call.frame, call.me.person, k) == OWNED)]
    found = []
    for key in keys:
        a = cfg.account(key)
        if a is not None:
            found.append(_account_json(call, key, a, held, cfg))
    _store, providers = _ports(call)
    google = getattr(providers.of(GOOGLE), "signin", None)
    return {"plugged": True, "accounts": found,
            "google": {"app": settings.google_application() is not None,
                       "direct": bool(google is not None and google.direct())},
            "microsoft_app": bool(settings.mail_application()),
            "kinds": [{"code": k, "label": KIND_WORDS[k]} for k in PLUGGABLE],
            "services": [{"key": x.key, "name": x.name, "url": x.url, "help": x.help} for x in SERVICES],
            "colors": [{"code": c, "label": w} for c, w in COLORS],
            "reminders": [{"code": c, "label": w} for c, w in REMINDERS],
            "max": None if call.me.operator else OWN_MAX}


def _owner_for(call: Call) -> str:
    """À qui est ce qu'elle branche : « à toi » pour une de ses propriétaires, sinon à son nom (la règle du
    courrier)."""
    return "" if call.me.owner else PERSON + call.me.person


def _account_key(call: Call, label: str, kind: str, taken: set[str]) -> str:
    """La clé d'un compte branché : son nom affiché (sinon sa sorte), puis la fin d'un identifiant de l'``IdGen`` —
    jamais son adresse, ni un nom qui en est une : ses réglages, ses agendas et l'audit sont journalisés, et l'oubli
    d'une adresse ne les atteint pas. Un compte déjà branché garde la sienne."""
    said = "" if "@" in label else label
    base = re.sub(r"[^a-z0-9_-]+", "-", fold(said or KIND_WORDS[kind])).strip("-_")[:30].strip("-_")
    base = base if base and ACCOUNT_KEY.fullmatch(base) else "agenda"
    mind = call.kernel.mind
    while True:
        key = f"{base}-{mind.ids.new(mind.clock.now())[-6:].lower()}"
        if key not in taken:
            return key


def _mine_count(call: Call, cfg: AgendaConfig) -> int:
    return sum(1 for k, a in cfg.accounts.items() if not system_person(k) and a.owner == _owner_for(call))


def _values(call: Call) -> dict[str, Any]:
    raw = call.data.get("values", {})
    if not isinstance(raw, dict):
        raise Denied(400, "« values » : un objet.")
    unknown = sorted(set(raw) - set(ACCOUNT_FIELDS))
    if unknown:
        raise Denied(400, f"« {unknown[0]} » ne se règle pas ici.", {unknown[0]: "inconnu"})
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if k == "enabled":
            out[k] = v is True
        elif not isinstance(v, str) or len(v) > 2000:
            raise Denied(400, f"« {k} » : une chaîne de 2 000 caractères au plus.", {k: "une chaîne"})
        else:
            out[k] = v.strip()
    return out


async def _rejournal(call: Call) -> None:
    if call.api.reconfigure is not None:
        await call.api.reconfigure()


async def account_save(call: Call) -> dict[str, Any]:
    """Brancher un compte (sans ``account`` : sa sorte, ``kind``) ou régler un des siens. Un secret laissé vide reste
    celui qui est gardé, tant que le serveur ne change pas ; pour qui n'est pas opératrice, un serveur sur Internet
    seulement. Une création redite avec la même clé d'envoi ne refait rien."""
    if call.arg("account", limit=200):
        return await _account_save(call)
    return await call.once(lambda: _account_save(call))


async def _account_save(call: Call) -> dict[str, Any]:
    settings = settings_of(call)
    cfg = settings.agenda()
    values = _values(call)
    key = call.arg("account", limit=200)
    before: AgendaAccount | None = None
    if key:
        _account_mine(call, key)
        before = cfg.account(key)
        assert before is not None
        if system_person(key):
            values = {k: v for k, v in values.items() if k == "label"}
        merged = {**before.model_dump(), **values, "owner": before.owner, "kind": before.kind,
                  "calendars": before.calendars}
        moved = before.url != merged.get("url", before.url) or before.username != merged.get("username",
                                                                                              before.username)
        if not values.get("password") and before.password and not moved:
            merged["password"] = before.password
        elif not values.get("password") and before.password and moved and before.kind == CALDAV:
            raise Denied(400, "Le serveur change : redonne son mot de passe.", {"password": "à redonner"})
        if before.kind == ICAL and not values.get("url"):
            merged["url"] = before.url
        targets = {"url": merged.get("url")} if moved or (before.kind == ICAL and values.get("url")) else {}
    else:
        kind = call.arg("kind", limit=20)
        if kind not in PLUGGABLE:
            raise Denied(400, "« kind » : google, microsoft, caldav ou ical.", {"kind": "une sorte de compte"})
        own_room(call, _mine_count(call, cfg))
        key = _account_key(call, str(values.get("label") or "").strip(), kind, set(cfg.accounts))
        merged = {**values, "kind": kind, "owner": _owner_for(call)}
        if kind in (CALDAV, ICAL) and not merged.get("url"):
            raise Denied(400, "Son adresse, d'abord.", {"url": "valeur requise"})
        targets = {"url": merged.get("url")}
    if merged.get("kind") in (GOOGLE, MICROSOFT):
        merged["url"] = merged["password"] = ""
        targets = {}
    await public_only(call, {f: server_host(str(v or "")) for f, v in targets.items() if v})
    # son serveur revérifié sur Internet à chaque connexion, pas seulement ici (une opératrice vise ce qu'elle veut)
    merged["internet"] = not call.me.operator and merged.get("kind") in (CALDAV, ICAL)
    try:
        account = AgendaAccount.model_validate(merged)
    except ValidationError as exc:
        raise refused(exc) from None
    async with settings.writing:
        cfg = settings.agenda()
        if before is not None:
            if cfg.account(key) != before:
                raise Denied(409, "Ce compte vient d'être réglé ailleurs : rouvre-le, puis recommence.")
        else:
            own_room(call, _mine_count(call, cfg))
        try:
            await settings.save_agenda(AgendaConfig(accounts={**cfg.accounts, key: account}))
        except ValidationError as exc:
            raise refused(exc) from None
        await _rejournal(call)
    await audit(call.kernel, "moi.agenda_compte", by=call.me.handle, subject_kind="compte_agenda", subject=key)
    if account.kind in (CALDAV, ICAL) and account.enabled:
        await call.act("agenda.synchroniser", form(fixed={"account": key}), part="sync")
    return {"ok": True, "message": "Compte d'agenda enregistré.", "account": key}


async def account_remove(call: Call) -> dict[str, Any]:
    """Retirer un compte branché : ses agendas et leur copie partent ; ce que Mika en a appris reste."""
    settings = settings_of(call)
    key = call.arg("account", limit=200)
    _account_mine(call, key)
    if system_person(key):
        raise Denied(409, "Ton agenda du système reste : on ne le retire pas.")
    async with settings.writing:
        cfg = settings.agenda()
        if key not in cfg.accounts:
            raise missing()
        await settings.save_agenda(AgendaConfig(accounts={k: a for k, a in cfg.accounts.items() if k != key}))
        await _rejournal(call)
    store, _providers = _ports(call)
    store.drop_account(key)
    await audit(call.kernel, "moi.agenda_compte_retire", by=call.me.handle, subject_kind="compte_agenda", subject=key)
    return {"ok": True, "message": "Compte d'agenda retiré."}


async def account_try(call: Call) -> dict[str, Any]:
    """Essayer un serveur CalDAV (son adresse, son identifiant, son mot de passe ; ou un compte déjà branché, dont le
    mot de passe gardé sert tant que le serveur ne change pas) : les agendas qu'il propose, sans rien enregistrer."""
    _store, providers = _ports(call)
    key = call.arg("account", limit=200)
    url, user, password = call.arg("url", limit=1000).strip(), call.arg("username", limit=300).strip(), \
        call.arg("password", limit=300)
    if key:
        _account_mine(call, key)
        a = settings_of(call).agenda().account(key)
        if a is None or a.kind != CALDAV:
            raise Denied(409, "Seul un compte CalDAV s'essaie ainsi.")
        url, user = url or a.url, user or a.username
        if not password and url == a.url and user == a.username:
            password = a.password
    if not url:
        raise Denied(400, "Son adresse, d'abord.", {"url": "valeur requise"})
    await public_only(call, {"url": server_host(url)})
    call.probe()
    provider = providers.of(CALDAV)
    if provider is None:
        raise Denied(503, "CalDAV n'est pas branché sur ce serveur.")
    conn = Connection(key=key or "essai", kind=CALDAV, url=url, username=user, secret=password,
                      internet=not call.me.operator)
    try:
        found = await provider.calendars(conn)
    except AgendaError as exc:
        return {"ok": False, "message": str(exc)[:300] or "Le serveur a refusé.", "calendars": []}
    except Exception as exc:  # noqa: BLE001 — un serveur en panne, quelle qu'elle soit, se dit en mots
        return {"ok": False, "message": f"Le serveur n'a pas répondu : {type(exc).__name__}", "calendars": []}
    return {"ok": True, "message": f"{len(found)} agenda{'s' if len(found) > 1 else ''} trouvé"
                                   f"{'s' if len(found) > 1 else ''}.",
            "calendars": [{"local": split_calendar_key(c.key)[1], "name": c.name, "color": c.color,
                           "writable": c.writable, "primary": c.primary, "selected": c.selected} for c in found]}


def _connectable(call: Call, kind: str) -> tuple[str, Any, Connection]:
    key = call.arg("account", limit=200)
    _account_mine(call, key)
    _store, providers = _ports(call)
    conn = providers.connection(key)
    signin = getattr(providers.of(kind), "signin", None)
    if conn is None or conn.kind != kind or signin is None:
        raise Denied(409, f"Ce compte n'entre pas par {KIND_WORDS[kind]}.")
    return key, signin, conn


async def google_start(call: Call) -> dict[str, Any]:
    """Commencer la connexion Google d'un compte : l'adresse de consentement à ouvrir ; on finit en collant l'adresse
    de la page qui n'a pas pu s'ouvrir (ou son code), ou la redirection revient seule (``direct``)."""
    key, signin, conn = _connectable(call, GOOGLE)
    if settings_of(call).google_application() is None:
        raise Denied(409, NO_GOOGLE_APP)
    origin = call.request.headers.get("origin") or str(call.request.base_url).rstrip("/")
    try:
        got = signin.start(key, who=call.me.handle, origin=origin, hint=conn.address)
    except AgendaError as exc:
        raise Denied(409, str(exc)[:300]) from None
    return {"ok": True, "url": got.url, "until": millis(got.until), "direct": signin.direct()}


async def _connected(call: Call, key: str, kind: str) -> None:
    """Après une connexion : l'adresse du compte (pour y reconnaître ses invitations), puis une synchronisation."""
    settings = settings_of(call)
    _store, providers = _ports(call)
    provider, conn = providers.of(kind), providers.connection(key)
    address = ""
    try:
        address = await provider.whoami(conn) if provider is not None and conn is not None else ""
    except Exception:  # noqa: BLE001 — l'adresse est un surcroît : la connexion, elle, est faite
        address = ""
    if address:
        async with settings.writing:
            cfg = settings.agenda()
            a = cfg.accounts.get(key)
            if a is not None and a.address != address:
                await settings.save_agenda(AgendaConfig(accounts={
                    **cfg.accounts, key: a.model_copy(update={"address": address})}))
                await _rejournal(call)
    await call.act("agenda.synchroniser", form(fixed={"account": key}), part="sync")


async def google_finish(call: Call) -> dict[str, Any]:
    """Finir la connexion Google : l'adresse collée (ou son code)."""
    key, signin, _conn = _connectable(call, GOOGLE)
    text = call.arg("text", limit=4000).strip()
    if not text:
        raise Denied(400, "Colle l'adresse de la page qui n'a pas pu s'ouvrir.", {"text": "valeur requise"})
    try:
        await signin.finish(text, key=key, who=call.me.handle)
    except AgendaError as exc:
        raise Denied(400, str(exc)[:300], {"text": str(exc)[:200]}) from None
    await _connected(call, key, GOOGLE)
    await audit(call.kernel, "moi.agenda_connexion", by=call.me.handle, subject_kind="compte_agenda", subject=key)
    return {"ok": True, "message": "Connecté à Google : l'agenda se synchronise."}


def _page(title: str, text: str, address: str = "") -> HTMLResponse:
    shown = f"<p><code style=\"word-break:break-all\">{escape(address)}</code></p>" if address else ""
    body = (f"<!doctype html><meta charset=utf-8><meta name=viewport content=\"width=device-width\">"
            f"<title>{escape(title)}</title><h1>{escape(title)}</h1><p>{escape(text)}</p>{shown}")
    return HTMLResponse(body, headers={**NO_STORE, "Content-Security-Policy": "default-src 'none'",
                                       "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})


#: le retour de Google dans un navigateur sans session (celui du téléphone, où l'application l'a ouvert)
PASTE_HERE = ("Copie l'adresse de cette page, puis colle-la dans l'application, là où tu as lancé la connexion "
              "(Paramètres › Agendas). Elle seule la finit, pour ton compte.")


def _return_route(api: MeApiBase) -> Route:
    """La redirection directe de Google. Avec une session, le parcours se finit ici, pour qui l'a commencé. Sans (le
    navigateur du téléphone, où l'application a ouvert le consentement), une page en mots dit de copier son adresse et
    de la coller dans l'application : le ``state`` seul ne dit pas qui revient — un parcours commencé par une
    personne et consenti par une autre rattacherait l'agenda Google de la seconde au compte de la première."""
    inner = api.route("/agenda/google/retour", google_return, raw=True)

    async def endpoint(request: Request) -> Response:
        if account_of(request, api.accounts) is None:
            return _page("Encore une étape", PASTE_HERE, str(request.url))
        return await inner.endpoint(request)

    return Route(inner.path, endpoint, methods=["GET"])


async def google_return(call: Call) -> HTMLResponse:
    """La redirection directe de Google (une « Application Web » du serveur) : le parcours se finit ici, pour qui l'a
    commencé ; une page dit ce qui s'est passé (le client l'apprend par le direct)."""
    _store, providers = _ports(call)
    signin = getattr(providers.of(GOOGLE), "signin", None)
    if signin is None:
        raise missing()
    try:
        key = await signin.finish("?" + call.request.url.query, who=call.me.handle)
    except AgendaError as exc:
        return _page("Google Agenda n'est pas connecté", str(exc)[:300])
    await _connected(call, key, GOOGLE)
    await audit(call.kernel, "moi.agenda_connexion", by=call.me.handle, subject_kind="compte_agenda", subject=key)
    return _page("Google Agenda est connecté", "Tu peux fermer cette page : l'agenda se synchronise.")


async def microsoft_start(call: Call) -> dict[str, Any]:
    """Connecter un compte Outlook.com / Microsoft 365 : un code à entrer chez Microsoft ; la fin de l'attente est
    poussée en direct (``agenda``), puis ``…/account/sync`` relit le compte."""
    key, signin, conn = _connectable(call, MICROSOFT)
    try:
        got = await signin.start(key, conn)
    except (OSError, RuntimeError, ValueError) as exc:
        raise Denied(409, f"La connexion n'a pas pu commencer : {exc}"[:300]) from None
    return {"ok": True, "code": got.code, "url": got.url, "until": millis(got.until), "state": got.state,
            "error": got.error}


async def account_sync(call: Call) -> dict[str, Any]:
    """Synchroniser maintenant un de ses comptes (un compte Google ou Microsoft connecté retrouve d'abord son
    adresse)."""
    key = call.arg("account", limit=200)
    _account_mine(call, key)
    if system_person(key):
        return {"ok": True, "message": "Ton agenda du système est toujours à jour.", "deduped": False}
    kind = _kind_of(call, key)
    a = settings_of(call).agenda().accounts.get(key)
    if kind in (GOOGLE, MICROSOFT) and a is not None and not a.address:
        signed = _signin(call, key, kind, _ports(call)[1].connection(key))
        if signed is not None and signed["state"] == SIGNED_IN:
            await _connected(call, key, kind)
            return {"ok": True, "message": "Synchronisation demandée.", "deduped": False}
    return done(await call.act("agenda.synchroniser", form(fixed={"account": key})))


async def account_disconnect(call: Call) -> dict[str, Any]:
    """Déconnecter un compte Google ou Microsoft : sa connexion est retirée (chez Google aussi) et oubliée ; le compte
    reste, « à reconnecter »."""
    settings = settings_of(call)
    key = call.arg("account", limit=200)
    _account_mine(call, key)
    kind = _kind_of(call, key)
    if kind not in (GOOGLE, MICROSOFT):
        raise Denied(409, "Ce compte n'a pas de connexion à retirer : retire le compte.")
    signin = getattr(_ports(call)[1].of(kind), "signin", None)
    if signin is not None:
        if kind == GOOGLE:
            try:
                await signin.revoke(key)
            except (AgendaError, OSError, RuntimeError, ValueError):
                pass  # Google injoignable : la connexion part quand même d'ici
        signin.drop(key)
    await settings.drop_agenda_grant(key)
    await audit(call.kernel, "moi.agenda_deconnexion", by=call.me.handle, subject_kind="compte_agenda", subject=key)
    return {"ok": True, "message": "Déconnecté."}


async def calendar_new(call: Call) -> dict[str, Any]:
    account = call.arg("account", limit=200) or system_account(call.me.person)
    _account_mine(call, account)
    return _with_show(await call.act("agenda.nouvel_agenda", form(fixed={"account": account},
                                                                  name=call.arg("name", limit=200))))


async def calendar_save(call: Call) -> dict[str, Any]:
    """Régler un de ses agendas : son nom (``agenda.renommer``), sa couleur, masqué (Mika ne s'en sert plus), « Mika
    te le rappelle », suivi."""
    settings = settings_of(call)
    key = call.arg("calendar", limit=200)
    _owned(call, key)
    account, local_ = split_calendar_key(key)
    renamed = None
    if "name" in call.data:
        renamed = await call.act("agenda.renommer", form(fixed={"calendar": key}, name=call.arg("name", limit=200)))
        if not renamed.ok or not ({"color", "hidden", "reminder", "followed"} & set(call.data)):
            return done(renamed)
    changes: dict[str, Any] = {}
    if "color" in call.data:
        changes["color"] = call.arg("color", limit=20)
    if "hidden" in call.data:
        changes["hidden"] = call.data["hidden"] is True
    if "reminder" in call.data:
        changes["reminder"] = call.arg("reminder", limit=10)
    if "followed" in call.data:
        raw = call.data["followed"]
        if raw is not None and not isinstance(raw, bool):
            raise Denied(400, "« followed » : vrai, faux ou null.", {"followed": "vrai, faux ou null"})
        changes["followed"] = raw
    if not changes:
        raise Denied(409, "Rien à changer.")
    async with settings.writing:
        cfg = settings.agenda()
        found = cfg.account(account)
        if found is None:
            raise missing()
        try:
            setting = found.setting(local_).model_validate({**found.setting(local_).model_dump(), **changes})
            changed = found.model_copy(update={"calendars": {**found.calendars, local_: setting}})
            await settings.save_agenda(AgendaConfig(accounts={**cfg.accounts, account: changed}))
        except ValidationError as exc:
            raise refused(exc) from None
        await _rejournal(call)
    await audit(call.kernel, "moi.agenda_reglage", by=call.me.handle, subject_kind="agenda", subject=key)
    return {"ok": True, "message": "Agenda réglé."}


# ── son tableau de droits ──


def _rule_json(call: Call, line: AgendaRule) -> dict[str, Any]:
    return {**line.model_dump(mode="json"),
            "words": {"who": who_words(line.who, lambda p: _name(call, p)) if line.who else "—",
                      "canal": canal_words(line.canal), "when": when_words(line.when),
                      "read": "oui" if line.read else "non", "write": WRITE_WORDS[line.write],
                      "respond": WRITE_WORDS[line.respond], "keep": KEEP_WORDS[line.keep]}}


async def rights_get(call: Call) -> dict[str, Any]:
    """Le tableau de droits d'un de ses agendas : réglé (``set``), sinon celui que son propriétaire et ses partages
    donnent."""
    key = call.arg("calendar", limit=200)
    _owned(call, key)
    rights = rights_of(call.frame.env)
    table = table_of(params_of(call.frame), rights, key)
    return {"calendar": key, "set": key in rights.agendas, "lines": [_rule_json(call, x) for x in table.lines],
            "default": _rule_json(call, table.default)}


async def rights_save(call: Call) -> dict[str, Any]:
    """Régler le tableau d'un de ses agendas (``lines`` et ``default``), ou revenir à celui de départ (``reset``)."""
    settings = settings_of(call)
    key = call.arg("calendar", limit=200)
    _owned(call, key)
    if call.flag("reset"):
        table = None
    else:
        lines, default = call.data.get("lines"), call.data.get("default")
        if not isinstance(lines, list) or len(lines) > 30 or not isinstance(default, dict):
            raise Denied(400, "« lines » (30 au plus) et « default » : le tableau.", {"lines": "une liste"})
        strip = ("words",)
        try:
            table = Table[AgendaRule].model_validate({
                "lines": [{k: v for k, v in x.items() if k not in strip} if isinstance(x, dict) else x
                          for x in lines],
                "default": {k: v for k, v in default.items() if k not in strip}})
        except ValidationError as exc:
            raise refused(exc) from None
    try:
        await settings.save_agenda_table(key, table)
    except ValueError as exc:
        raise Denied(400, str(exc)[:300]) from None
    await audit(call.kernel, "moi.agenda_droits", by=call.me.handle, subject_kind="agenda", subject=key)
    return {"ok": True, "message": "Tableau enregistré." if table is not None else "Tableau de départ rétabli."}


# ── pour le direct et les partages ──


def seen_calendars(call: Call) -> tuple[frozenset[str], frozenset[str]]:
    """Ce que le direct lui fait relire (ADR 0308), sans base ni réglages : les agendas qu'on lui partage (tels que les
    paramètres journalisés les disent, encore ouverts) et ses comptes (son compte du système, ceux qui sont à elle) —
    tout agenda d'un compte à elle est à elle, même avant d'être dans les paramètres."""
    p, frame, person = params_of(call.frame), call.frame, call.me.person
    accounts = {system_account(person)} | {a for a in p.kinds if account_level(p, frame, person, a) == OWNED}
    shared = {c for c in p.shares if split_calendar_key(c)[0] not in accounts and level_of(p, frame, person, c)}
    return frozenset(shared), frozenset(accounts)


def is_hers(call: Call, calendar: str) -> bool:
    """Le direct : cet agenda la regarde-t-il (le sien, ou un partage encore ouvert) ?"""
    return bool(level_of(params_of(call.frame), call.frame, call.me.person, calendar))


def calendar_names(store: Any) -> dict[str, str]:
    """Le nom de chaque agenda connu de la base (ce que les partages montrent)."""
    return {c.key: c.name for c in store.calendars()} if store is not None else {}


def holder_person(p: Any, calendar: str) -> str:
    """À qui est un agenda, tel que les paramètres le disent (``personne:<clé>`` ; vide : à toi)."""
    return owner(p, split_calendar_key(calendar)[0])


__all__ = ["HER", "calendar_names", "count", "event_json", "holder_person", "is_hers", "mine", "routes",
           "seen_calendars"]


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    return [r("/agenda/calendars", calendars), r("/agenda/period", period), r("/agenda/event", event),
            r("/agenda/search", search), r("/agenda/invitations", invitations), r("/agenda/proposals", proposals),
            r("/agenda/event/create", create, write=True), r("/agenda/event/edit", edit, write=True),
            r("/agenda/event/delete", delete, write=True), r("/agenda/event/duplicate", duplicate, write=True),
            r("/agenda/event/respond", respond, write=True), r("/agenda/event/remind", remind, write=True),
            r("/agenda/proposal/accept", proposal_accept, write=True),
            r("/agenda/proposal/refuse", proposal_refuse, write=True),
            r("/agenda/proposal/edit", proposal_edit, write=True),
            r("/agenda/accounts", accounts), r("/agenda/account/save", account_save, write=True),
            r("/agenda/account/remove", account_remove, write=True),
            r("/agenda/account/try", account_try, write=True),
            r("/agenda/account/sync", account_sync, write=True),
            r("/agenda/account/disconnect", account_disconnect, write=True),
            r("/agenda/account/google/start", google_start, write=True),
            r("/agenda/account/google/finish", google_finish, write=True),
            _return_route(api),
            r("/agenda/account/microsoft/start", microsoft_start, write=True),
            r("/agenda/calendar/new", calendar_new, write=True),
            r("/agenda/calendar/save", calendar_save, write=True),
            r("/agenda/rights", rights_get), r("/agenda/rights/save", rights_save, write=True)]

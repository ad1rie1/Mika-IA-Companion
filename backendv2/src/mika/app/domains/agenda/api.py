"""Agenda, pour qui est connecté (ADR 0309, lot 4) : ses agendas — les siens, ceux qu'on lui partage, ses abonnements,
« L'agenda de Mika » vu par elle —, une période, un événement, chercher, ses invitations et ce que Mika propose ;
écrire, répondre, décider ; le tableau de droits de ses agendas ; ce qui attend son geste, pour la barre du haut
(``COUNTERS``). Ses comptes d'agenda (Paramètres › Agendas) ont leurs routes dans ``account_settings.py``, qu'il
ajoute aux siennes.

Quels agendas sont à elle et ce qu'elle peut y faire, il le lit dans ``reach.py`` (la base de l'API, des partages et du
direct). Un événement, une proposition sont à l'agenda qu'ils désignent : hors de ses agendas, rien n'existe (404). Un
événement privé d'une autre personne se lit « Occupé ».

Ce qui s'écrit passe par les actions du plugin (``agenda.creer``, ``modifier``, ``supprimer``, ``dupliquer``,
``repondre``, ``rappel``, ``accepter``, ``refuser``, ``ajouter_modifie``), au nom de la personne, auditées
``moi.agenda.<action>`` ; le tableau d'un agenda se règle dans les réglages, audité ``moi.<geste>``. Le contrat :
``docs/protocole-moi.md``, § 13.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any

from pydantic import ValidationError
from starlette.routing import Route

from mika.adapters.agenda.config import COLORS
from mika.app.domains.agenda import account_settings
from mika.app.domains.agenda.her import her_agenda, title_of
from mika.app.domains.agenda.reach import (
    NO_ANSWER_PRIVATE,
    NO_ANSWER_READ_ONLY,
    NO_ANSWER_SHARED,
    NO_ANSWER_TOLD,
    ONLY_OWNER,
    agenda_ports,
    alerts_json,
    answers_reach,
    calendar_json,
    can_use,
    can_write,
    done_with_made,
    mine,
    opened_calendar,
    owned_calendar,
    person_name,
)
from mika.app.domains.agenda.settings import AgendaSettings
from mika.app.me.api import Call, Denied, MeApiBase, done, form, missing, refused
from mika.app.me.common import millis, settings_of
from mika.contracts import runtime as rt
from mika.kernel.clock import local
from mika.plugins.agenda import CREATE, RESPOND, WAITING, AgendaState, params_of
from mika.plugins.agenda.actions import KEEP, handles_of, level_of
from mika.plugins.agenda.rights import table_of
from mika.plugins.agenda.tools import busy_summary
from mika.plugins.agenda.watch import invitation_key
from mika.plugins.agenda.when import midnight
from mika.ports.agenda import (
    ALERT_METHODS,
    ALERTS_MAX,
    DAY_US,
    NEEDS,
    REMINDERS,
    Alert,
    Calendar,
    Event,
    Occurrence,
    Participant,
    instance,
    masked,
    occurrences,
    readable_key,
)
from mika.runtime import decisions
from mika.runtime.operations import audit
from mika.runtime.state import RUNTIME
from mika.vocab.access import (
    KEEP_WORDS,
    SHARE_PREPARE,
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
TOO_LOW = {"lire": "Cet agenda t'est partagé en lecture : tu le lis, sans y écrire.",
           "preparer": "Cet agenda t'est partagé en lecture et préparation : elle peut t'y préparer un ajout, que son "
                       "propriétaire approuve ; tu n'y écris pas toi-même."}


# ── ses agendas ──


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
    cfg = settings.of(AgendaSettings).agenda() if settings is not None else None
    held = mine(call)
    rank = {"mine": 0, "subscriptions": 1, "shared": 2}
    items = [calendar_json(call, cal, level, cfg) for cal, level in held.values()]
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
    lo = midnight(first, tz)
    hi = midnight(last + timedelta(days=1), tz)
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
        why = (NO_ANSWER_SHARED if not can_use(level) else NO_ANSWER_READ_ONLY) if not writable \
            else NO_ANSWER_PRIVATE if hidden_words else "" if answers_reach(call, e.calendar) else NO_ANSWER_TOLD
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
    store, _providers = agenda_ports(call)
    held = mine(call)
    first, last, lo, hi = _bounds(call)
    keys, with_her = _chosen(call, held)
    writable = {k: can_write(call, held[k][0], held[k][1]) for k in keys}
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
    store, _providers = agenda_ports(call)
    raw = call.arg("event", limit=20)
    if not raw.isdigit():
        raise missing()
    e = store.event(int(raw))
    if e is None:
        raise missing()
    cal, level = opened_calendar(call, e.calendar)
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
    out = event_json(call, o, level, can_write(call, cal, level), cal.reminders)
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
    store, _providers = agenda_ports(call)
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
    writable = {k: can_write(call, held[k][0], held[k][1]) for k in keys}
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
    return [k for k, (_cal, level) in held.items() if can_use(level)]


async def invitations(call: Call) -> dict[str, Any]:
    """Les invitations qui attendent sa réponse, dans ses agendas (et ceux qu'on lui partage pour s'en servir), la
    plus proche d'abord, chacune avec la réponse que Mika a préparée (son accord à elle)."""
    store, _providers = agenda_ports(call)
    held = mine(call)
    s: AgendaState = call.frame.state("agenda")
    prepared = {x["invitation"]: x for x in await _proposals(call, held) if x["op"] == RESPOND and x["invitation"]}
    now = call.frame.now
    out = []
    for e in store.invitations(_answerable(held)):
        cal, level = held[e.calendar]
        nxt = occurrences(e, now, now + 400 * DAY_US, limit=1) if e.recurring and not e.original else []
        o = nxt[0] if nxt else Occurrence(e, e.original, e.span)
        item = event_json(call, o, level, can_write(call, cal, level), cal.reminders)
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
    keys = [c.key for c in store.calendars() if can_use(level_of(p, frame, call.me.person, c.key))]
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


def _target(call: Call, need_write: bool = True) -> tuple[Event, str, Calendar, str]:
    e, key, cal, level = _event_of(call)
    if need_write and not can_use(level):
        raise Denied(403, TOO_LOW.get(level, "Cet agenda ne t'est pas ouvert pour cela."))
    return e, key, cal, level


async def create(call: Call) -> dict[str, Any]:
    key = call.arg("calendar", limit=200)
    _cal, level = opened_calendar(call, key)
    if not can_use(level):
        raise Denied(403, TOO_LOW.get(level, "Cet agenda ne t'est pas ouvert pour cela."))
    values = _fields(call, EVENT_FIELDS)
    return done_with_made(await call.act("agenda.creer", form(fixed={"calendar": key}, **values)))


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
        opened_calendar(call, to)
    return done_with_made(await call.act("agenda.dupliquer", form(fixed={"calendar": cal.key, "event": e.id,
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
    _cal, level = opened_calendar(call, key)
    if not can_use(level):
        raise Denied(403, TOO_LOW.get(level, "Cet agenda ne t'est pas ouvert pour cela."))
    values = _fields(call, EVENT_FIELDS)
    conversation = str(_args(call, w.proposal).get("ref") or "")
    return done_with_made(await call.act("agenda.ajouter_modifie", form(
        fixed={"calendar": key, "proposal": w.proposal, "conversation": conversation}, **values)))


# ── son tableau de droits ──


def _rule_json(call: Call, line: AgendaRule) -> dict[str, Any]:
    return {**line.model_dump(mode="json"),
            "words": {"who": who_words(line.who, lambda p: person_name(call, p)) if line.who else "—",
                      "canal": canal_words(line.canal), "when": when_words(line.when),
                      "read": "oui" if line.read else "non", "write": WRITE_WORDS[line.write],
                      "respond": WRITE_WORDS[line.respond], "keep": KEEP_WORDS[line.keep]}}


async def rights_get(call: Call) -> dict[str, Any]:
    """Le tableau de droits d'un de ses agendas : réglé (``set``), sinon celui que son propriétaire et ses partages
    donnent."""
    key = call.arg("calendar", limit=200)
    owned_calendar(call, key)
    rights = rights_of(call.frame.env)
    table = table_of(params_of(call.frame), rights, key)
    return {"calendar": key, "set": key in rights.agendas, "lines": [_rule_json(call, x) for x in table.lines],
            "default": _rule_json(call, table.default)}


async def rights_save(call: Call) -> dict[str, Any]:
    """Régler le tableau d'un de ses agendas (``lines`` et ``default``), ou revenir à celui de départ (``reset``)."""
    settings = settings_of(call)
    key = call.arg("calendar", limit=200)
    owned_calendar(call, key)
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
        await settings.of(AgendaSettings).save_agenda_table(key, table)
    except ValueError as exc:
        raise Denied(400, str(exc)[:300]) from None
    await audit(call.kernel, "moi.agenda_droits", by=call.me.handle, subject_kind="agenda", subject=key)
    return {"ok": True, "message": "Tableau enregistré." if table is not None else "Tableau de départ rétabli."}


#: ce qu'il compte pour la barre du haut
COUNTERS = {"agenda": count}

__all__ = ["COUNTERS", "HER", "count", "event_json", "routes"]


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
            *account_settings.routes(api),
            r("/agenda/rights", rights_get), r("/agenda/rights/save", rights_save, write=True)]

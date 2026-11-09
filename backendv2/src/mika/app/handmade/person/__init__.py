"""Une personne : tout ce qu'elle vit avec elle, sur une page dessinée à la main (ADR 0121).

La fiche d'une personne a un onglet par faculté qui la regarde. « Qu'est-ce qu'elle vit avec cette personne ? »
les traverse : cette page les croise, lus aux faits au même instant, à sa mémoire (par sa seule porte,
``contracts.memory``), au fil et au journal :

- qui elle est pour elle : le lien, ce qu'elle ressent envers elle (et ce que son prompt lui en dit), la chaleur,
  l'attachement, une rancune ;
- leur histoire : six mois de jours échangés, de la couleur de ce qu'elle ressentait en lui écrivant, les heures où
  la personne écrit, son rythme, qui ouvre leurs conversations, les étapes de leur lien ;
- ce qu'elle sait d'elle : les moments de sa vie, ses croyances et leurs témoins, ses souvenirs, ce que la personne
  dit d'elle-même, ce qu'elle lui a caché ;
- ce qu'elle lit d'elle, leurs derniers mots, ce qui reste en suspens, son entourage.

Réservée aux opérateurs, comme la console (secrets compris) ; elle se relit seule (``handmade/live.js``). Une adresse mène à
la page de sa personne.

Son en-tête dit aussi si un de ses moyens de communication est un compte (utilisateur ou opérateur) et mène à sa page
(Réglages › Comptes). Son onglet Comptes réunit en sous-onglets ses boîtes et ses comptes Teams (les listes des
plugins), puis les services qu'elle a branchés et ses partages, lus dans les réglages (``owned``). Son onglet Voyages
(``voyages.py``) montre ses voyages et sert leur GPX ; un opérateur peut y en supprimer un, rien de plus (ADR 0204).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import quote, urlencode

from markupsafe import Markup
from sqlalchemy import or_, select
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from mika.adapters.mcp.config import TRANSPORTS
from mika.adapters.web.accounts import Account, account_of_handle
from mika.adapters.web.app import LoginThrottle
from mika.app.handmade import (
    FORGOTTEN,
    MONTHS,
    PERSON_BASE,
    Look,
    affect_params,
    date_fr,
    emotion,
    excerpt,
    felt_of,
    live_wait,
    read_parts,
    span,
    unit,
)
from mika.app.handmade.blocks import tab as blocks_tab
from mika.app.handmade.exchanges import exchanges
from mika.app.handmade.lists import Roles, drawn, listing
from mika.app.handmade.person.files import files
from mika.app.handmade.person.memoire import memory
from mika.app.handmade.person.senses import phone_tab, position_tab
from mika.app.handmade.person.voyages import GPX as TRIP_GPX
from mika.app.handmade.person.voyages import gpx as trip_gpx
from mika.app.handmade.person.voyages import voyages
from mika.app.handmade.tabs import anchored
from mika.app.moi import OUTBOUND
from mika.app.moi.shares import _mcp_shares as service_shares
from mika.contracts import affect as affect_c
from mika.contracts import attention as attention_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import others as others_c
from mika.contracts import presence as presence_c
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.affect import prose
from mika.faculties.attention.inspect import ORIGIN_FR as THOUGHT_ORIGIN_FR
from mika.faculties.goals.inspect import KIND_FR as GOAL_KIND_FR
from mika.faculties.goals.inspect import STATUS_FR as GOAL_STATUS_FR
from mika.faculties.memory.inspect import ORIGIN_SHORT, SENSITIVITY_FR
from mika.faculties.social.inspect import CLOSENESS_FR
from mika.faculties.social.sections import profile_parts, refs_of
from mika.inspector import render
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import PREFIX, UI, Overview, env, secure
from mika.kernel.clock import DAY, US
from mika.kernel.inspect import Fields, Head, Note, Section, Table, num_fr, pct_fr
from mika.plugins import email as email_p
from mika.plugins import teams as teams_p
from mika.plugins.teams.console import ACCOUNT as TEAMS_ACCOUNT
from mika.plugins.teams.console import SECTION as TEAMS_SECTION
from mika.plugins.teams.console import WHOSE as TEAMS_WHOSE
from mika.plugins.teams.console import YOURS
from mika.runtime.boundary import Failed, call
from mika.vocab import affect as A
from mika.vocab import privacy
from mika.vocab.access import PERSON, SHARES
from mika.vocab.knowledge import knowns
from mika.vocab.people import is_identifiable

#: la page, et le fragment qu'elle relit
BASE = PERSON_BASE
FRAGMENT = f"{PREFIX}/_personne"
#: la page d'un compte (Réglages › Comptes, ``?compte=<id>``)
ACCOUNTS = f"{PREFIX}/reglages/comptes"
#: leur histoire : tant de semaines de jours échangés (lundi en tête) ; les messages relus au plus
WEEKS = 26
HISTORY_ROWS = 40_000
#: au plus tant d'éléments par liste
SHOWN = 6
THREAD_SHOWN = 10
#: un moment passé de sa vie se dit encore tant de jours après
PAST_MOMENT_DAYS = 21
#: le calendrier : une case, son pas, la marge des jours et des mois (en pixels)
CELL, PITCH, DAY_GUTTER, MONTH_GUTTER = 13, 16, 30, 18
#: les heures : une barre, son pas, la hauteur
HOUR_BAR, HOUR_PITCH, HOURS_H = 11, 14, 54

#: les liens qu'on lui a racontés (``memory.Relation``), et ce qu'ils sont devenus
RELATION_FR = {"friend": "amitié", "family": "famille", "partner": "en couple", "colleague": "travail",
               "acquaintance": "connaissance", "hostile": "en froid"}
RELATION_STATUS_FR = {"ended": "fini", "uncertain": "incertain"}
WEEKDAY_SHORT = ("lun", "", "mer", "", "ven", "", "")
#: devant un nom qui commence par une voyelle, « de » et « que » s'élident (« d'Adrien », « qu'Adrien »)
VOWELS = frozenset("aeiouyàâäéèêëîïôöùûüÿœæ")


def elided(word: str, name: str) -> str:
    """« de Béa », « d'Adrien » ; « que Béa », « qu'Adrien »."""
    return f"{word[:-1]}'{name}" if name[:1].lower() in VOWELS else f"{word} {name}"


@dataclass(frozen=True, slots=True)
class Who:
    """La personne de la page : sa clé, son nom, ses adresses, et toutes les clés sous lesquelles sa mémoire a pu la
    noter (ses adresses, les noms dont on lui a parlé et qui la désignent)."""

    person: str
    name: str
    handles: tuple[str, ...]
    keys: tuple[str, ...]


def who_of(look: Look, person: str) -> Who:
    head = look.ui.inspection.head("person", person)
    aliases = head.aliases if isinstance(head, Head) else ()
    handles = tuple(look.frame.get(identity_c.HANDLES(person)) or ())
    return Who(person, look.name(person), handles, tuple(dict.fromkeys((person, *handles, *aliases))))


def _store(look: Look) -> Any:
    return look.ui.kernel.ports["store"]


def _query(look: Look, query: Any) -> list[Any]:
    got = call(_store(look).query_mind, query, label="lecture")
    return [] if isinstance(got, Failed) else list(got)


def _known(look: Look, where: Sequence[Any], limit: int) -> list[Any]:
    """Ce qu'elle sait, par sa seule porte (``contracts.memory.KNOWLEDGE``), du plus récent au plus ancien."""
    v = memory_c.KNOWLEDGE
    rows = _query(look, memory_c.select_known().where(*where).order_by(v.c.id.desc()).limit(limit))
    return knowns(rows, memory_c.KNOWN_COLUMNS)


# ── l'en-tête de sa fiche ──


def heading(look: Look, who: Who) -> dict[str, Any]:
    """Le haut de sa fiche, sur tous ses onglets : son nom, ce qu'elle est pour elle, depuis quand elles se
    parlent, par où, et ce qu'elle ferait envers elle maintenant."""
    frame, person = look.frame, who.person
    closeness = frame.get(social_c.CLOSENESS(person))
    contact = frame.get(social_c.CONTACT(person))
    stance = frame.get(affect_c.STANCE(person))
    view = frame.get(identity_c.IDENTITY(person))
    felt = felt_of(stance)
    facts = []
    if contact.first_in:
        facts.append(f"premier message le {look.date(contact.first_in)}")
    if contact.days:
        facts.append(f"{contact.days} jour{'s' if contact.days > 1 else ''} de contact")
    if contact.inbound:
        facts.append(f"{contact.inbound} message{'s' if contact.inbound > 1 else ''} reçu{'s' if contact.inbound > 1 else ''}")
    if contact.last_in:
        facts.append(f"le dernier {look.ago(contact.last_in)}")
    count = len(who.handles)
    how = "vérifiée" if view.authenticated else f"certitude {pct_fr(view.certainty)}"
    account = account_of(look, who)
    return {
        "name": who.name, "initial": (who.name[:1] or "?").upper(),
        "emotion": felt["emotion"] if felt else "neutral",
        "owner": bool(frame.get(identity_c.IS_OWNER(person))),
        "closeness": CLOSENESS_FR.get(closeness, closeness), "close": closeness in (social_c.FRIEND, social_c.CLOSE),
        "online": bool(set(frame.get(presence_c.PRESENT) or ()) & set(who.handles)),
        "composing": any(frame.get(presence_c.COMPOSING(h)) for h in who.handles),
        "facts": facts,
        "where": f"{count} moyen{'s' if count > 1 else ''} de communication" + (f" · {view.channel}, {how}" if view.channel else ""),
        "where_href": fiche_url("person", person, "adresses"),
        "toward": f"{PREFIX}/decisions/envers?personne={quote(person, safe='')}",
        # un de ses moyens de communication est un compte : lequel, et sa page (Réglages › Comptes)
        "account": {"kind": "compte opérateur" if account.operator else "compte utilisateur",
                    "off": not account.active, "href": f"{ACCOUNTS}?compte={account.id}"} if account else None,
    }


def account_of(look: Look, who: Who) -> Account | None:
    """Son compte : un de ses moyens de communication (``user_<n>``) — l'actif d'abord, s'il y en a plusieurs."""
    ids = {i for i in (account_of_handle(h) for h in (who.person, *who.handles)) if i is not None}
    found = [a for a in look.ui.deps.accounts.all() if a.id in ids] if ids else []
    return next((a for a in found if a.active), found[0] if found else None)


# ── qui elle est pour elle ──


def portrait(look: Look, who: Who) -> dict[str, Any]:
    """Ce qu'elle ressent envers elle (et ce que son prompt lui en dit), ce que leur lien a installé."""
    frame, now, person = look.frame, look.now, who.person
    stance = frame.get(affect_c.STANCE(person))
    voice = prose.stance(stance, affect_params(frame), name=who.name, now=now)
    regard = stance.regard
    hard = frame.get(memory_c.HARD_TIMES(person))
    return {
        "felt": felt_of(stance), "voice": [line for line in voice.split("\n") if line.strip()],
        "regard": num_fr(regard, 2, signed=True), "regard_w": unit(abs(regard)),
        "regard_tone": "warm" if regard > 0.05 else "cold" if regard < -0.05 else "",
        "bond": pct_fr(stance.bond), "bond_w": unit(stance.bond),
        "hostility": pct_fr(stance.hostility) if stance.hostility > 0.05 else "", "hostility_w": unit(stance.hostility),
        "withdrawn": look.hm(stance.withdrawn_until) if stance.withdrawn_until > now else "",
        "apologized": look.ago(stance.apologized_at) if stance.apologized_at else "",
        "hard": look.date(hard) if hard else "",
    }


# ── leur histoire ──


def _history(look: Look, who: Who, since: int) -> list[Any]:
    t = transcript_c.thread_table()
    return _query(look, select(t.c.at, t.c.role, t.c.emotion, t.c.emotion_intensity)
                  .where(t.c.person.in_(sorted({who.person, *who.handles})), t.c.at >= since)
                  .order_by(t.c.at).limit(HISTORY_ROWS))


def _level(count: int) -> int:
    return 0 if count == 0 else 1 if count <= 3 else 2 if count <= 10 else 3 if count <= 30 else 4


def story(look: Look, who: Who) -> dict[str, Any]:
    frame, now, person = look.frame, look.now, who.person
    today = frame.local(now).date()
    first_day = today - timedelta(days=today.weekday() + 7 * (WEEKS - 1))  # un lundi, il y a WEEKS semaines
    start = frame.local(now).replace(year=first_day.year, month=first_day.month, day=first_day.day, hour=0,
                                     minute=0, second=0, microsecond=0)
    rows = _history(look, who, int(start.timestamp() * US))
    days: dict[Any, dict[str, Any]] = defaultdict(lambda: {"in": 0, "out": 0, "felt": Counter()})
    hours = [0] * 24
    for at, role, name, intensity in rows:
        local = frame.local(int(at))
        day = days[local.date()]
        if role == "user":
            day["in"] += 1
            hours[local.hour] += 1
        else:
            day["out"] += 1
            if name:
                day["felt"][emotion(name)] += float(intensity or 0.3)
    cells = []
    months = []
    for w in range(WEEKS):
        for d in range(7):
            date = first_day + timedelta(days=7 * w + d)
            if date > today:
                continue
            got = days.get(date)
            count = (got["in"] + got["out"]) if got else 0
            felt = got["felt"].most_common(1)[0][0] if got and got["felt"] else None
            title = date_fr(date)
            if count:
                title += f" — {got['in']} de sa part, {got['out']} d'elle"
                title += f" · elle : {A.FR[felt]}" if felt is not None else ""
            cells.append({"x": DAY_GUTTER + w * PITCH, "y": MONTH_GUTTER + d * PITCH, "level": _level(count),
                          "emotion": felt.value if felt is not None else "", "today": date == today, "title": title})
            # le mois au-dessus de sa première semaine, s'il a la place (deux colonnes au moins après le précédent)
            if d == 0 and (date.day <= 7 or w == 0) and (not months or w - months[-1]["w"] >= 3):
                months.append({"x": DAY_GUTTER + w * PITCH, "w": w, "label": MONTHS[date.month - 1]})
    contact = frame.get(social_c.CONTACT(person))
    hours_known = frame.get(others_c.HOURS(person))
    top = max(hours) or 1
    bars = [{"x": h * HOUR_PITCH, "h": round(max(1.5 if n else 0, n / top * (HOURS_H - 14)), 1),
             "y": round(HOURS_H - 14 - max(1.5 if n else 0, n / top * (HOURS_H - 14)), 1),
             "usual": bool(hours_known.learned and hours_known.active[h]), "title": f"{h} h — {n} message{'s' if n > 1 else ''}"}
            for h, n in enumerate(hours)]
    rhythm = []
    if contact.measured and contact.usual_days:
        rhythm.append({"text": f"écrit en général tous les {num_fr(contact.usual_days, 1)} jours", "tone": ""})
    if contact.last_in:
        silence = f"dernier message {look.ago(contact.last_in)}"
        if contact.silence_ratio >= 1.5:
            rhythm.append({"text": f"{silence} — plus long que d'habitude", "tone": "warn"})
        else:
            rhythm.append({"text": silence, "tone": ""})
    starts = contact.her_starts + contact.their_starts
    if starts == 1:
        opened = "c'est elle qui a ouvert leur dernière conversation" if contact.her_starts else \
            f"leur dernière conversation, c'est {who.name} qui l'a ouverte"
        rhythm.append({"text": opened, "tone": ""})
    elif starts:
        rhythm.append({"text": f"elle a ouvert {contact.her_starts} de leurs {starts} dernières conversations",
                       "tone": "warn" if contact.one_sided else ""})
    delay = frame.get(others_c.REPLY_DELAY((person, privacy.WEB)))
    if delay.samples and delay.median_us:
        rhythm.append({"text": f"lui répond en général en {span(delay.median_us)}", "tone": ""})
    if hours_known.learned and hours_known.usual is not None:
        rhythm.append({"text": f"écrit le plus souvent vers {hours_known.usual} h", "tone": ""})
    steps = []
    seen: set[int] = set()
    for key in (person, *who.handles):
        got = call(lambda k=key: look.events([social_c.BOND_SHIFTED, social_c.BOND_NOTED], 20, where=("person", k)),
                   label="journal")
        for e in [] if isinstance(got, Failed) else got:
            if e.seq in seen:
                continue
            seen.add(e.seq)
            if e.type.name == social_c.BOND_SHIFTED.name:
                text = f"de « {CLOSENESS_FR.get(e.data.before, e.data.before)} » à « {CLOSENESS_FR.get(e.data.after, e.data.after)} »"
            else:
                text = f"relevé : « {CLOSENESS_FR.get(e.data.level, e.data.level)} »"
            steps.append({"at": e.at, "date": look.date(e.at), "text": text})
    steps.sort(key=lambda x: x["at"], reverse=True)
    return {
        "cells": cells, "months": months, "w": DAY_GUTTER + WEEKS * PITCH, "h": MONTH_GUTTER + 7 * PITCH,
        "cell": CELL, "weekdays": [{"y": MONTH_GUTTER + d * PITCH + CELL - 2, "label": label}
                                   for d, label in enumerate(WEEKDAY_SHORT) if label],
        "active_days": sum(1 for d in days.values() if d["in"] or d["out"]), "weeks": WEEKS,
        "hours": bars, "hours_w": 24 * HOUR_PITCH, "hours_h": HOURS_H, "hour_bar": HOUR_BAR,
        "hour_marks": [{"x": h * HOUR_PITCH + HOUR_BAR / 2, "label": f"{h} h"} for h in (0, 6, 12, 18)],
        "hours_any": any(hours), "hours_learned": hours_known.learned, "rhythm": rhythm, "steps": steps[:SHOWN],
    }


# ── ce qu'elle sait d'elle ──


def _item(look: Look, k: Any) -> dict[str, Any]:
    tag, tone = ("secret", "danger") if k.secret else (SENSITIVITY_FR.get(k.sensitivity, ""), "")
    told = [p for p in k.told_by if p]
    return {"text": excerpt(k.text, 260), "tag": tag, "tone": tone, "when": look.ago(k.born_at),
            "origin": ORIGIN_SHORT.get(k.origin or "", ""), "told_by": look.who(told),
            "confidence": pct_fr(k.confidence) if k.confidence is not None else "",
            "confidence_w": unit(k.confidence or 0.0)}


def knows(look: Look, who: Who) -> dict[str, Any]:
    frame, now, person = look.frame, look.now, who.person
    v = memory_c.KNOWLEDGE
    about = memory_c.concerning(v, who.keys)
    beliefs = _known(look, (v.c.kind == memory_c.BELIEF, v.c.status == "active", about), SHOWN)
    souvenirs = _known(look, (v.c.kind == memory_c.SOUVENIR, v.c.status == "active", about,
                              or_(v.c.origin.is_(None), v.c.origin != memory_c.LIED)), SHOWN)
    lies = _known(look, (v.c.kind == memory_c.SOUVENIR, v.c.origin == memory_c.LIED, about), SHOWN)
    moments = []
    for ev in frame.get(memory_c.LIFE_EVENTS(person)) or ():
        if ev.ended_at:
            continue
        upcoming = ev.when >= now
        if not (ev.ongoing or upcoming or now - ev.when <= PAST_MOMENT_DAYS * DAY):
            continue
        moments.append((0 if ev.ongoing else 1 if upcoming else 2, abs(ev.when - now), ev))
    moments.sort(key=lambda m: (m[0], m[1]))
    shown = [ev for _o, _d, ev in moments[:SHOWN]]
    profile = frame.state("social").profiles.get(person)
    texts = look.texts([ev.text_ref for ev in shown] + (refs_of(profile) if profile is not None else []))
    life = []
    for ev in shown:
        when = f"depuis le {look.date(ev.when)}" if ev.ongoing else look.day(ev.when, all_day=ev.all_day)
        felt = [{"emotion": emotion(e).value, "word": A.NOUN[emotion(e)]} for e, x in ev.felt if x >= 0.3][:2]
        life.append({"text": excerpt(texts.get(ev.text_ref), 200), "when": when, "ongoing": ev.ongoing,
                     "past": not ev.ongoing and ev.when < now, "secret": ev.secret,
                     "important": ev.importance >= memory_c.IMPORTANT_MOMENT, "festive": ev.festive, "felt": felt})
    said_of_self = None
    if profile is not None and not getattr(profile, "masked", False):
        summary, _tone, interests, sensitive = profile_parts(profile, texts)
        if summary or interests or sensitive:
            said_of_self = {"summary": excerpt(summary, 400) if summary else "",
                            "interests": list(interests)[:10], "sensitive": list(sensitive)[:8]}
    return {"beliefs": [_item(look, k) for k in beliefs], "souvenirs": [_item(look, k) for k in souvenirs],
            "lies": [_item(look, k) for k in lies], "life": life, "self": said_of_self}


# ── ce qu'elle lit d'elle ──


def _tone(valence: float, arousal: float) -> str:
    feel = "chaleureux" if valence > 0.25 else "plutôt léger" if valence > 0.08 else \
        "sombre" if valence < -0.25 else "un peu lourd" if valence < -0.08 else "neutre"
    pace = "vif" if arousal > 0.35 else "posé" if arousal < -0.1 else ""
    return f"{feel}{', ' + pace if pace else ''}"


def reads(look: Look, who: Who) -> dict[str, Any]:
    mind = look.frame.get(others_c.MIND(who.person))
    if not mind.observed:
        return {"observed": 0}
    shift = ""
    if mind.deviation > 0.15:
        shift = "plus léger que d'habitude"
    elif mind.deviation < -0.15:
        shift = "plus lourd que d'habitude"
    last = [{"emotion": emotion(e).value, "word": A.NOUN[emotion(e)], "pct": pct_fr(x)}
            for e, x in sorted(mind.last_felt, key=lambda f: -f[1]) if x >= 0.15][:4]
    return {"observed": mind.observed, "usual": _tone(mind.usual_valence, mind.usual_arousal),
            "now": _tone(mind.current_valence, mind.current_arousal), "shift": shift,
            "confidence": pct_fr(mind.confidence), "confidence_w": unit(mind.confidence),
            "last": last, "last_at": look.ago(mind.last_at) if mind.last_at else ""}


# ── leurs derniers mots ──


def thread(look: Look, who: Who) -> dict[str, Any]:
    t = transcript_c.thread_table()
    rows = _query(look, select(t.c.id, t.c.at, t.c.role, t.c.text, t.c.emotion, t.c.room, t.c.unanswered)
                  .where(t.c.person.in_(sorted({who.person, *who.handles})))
                  .order_by(t.c.id.desc()).limit(THREAD_SHOWN))
    today = look.frame.local(look.now).date()
    out = []
    for n, at, role, text, name, room, unanswered in reversed(rows):
        local = look.frame.local(int(at))
        e = emotion(name) if name else None
        out.append({"mine": role == "assistant", "text": excerpt(text, 320) if text else FORGOTTEN,
                    "when": look.hm(int(at)) if local.date() == today else f"{look.date(int(at))}, {look.hm(int(at))}",
                    "emotion": e.value if e is not None else "", "word": A.FR[e] if e is not None else "",
                    "room": bool(room), "unanswered": bool(unanswered and role == "user"),
                    "why": f"{PREFIX}/parole/{n}" if role == "assistant" else ""})
    return {"messages": out, "all": fiche_url("person", who.person, "echanges")}


# ── ce qui reste en suspens ──


def pending(look: Look, who: Who) -> dict[str, Any]:
    frame, now, person = look.frame, look.now, who.person
    keys = set(who.keys)
    out: list[dict[str, Any]] = []
    waiting = frame.get(attention_c.AWAITING(person))
    if waiting.unanswered and waiting.last_out and now - waiting.last_out >= live_wait(frame):
        many = f" ({waiting.initiatives} messages d'elle)" if waiting.initiatives > 1 else ""
        out.append({"kind": "attente", "text": f"Elle attend sa réponse depuis {span(now - waiting.last_out)}{many}",
                    "tone": "warn"})
    elif waiting.unanswered and waiting.last_out:
        out.append({"kind": "conversation", "text": "Une conversation en cours", "tone": "ok"})
    promises = list(frame.get(memory_c.PROMISES_TO(person)) or ())
    if promises:
        v = memory_c.KNOWLEDGE
        said_by_id = {k.id: k.text for k in _known(look, (v.c.id.in_([p.id for p in promises]),), len(promises))}
        work = look.texts([p.text_ref for p in promises if p.text_ref])
        for p in sorted(promises, key=lambda p: p.due or 2**62)[:SHOWN]:
            due = f" — {look.day(p.due, all_day=p.all_day)}" if p.due else ""
            late = bool(p.due and p.due < now)
            out.append({"kind": "promesse", "text": excerpt(said_by_id.get(p.id) or work.get(p.text_ref), 180) + due,
                        "tone": "danger" if late else ""})
    thoughts = [t for t in frame.get(attention_c.THOUGHTS) or () if keys & set(t.about)][:SHOWN]
    texts = look.texts([t.text_ref for t in thoughts])
    for t in thoughts:
        e = emotion(t.emotion)
        out.append({"kind": "pensée", "text": excerpt(texts.get(t.text_ref), 180), "emotion": e.value,
                    "note": f"{A.FR[e]} · {THOUGHT_ORIGIN_FR.get(t.origin, '')}".strip(" ·"), "tone": "thought"})
    goals = [g for g in frame.get(goals_c.LIVE) or () if g.owner in keys or keys & set(g.about)][:SHOWN]
    titles = look.texts([g.title_ref for g in goals])
    for g in goals:
        kind = "rêverie" if g.musing else GOAL_KIND_FR.get(g.kind, g.kind)
        out.append({"kind": kind, "text": excerpt(titles.get(g.title_ref), 140),
                    "note": GOAL_STATUS_FR.get(g.status, g.status), "href": fiche_url("goal", str(g.id)), "tone": ""})
    check_in = frame.get(others_c.CHECK_IN_AT(person))
    if check_in > now:
        out.append({"kind": "nouvelles", "text": f"Elle prendra de ses nouvelles {look.day(check_in)}", "tone": ""})
    return {"items": out}


# ── son entourage ──


def circle(look: Look, who: Who) -> dict[str, Any]:
    frame, person = look.frame, who.person
    relations = frame.state("social").relations.get(person) or {}
    kinds: dict[str, list[str]] = defaultdict(list)
    for rel in relations.values():
        other = frame.get(identity_c.PERSON(rel.other)) or rel.other
        word = RELATION_FR.get(rel.kind, rel.kind)
        if rel.status in RELATION_STATUS_FR:
            word += f" ({RELATION_STATUS_FR[rel.status]})"
        if rel.secret:
            word += " · secret"
        if word and word not in kinds[other]:
            kinds[other].append(word)
    people = []
    for other in dict.fromkeys((*(frame.get(social_c.TIES(person)) or ()), *kinds)):
        if other == person:
            continue
        closeness = frame.get(social_c.CLOSENESS(other)) if is_identifiable(other) else ""
        people.append({"name": look.name(other), "href": look.href(other), "kinds": kinds.get(other, []),
                       "closeness": CLOSENESS_FR.get(closeness, "") if closeness else ""})
    return {"people": people[:12], "more": max(0, len(people) - 12)}


# ── ses comptes : ses boîtes, ses comptes Teams, ses services, ses partages ──

#: les sous-onglets de Comptes que les plugins remplissent, dans l'ordre où la console passe leurs sections (l'onglet
#: qui porte l'autre d'abord) : leur onglet (l'ancre où mène son adresse), leur nom, la forme de leurs listes
OWNED = (("boites", "Courrier", Roles(title="boîte", badges=("état", "elle y écrit"), tiles=True)),
         ("teams", "Teams", Roles(title="compte", badges=("état",), tiles=True)))
#: ce qui se partage (ADR 0188), et à quel niveau, tels que la fiche les nomme
SHARED_KINDS = {"mail": "boîte", "teams": "compte Teams", "mcp": "service"}
LEVEL_FR = {level: label.lower() for level, label in SHARES}


def _with(look: Look, who: str, level: str) -> dict[str, str]:
    """Une personne d'un partage (``personne:<clé>``) et son niveau, pour la fiche."""
    person = who.removeprefix(PERSON)
    return {"name": look.name(person), "person_href": look.href(person), "level": LEVEL_FR.get(level, level)}


def services(look: Look, who: Who) -> list[dict[str, Any]]:
    """Les services MCP qu'elle a branchés depuis son espace (ADR 0192 : ``McpServer.owner``), lus dans les réglages :
    chacun, à quoi il sert, s'il est actif, avec qui elle le partage."""
    settings = look.ui.deps.settings
    if settings is None:
        return []
    mine = PERSON + who.person
    return [{"name": name, "href": fiche_url("serveur", name), "purpose": excerpt(spec.purpose, 200),
             "on": spec.enabled, "where": dict(TRANSPORTS).get(spec.transport, spec.transport),
             "shared": [_with(look, p, level) for p, level in sorted(service_shares(spec, mine).items())]}
            for name, spec in sorted(settings.mcp().servers.items()) if spec.owner == mine]


def shares(look: Look, who: Who) -> dict[str, list[dict[str, Any]]]:
    """Ce qu'elle partage et ce qu'on lui partage (ADR 0188) : ses boîtes et ses comptes Teams (les partages
    journalisés, ``EmailParams.shares``, ``TeamsParams.shares`` ; une boîte « à toi » est à chacune de ses
    propriétaires), ses services (une ligne d'accès à une seule personne, ``app/moi/shares.py``). Lecture seule."""
    frame, mine = look.frame, PERSON + who.person
    owner = bool(frame.get(identity_c.IS_OWNER(who.person)))
    given: list[dict[str, Any]] = []
    received: list[dict[str, Any]] = []

    def teams_href(key: str, whose: str) -> str:
        return f"{PREFIX}/{TEAMS_SECTION}/extension?" + urlencode({TEAMS_WHOSE: whose or YOURS, TEAMS_ACCOUNT: key})

    for kind, of, href, holder in (
            ("mail", email_p.params_of, lambda key, _whose: fiche_url("compte", key), email_p.approver_name),
            ("teams", teams_p.params_of, teams_href, teams_p.writer_of)):
        port = look.ui.kernel.ports.get(kind)
        if port is None:
            continue
        p = of(frame)
        for a in port.accounts():
            whose, shared = p.owners.get(a.key, ""), p.shares.get(a.key, {})
            resource = {"kind": SHARED_KINDS[kind], "title": a.name, "href": href(a.key, whose)}
            if (not whose and owner) or whose == mine:
                given += [{**resource, **_with(look, x, level)} for x, level in sorted(shared.items())]
            elif level := shared.get(mine, ""):
                received.append({**resource, "owner": holder(frame, a.key), "level": LEVEL_FR.get(level, level)})
    settings = look.ui.deps.settings
    for name, spec in sorted(settings.mcp().servers.items()) if settings is not None else ():
        resource = {"kind": SHARED_KINDS["mcp"], "title": name, "href": fiche_url("serveur", name)}
        if spec.owner == mine:
            given += [{**resource, **_with(look, x, level)} for x, level in sorted(service_shares(spec, mine).items())]
        elif spec.owner and (level := service_shares(spec, spec.owner).get(mine, "")):
            received.append({**resource, "owner": look.name(spec.owner.removeprefix(PERSON)),
                             "level": LEVEL_FR.get(level, level)})
    return {"given": given, "received": received}


def owned(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup | None:
    """L'onglet Comptes, dessiné : en sous-onglets, ses boîtes et ses comptes Teams (les listes des plugins, réunies
    par ``joined``, ADR 0185, 0186), puis ses services et ses partages, lus dans les réglages (ADR 0188, 0192) — ce
    que la console voit de tous, en lecture seule (chacun les règle dans son espace)."""
    sections = list(blocks) if blocks and all(isinstance(b, Section) for b in blocks) \
        else [Section(OWNED[0][1], tuple(blocks))]
    shown, name, counter = ui.env(), ui.names.name_of(key), [0]
    panes = []
    for (anchor, label, roles), section in zip(OWNED, sections, strict=False):
        lists = [{**anchored(listing(t, shown, query, name, roles, counter), anchor), "kind": anchor}
                 for t in section.items if isinstance(t, Table)]
        panes.append({"id": anchor, "label": label, "count": sum(x["count"] or 0 for x in lists), "lists": lists,
                      "facts": [render.block(b, shown, query) for b in section.items if isinstance(b, Fields)],
                      "notes": [{"text": b.text, "title": b.title, "tone": b.tone} for b in section.items
                                if isinstance(b, Note)]})
    look = Look.of(ui, DAY)
    who = who_of(look, key)
    plugged, shared = services(look, who), shares(look, who)
    panes += [{"id": "services", "label": "Services", "count": len(plugged), "services": plugged},
              {"id": "partages", "label": "Partages", "count": len(shared["given"]) + len(shared["received"]),
               "shares": shared}]
    return Markup(env.get_template("handmade/person/tabs/comptes.html").render(
        panes=panes, name=who.name, of=elided("de", who.name), that=elided("que", who.name)))


# ── la page ──

#: les onglets des facultés dessinés : leur nom → ce qui les dessine (les données restent celles de la faculté)
TABS: dict[str, Callable[[UI, str, Sequence[Any], Mapping[str, str]], Any]] = {
    "echanges": exchanges,
    "memoire": memory,
    "adresses": drawn(Roles(title="moyen de communication", badges=("confiance",), tiles=True), "adresses"),
    # ce qu'elle a envoyé et ce qu'on lui a envoyé, en deux sous-onglets (``joined``), « Retirer » sur chacun
    # (ADR 0205) ; les pièces seules, sans l'autre
    "fichiers": files,
    "pieces": drawn(Roles(title="nom", badges=("sorte", "état"), body=("ce qu'elle y a lu",), time="reçue",
                          tiles=True), "pieces"),
    "buts": drawn(Roles(title="titre", badges=("sorte", "statut"), time="ouvert"), "buts"),
    "projets": drawn(Roles(title="projet", badges=("mode", "état"), time="ouvert"), "projets"),
    # ses comptes : les boîtes aux lettres et les comptes Teams qui sont à elle (ADR 0185, 0186), réunis (``joined``),
    # puis ses services et ses partages (ADR 0188, 0192) ; sans boîte, Teams reste un onglet à lui
    "boites": owned,
    "teams": drawn(OWNED[1][2], "teams"),
    # ce que son téléphone lui a montré, où il dit qu'elle est (seulement s'il en a dit quelque chose)
    "telephone": phone_tab, "position": position_tab,
    # ses voyages (seulement si elle en a) : leurs arrêts jour par jour, leur GPX, « Supprimer » (ADR 0204)
    "voyages": voyages,
    # le détail de ce que la vue d'ensemble résume : bloc par bloc, ses formulaires laissés à la console
    "synthese": blocks_tab, "lien": blocks_tab, "devine": blocks_tab, "affect": blocks_tab, "pensees_personne": blocks_tab,
}

#: les onglets dessinés qui posent aussi les formulaires de la console (``Forms``) : le détail bloc par bloc (« fixer la
#: proximité »), les voyages (« Supprimer ») et les fichiers (« Retirer ») ; les autres n'en ont pas
FORMED = (blocks_tab, voyages, files)

#: chaque partie de la page, lue à part
PARTS: tuple[tuple[str, Callable[[Look, Who], dict[str, Any]]], ...] = (
    ("portrait", portrait), ("story", story), ("knows", knows), ("reads", reads), ("thread", thread),
    ("pending", pending), ("circle", circle))


class PersonOverview(Overview):
    """La vue d'ensemble de la fiche d'une personne (``/inspecteur/fiche/person/<clé>`` : son premier onglet, ouvert
    par défaut ; le détail de chaque faculté reste dans les suivants), et son fragment qui se relit seul.
    L'adresse ``/inspecteur/personne/<clé>`` mène à la fiche."""

    slug = "ensemble"
    title = "Vue d'ensemble"
    styles = ("handmade/person.css", "handmade/senses.css")
    scripts = ("handmade/live.js",)
    #: ce que la vue d'ensemble résume (son ressenti, leur lien, ce qu'elle lit d'elle, ses pensées, et la mécanique
    #: de ce qu'elle peut lui dire) : le détail reste à un clic, au bout de la barre
    folded = ("synthese", "lien", "devine", "affect", "pensees_personne")
    #: les onglets des facultés qu'elle dessine (``TABS``)
    tabs = tuple(TABS)
    #: Fichiers porte aussi les pièces reçues : un onglet pour ce qui va et vient entre elles (ADR 0179) ; Comptes, ses
    #: boîtes aux lettres et ses comptes Teams (ADR 0185, 0186 — sans boîte, Teams reste un onglet à lui)
    joined = {"fichiers": ("pieces",), "boites": ("teams",)}

    def __init__(self) -> None:
        #: la console, posée quand ses routes le sont (la fiche, elle, passe la sienne à ``render``)
        self.ui: UI | None = None

    @staticmethod
    def snapshot(ui: UI, person: str) -> dict[str, Any]:
        look = Look.of(ui, DAY)
        who = who_of(look, person)
        parts = tuple((key, lambda lk, fn=fn: fn(lk, who)) for key, fn in PARTS)
        return {"name": who.name, "stamp": look.frame.local(look.now).strftime("%H:%M:%S"),
                "fiche": fiche_url("person", who.person), "of": elided("de", who.name), "that": elided("que", who.name),
                **read_parts(look, parts, f"une personne · {person}")}

    @staticmethod
    def known(ui: UI, person: str) -> bool:
        """Une personne qu'elle connaît : une adresse à elle, ou une identité déjà vue."""
        frame = ui.kernel.mind.frame()
        return is_identifiable(person) and bool(frame.get(identity_c.HANDLES(person))
                                                or frame.get(identity_c.IDENTITY(person)).known)

    def render(self, ui: UI, key: str) -> Markup | None:
        if not self.known(ui, key):
            return None
        # un gabarit de la console (échappement automatique) : son rendu est sûr à insérer tel quel
        return Markup(env.get_template("handmade/person/overview.html").render(
            now=self.snapshot(ui, key), fragment=f"{FRAGMENT}/{quote(key, safe='')}"))

    def head(self, ui: UI, key: str) -> Markup | None:
        if not self.known(ui, key):
            return None
        look = Look.of(ui, DAY)
        return Markup(env.get_template("handmade/person/head.html").render(h=heading(look, who_of(look, key))))

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Sequence[Any], query: Mapping[str, str],
                   forms: Mapping[str, Any] | None = None) -> Any:
        draw = TABS.get(tab)
        if draw is None or not self.known(ui, key):
            return None
        return draw(ui, key, blocks, query, forms) if draw in FORMED else draw(ui, key, blocks, query)

    async def fragment(self, request: Request) -> Response:
        assert self.ui is not None
        person = self.ui.names.person_of(request.path_params["key"])
        if not self.known(self.ui, person):
            return secure(Response(status_code=404))
        return self.ui.fragment("handmade/person/body.html", now=self.snapshot(self.ui, person))

    async def page(self, request: Request) -> Response:
        """L'ancienne adresse de la page : la fiche, ouverte sur sa vue d'ensemble."""
        return secure(RedirectResponse(fiche_url("person", request.path_params["key"]), status_code=303))

    def routes(self, ui: UI, outbound: LoginThrottle | None = None) -> list[Route]:
        """Ses routes. ``outbound`` : la borne des demandes au serveur d'itinéraires, celle de l'écran Carte
        (``MeApi.outbound``), que le GPX d'un voyage use sur le compte de l'opérateur ; sans elle, une borne à la
        console seule, aux mêmes nombres (``OUTBOUND``) — jamais aucune."""
        self.ui = ui
        throttle = outbound if outbound is not None else LoginThrottle(*OUTBOUND)

        async def gpx(request: Request) -> Response:
            return await trip_gpx(ui, request, throttle)

        return [Route(BASE + "/{key:path}", ui.guarded(self.page), methods=["GET"]),
                Route(FRAGMENT + "/{key:path}", ui.guarded(self.fragment), methods=["GET"]),
                # le GPX d'un voyage, depuis son onglet (ADR 0204)
                Route(TRIP_GPX + "/{trip:int}/gpx", ui.guarded(gpx), methods=["GET"])]

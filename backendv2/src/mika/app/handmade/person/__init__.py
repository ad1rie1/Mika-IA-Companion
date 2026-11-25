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
(Réglages › Comptes) et à ses droits exacts (Réglages › Droits). Son onglet Comptes réunit en sous-onglets ses boîtes
et ses comptes Teams (les listes des plugins), puis les services qu'elle a branchés et ses partages, lus dans les
réglages (``owned``). Un onglet qu'un seul domaine nourrit (ses agendas, ses voyages et sa position, son téléphone, ce
qui l'identifie et ses contacts, ses projets) est dans la part de ce domaine (``PersonPart``, ADR 0310), avec ce qu'il
y compte et ce qu'il tait : la fiche réunit les parts après ce qu'elle dit elle-même (``persons``), sans nommer aucun
domaine. Les onglets de sa barre disent leur compte (``PersonOverview.counts``).
"""

from __future__ import annotations

import functools
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from typing import Any
from urllib.parse import quote

from markupsafe import Markup
from sqlalchemy import func, or_, select
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from mika.adapters.web.accounts import Account, account_of_handle
from mika.adapters.web.gate import SlidingWindow
from mika.app.domains import DOMAINS, PersonPart, part
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
from mika.app.handmade.person.common import LEVEL_FR, Who, _slice, _with
from mika.app.handmade.person.files import files
from mika.app.handmade.person.memory import memory
from mika.app.handmade.rights import UNSHARE, retiring, share_consoles
from mika.app.handmade.tabs import anchored
from mika.app.me import OUTBOUND
from mika.app.me import accounts as channels
from mika.app.me.sharing import Shared, every_share, given_and_received, sharer
from mika.app.me.sharing import parts as share_parts
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
from mika.faculties.goals.inspect import of_person as goals_of
from mika.faculties.memory.inspect import ORIGIN_SHORT, SENSITIVITY_FR
from mika.faculties.memory.inspect import person_total as memory_total
from mika.faculties.social.inspect import CLOSENESS_FR
from mika.faculties.social.sections import profile_parts, refs_of
from mika.inspector import render
from mika.inspector.pages.accounts import rights_url
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import PREFIX, UI, Overview, env, secure
from mika.kernel.clock import DAY, US
from mika.kernel.inspect import Fields, Head, Note, Section, Table, num_fr, pct_fr, plural
from mika.runtime.boundary import Failed, call
from mika.vocab import affect as A
from mika.vocab import privacy
from mika.vocab.access import PERSON
from mika.vocab.knowledge import knowns
from mika.vocab.people import is_identifiable
from mika.vocab.words import elided

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
        # ceux que compte la faculté sociale : un message entendu dans un groupe sans lui être adressé n'y est pas
        # (Échanges les compte tous, « reçus »)
        facts.append(plural(contact.inbound, "message adressé à elle", "messages adressés à elle"))
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
        "where_href": subject_url("person", person, "adresses"),
        "toward": f"{PREFIX}/decisions/envers?personne={quote(person, safe='')}",
        # un de ses moyens de communication est un compte : lequel, sa page (Réglages › Comptes) et ses droits exacts
        # (Réglages › Droits, par son chat web en privé)
        "account": {"kind": "compte opérateur" if account.operator else "compte utilisateur",
                    "off": not account.active, "href": f"{ACCOUNTS}?compte={account.id}",
                    "rights": rights_url(frame, person)} if account else None,
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
    souvenirs = _known(look, (v.c.kind == memory_c.EPISODE_MEMORY, v.c.status == "active", about,
                              or_(v.c.origin.is_(None), v.c.origin != memory_c.LIED)), SHOWN)
    lies = _known(look, (v.c.kind == memory_c.EPISODE_MEMORY, v.c.origin == memory_c.LIED, about), SHOWN)
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
    return {"messages": out, "all": subject_url("person", who.person, "echanges")}


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
                    "note": GOAL_STATUS_FR.get(g.status, g.status), "href": subject_url("goal", str(g.id)), "tone": ""})
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


@functools.cache
def owned_tabs() -> tuple[tuple[str, str, Roles], ...]:
    """Les sous-onglets de Comptes que les plugins remplissent, un par canal, dans l'ordre où la console passe leurs
    sections (``app/me/accounts.py::CHANNELS`` : l'onglet qui porte les autres d'abord) : leur onglet (l'ancre où mène
    son adresse), leur nom, la forme de leurs listes — ce que dit la part de chaque canal (``AccountsPart``). Lus à
    la demande, une fois : la part d'un canal importe son API par personne."""
    return tuple((p.tab, p.label, Roles(title=p.noun, badges=p.badges, tiles=True)) for p in channels.parts().values())


def _resource(s: Shared) -> dict[str, str]:
    """La ressource d'un partage, pour la fiche : sa sorte en mots (``SharingPart.word``), son nom, où elle mène (ce
    qu'en dit la part de console de sa sorte : ``ConsolePart.shared``)."""
    return {"kind": share_parts()[s.kind].word, "title": s.title, "href": share_consoles()[s.kind].shared(s)}


def shares(look: Look, who: Who) -> dict[str, list[dict[str, Any]]]:
    """Ce qu'elle partage et ce qu'on lui partage (ADR 0188) : ses boîtes, ses comptes Teams et ses services, lus dans
    les réglages comme Réglages › Droits › Partages et Paramètres › Partages (``every_share``, ADR 0210), et triés par
    la même règle (``given_and_received`` : une ressource « à toi » est à chacune de ses propriétaires). Chacun porte
    de quoi le retirer, comme dans Droits (``off`` : ``rights.retiring``, ADR 0210) ; sans réglages joignables, rien."""
    settings = look.ui.deps.settings
    if settings is None:
        return {"given": [], "received": []}
    owner = bool(look.frame.get(identity_c.IS_OWNER(who.person)))
    given, received = given_and_received(every_share(settings), who.person, owner=owner)
    return {"given": [{**_resource(s), **_with(look, s.person, s.level), "off": retiring(look.ui, s)} for s in given],
            "received": [{**_resource(s), "owner": sharer(look.frame, s, look.name), "level": LEVEL_FR.get(s.level, s.level),
                          "off": retiring(look.ui, s)} for s in received]}


def owned(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str],
          forms: Mapping[str, Any] | None = None) -> Markup | None:
    """L'onglet Comptes, dessiné : en sous-onglets, ses boîtes et ses comptes Teams (les listes des plugins, réunies
    par ``joined``, ADR 0185, 0186), puis ses services et ses partages, lus dans les réglages (ADR 0188, 0192) — ce
    que la console voit de tous. Chacun les donne et les règle dans son espace ; la console retire un partage de
    boîte ou de compte Teams (« Retirer », le geste de Réglages › Droits › Partages, ADR 0210 : confirmé, audité,
    retour sur ce sous-onglet), et mène aux lignes d'accès d'un service. Le jeton du formulaire est celui de la page
    (``forms.csrf``) : sans lui (un rendu hors d'une page), pas de « Retirer »."""
    kinds = owned_tabs()
    sections = list(blocks) if blocks and all(isinstance(b, Section) for b in blocks) \
        else [Section(kinds[0][1], tuple(blocks))]
    shown, name, counter = ui.env(), ui.names.name_of(key), [0]
    panes = []
    for (anchor, label, roles), section in zip(kinds, sections, strict=False):
        lists = [{**anchored(listing(t, shown, query, name, roles, counter), anchor), "kind": anchor}
                 for t in section.items if isinstance(t, Table)]
        panes.append({"id": anchor, "label": label, "count": sum(x["count"] or 0 for x in lists), "lists": lists,
                      "facts": [render.block(b, shown, query) for b in section.items if isinstance(b, Fields)],
                      "notes": [{"text": b.text, "title": b.title, "tone": b.tone} for b in section.items
                                if isinstance(b, Note)]})
    look = Look.of(ui, DAY)
    who = who_of(look, key)
    # ce que chaque domaine y montre après les comptes des canaux (``PersonPart.owned`` : ses services), puis ses
    # partages
    held = [(anchor, label, rows(look, who)) for anchor, label, rows in owned_parts()]
    shared = shares(look, who)
    panes += [*({"id": anchor, "label": label, "count": len(found), anchor: found} for anchor, label, found in held),
              {"id": "partages", "label": "Partages", "count": len(shared["given"]) + len(shared["received"]),
               "shares": shared}]
    return Markup(env.get_template("handmade/person/tabs/comptes.html").render(
        panes=panes, name=who.name, of=elided(who.name, "de"), that=elided(who.name, "que"),
        unshare=UNSHARE, csrf=getattr(forms, "csrf", ""), back=subject_url("person", key, kinds[0][0]) + "#partages"))


# ── la page ──

#: les onglets des facultés que le cadre dessine : leur nom → ce qui les dessine (les données restent celles de la
#: faculté). Ceux qu'un seul domaine nourrit sont dans sa part (``PersonPart.tabs``) : ``every_tab`` les réunit
TABS: dict[str, Callable[[UI, str, Sequence[Any], Mapping[str, str]], Any]] = {
    "echanges": exchanges,
    "memoire": memory,
    # ce qu'elle a envoyé et ce qu'on lui a envoyé, en deux sous-onglets (``joined``), « Retirer » sur chacun
    # (ADR 0205) ; les pièces seules, sans l'autre
    "fichiers": files,
    "pieces": drawn(Roles(title="nom", badges=("sorte", "état"), body=("ce qu'elle y a lu",), time="reçue",
                          tiles=True), "pieces"),
    "buts": drawn(Roles(title="titre", badges=("sorte", "statut"), time="ouvert"), "buts"),
    # le détail de ce que la vue d'ensemble résume : bloc par bloc, ses formulaires laissés à la console
    "synthese": blocks_tab, "lien": blocks_tab, "devine": blocks_tab, "affect": blocks_tab, "pensees_personne": blocks_tab,
}

@functools.cache
def account_tabs() -> dict[str, Callable[..., Any]]:
    """Ses comptes : les boîtes aux lettres et les comptes Teams qui sont à elle (ADR 0185, 0186), réunis (``joined``)
    sous l'onglet du premier canal (``owned_tabs``), puis ses services et ses partages (ADR 0188, 0192) ; sans boîte,
    Teams reste un onglet à lui, sauf si elle a un service ou un partage (``shows``, ADR 0219) : Comptes les réunit
    alors."""
    first, *others = owned_tabs()
    return {first[0]: owned, **{tab: drawn(roles, tab) for tab, _label, roles in others}}


#: les onglets dessinés qui posent aussi les formulaires de la console (``Forms``) : le détail bloc par bloc (la
#: Synthèse : « C'est la personne dont on lui a parlé »), les fichiers (« Retirer ») et Comptes (« Retirer » un
#: partage, par le jeton de la page) ; ceux des domaines le disent dans leur part (``PersonPart.formed``)
FORMED = (blocks_tab, files, owned)


@functools.cache
def persons() -> tuple[PersonPart, ...]:
    """La part de chaque domaine dans la fiche d'une personne, dans l'ordre des fiches. Lue à la demande, une fois :
    la part d'un domaine importe un module de ce paquet (``common``), qui ne peut donc pas importer la sienne en
    naissant."""
    consoles = (part(d.console, "CONSOLE") for d in DOMAINS if d.console is not None)
    return tuple(console.person for console in consoles if console.person is not None)


def owned_parts() -> tuple[tuple[str, str, Callable[..., list[Any]]], ...]:
    """Ce que chaque domaine montre en sous-onglet de Comptes après les comptes des canaux (``PersonPart.owned`` : les
    services qu'elle a branchés), dans l'ordre des fiches."""
    return tuple(p.owned for p in persons() if p.owned is not None)


def every_tab() -> dict[str, Callable[..., Any]]:
    """Les onglets dessinés de la fiche : ceux du cadre (``TABS``, puis ses comptes : ``account_tabs``), puis ceux de
    chaque domaine."""
    return {**TABS, **account_tabs(), **{tab: draw for p in persons() for tab, draw in p.tabs.items()}}


def every_formed() -> tuple[Callable[..., Any], ...]:
    """Ce qui dessine un onglet qui pose aussi les formulaires de la console : ceux du cadre (``FORMED``), puis ceux que
    chaque domaine nomme dans sa part."""
    return (*FORMED, *(p.tabs[tab] for p in persons() for tab in p.formed))


# ── le compte de ses onglets ──

def _count(look: Look, query: Any) -> int:
    """Un ``COUNT`` ; une lecture en panne rend 0, qui tait le compte (jamais la fiche)."""
    rows = _query(look, query)
    return int(rows[0][0]) if rows else 0


def _accounts(look: Look, who: Who) -> dict[str, int]:
    """Ses comptes de chaque canal — ses boîtes, ses comptes Teams —, par l'onglet de sa faculté
    (``AccountsPart.tab``), lus dans les réglages comme leurs plugins les listent (``owner`` : vide pour ce qui est
    « à toi », quand elle est une de ses propriétaires ; ``personne:<clé>`` sinon)."""
    settings = look.ui.deps.settings
    found = channels.parts().values()
    if settings is None:
        return {p.tab: 0 for p in found}
    mine = "" if look.frame.get(identity_c.IS_OWNER(who.person)) else PERSON + who.person
    return {p.tab: sum(1 for spec in p.configured(settings).values() if spec.owner == mine) for p in found}


def tab_counts(look: Look, who: Who) -> dict[str, int]:
    """Combien chaque onglet de sa barre en compte, par son nom (``Overview.counts``, la vue d'un objet) : ce qui se
    lit au frame (ses moyens de communication, ses buts) et dans les réglages (Comptes : ses boîtes, ses comptes
    Teams, ses services, ses partages), et deux ``COUNT`` d'une requête chacun — ses messages (le fil, comme
    ``_history``) et ce que liste sa Mémoire (compté par la mémoire, aux clauses de son onglet : tous statuts, comme sa
    bande de chiffres) ; puis ce que chaque domaine y compte (``PersonPart.counts``, ajouté à ce que la fiche compte
    déjà : ses voyages, ses contacts, ses agendas, ses projets, et les identifiants de l'annuaire qui lui sont reliés,
    avec ses moyens de communication). Fichiers n'en a pas : ses deux listes sont à deux facultés, chacune sa table ;
    les onglets repliés sous « Le détail » non plus."""
    frame, person = look.frame, who.person
    handles = sorted({person, *who.handles})
    t = transcript_c.thread_table()
    known = call(memory_total, _store(look), frame, person, label="lecture")
    held = _accounts(look, who)
    shared = shares(look, who)
    goals = _slice(look, "goals")
    counts = {
        "adresses": len(who.handles),
        "echanges": _count(look, select(func.count()).select_from(t).where(t.c.person.in_(handles))),
        "memoire": 0 if isinstance(known, Failed) else known,
        # Comptes, sous l'onglet du premier canal, réunit les autres (``joined``) ; sans Comptes, Teams est un onglet à
        # lui
        **held,
        owned_tabs()[0][0]: sum(held.values()) + sum(len(rows(look, who)) for _a, _l, rows in owned_parts())
        + len(shared["given"]) + len(shared["received"]),
        "buts": len(goals_of(goals, handles)) if goals is not None else 0,
    }
    for p in persons():  # ce que chaque domaine y compte, ajouté à ce que la fiche compte déjà
        for tab, count in p.counts.items():
            counts[tab] = counts.get(tab, 0) + count(look, who)
    return counts


#: chaque partie de la page, lue à part
PARTS: tuple[tuple[str, Callable[[Look, Who], dict[str, Any]]], ...] = (
    ("portrait", portrait), ("story", story), ("knows", knows), ("reads", reads), ("thread", thread),
    ("pending", pending), ("circle", circle))


class PersonOverview(Overview):
    """La vue d'ensemble de la fiche d'une personne (``/admin/fiche/person/<clé>`` : son premier onglet, ouvert
    par défaut ; le détail de chaque faculté reste dans les suivants), et son fragment qui se relit seul.
    L'adresse ``/admin/personne/<clé>`` mène à la fiche."""

    slug = "ensemble"
    title = "Vue d'ensemble"
    # et celles de l'annuaire : « Ce qui l'identifie » et « Contacts » (ADR 0298)
    styles = ("handmade/person.css", "handmade/sens.css", "handmade/personnes.css", "handmade/personnes_annuaire.css",
              "handmade/agendas.css")
    scripts = ("handmade/live.js",)
    #: ce que la vue d'ensemble résume (son ressenti, leur lien, ce qu'elle lit d'elle, ses pensées, et la mécanique
    #: de ce qu'elle peut lui dire) : le détail reste à un clic, au bout de la barre
    folded = ("synthese", "lien", "devine", "affect", "pensees_personne")
    @property
    def joined(self) -> Mapping[str, tuple[str, ...]]:
        """Fichiers porte aussi les pièces reçues : un onglet pour ce qui va et vient entre elles (ADR 0179) ; Comptes
        (l'onglet du premier canal), ses boîtes aux lettres et ses comptes Teams (ADR 0185, 0186 — sans boîte, Teams
        reste un onglet à lui : ``owned_tabs``)."""
        first, *others = owned_tabs()
        return {"fichiers": ("pieces",), first[0]: tuple(tab for tab, _label, _roles in others)}

    def __init__(self) -> None:
        #: la console, posée quand ses routes le sont (la fiche, elle, passe la sienne à ``render``)
        self.ui: UI | None = None

    @property
    def tabs(self) -> tuple[str, ...]:
        """Les onglets des facultés qu'elle dessine : ceux du cadre, puis ceux des domaines (``every_tab``)."""
        return tuple(every_tab())

    @staticmethod
    def snapshot(ui: UI, person: str) -> dict[str, Any]:
        look = Look.of(ui, DAY)
        who = who_of(look, person)
        parts = tuple((key, lambda lk, fn=fn: fn(lk, who)) for key, fn in PARTS)
        return {"name": who.name, "stamp": look.frame.local(look.now).strftime("%H:%M:%S"),
                "fiche": subject_url("person", who.person), "of": elided(who.name, "de"), "that": elided(who.name, "que"),
                **read_parts(look, parts, f"une personne · {person}")}

    def counts(self, ui: UI, key: str) -> Mapping[str, int]:
        """Le compte de chaque onglet de sa barre (``tab_counts``) ; une personne qu'elle ne connaît pas, aucun."""
        if not self.known(ui, key):
            return {}
        look = Look.of(ui, DAY)
        return tab_counts(look, who_of(look, key))

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

    def hidden(self, ui: UI, key: str) -> Sequence[str]:
        """Ce que chaque domaine tait sur sa fiche (``PersonPart.hidden`` : Contacts, seulement pour qui en a)."""
        if not self.known(ui, key):
            return ()
        return tuple(tab for p in persons() if p.hidden is not None for tab in p.hidden(ui, key))

    def shows(self, ui: UI, key: str) -> Sequence[str]:
        """Comptes (``boites``) aussi pour qui n'a pas de boîte à elle mais a branché un service ou partage quelque
        chose, dans un sens ou dans l'autre (C9-02) : ses sous-onglets Services (la part de ses outils,
        ``PersonPart.owned``) et Partages sont dessinés ici (``owned``), et le plugin du courrier ne montre l'onglet
        qu'à qui a une boîte."""
        if not self.known(ui, key):
            return ()
        look = Look.of(ui, DAY)
        who = who_of(look, key)
        shared = shares(look, who)
        mine = any(rows(look, who) for _anchor, _label, rows in owned_parts())
        return (owned_tabs()[0][0],) if mine or shared["given"] or shared["received"] else ()

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Sequence[Any], query: Mapping[str, str],
                   forms: Mapping[str, Any] | None = None) -> Any:
        draw = every_tab().get(tab)
        if draw is None or not self.known(ui, key):
            return None
        return draw(ui, key, blocks, query, forms) if draw in every_formed() else draw(ui, key, blocks, query)

    async def fragment(self, request: Request) -> Response:
        assert self.ui is not None
        person = self.ui.names.person_of(request.path_params["key"])
        if not self.known(self.ui, person):
            return secure(Response(status_code=404))
        return self.ui.fragment("handmade/person/body.html", now=self.snapshot(self.ui, person))

    async def page(self, request: Request) -> Response:
        """L'ancienne adresse de la page : la fiche, ouverte sur sa vue d'ensemble."""
        return secure(RedirectResponse(subject_url("person", request.path_params["key"]), status_code=303))

    def routes(self, ui: UI, outbound: SlidingWindow | None = None) -> list[Route]:
        """Ses routes, puis celles que chaque domaine pose sous la fiche (``PersonPart.routes`` : le GPX d'un voyage).
        ``outbound`` : la borne des demandes au serveur d'itinéraires, celle de l'écran Carte (``MeApi.outbound``), que
        le GPX d'un voyage use sur le compte de l'opérateur ; sans elle, une borne à la console seule, aux mêmes
        nombres (``OUTBOUND``) — jamais aucune. Les parts reçoivent celle-ci."""
        self.ui = ui
        throttle = outbound if outbound is not None else SlidingWindow(*OUTBOUND)
        return [Route(BASE + "/{key:path}", ui.guarded(self.page), methods=["GET"]),
                Route(FRAGMENT + "/{key:path}", ui.guarded(self.fragment), methods=["GET"]),
                *(route for p in persons() if p.routes is not None for route in p.routes(ui, throttle))]

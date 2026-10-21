"""Une personne : tout ce qu'elle vit avec elle, sur une page dessinée à la main (ADR 0121).

La fiche d'une personne a douze onglets, un par faculté. « Qu'est-ce qu'elle vit avec cette personne ? » les
traverse : cette page les croise, lus aux faits au même instant, à sa mémoire (par sa seule porte,
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
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import quote

from markupsafe import Markup
from sqlalchemy import or_, select
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from mika.app.handmade import (
    LIVE_WAIT,
    MONTHS,
    PERSON_BASE,
    WEEKDAYS,
    Look,
    affect_params,
    emotion,
    excerpt,
    read_parts,
    senses,
    span,
    unit,
)
from mika.app.handmade.blocks import tab as blocks_tab
from mika.app.handmade.lists import Roles, drawn
from mika.app.handmade.person.echanges import exchanges
from mika.app.handmade.person.memoire import memory
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
from mika.faculties.memory.inspect import SENSITIVITY_FR
from mika.faculties.social.inspect import CLOSENESS_FR
from mika.faculties.social.sections import profile_parts, refs_of
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import PREFIX, UI, Overview, env, secure
from mika.kernel.clock import DAY, US
from mika.kernel.inspect import Head, num_fr, pct_fr
from mika.runtime.boundary import Failed, call
from mika.vocab import affect as A
from mika.vocab import privacy
from mika.vocab.knowledge import knowns
from mika.vocab.people import is_identifiable

#: la page, et le fragment qu'elle relit
BASE = PERSON_BASE
FRAGMENT = f"{PREFIX}/_personne"
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

ORIGIN_FR = {memory_c.TOLD: "dit", memory_c.OBSERVED: "vu", memory_c.INFERRED: "déduit", memory_c.READ: "lu"}
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
    felt = not stance.at_rest and stance.felt_intensity >= 0.1 and stance.felt is not A.Emotion.NEUTRAL
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
    fiche = f"{PREFIX}/fiche/person/{quote(person, safe='')}"
    return {
        "name": who.name, "initial": (who.name[:1] or "?").upper(),
        "emotion": stance.felt.value if felt else "neutral",
        "owner": bool(frame.get(identity_c.IS_OWNER(person))),
        "closeness": CLOSENESS_FR.get(closeness, closeness), "close": closeness in (social_c.FRIEND, social_c.CLOSE),
        "online": bool(set(frame.get(presence_c.PRESENT) or ()) & set(who.handles)),
        "composing": any(frame.get(presence_c.COMPOSING(h)) for h in who.handles),
        "facts": facts,
        "where": f"{count} moyen{'s' if count > 1 else ''} de communication" + (f" · {view.channel}, {how}" if view.channel else ""),
        "where_href": f"{fiche}?onglet=adresses",
        "toward": f"{PREFIX}/decisions/envers?personne={quote(person, safe='')}",
    }


# ── qui elle est pour elle ──


def portrait(look: Look, who: Who) -> dict[str, Any]:
    """Ce qu'elle ressent envers elle (et ce que son prompt lui en dit), ce que leur lien a installé."""
    frame, now, person = look.frame, look.now, who.person
    stance = frame.get(affect_c.STANCE(person))
    felt = None
    if not stance.at_rest and stance.felt_intensity >= 0.1 and stance.felt is not A.Emotion.NEUTRAL:
        felt = {"emotion": stance.felt.value, "word": A.FR[stance.felt], "how": A.intensity_word(stance.felt_intensity)}
    voice = prose.stance(stance, affect_params(frame), name=who.name, now=now)
    regard = stance.regard
    hard = frame.get(memory_c.HARD_TIMES(person))
    return {
        "fiche": f"{PREFIX}/fiche/person/{quote(person, safe='')}",
        "felt": felt, "voice": [line for line in voice.split("\n") if line.strip()],
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
            title = f"{WEEKDAYS[date.weekday()]} {date.day} {MONTHS[date.month - 1]}"
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
            "origin": ORIGIN_FR.get(k.origin or "", ""), "told_by": look.who(told),
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
        summary, tone, interests, sensitive = profile_parts(profile, texts)
        if summary or interests or sensitive:
            said_of_self = {"summary": excerpt(summary, 400) if summary else "", "tone": tone,
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
    frame, now, person = look.frame, look.now, who.person
    mind = frame.get(others_c.MIND(person))
    check_in = frame.get(others_c.CHECK_IN_AT(person))
    if not mind.observed:
        return {"observed": 0, "check_in": look.day(check_in) if check_in > now else ""}
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
            "last": last, "last_at": look.ago(mind.last_at) if mind.last_at else "",
            "check_in": look.day(check_in) if check_in > now else ""}


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
        out.append({"mine": role == "assistant", "text": excerpt(text, 320) if text else "(oublié)",
                    "when": local.strftime("%H:%M") if local.date() == today else f"{look.date(int(at))}, "
                                                                              f"{local.strftime('%H:%M')}",
                    "emotion": e.value if e is not None else "", "word": A.FR[e] if e is not None else "",
                    "room": bool(room), "unanswered": bool(unanswered and role == "user"),
                    "why": f"{PREFIX}/parole/{n}" if role == "assistant" else ""})
    return {"messages": out, "all": f"{PREFIX}/fiche/person/{quote(who.person, safe='')}?onglet=echanges"}


# ── ce qui reste en suspens ──


def pending(look: Look, who: Who) -> dict[str, Any]:
    frame, now, person = look.frame, look.now, who.person
    keys = set(who.keys)
    out: list[dict[str, Any]] = []
    waiting = frame.get(attention_c.AWAITING(person))
    if waiting.unanswered and waiting.last_out and now - waiting.last_out >= LIVE_WAIT:
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
                    "note": GOAL_STATUS_FR.get(g.status, g.status), "href": f"{PREFIX}/fiche/goal/{g.id}", "tone": ""})
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


# ── la page ──

#: les onglets des facultés dessinés : leur nom → ce qui les dessine (les données restent celles de la faculté)
TABS: dict[str, Callable[[UI, str, Sequence[Any], Mapping[str, str]], Any]] = {
    "echanges": exchanges,
    "memoire": memory,
    "adresses": drawn(Roles(title="moyen de communication", badges=("confiance",), tiles=True), "adresses"),
    "fichiers": drawn(Roles(title="nom", badges=("état",), time="quand", tiles=True), "fichiers"),
    "pieces": drawn(Roles(title="nom", badges=("sorte", "état"), body=("ce qu'elle y a lu",), time="reçue",
                          tiles=True), "pieces"),
    "buts": drawn(Roles(title="titre", badges=("sorte", "statut"), time="ouvert"), "buts"),
    "projets": drawn(Roles(title="projet", badges=("mode", "état"), time="ouvert"), "projets"),
    # ce que son téléphone lui a montré, où il dit qu'elle est (seulement s'il en a dit quelque chose)
    "telephone": senses.phone_tab, "position": senses.position_tab,
    # le détail de ce que la vue d'ensemble résume : bloc par bloc, ses formulaires laissés à la console
    "synthese": blocks_tab, "lien": blocks_tab, "devine": blocks_tab, "affect": blocks_tab, "pensees_personne": blocks_tab,
}

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
    #: les onglets des facultés qu'elle dessine, chacun dans son module (``person/<onglet>.py``)
    tabs = tuple(TABS)

    def __init__(self) -> None:
        #: la console, posée quand ses routes le sont (la fiche, elle, passe la sienne à ``render``)
        self.ui: UI | None = None

    @staticmethod
    def snapshot(ui: UI, person: str) -> dict[str, Any]:
        look = Look.of(ui, DAY)
        who = who_of(look, person)
        parts = tuple((key, lambda lk, fn=fn: fn(lk, who)) for key, fn in PARTS)
        return {"her": ui.her_name(), "name": who.name, "stamp": look.frame.local(look.now).strftime("%H:%M:%S"),
                "of": elided("de", who.name), "that": elided("que", who.name),
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
        # dessiné bloc par bloc, un onglet dessine aussi ses formulaires (« fixer la proximité ») ; les autres n'en ont pas
        return draw(ui, key, blocks, query, forms) if draw is blocks_tab else draw(ui, key, blocks, query)

    async def fragment(self, request: Request) -> Response:
        assert self.ui is not None
        person = self.ui.names.person_of(request.path_params["key"])
        if not self.known(self.ui, person):
            return secure(Response(status_code=404))
        return self.ui.fragment("handmade/person/body.html", now=self.snapshot(self.ui, person))

    async def page(self, request: Request) -> Response:
        """L'ancienne adresse de la page : la fiche, ouverte sur sa vue d'ensemble."""
        return secure(RedirectResponse(fiche_url("person", request.path_params["key"]), status_code=303))

    def routes(self, ui: UI) -> list[Route]:
        self.ui = ui
        return [Route(BASE + "/{key:path}", ui.guarded(self.page), methods=["GET"]),
                Route(FRAGMENT + "/{key:path}", ui.guarded(self.fragment), methods=["GET"])]

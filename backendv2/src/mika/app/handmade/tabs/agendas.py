"""Relations & échanges › Agendas (ADR 0309, lot 5) : ses onglets, chacun dans sa forme (ADR 0177), d'après la maquette
validée (``output/maquette-agenda-console/``).

- **Tous les agendas** : à gauche, les agendas montrés, par personne, cochables (``?masques=`` : décocher ne change que
  l'affichage ; un agenda masqué par son propriétaire part décoché), chacun avec l'état de sa synchro ; au centre « Les
  agendas de » (``?qui=``, une ou plusieurs personnes, et elle), la période (``?du=``) et la vue (``?vue=`` : semaine,
  mois, liste — le bouton à choix au bout de la barre d'onglets), un seul bandeau quand un compte est à reconnecter ou
  en panne ; un événement ouvert (``?ev=``) à droite — son agenda, à qui, son compte, ses participants, ce qu'elle en a
  fait (un rappel dit, prévu ou tombé ; ajouté par elle ; une proposition, une réponse d'invitation préparée, qui
  mènent à « À valider »). Un événement privé d'une autre personne reste « Occupé · privé ». Ce qu'elle propose
  d'ajouter et qui attend un accord est hachuré ; son agenda à elle est en rose.
- **Comptes** : chaque compte en liste serrée — fournisseur, à qui, ses agendas (leur fiche), sa synchro (l'erreur en
  mots), avec qui ses agendas sont partagés ici.
- **Ce qu'elle en fait** : en sous-onglets, ses rappels (dits, dus, tombés ; les prochains), ses propositions d'ajout,
  ses réponses d'invitation, ce qu'elle a ajouté seule — chacun avec sa conversation — et d'où ça vient.
- **L'agenda de <son nom>** (l'onglet la nomme : ``self_.NAME_SLOT``) : sa mémoire montrée comme un agenda (``app/her_agenda.py``), tout, par personne.

Les données sont celles du plugin ``agenda`` (sa base, sa tranche, ses vues : la source pour la console en MCP et le
repli), lues par ``agenda_reads.py``. Ses paramètres sont derrière la roue (``agendas/parametres``, ADR 0206).
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from mika.app.handmade import WEEKDAYS
from mika.app.handmade.agenda_reads import ROSE, Item, Read, conversation_of, items, proposal_args, read
from mika.app.handmade.tabs import Got, Tab
from mika.app.her_agenda import AHEAD, MOMENT, PROMISE, YEARLY, her_agenda
from mika.contracts import agenda as agenda_c
from mika.contracts import identity as identity_c
from mika.inspector import render
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import PREFIX
from mika.kernel.clock import DAY, MINUTE
from mika.kernel.inspect import Pager
from mika.plugins.agenda import CREATE, RESPOND, WAITING, Written, params_of
from mika.plugins.agenda.inspect.views import (
    DROPPED_WHY,
    FROM,
    HER,
    HIDDEN,
    KIND,
    KIND_SHORT,
    LIST,
    MONTH,
    OPEN,
    REMINDED_WORDS,
    REMINDER_WORDS,
    SYNC_MODE,
    VIEW,
    WEEK,
    WHOSE,
    WRITE_STATUS,
    YOURS,
    Shown,
    account_label,
    bounds,
    chosen,
    count_events,
    planned_reminder,
    sees_private,
    shown_accounts,
    synced,
    week_of,
)
from mika.plugins.agenda.watch import invitation_key, reminder_key
from mika.ports.agenda import CANCELLED, MAYBE, NEEDS, NO, YES, Occurrence, Participant
from mika.runtime.boundary import Failed, call
from mika.vocab.access import PERSON, SHARES

STYLES = ("handmade/agendas.css", "handmade/person.css")
#: la grille de la semaine : de 8 h à 22 h, par quart d'heure (56 lignes), douze sous-colonnes par jour
FIRST_HOUR, LAST_HOUR, SLOTS, LANES = 8, 22, 56, 12
#: au plus tant d'éléments par jour dans le mois
MONTH_SHOWN = 3
MONTHS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
          "décembre")
SHORT_MONTHS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")
DAYS_SHORT = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")
#: la réponse d'une participante, en mots, et son ton
ANSWERS = {"": ("organise", "info"), YES: ("oui", "ok"), MAYBE: ("peut-être", "warn"), NO: ("non", "danger"),
           NEEDS: ("sans réponse", "")}
#: ce qu'elle répond, en mots
ANSWER_WORDS = {YES: "oui", MAYBE: "peut-être", NO: "non"}
#: son agenda à elle : la sorte d'une date, en mots, et son ton
HER_KINDS = {PROMISE: ("promesse", "info"), MOMENT: ("ce qu'elle voit venir", ""),
             YEARLY: ("revient chaque année", ""), AHEAD: ("dans le monde", "")}
APPROVALS = f"{PREFIX}/approbations/en_attente"
#: « Synchroniser maintenant », l'action de la fiche d'un agenda, posée aussi sur sa ligne
SYNC_ACTION = f"{PREFIX}/action/agenda.relire"


# ── les mots du temps ──


def num(d: date) -> str:
    return "1er" if d.day == 1 else str(d.day)


def day_long(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {num(d)} {MONTHS[d.month - 1]}"


def day_short(d: date) -> str:
    return f"{DAYS_SHORT[d.weekday()]} {num(d)}"


def hm(r: Read, at: int) -> str:
    return r.frame.local(at).strftime("%H:%M")


def hours(r: Read, x: Item) -> str:
    return "journée" if x.all_day else f"{hm(r, x.start)} – {hm(r, x.end)}"


def when_long(r: Read, x: Item) -> str:
    """Quand, en entier : « lundi 23 novembre · 14:00 – 15:00 (1 h) », ou une journée entière."""
    if x.all_day:
        span = f" → {day_long(x.last)}" if x.last != x.first else ""
        return f"{day_long(x.first)}{span} · journée entière"
    minutes = max(0, (x.end - x.start) // MINUTE)
    h, m = divmod(minutes, 60)
    length = f"{h} h{m:02d}" if h and m else f"{h} h" if h else f"{m} min"
    return f"{day_long(x.first)} · {hm(r, x.start)} – {hm(r, x.end)} ({length})"


def stamp(r: Read, at: int) -> str:
    """Un instant proche, court : « 13:30 », « hier 18:41 », « jeu. 19 18:12 »."""
    local, today = r.frame.local(at).date(), r.frame.local(r.now).date()
    days = (local - today).days
    if days == 0:
        return hm(r, at)
    if days == -1:
        return f"hier {hm(r, at)}"
    if days == 1:
        return f"demain {hm(r, at)}"
    return f"{day_short(local)} {hm(r, at)}"


def relative_day(r: Read, d: date) -> str:
    today = r.frame.local(r.now).date()
    if d == today:
        return "Aujourd'hui"
    if d == today + timedelta(days=1):
        return "Demain"
    return WEEKDAYS[d.weekday()].capitalize()


# ── ce que l'adresse garde ──


def _query(got: Got) -> dict[str, str]:
    return {k: v for k, v in got.query.items() if k in (WHOSE, VIEW, FROM, HIDDEN, OPEN)}


def link(base: Mapping[str, str], **changes: str | None) -> str:
    """Une adresse de Tous les agendas : ce que la page garde, changé ; ``None`` retire."""
    q = dict(base)
    for k, v in changes.items():
        if v is None:
            q.pop(k, None)
        else:
            q[k] = v
    kept = {k: v for k, v in q.items() if v or k == HIDDEN}
    return "?" + urlencode(kept) if kept else "?"


def hidden_of(got: Got, calendars: Sequence[Shown]) -> set[str]:
    """Les agendas qu'on ne montre pas : ceux que l'adresse dit (``?masques=``, même vide), sinon ceux que leur
    propriétaire a masqués."""
    if HIDDEN in got.query:
        known = {c.key for c in calendars} | {HER}
        return {k for k in str(got.query.get(HIDDEN, "")).split(",") if k in known}
    return {c.key for c in calendars if c.hidden}


# ── « Les agendas de », la légende ──


def chips(r: Read, picked: set[str], base: Mapping[str, str], people: Sequence[str], *,
          her: bool = True, counts: Mapping[str, int] | None = None, single: bool = False) -> list[dict[str, Any]]:
    """Les puces de qui : tout le monde, toi, chaque personne, elle ; une puce ajoute ou retire sa personne
    (``single`` : n'en garde qu'une)."""
    out = [{"text": "Tout le monde", "on": not picked, "href": link(base, qui=None, ev=None),
            "count": sum(counts.values()) if counts is not None else None}]
    for who in [*people, *((HER,) if her else ())]:
        on = who in picked
        nxt = ({who} if not on else set()) if single else (picked ^ {who})
        out.append({"text": r.short(who),
                    "on": on, "pressed": on, "count": counts.get(who) if counts is not None else None,
                    "href": link(base, qui=",".join(sorted(nxt, key=lambda k: (k != YOURS, k == HER, k))) or None,
                                 ev=None),
                    "muted": counts is not None and not counts.get(who)})
    return out


def people_of(r: Read) -> list[str]:
    keys = list(dict.fromkeys(c.who for c in r.calendars))
    if YOURS in keys:
        keys.remove(YOURS)
    return [YOURS, *keys]


def legend(r: Read, picked: set[str], hidden: set[str], base: Mapping[str, str]) -> dict[str, Any]:
    """Les agendas montrés, par personne : chacun cochable, sa sorte, l'état de sa synchro ; son agenda à elle."""
    groups = []
    shown = total = 0
    people = [p for p in people_of(r) if not picked or p in picked]
    for who in people:
        rows = []
        for c in r.calendars:
            if c.who != who or not c.followed:
                continue
            total += 1
            on = c.key not in hidden
            shown += on
            said = synced(r.ports, r.frame, c, lambda t: stamp(r, t) if t else "jamais")
            sub = KIND_SHORT.get(c.kind, c.kind) + (" · masqué" if c.hidden else "") + \
                (f" · {said.label}" if said.tone == "warn" else "")
            rows.append({"key": c.key, "name": c.name, "color": r.colors.get(c.key, "ardoise"), "on": on, "sub": sub,
                         "warn": said.tone == "warn", "dot": "warn" if said.tone == "warn" else "ok" if said.tone == "ok"
                         else "", "title": f"{said.label} · {said.when}", "href": subject_url(KIND, c.key)})
        if not rows:
            continue
        owners = [str(o) for o in r.frame.get(identity_c.OWNERS) or ()]
        head = (f"Toi · {r.short(owners[0])}" if len(owners) == 1 and r.look.name(owners[0]) != owners[0] else "Toi") \
            if who == YOURS else r.short(who)
        fiche = "" if who == YOURS else subject_url("person", who, "agendas")
        groups.append({"title": head, "fiche": fiche, "rows": rows})
    if not picked or HER in picked or bool(picked - {HER}):
        total += 1
        shown += HER not in hidden
        names = [r.whose(w) for w in people if w != HER]
        sub = "sa mémoire · lecture seule" if not picked or HER in picked else \
            "ce qu'elle retient pour " + " et ".join(names)
        groups.append({"title": r.ui.her_name(), "fiche": "", "rows": [
            {"key": HER, "name": r.her_title, "color": ROSE, "on": HER not in hidden, "sub": sub, "warn": False,
             "dot": "",
             "title": "", "href": link(base, qui=HER), "her": True}]})
    accounts = [a for a in shown_accounts(r.ports, r.frame, r.calendars) if not a.system]
    warned = sum(1 for a in accounts if synced(r.ports, r.frame, a, str).tone == "warn")
    return {"groups": groups, "shown": shown, "total": total, "accounts": len(accounts), "warned": warned,
            "zone": str(getattr(r.frame.env.tz_of(r.frame.root), "key", "") or "UTC")}


def banner(r: Read, picked: set[str]) -> dict[str, str] | None:
    """Le seul bandeau : le premier compte à reconnecter ou en panne, parmi ceux qu'on montre."""
    for a in shown_accounts(r.ports, r.frame, r.calendars):
        if a.system or (picked and a.who not in picked):
            continue
        said = synced(r.ports, r.frame, a, str)
        if said.tone != "warn":
            continue
        whose = "à toi" if a.who == YOURS else f"à {r.short(a.who)}"
        names = ", ".join(f"« {c.name} »" for c in a.calendars)
        if a.state is not None and a.state.synced_at:
            since = r.frame.local(a.state.synced_at)
            text = f"depuis {day_long(since.date())} à {since.strftime('%H:%M')}" + \
                (f" : {'son agenda' if len(a.calendars) == 1 else 'ses agendas'} {names} "
                 f"n'{'est' if len(a.calendars) == 1 else 'sont'} plus à jour." if names else ".")
            text = f"{text} {said.error}".strip()
        else:
            text = "depuis qu'il est branché : il n'a encore jamais été relu. Son propriétaire le connecte dans son " \
                   "espace (Paramètres › Agendas)."
        return {"title": f"{r.labels.get(a.account) or KIND_SHORT.get(a.kind, a.kind)} ({whose}) est {said.label}",
                "text": text, "href": f"{PREFIX}/agendas/comptes"}
    return None


# ── la semaine, le mois, la liste ──


def classes(r: Read, x: Item, opened: str) -> list[str]:
    out = [f"c-{x.color}"]
    if x.end <= r.now:
        out.append("p")
    if x.invitation:
        out.append("inv")
    if x.proposed:
        out.append("prop")
    if x.private:
        out.append("prive")
    if x.hers:
        out.append("mika")
    if x.key == opened:
        out.append("sel")
    return out


def tip(r: Read, x: Item) -> str:
    extra = " · invitation sans réponse" if x.invitation else " · proposé par elle" if x.proposed else ""
    who = r.whose(x.who)
    return f"{x.title} · {day_short(x.first)} {hours(r, x)} · {x.calendar_name} ({who}){extra}"


def _slot(r: Read, at: int) -> int:
    t = r.frame.local(at)
    return (t.hour - FIRST_HOUR) * 4 + t.minute // 15 + 1


def lanes(spans: list[tuple[int, int, Item]]) -> list[tuple[tuple[int, int, Item], int, int]]:
    """Les éléments qui se chevauchent côte à côte : leur couloir, et combien de couloirs a leur groupe."""
    spans.sort(key=lambda t: (t[0], -t[1]))
    groups: list[list[tuple[int, int, Item]]] = []
    current: list[tuple[int, int, Item]] = []
    end = 0
    for s in spans:
        if current and s[0] >= end:
            groups.append(current)
            current, end = [], 0
        current.append(s)
        end = max(end, s[1])
    if current:
        groups.append(current)
    out = []
    for g in groups:
        ends: list[int] = []
        placed = []
        for s in g:
            for k, e in enumerate(ends):
                if s[0] >= e:
                    ends[k] = s[1]
                    placed.append(k)
                    break
            else:
                ends.append(s[1])
                placed.append(len(ends) - 1)
        n = min(len(ends), LANES)
        out += [(s, min(k, n - 1), n) for s, k in zip(g, placed, strict=True)]
    return out


def week(r: Read, found: Sequence[Item], first: date, base: Mapping[str, str], opened: str) -> dict[str, Any]:
    """La semaine : ses jours, sa ligne « journée », sa grille de 8 h à 22 h (les quarts d'heure en lignes, douze
    sous-colonnes par jour), le trait de maintenant."""
    days = [first + timedelta(days=i) for i in range(7)]
    today = r.frame.local(r.now).date()
    whole = [x for x in found if x.all_day or x.first != x.last and (x.end - x.start) >= DAY]
    rows: list[tuple[int, int, int]] = []
    allday = []
    for x in whole:
        c0, c1 = max(0, (x.first - first).days), min(6, (x.last - first).days)
        if c1 < 0 or c0 > 6:
            continue
        row = 0
        while any(rr == row and not (c1 < a0 or c0 > a1) for rr, a0, a1 in rows):
            row += 1
        rows.append((row, c0, c1))
        allday.append({"x": x, "cls": ["agc-ade", *classes(r, x, opened), f"dc-{c0 + 1}", f"ds-{c1 - c0 + 1}",
                                       f"ar-{min(row, 5) + 1}"],
                       "mcls": ["agc-ade", "agc-m-only", *classes(r, x, opened)],
                       "href": link(base, ev=x.key), "tip": tip(r, x)})
    timed = [x for x in found if x not in whole]
    columns = []
    for n, d in enumerate(days):
        spans = []
        for x in timed:
            if x.first != d:
                continue
            s = min(SLOTS - 1, max(1, _slot(r, x.start)))
            stop = _slot(r, x.end) if r.frame.local(x.end).date() == d else SLOTS + 1
            e = min(SLOTS + 1, max(s + 2, stop))
            spans.append((s, e, x))
        events = []
        for (s, e, x), k, count in lanes(spans):
            width = LANES // count
            cls = ["agc-ev", *classes(r, x, opened), f"gs-{s}", f"ge-{e}", f"cs-{k * width + 1}", f"cw-{width}"]
            if e - s <= 3:
                cls.append("short")
            if r.frame.local(x.end).date() != d or r.frame.local(x.end).hour >= LAST_HOUR and \
                    r.frame.local(x.end).minute > 0:
                cls.append("suite")
            events.append({"x": x, "cls": cls, "hours": hours(r, x), "href": link(base, ev=x.key), "tip": tip(r, x)})
        mobile = [a for a in allday if a["x"].first <= d <= a["x"].last]
        now_slot = _slot(r, r.now) if d == today and FIRST_HOUR <= r.frame.local(r.now).hour < LAST_HOUR else 0
        columns.append({"n": n + 1, "date": d, "name": day_long(d).capitalize(), "today": d == today,
                        "events": events, "mobile": mobile, "now": now_slot, "empty": not events and not mobile})
    return {"heads": [{"day": DAYS_SHORT[d.weekday()], "n": d.day, "today": d == today} for d in days],
            "allday": allday, "hours": [{"slot": (h - FIRST_HOUR) * 4 + 1, "text": f"{h:02d}:00",
                                         "first": h == FIRST_HOUR} for h in range(FIRST_HOUR, LAST_HOUR)],
            "columns": columns, "label": f"Semaine du {num(days[0])} au {num(days[-1])} {MONTHS[days[-1].month - 1]}",
            "zone": r.frame.local(r.now).strftime("UTC%z")[:-2].replace("+0", "+").replace("-0", "-")}


def month(r: Read, found: Sequence[Item], first: date, last: date, focus: date, base: Mapping[str, str]) -> dict:
    """Le mois : une case par jour, de ses premières lignes aux dernières (les jours d'à côté, grisés), trois éléments
    au plus par case."""
    today = r.frame.local(r.now).date()
    cells = []
    d = first
    while d <= last:
        of_day = [x for x in found if x.first <= d <= x.last]
        cells.append({"date": d, "n": f"1er {SHORT_MONTHS[d.month - 1]}" if d.day == 1 else str(d.day),
                      "out": d.month != focus.month, "today": d == today,
                      "chips": [{"x": x, "cls": ["agc-chip", f"c-{x.color}", *(["allday"] if x.all_day else []),
                                                 *[c for c in classes(r, x, "") if c in ("p", "prop", "mika")]],
                                 "hour": "" if x.all_day else hm(r, x.start), "tip": tip(r, x),
                                 "href": link(base, vue=None, du=x.first.isoformat(), ev=x.key)}
                                for x in of_day[:MONTH_SHOWN]],
                      "more": max(0, len(of_day) - MONTH_SHOWN)})
        d += timedelta(days=1)
    return {"heads": DAYS_SHORT, "cells": cells, "label": f"{MONTHS[focus.month - 1]} {focus.year}"}


def plan(r: Read, found: Sequence[Item], first: date, base: Mapping[str, str]) -> list[dict[str, Any]]:
    """La liste : jour par jour, ce qui a lieu, avec à qui c'est."""
    out = []
    today = r.frame.local(r.now).date()
    for i in range(7):
        d = first + timedelta(days=i)
        of_day = [x for x in found if x.first <= d <= x.last]
        if not of_day:
            continue
        rows = []
        for x in of_day:
            whose = ("pour " + " et ".join(r.whose(r.who_of_person(p)) for p in x.date.persons)) \
                if x.hers and x.date is not None and x.date.persons else r.whose(x.who)
            extra = "invitation sans réponse" if x.invitation else "proposé par elle" if x.proposed else \
                "" if x.private else x.location
            rows.append({"x": x, "cls": ["agc-plan-row", f"c-{x.color}", *[c for c in classes(r, x, "")
                                                                          if c in ("p", "prop", "mika")]],
                         "hours": hours(r, x), "extra": extra, "where": f"{x.calendar_name} · {whose}",
                         "href": link(base, vue=WEEK, ev=x.key)})
        out.append({"date": d, "name": relative_day(r, d) if today <= d <= today + timedelta(days=1)
                    else WEEKDAYS[d.weekday()].capitalize(), "sub": f"{num(d)} {MONTHS[d.month - 1]}",
                    "today": d == today, "rows": rows})
    return out


# ── un événement ouvert ──


def _person_words(p: Participant) -> str:
    return p.name or p.address or p.person or "quelqu'un"


def _write_feed(r: Read, w: Written, args: Mapping[str, Any], texts: Mapping[str, str]) -> dict[str, Any]:
    label, tone = WRITE_STATUS.get(w.status, (w.status, ""))
    if w.op == RESPOND:
        what = f"Réponse préparée : « {ANSWER_WORDS.get(str(args.get('response') or ''), '?')} » — {label}."
    elif not w.approval:
        what = f"Ajouté seule, sans demander : son tableau le lui permet — {label}."
    else:
        what = f"Proposé ({w.op}) — {label}."
    return {"time": stamp(r, w.at), "tone": "ok" if w.status == "fait" else "accent" if w.status == WAITING else
            "muted", "text": what, "quote": str(args.get("comment") or "") or texts.get(w.summary_ref, "")}


def reader(r: Read, x: Item, base: Mapping[str, str]) -> dict[str, Any]:
    """Un élément ouvert, à côté de la vue : son agenda et à qui, son titre, quand, ses étiquettes, ses faits ; ce
    qu'elle en a fait ; où le décider ; ses liens."""
    c = r.calendar(x.calendar)
    tags: list[tuple[str, str]] = []
    facts: list[dict[str, Any]] = []
    feed: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    links: list[tuple[str, str]] = []
    keeps: list[dict[str, str]] = []
    st = r.state
    if x.hers and x.date is not None:
        d = x.date
        label, tone = HER_KINDS.get(d.kind, (d.kind, ""))
        tags.append((label, tone))
        if d.secret:
            tags.append(("confié en secret", "warn"))
        facts += [{"label": "Pour", "text": ", ".join(r.whose(r.who_of_person(p)) for p in d.persons) or "—"},
                  {"label": "D'où", "text": d.source}]
        keeps.append({"text": d.title, "sub": d.source})
        keeps.append({"text": "On ne l'édite pas : on le lui dit (« c'est reporté », « oublie ça »).", "sub": ""})
        if (href := conversation_of(r.ui, d.conversation)):
            links.append(("Leur conversation", href))
        top = f"{r.her_title} · sa mémoire"
    else:
        top = f"{x.calendar_name} · {'à toi' if x.who == YOURS else 'à ' + r.short(x.who)}"
        if x.proposed:
            tags.append(("proposé par elle · en attente", "warn"))
        elif x.invitation:
            tags.append(("invitation sans réponse", "warn"))
        elif x.private:
            tags.append(("privé", ""))
        elif x.occurrence is not None and x.occurrence.event.status != CANCELLED:
            tags.append(("confirmé" if x.occurrence.event.status != "provisoire" else "provisoire",
                         "ok" if x.occurrence.event.status != "provisoire" else ""))
        if x.by_her:
            tags.append(("ajouté par elle", "live"))
        e = x.occurrence.event if x.occurrence is not None else None
        if e is not None and e.recurring:
            tags.append(("répété", ""))
        if c is not None:
            facts.append({"label": "Agenda", "swatch": x.color, "text": c.name, "href": subject_url(KIND, c.key)})
            facts.append({"label": "Propriétaire", "text": r.whose(c.who)})
            facts.append({"label": "Compte", "text": f"{KIND_SHORT.get(c.kind, c.kind)} · {account_label(c)}"})
        location = (e.location if e is not None else x.location) or ""
        if location and not x.private:
            facts.append({"label": "Lieu", "text": location})
        if e is not None and e.conference and not x.private:
            facts.append({"label": "Visio", "text": e.conference})
        if e is not None and e.participants and not x.private:
            people = []
            if e.organizer is not None and all(p.address != e.organizer.address for p in e.participants):
                people.append({"name": _person_words(e.organizer), "tag": ANSWERS[""]})
            for p in e.participants:
                organizes = e.organizer is not None and p.address and p.address == e.organizer.address
                people.append({"name": _person_words(p) + (" (ce compte)" if p.me else ""),
                               "tag": ANSWERS[""] if organizes else ANSWERS.get(p.response, (p.response, ""))})
            facts.append({"label": "Participants", "people": people})
        elif e is not None and e.organizer is not None and not x.private:
            facts.append({"label": "Organisé par", "text": _person_words(e.organizer)})
        if st is not None and x.occurrence is not None and c is not None:
            o = x.occurrence
            delay = o.event.remind or c.reminder
            facts.append({"label": "rappel", "text": REMINDER_WORDS.get(delay, delay) if delay else "non"})
            feed += _occurrence_feed(r, c, o, delay)
            for w, args in _writes_on(r, o):
                if w.op == RESPOND and w.status == WAITING:
                    blocks.append({"title": f"Sa réponse préparée : « {ANSWER_WORDS.get(str(args.get('response')), '?')} »",
                                   "quote": str(args.get("comment") or ""),
                                   "text": "Elle attend l'accord de la personne, dans son chat, ou le tien ici.",
                                   "href": f"{APPROVALS}?demande={w.proposal}"})
        if x.proposed and x.write is not None:
            w = x.write
            texts = r.look.texts([w.summary_ref])
            blocks.append({"title": f"Pas encore dans « {x.calendar_name} » : elle propose de l'ajouter",
                           "quote": "", "text": "Hachuré tant qu'il attend un accord ; refusé, il disparaît.",
                           "href": f"{APPROVALS}?demande={w.proposal}"})
            feed.append({"time": stamp(r, w.at), "tone": "accent", "text": "Proposé d'ajouter, depuis la conversation.",
                         "quote": texts.get(w.summary_ref, "")})
            if (href := conversation_of(r.ui, str(x.args.get("ref") or ""))):
                links.append(("Leur conversation", href))
        if e is not None and e.added is not None and (href := conversation_of(r.ui, e.added.ref)):
            links.append(("Leur conversation", href))
        if c is not None:
            links.insert(0, ("La fiche de l'agenda", subject_url(KIND, c.key)))
    return {"top": top, "color": x.color, "title": x.title, "marked": x.marked, "when": when_long(r, x), "tags": tags,
            "facts": facts, "feed": feed, "blocks": blocks, "keeps": keeps, "hers": x.hers,
            "links": list(dict.fromkeys(links)), "close": link(base, ev=None)}


def _writes_on(r: Read, o: Occurrence) -> list[tuple[Written, dict[str, Any]]]:
    """Ce qu'elle a proposé d'écrire sur cet événement (une réponse d'invitation, une modification…), avec ses
    arguments."""
    if r.state is None:
        return []
    e = o.event
    found = [w for w in r.state.writes.values() if w.calendar == e.calendar and w.uid and w.uid == e.uid
             and (not w.occurrence or not o.key or w.occurrence == o.key)]
    args = proposal_args(r.ui, [w.proposal for w in found])
    return [(w, args.get(w.proposal) or {}) for w in sorted(found, key=lambda w: w.proposal)]


def _occurrence_feed(r: Read, c: Shown, o: Occurrence, delay: str) -> list[dict[str, Any]]:
    """Ce qu'elle a fait d'une occurrence : ajoutée par elle, une invitation remarquée et sa réponse préparée, ce
    qu'elle a proposé d'y écrire, son rappel — dit, dû, tombé, ou prévu."""
    assert r.state is not None
    e = o.event
    out: list[dict[str, Any]] = []
    if e.added is not None and e.added.at:
        out.append({"time": stamp(r, e.added.at), "tone": "ok", "text": "Ajouté par elle, depuis la conversation.",
                    "quote": ""})
    inv = r.state.invitations.get(invitation_key(e))
    if inv is not None:
        out.append({"time": stamp(r, inv.at), "tone": "muted", "text": "Invitation remarquée : elle en prépare la "
                    "réponse, qui ne part qu'avec un accord.", "quote": ""})
    writes = _writes_on(r, o)
    texts = r.look.texts([w.summary_ref for w, _ in writes])
    out += [_write_feed(r, w, a, texts) for w, a in writes]
    rem = r.state.reminders.get(reminder_key(o))
    if rem is not None:
        label, _tone = REMINDED_WORDS.get(rem.status, (rem.status, ""))
        if rem.status == agenda_c.TOLD:
            out.append({"time": stamp(r, rem.told_at), "tone": "accent", "text": f"Rappel {label} à "
                        f"{r.look.name(rem.person)}, {REMINDER_WORDS.get(rem.delay, rem.delay)}.", "quote": ""})
        elif rem.status == agenda_c.DROPPED:
            out.append({"time": stamp(r, rem.due_at), "tone": "muted",
                        "text": f"Rappel tombé : {DROPPED_WHY.get(rem.why, rem.why)}.", "quote": ""})
        else:
            out.append({"time": stamp(r, rem.due_at), "tone": "warn", "text": "Rappel dû : elle le dit dès que "
                        "l'arbitre le laisse passer.", "quote": ""})
    elif delay and delay != "non":
        at = planned_reminder(r.frame, delay, o)
        if at is not None and at > r.now:
            out.append({"time": stamp(r, at), "tone": "muted",
                        "text": f"Rappel prévu, {REMINDER_WORDS.get(delay, delay)}.", "quote": ""})
    return out


def find_opened(r: Read, wanted: str, found: Sequence[Item]) -> Item | None:
    return next((x for x in found if x.key == wanted), None) if wanted else None


# ── Tous les agendas ──


def tous(got: Got) -> Any:
    """Tous les agendas : la légende, la semaine (ou le mois, ou la liste), l'événement ouvert."""
    if got.ui.kernel.ports.get("agenda") is None:
        return None
    r = read(got.ui)
    base = _query(got)
    picked = chosen(str(got.query.get(WHOSE, "")))
    hidden = hidden_of(got, r.calendars)
    view = str(got.query.get(VIEW, "") or WEEK)
    view = view if view in (WEEK, MONTH, LIST) else WEEK
    try:
        focus = date.fromisoformat(str(got.query.get(FROM, ""))) if got.query.get(FROM) else \
            r.frame.local(r.now).date()
    except ValueError:
        focus = r.frame.local(r.now).date()
    if view == MONTH:
        first_of = focus.replace(day=1)
        start_day = week_of(first_of)
        nxt = first_of.replace(year=first_of.year + 1, month=1) if first_of.month == 12 else \
            first_of.replace(month=first_of.month + 1)
        end_day = week_of(nxt - timedelta(days=1)) + timedelta(days=6)
        prev_focus, next_focus = (first_of - timedelta(days=1)).replace(day=1), nxt
        label = f"{MONTHS[first_of.month - 1]} {first_of.year}"
    else:
        start_day = week_of(focus)
        end_day = start_day + timedelta(days=6)
        prev_focus, next_focus = start_day - timedelta(days=7), start_day + timedelta(days=7)
        label = (f"{num(start_day)} {MONTHS[start_day.month - 1] + ' ' if start_day.month != end_day.month else ''}"
                 f"– {num(end_day)} {MONTHS[end_day.month - 1]} {end_day.year}")
    start, end = bounds(r.frame, start_day, end_day)
    found = items(r, picked, hidden, start, end)
    opened = find_opened(r, str(got.query.get(OPEN, "")), found)
    period = {"label": label, "today": link(base, du=None, ev=None),
              "prev": link(base, du=prev_focus.isoformat(), ev=None),
              "next": link(base, du=next_focus.isoformat(), ev=None), "unit": "Mois" if view == MONTH else "Semaine"}
    context = {
        "view": view, "period": period, "chips": chips(r, picked, base, people_of(r)),
        "legend": legend(r, picked, hidden, base), "banner": banner(r, picked), "hidden": sorted(hidden),
        "opened": reader(r, opened, base) if opened is not None else None, "base": base,
        "week": week(r, found, start_day, base, opened.key if opened else "") if view == WEEK else None,
        "month": month(r, found, start_day, end_day, focus, base) if view == MONTH else None,
        "plan": plan(r, found, start_day, base) if view == LIST else None, "her": got.ui.her_name(),
        "base_query": urlencode({k: v for k, v in base.items() if k not in (HIDDEN, OPEN)})}
    head, _rest = got.lift()
    return got.draw("handmade/agendas/tous.html", **context), [], got.head(items=head)


# ── Comptes ──


def comptes(got: Got) -> Any:
    """Chaque compte, en liste serrée."""
    if got.ui.kernel.ports.get("agenda") is None:
        return None
    r = read(got.ui)
    base = _query(got)
    picked = chosen(str(got.query.get(WHOSE, "")))
    people = people_of(r)
    accounts = shown_accounts(r.ports, r.frame, r.calendars)
    counts_by: dict[str, int] = {}
    for a in accounts:
        counts_by[a.who] = counts_by.get(a.who, 0) + 1
    events = count_events(r.ports, [c.key for c in r.calendars])
    levels = dict(SHARES)
    rows = []
    warned = 0
    for a in accounts:
        if picked and a.who not in picked:
            continue
        cals = a.calendars
        said = synced(r.ports, r.frame, a, lambda t: r.look.day(t) if t else "jamais")
        warned += said.tone == "warn"
        shared = [{"cal": x.name, "who": r.look.name(who[len(PERSON):]),
                   "href": subject_url("person", who[len(PERSON):], "agendas"),
                   "level": levels.get(level, level).lower()} for x in cals for who, level in sorted(x.shares.items())]
        address = a.state.address if a.state is not None else ""
        rows.append({"label": address, "system": a.system,
                     "name": "Ce serveur" if a.system else r.labels.get(a.account, a.account),
                     "kind": KIND_SHORT.get(a.kind, a.kind),
                     "who": "à toi" if a.who == YOURS else f"à {r.short(a.who)}",
                     "who_href": "" if a.who == YOURS else subject_url("person", a.who, "agendas"),
                     "calendars": [{"name": x.name, "href": subject_url(KIND, x.key), "color": r.colors.get(x.key),
                                    "notes": " · ".join(filter(None, ("masqué" if x.hidden else "",
                                                                      "lecture seule" if x.read_only else "",
                                                                      "plus suivi" if not x.followed else "",
                                                                      f"{events.get(x.key, 0)} événement"
                                                                      f"{'s' if events.get(x.key, 0) > 1 else ''}")))}
                                   for x in cals],
                     "said": said, "mode": "" if a.system else SYNC_MODE.get(a.kind, ""), "shared": shared,
                     "fiche": subject_url(KIND, cals[0].key) if cals else "", "warn": said.tone == "warn",
                     "sync": None if a.system or a.off else {"url": SYNC_ACTION, "subject": cals[0].key,
                                                              "nonce": secrets.token_urlsafe(12)} if cals else None})
    total = len(accounts)
    all_warned = sum(1 for a in accounts if synced(r.ports, r.frame, a, str).tone == "warn")
    return got.draw("handmade/agendas/comptes.html", rows=rows, warned=warned, csrf=getattr(got.forms, "csrf", ""),
                    pager=render._pager(Pager(size=max(1, len(rows)), total=max(1, len(rows))), {}),
                    back=f"{PREFIX}/agendas/comptes" + (link(base) if base else ""),
                    chips=chips(r, picked, base, people, her=False, counts=counts_by, single=True),
                    facts={"accounts": total, "calendars": len(r.calendars), "ok": total - all_warned,
                           "warned": all_warned, "window": _window_words(r)}), [], got.head(items=got.lift()[0])


def _window_words(r: Read) -> str:
    p = params_of(r.frame)
    past, ahead = p.past_us // DAY, p.ahead_us // DAY
    return f"{past} jours derrière, {'un an' if ahead in (365, 366) else f'{ahead} jours'} devant"


# ── Ce qu'elle en fait ──


def _for(r: Read, picked: set[str], person: str) -> bool:
    return not picked or r.who_of_person(person) in picked


def fait(got: Got) -> Any:
    """Ses rappels, ses propositions d'ajout, ses réponses d'invitation, ce qu'elle a ajouté seule."""
    r = read(got.ui)
    base = _query(got)
    picked = chosen(str(got.query.get(WHOSE, "")))
    st = r.state
    reminders: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    invitations: list[dict[str, Any]] = []
    alone: list[dict[str, Any]] = []
    store = r.ports.get("agenda")
    names = {c.key: c for c in r.calendars}
    if st is not None:
        rem = sorted(st.reminders.values(), key=lambda x: -(x.told_at or x.due_at))
        events = {x.event: store.event(x.event) for x in rem if x.event} if store is not None else {}
        for x in rem:
            if not _for(r, picked, x.person):
                continue
            c = names.get(x.calendar)
            e = events.get(x.event)
            title = "Occupé · privé" if e is not None and e.private and not sees_private(r.frame, x.calendar) else \
                e.title if e is not None else "(un rendez-vous parti)"
            label, tone = REMINDED_WORDS.get(x.status, (x.status, ""))
            facts = [("pour", r.look.name(x.person)),
                     ("rendez-vous", f"{stamp(r, x.start)} · {REMINDER_WORDS.get(x.delay, x.delay)}")]
            if x.told_to:
                facts.append(("par", x.told_to))
            if x.status == agenda_c.DROPPED:
                facts.append(("pourquoi", DROPPED_WHY.get(x.why, x.why)))
            reminders.append({"title": title, "tags": [(label, tone)], "cal": c, "color": r.colors.get(x.calendar),
                              "time": stamp(r, x.told_at or x.due_at), "text": "", "facts": facts,
                              "links": [("Leur conversation →", subject_url("person", x.person, "echanges"))]})
        writes = sorted(st.writes.values(), key=lambda w: -w.proposal)
        args = proposal_args(got.ui, [w.proposal for w in writes[:200]])
        texts = r.look.texts([w.summary_ref for w in writes[:200]])
        for w in writes[:200]:
            target = r.look.person_of(w.target) if w.target else ""
            if picked and not (target and _for(r, picked, target)) and not _for(r, picked, _holder_person(r, w)):
                continue
            a = args.get(w.proposal) or {}
            draft = a.get("draft") or {}
            span = draft.get("span") or {}
            label, tone = WRITE_STATUS.get(w.status, (w.status, ""))
            c = names.get(w.calendar)
            entry: dict[str, Any] = {"cal": c, "color": r.colors.get(w.calendar), "time": stamp(r, w.at),
                                     "tags": [(label, tone)], "text": texts.get(w.summary_ref, ""), "facts": [],
                                     "links": [], "waiting": w.status == WAITING and w.approval}
            if target:
                entry["facts"].append(("pour", r.look.name(target)))
            if w.status == WAITING and w.approval:
                entry["links"].append(("Examiner →", f"{APPROVALS}?demande={w.proposal}"))
            if (href := conversation_of(got.ui, str(a.get("ref") or ""))):
                entry["links"].append(("Leur conversation →", href))
            if w.by:
                entry["facts"].append(("décidé par", r.look.name(r.look.person_of(w.by)) if w.by != "délai" else
                                       "le délai"))
            if w.op == RESPOND:
                e = store.find(w.calendar, w.uid, w.original) if store is not None and w.uid else None
                answer = ANSWER_WORDS.get(str(a.get("response") or ""), "?")
                entry["title"] = f"{e.title if e is not None else 'Une invitation'} · « {answer} »"
                entry["text"] = str(a.get("comment") or "") or entry["text"]
                if e is not None and e.organizer is not None:
                    entry["facts"].append(("de la part de", _person_words(e.organizer)))
                if a.get("why"):
                    entry["facts"].append(("pourquoi", str(a["why"])))
                invitations.append(entry)
            elif w.op == CREATE:
                entry["title"] = str(draft.get("title") or "(sans titre)")
                if span.get("start"):
                    entry["facts"].append(("le", stamp(r, int(span["start"]))))
                (proposals if w.approval else alone).append(entry)
            elif not w.approval:
                entry["title"] = {"modifier": "Un événement modifié", "supprimer": "Un événement supprimé"}.get(
                    w.op, w.op)
                alone.append(entry)
            else:
                entry["title"] = {"modifier": "Modifier un événement", "supprimer": "Supprimer un événement"}.get(
                    w.op, w.op)
                proposals.append(entry)
    waiting = sum(1 for w in (st.writes.values() if st is not None else ()) if w.status == WAITING and w.approval)
    people = people_of(r)
    return got.draw("handmade/agendas/fait.html", chips=chips(r, picked, base, people, her=False, single=True),
                    reminders=reminders, proposals=proposals, invitations=invitations, alone=alone,
                    upcoming=_upcoming(r, picked), waiting=waiting,
                    settings=f"{PREFIX}/agendas/parametres#rappels", rights=f"{PREFIX}/reglages/droits#d-agendas",
                    initiatives=f"{PREFIX}/decisions/initiatives", approvals=APPROVALS), [], ""


def _holder_person(r: Read, w: Written) -> str:
    c = r.calendar(w.calendar)
    return "" if c is None else (r.look.person_of(c.holder[len(PERSON):]) if c.holder else "")


def _upcoming(r: Read, picked: set[str]) -> list[str]:
    """Les prochains rappels prévus, dans les deux jours : quoi, quand, à quel délai."""
    store = r.ports.get("agenda")
    if store is None:
        return []
    shown = [c for c in r.calendars if (not picked or c.who in picked) and c.reminder not in ("", "non")
             and not c.hidden and not c.off]
    out = []
    for cal in shown:
        for o in store.period([cal.key], r.now, r.now + 2 * DAY):
            delay = o.event.remind or cal.reminder
            at = planned_reminder(r.frame, delay, o)
            if at is not None and at > r.now:
                title = "Occupé · privé" if o.event.private and not sees_private(r.frame, cal.key) else o.event.title
                out.append((at, f"{title} ({r.whose(cal.who)}), {stamp(r, at)} "
                                f"({REMINDER_WORDS.get(delay, delay)})"))
    return [t for _at, t in sorted(out)[:4]]


# ── Son agenda ──


def mika(got: Got) -> Any:
    """Son agenda à elle : ses promesses datées, ce qu'elle voit venir, les dates qui reviennent ; par personne."""
    r = read(got.ui)
    base = _query(got)
    picked = chosen(str(got.query.get(WHOSE, "")))
    today = r.frame.local(r.now).date()
    end_of_week = week_of(today) + timedelta(days=7)
    _start, week_end = bounds(r.frame, today, end_of_week - timedelta(days=1))
    every = call(her_agenda, got.ui.kernel, label="son agenda")
    every = [] if isinstance(every, Failed) else list(every)

    def whos(d: Any) -> set[str]:
        return {r.who_of_person(p) for p in d.persons}

    counts: dict[str, int] = {}
    for d in every:
        if d.start < week_end:
            for w in whos(d):
                counts[w] = counts.get(w, 0) + 1
    chosen_dates = [d for d in every if not picked or whos(d) & picked]
    more = bool(got.query.get("plus"))
    shown = [d for d in chosen_dates if more or d.start < week_end]
    entries = []
    for d in shown:
        label, tone = HER_KINDS.get(d.kind, (d.kind, ""))
        start = r.frame.local(d.start)
        when = day_short(start.date()) if d.all_day else f"{day_short(start.date())} · {start.strftime('%H:%M')}"
        tags = [(label, tone)] + ([("confié en secret", "warn")] if d.secret else [])
        links = [(t, h) for t, h in (("Leur conversation →", conversation_of(got.ui, d.conversation)),) if h]
        entries.append({"title": d.title, "time": when, "tags": tags,
                        "facts": [("pour", " et ".join(r.whose(w) for w in whos(d)) or "—"), ("d'où", d.source)],
                        "links": links, "href": "?" + urlencode({VIEW: WEEK, FROM: start.date().isoformat(),
                                                                 OPEN: f"m{d.ref.partition(':')[2]}"})})
    later = sum(1 for d in chosen_dates if d.start >= week_end)
    kinds = {k: sum(1 for d in chosen_dates if d.kind == k) for k in (PROMISE, MOMENT, YEARLY, AHEAD)}
    people = [w for w in people_of(r) if w in counts or w == YOURS]
    return got.draw("handmade/agendas/mika.html", her=got.ui.her_name(), title=r.her_title,
                    chips=chips(r, picked, base, people, her=False, counts=counts, single=True), entries=entries,
                    later=later, more=more, kinds=kinds, more_href=link(base, plus="1"),
                    less_href=link(base, plus=None),
                    promises=f"{PREFIX}/memoire/promesses", moments=f"{PREFIX}/memoire/moments",
                    grid=f"{PREFIX}/agendas/tous?" + urlencode({WHOSE: HER}),
                    week=f"du {num(today)} au {num(end_of_week - timedelta(days=1))} "
                         f"{MONTHS[(end_of_week - timedelta(days=1)).month - 1]}"), [], ""


TABS: dict[str, Any] = {
    "agendas/tous": Tab(tous, *STYLES),
    "agendas/comptes": Tab(comptes, *STYLES),
    "agendas/fait": Tab(fait, *STYLES),
    "agendas/mika": Tab(mika, *STYLES),
}

__all__ = ["TABS"]

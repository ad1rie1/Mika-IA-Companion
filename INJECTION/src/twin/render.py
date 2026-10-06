"""Montrer des séances à Claude Code : un texte lisible, numéroté, sans ambiguïté sur qui parle.

    Personnes :
    - p12 : Julie Martin (amie)

    ## Séance s345 — WhatsApp avec Julie Martin (p12) — mardi 12 mars 2019
    [m4567] 14:05 Julie Martin (p12) : t'es où ?
    [m4568] 14:06 ELLE : j'arrive !!

Ses messages à elle sont « ELLE » ; chaque autre personne porte son identifiant du corpus.
Une date imprécise se dit telle quelle (« vers mars 2009 », « date inconnue »).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from twin.corpus import Corpus
from twin.dating import describe
from twin.records import MSN
from twin.timing import Precision, Temps, from_us

DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]
CHANNEL_WORDS = {"whatsapp": "WhatsApp", "messenger": "Messenger", "instagram": "Instagram", "msn": "MSN",
                 "sms": "SMS", "signal": "Signal", "mail": "mail", "notes": "notes"}
#: un message très long (un mail) est coupé : la lecture reste dans son budget
MAX_MESSAGE_CHARS = 4000
MAX_DOCUMENT_CHARS = 20000


@dataclass
class Rendered:
    text: str
    sessions: list[str] = field(default_factory=list)  # « s345 », « d45 »
    her_messages: dict[str, list[int]] = field(default_factory=dict)  # séance → ses messages
    all_messages: dict[str, set[int]] = field(default_factory=dict)  # séance → tous ses messages
    persons: set[int] = field(default_factory=set)


def day_words(us: int, tz: ZoneInfo) -> str:
    d = from_us(us, tz)
    return f"{DAYS[d.weekday()]} {'1er' if d.day == 1 else d.day} {MONTHS[d.month - 1]} {d.year}"


def when_words(t: Temps, tz: ZoneInfo) -> str:
    if t.point is None:
        return "date inconnue" if t.start is None and t.end is None else describe(t, tz)
    if t.precision in (Precision.EXACT, Precision.DAY):
        return day_words(t.point, tz)
    return "vers " + describe(t, tz)


def her_name(corpus: Corpus) -> str:
    """Son nom : celui que la revue lui donne (``elle.nom``), sinon celui que ses archives disent le plus souvent —
    un vrai nom (carnet d'adresses, profil, mails) avant un pseudo MSN (« Léa ~ zik » n'est pas un prénom) ;
    « elle » à défaut."""
    row = corpus.db.execute("SELECT name FROM persons WHERE is_me = 1").fetchone()
    if row and row["name"] and row["name"] != "elle":
        return str(row["name"])
    weights = {(r["name"], r["channel"] == MSN): r["n"] for r in corpus.db.execute(
        "SELECT pa.name, pa.channel, COUNT(m.id) n FROM participants pa JOIN persons p ON p.id = pa.person "
        "LEFT JOIN messages m ON m.author = pa.id WHERE p.is_me = 1 AND pa.name != '' GROUP BY pa.name, pa.channel")}
    if not weights:
        return "elle"
    name, _nick = max(weights, key=lambda k: (not k[1], weights[k]))
    return str(name)


def render_sessions(corpus: Corpus, session_ids: list[int], tz: ZoneInfo) -> Rendered:
    db = corpus.db
    me = db.execute("SELECT id FROM persons WHERE is_me = 1").fetchone()
    me_id = me["id"] if me else -1
    person_of = {r["id"]: r["person"] for r in db.execute("SELECT id, person FROM participants")}
    names = {r["id"]: (r["name"], r["relation"]) for r in db.execute("SELECT id, name, relation FROM persons")}
    out = Rendered("")
    blocks: list[str] = []
    for sid in session_ids:
        s = db.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        if s is None:
            continue
        if s["document"] is not None:
            blocks.append(_document_block(db, s, tz, out))
        else:
            blocks.append(_conversation_block(db, s, tz, out, person_of, names, me_id))
    glossary = ["Personnes :"] + [
        f"- p{pid} : {names[pid][0]}" + (f" ({names[pid][1]})" if names[pid][1] else "")
        for pid in sorted(out.persons) if pid in names] if out.persons else []
    out.text = "\n".join(glossary) + ("\n\n" if glossary else "") + "\n\n".join(blocks)
    return out


def _conversation_block(db: sqlite3.Connection, s: sqlite3.Row, tz: ZoneInfo, out: Rendered,
                        person_of: dict[int, int], names: dict[int, tuple[str, str]], me_id: int) -> str:
    key = f"s{s['id']}"
    conv = db.execute("SELECT * FROM conversations WHERE id = ?", (s["conversation"],)).fetchone()
    persons = json.loads(s["persons"] or "[]")
    out.persons.update(persons)
    who = ", ".join(f"{names[p][0]} (p{p})" for p in persons if p in names) or "?"
    kind = "groupe « " + conv["title"] + " »" if conv["is_group"] else "avec " + who
    t = Temps.from_row(s["t_start"], s["t_end"], s["t_point"], s["t_precision"], s["t_origin"])
    lines = [f"## Séance {key} — {CHANNEL_WORDS.get(conv['channel'], conv['channel'])} {kind} — {when_words(t, tz)}"]
    if conv["is_group"]:
        lines.append(f"(présents : {who})")
    out.sessions.append(key)
    out.her_messages[key] = []
    out.all_messages[key] = set()
    last_day = None
    for m in db.execute("SELECT * FROM messages WHERE session = ? ORDER BY t_point IS NULL, t_point, rank",
                        (s["id"],)):
        out.all_messages[key].add(m["id"])
        person = person_of.get(m["author"]) if m["author"] is not None else None
        if person == me_id:
            speaker = "ELLE"
            out.her_messages[key].append(m["id"])
        elif person is not None and person in names:
            speaker = f"{names[person][0]} (p{person})"
            out.persons.add(person)
        else:
            speaker = "(système)"
        clock = ""
        if m["t_point"] is not None and m["t_precision"] == Precision.EXACT.value:
            local = from_us(m["t_point"], tz)
            if last_day is not None and local.date() != last_day:
                lines.append(f"— {day_words(m['t_point'], tz)} —")
            last_day = local.date()
            clock = f"{local:%H:%M} "
        text = m["text"] if len(m["text"]) <= MAX_MESSAGE_CHARS else m["text"][:MAX_MESSAGE_CHARS] + " […]"
        attachments = json.loads(m["attachments"] or "[]")
        if attachments:
            text = (text + " " if text else "") + "[" + ", ".join(attachments[:3]) + "]"
        if m["subject"]:
            text = f"(objet : {m['subject']}) {text}"
        lines.append(f"[m{m['id']}] {clock}{speaker} : {text}")
    return "\n".join(lines)


def _document_block(db: sqlite3.Connection, s: sqlite3.Row, tz: ZoneInfo, out: Rendered) -> str:
    d = db.execute("SELECT * FROM documents WHERE id = ?", (s["document"],)).fetchone()
    key = f"d{d['id']}"
    out.sessions.append(key)
    out.her_messages[key] = []
    out.all_messages[key] = set()
    t = Temps.from_row(d["t_start"], d["t_end"], d["t_point"], d["t_precision"], d["t_origin"])
    kind = {"journal": "son journal", "note": "une de ses notes"}.get(d["kind"], "un de ses textes")
    text = d["text"] if len(d["text"]) <= MAX_DOCUMENT_CHARS else d["text"][:MAX_DOCUMENT_CHARS] + "\n[…]"
    title = f" « {d['title']} »" if d["title"] and d["kind"] != "journal" else ""
    return f"## Texte {key} — {kind}{title} — {when_words(t, tz)}\n{text}"

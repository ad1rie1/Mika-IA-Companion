"""Oublier quelqu'un avant l'injection : ``jumeau oublier <personne>``.

Une personne de ses archives peut demander à ne pas y être (ou on le décide pour elle). Avant
l'avance rapide, on la retire du corpus et de ce qui en a été tiré :

- ses messages, partout ; leurs tête-à-tête **entiers** (les réponses d'« elle » à cette
  personne ne se comprennent pas sans elle, et parlent d'elle) ;
- les séances où elle parlait : leur annotation est jetée et la séance repart en lecture,
  sans elle (``jumeau lire``) ; ailleurs, les souvenirs, croyances, événements, rêves et
  promesses qui la nomment sont retirés des annotations ;
- son profil, et les synthèses qui la nomment (mois, chapitres, persona, journaux, rêves) :
  ``jumeau synthetiser`` les refera ;
- l'oubli est **gardé** (table ``decisions``) : une source relue ne la fait pas revenir.

Ce qui reste à faire à la main est dit, jamais fait en silence : ses textes à elle (notes,
journaux) qui la nomment sont listés, pas modifiés ; une vie déjà vécue (``sortie/vie``)
s'oublie avec le moteur (``mika forget``), qui sait effacer ce qui la concerne.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from twin.corpus import Corpus
from twin.dates import fold

#: les champs d'une annotation où un élément nomme ses personnes
ITEM_FIELDS = ("souvenirs", "croyances", "evenements", "reves")


@dataclass
class ForgetReport:
    name: str
    handle: str
    participants: int = 0
    conversations: int = 0
    messages: int = 0
    sessions_reread: int = 0
    annotation_items: int = 0
    syntheses: int = 0
    documents_naming: list[str] = field(default_factory=list)


def find_person(corpus: Corpus, who: str) -> sqlite3.Row:
    """« p12 », « ext_julie-martin » ou un nom (exact, sans accents ni majuscules) : une seule personne."""
    db = corpus.db
    m = re.fullmatch(r"p?(\d+)", who.strip())
    if m:
        rows = db.execute("SELECT * FROM persons WHERE id = ? AND is_me = 0", (int(m.group(1)),)).fetchall()
    else:
        wanted = fold(who.strip())
        rows = [r for r in db.execute("SELECT * FROM persons WHERE is_me = 0")
                if r["handle"] == who.strip() or fold(r["name"]) == wanted]
    if len(rows) != 1:
        found = ", ".join(f"p{r['id']} {r['name']}" for r in rows) or "personne"
        raise ValueError(f"« {who} » désigne {found} : donner le numéro (p12) ou l'adresse (ext_…)")
    return rows[0]


def forget_person(corpus: Corpus, who: str) -> ForgetReport:
    db = corpus.db
    person = find_person(corpus, who)
    pid = int(person["id"])
    report = ForgetReport(person["name"], person["handle"])
    tag = f"p{pid}"
    parts = db.execute("SELECT * FROM participants WHERE person = ?", (pid,)).fetchall()
    part_ids = {int(r["id"]) for r in parts}
    me_ids = {int(r["id"]) for r in db.execute(
        "SELECT pa.id FROM participants pa JOIN persons p ON p.id = pa.person WHERE p.is_me = 1")}
    report.participants = len(parts)

    with corpus.transaction():
        # 1. l'oubli est gardé avant tout : une ingestion ne la fera pas revenir
        for r in parts:
            _decide(db, f"{r['channel']}:{r['key']}")
        # 2. leurs tête-à-tête, entiers ; ses messages ailleurs
        gone_messages: set[int] = set()
        for c in db.execute("SELECT * FROM conversations WHERE is_group = 0").fetchall():
            members = {int(r["participant"]) for r in db.execute(
                "SELECT participant FROM members WHERE conversation = ?", (c["id"],))}
            if members & part_ids and members <= part_ids | me_ids:
                _decide(db, f"conversation:{c['channel']}:{c['key']}")
                gone_messages |= {int(r["id"]) for r in db.execute(
                    "SELECT id FROM messages WHERE conversation = ?", (c["id"],))}
                db.execute("DELETE FROM members WHERE conversation = ?", (c["id"],))
                db.execute("DELETE FROM conversations WHERE id = ?", (c["id"],))
                report.conversations += 1
        if part_ids:
            marks = ",".join("?" * len(part_ids))
            gone_messages |= {int(r["id"]) for r in db.execute(
                f"SELECT id FROM messages WHERE author IN ({marks})", tuple(part_ids))}  # noqa: S608
        touched = _sessions_of(db, gone_messages) | {
            int(r["id"]) for r in db.execute("SELECT s.id FROM sessions s, json_each(s.persons) j WHERE j.value = ?",
                                             (pid,))}
        for chunk in _chunks(sorted(gone_messages)):
            db.execute(f"DELETE FROM messages WHERE id IN ({','.join('?' * len(chunk))})", chunk)  # noqa: S608
        report.messages = len(gone_messages)
        # 3. les séances où elle était : relues sans elle ; une séance vidée disparaît
        report.sessions_reread = _reset_sessions(db, touched, pid)
        # 4. ailleurs, ce que les annotations disent d'elle
        report.annotation_items = _scrub_annotations(db, tag, gone_messages)
        # 5. les synthèses qui la nomment, à refaire
        report.syntheses = _drop_syntheses(db, tag, person["name"])
        # 6. elle-même
        if part_ids:
            marks = ",".join("?" * len(part_ids))
            db.execute(f"DELETE FROM members WHERE participant IN ({marks})", tuple(part_ids))  # noqa: S608
            db.execute(f"DELETE FROM participants WHERE id IN ({marks})", tuple(part_ids))  # noqa: S608
        db.execute("DELETE FROM persons WHERE id = ?", (pid,))
    corpus.rebuild_search()
    report.documents_naming = _documents_naming(db, person["name"])
    return report


def _decide(db: sqlite3.Connection, ref: str) -> None:
    db.execute("INSERT OR IGNORE INTO decisions (kind, ref, value) VALUES ('oubli', ?, '')", (ref,))


def _chunks(ids: list[int], size: int = 500) -> list[tuple[int, ...]]:
    return [tuple(ids[i: i + size]) for i in range(0, len(ids), size)]


def _sessions_of(db: sqlite3.Connection, messages: set[int]) -> set[int]:
    out: set[int] = set()
    for chunk in _chunks(sorted(messages)):
        out |= {int(r["session"]) for r in db.execute(
            f"SELECT DISTINCT session FROM messages WHERE session IS NOT NULL AND id IN ({','.join('?' * len(chunk))})",  # noqa: S608
            chunk)}
    return out


def _has_table(db: sqlite3.Connection, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone() is not None


def _reset_sessions(db: sqlite3.Connection, sessions: set[int], pid: int) -> int:
    """Une séance où elle parlait perd son annotation et repart en lecture ; vidée, elle disparaît. Les lots déjà
    faits qui la contenaient l'oublient aussi (sinon ``jumeau lire`` la croirait déjà lue)."""
    if not sessions:
        return 0
    for sid in sessions:
        left = db.execute("SELECT COUNT(*) n, COALESCE(SUM(LENGTH(text)), 0) c FROM messages WHERE session = ?",
                          (sid,)).fetchone()
        row = db.execute("SELECT persons, document FROM sessions WHERE id = ?", (sid,)).fetchone()
        if row is None:
            continue
        if row["document"] is None and left["n"] == 0:
            db.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        else:
            persons = [p for p in json.loads(row["persons"] or "[]") if p != pid]
            db.execute("UPDATE sessions SET persons = ?, n_messages = CASE WHEN document IS NULL THEN ? "
                       "ELSE n_messages END, chars = CASE WHEN document IS NULL THEN ? ELSE chars END, status = 'todo' "
                       "WHERE id = ?", (json.dumps(persons), left["n"], left["c"], sid))
    if _has_table(db, "annotations"):
        for chunk in _chunks(sorted(sessions)):
            db.execute(f"DELETE FROM annotations WHERE session IN ({','.join('?' * len(chunk))})", chunk)  # noqa: S608
    if _has_table(db, "jobs"):
        for r in db.execute("SELECT id, payload FROM jobs WHERE pass = 'annoter'").fetchall():
            payload = json.loads(r["payload"])
            kept = [s for s in payload.get("sessions", []) if s not in sessions]
            if kept != payload.get("sessions", []):
                db.execute("UPDATE jobs SET payload = ? WHERE id = ?", (json.dumps({**payload, "sessions": kept}), r["id"]))
    return len(sessions)


def _names_her(item: dict[str, Any], tag: str) -> bool:
    return tag in (item.get("personnes") or []) or str(item.get("envers", "")).strip() == tag


def _scrub_annotations(db: sqlite3.Connection, tag: str, gone: set[int]) -> int:
    if not _has_table(db, "annotations"):
        return 0
    removed = 0
    for r in db.execute("SELECT rowid, data FROM annotations").fetchall():
        data = json.loads(r["data"])
        before = sum(len(data.get(f) or []) for f in (*ITEM_FIELDS, "promesses"))
        for f in (*ITEM_FIELDS, "promesses"):
            data[f] = [x for x in data.get(f) or [] if not _names_her(x, tag)]
        data["emotions"] = [e for e in data.get("emotions") or [] if e.get("id") not in gone]
        after = sum(len(data.get(f) or []) for f in (*ITEM_FIELDS, "promesses"))
        if after != before or gone:
            db.execute("UPDATE annotations SET data = ? WHERE rowid = ?", (json.dumps(data, ensure_ascii=False),
                                                                          r["rowid"]))
        removed += before - after
    return removed


def _drop_syntheses(db: sqlite3.Connection, tag: str, name: str) -> int:
    if not _has_table(db, "syntheses"):
        return 0
    first = name.split()[0] if name.split() else name
    pattern = re.compile(rf"(?<![\w]){re.escape(tag)}(?!\d)|\b{re.escape(first)}\b", re.I) if first else \
        re.compile(rf"(?<![\w]){re.escape(tag)}(?!\d)")
    gone = [r["rowid"] for r in db.execute("SELECT rowid, kind, key, data FROM syntheses")
            if (r["kind"] == "profil" and r["key"].startswith(f"{tag}:")) or pattern.search(r["data"])]
    for chunk in _chunks(gone):
        db.execute(f"DELETE FROM syntheses WHERE rowid IN ({','.join('?' * len(chunk))})", chunk)  # noqa: S608
    return len(gone)


def _documents_naming(db: sqlite3.Connection, name: str) -> list[str]:
    """Ses textes à elle qui la nomment : listés pour une relecture, jamais modifiés."""
    words = [w for w in re.findall(r"\w{3,}", fold(name))][:2]
    if not words:
        return []
    query = " ".join(f'"{w}"' for w in words)
    return [r["key"] for r in db.execute(
        "SELECT d.key FROM fts_documents JOIN documents d ON d.id = fts_documents.rowid "
        "WHERE fts_documents MATCH ? LIMIT 200", (query,))]

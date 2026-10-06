"""Dater sans modèle : l'ordre des sources, puis les corrections à la main.

``date_corpus`` reprend chaque suite ordonnée (les messages d'une conversation dans une
source, les entrées d'un journal dans son fichier), applique ``timing.propagate`` et
écrit ce qui a changé. Les conflits vont dans la table ``conflicts`` et dans la revue.

``travail/dates.yaml`` est la revue : ce qui reste sans date ou en plage large, par
source, et les conflits. On y écrit une date à la main (``date: "mars 2009"``,
``"2009-03-12"``, ``"été 2009"``, ``"2008..2010"``) ; le passage suivant l'applique
(origine ``manuel``) avant de propager. Ce que Claude Code saura dater par le contenu
et les recoupements viendra ensuite (étape 2, origine ``contenu`` / ``recoupement``).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from twin.corpus import Corpus
from twin.dates import find_date
from twin.timing import RANK, Origin, Precision, Temps, from_us, propagate

#: au-delà de cette précision, un élément est « à revoir »
REVIEW_FROM = Precision.YEAR


@dataclass
class DatingReport:
    sequences: int = 0
    narrowed: int = 0
    interpolated: int = 0
    conflicts: int = 0
    manual: int = 0
    to_review: dict[str, int] = field(default_factory=dict)


def parse_manual(text: str, tz: ZoneInfo) -> Temps | None:
    """Une date écrite à la main : « 2009-03-12 », « mars 2009 », « été 2009 », « 2008..2010 »."""
    text = str(text).strip()
    if ".." in text:
        a, b = (s.strip() for s in text.split("..", 1))
        ta, tb = find_date(a, tz, Origin.MANUAL), find_date(b, tz, Origin.MANUAL)
        if ta is None or tb is None or ta.start is None or tb.end is None or ta.start > tb.end:
            return None
        return Temps.span(ta.start, tb.end, Origin.MANUAL)
    return find_date(text, tz, Origin.MANUAL)


def apply_manual(corpus: Corpus, review_path: Path, tz: ZoneInfo) -> int:
    if not review_path.is_file():
        return 0
    data = yaml.safe_load(review_path.read_text(encoding="utf-8")) or {}
    n = 0
    for entry in data.get("a_dater", []) or []:
        when = entry.get("date")
        if not when:
            continue
        t = parse_manual(str(when), tz)
        if t is None:
            continue
        table = "documents" if entry.get("document") else "messages"
        if table == "documents":
            rows = corpus.db.execute("SELECT id FROM documents WHERE key = ?", (entry["document"],)).fetchall()
        else:
            rows = corpus.db.execute(
                "SELECT m.id FROM messages m JOIN sources s ON s.id = m.source WHERE s.path = ? AND m.t_precision "
                "NOT IN ('exacte')", (entry.get("source", ""),)).fetchall()
        for r in rows:
            corpus.db.execute(f"UPDATE {table} SET t_start = ?, t_end = ?, t_point = ?, t_precision = ?, "  # noqa: S608
                              "t_origin = ? WHERE id = ?", (*t.as_row(), r["id"]))
            n += 1
    corpus.db.commit()
    return n


def date_corpus(corpus: Corpus, review_path: Path, tz: ZoneInfo) -> DatingReport:
    report = DatingReport()
    report.manual = apply_manual(corpus, review_path, tz)
    db = corpus.db
    for table, group in (("messages", "source, conversation"), ("documents", "source")):
        keys = db.execute(f"SELECT DISTINCT {group} FROM {table}").fetchall()  # noqa: S608
        for key in keys:
            cond = " AND ".join(f"{col.strip()} = ?" for col in group.split(","))
            rows = db.execute(f"SELECT * FROM {table} WHERE {cond} ORDER BY rank, id", tuple(key)).fetchall()  # noqa: S608
            _date_sequence(corpus, table, rows, report)
    db.commit()
    write_review(corpus, review_path, tz, report)
    return report


def _date_sequence(corpus: Corpus, table: str, rows: list[sqlite3.Row], report: DatingReport) -> None:
    if len(rows) < 2:
        return
    report.sequences += 1
    before = [corpus.temps_of(r) for r in rows]
    if all(t.precision == Precision.EXACT for t in before) and all(
            a.point <= b.point for a, b in zip(before, before[1:], strict=False)):  # type: ignore[operator]
        return  # le cas courant (un fil de messagerie) : rien à faire
    after, conflicts = propagate(before)
    for r, old, new in zip(rows, before, after, strict=True):
        if new != old:
            corpus.db.execute(f"UPDATE {table} SET t_start = ?, t_end = ?, t_point = ?, t_precision = ?, "  # noqa: S608
                              "t_origin = ? WHERE id = ?", (*new.as_row(), r["id"]))
            if new.origin == Origin.INTERPOLATED and not old.known:
                report.interpolated += 1
            else:
                report.narrowed += 1
    for c in conflicts:
        corpus.db.execute("INSERT OR IGNORE INTO conflicts (table_name, ref, reason) VALUES (?, ?, ?)",
                          (table, rows[c.index]["id"], c.reason))
        report.conflicts += 1


def write_review(corpus: Corpus, path: Path, tz: ZoneInfo, report: DatingReport) -> None:
    """La revue : par source, ce qui reste mal daté ; les documents un par un (ils sont peu nombreux)."""
    db = corpus.db
    entries: list[dict[str, object]] = []
    for r in db.execute(
            "SELECT d.key, d.title, d.t_start, d.t_end, d.t_point, d.t_precision, d.t_origin, s.path FROM documents d "
            "JOIN sources s ON s.id = d.source ORDER BY s.path, d.rank"):
        t = corpus.temps_of(r)
        if RANK[t.precision] >= RANK[REVIEW_FROM]:
            entries.append({"document": r["key"], "titre": r["title"][:80], "estime": describe(t, tz), "date": ""})
    for r in db.execute(
            "SELECT s.path, COUNT(*) n, MIN(m.t_start) lo, MAX(m.t_end) hi FROM messages m JOIN sources s "
            "ON s.id = m.source WHERE m.t_precision IN ('annee', 'plage', 'inconnue') GROUP BY s.path"):
        span = Temps.span(r["lo"], r["hi"], Origin.NONE)
        entries.append({"source": r["path"], "messages": r["n"], "estime": describe(span, tz), "date": ""})
    conflicts = [
        {"table": c["table_name"], "id": c["ref"], "raison": c["reason"]}
        for c in db.execute("SELECT * FROM conflicts WHERE resolved = 0 ORDER BY table_name, ref LIMIT 500")]
    for e in entries:
        key = "documents" if "document" in e else "messages"
        report.to_review[key] = report.to_review.get(key, 0) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ("# Revue des dates — écrire une date dans « date » puis relancer `jumeau dater`.\n"
              "# Formes acceptées : 2009-03-12 · 12/03/2009 · mars 2009 · été 2009 · 2009 · 2008..2010\n"
              "# Une date laissée vide ne change rien. Les conflits se règlent dans la source ou ici.\n")
    body = yaml.safe_dump({"a_dater": entries, "conflits": conflicts}, allow_unicode=True, sort_keys=False, width=110)
    path.write_text(header + body, encoding="utf-8")


def describe(t: Temps, tz: ZoneInfo) -> str:
    """Une date en clair pour un humain (« vers mars 2009 », « entre 2008 et 2010 »)."""
    if t.start is None and t.end is None:
        return "inconnue"
    if t.start is None:
        return f"au plus tard le {from_us(t.end, tz):%d/%m/%Y}"  # type: ignore[arg-type]
    if t.end is None:
        return f"au plus tôt le {from_us(t.start, tz):%d/%m/%Y}"
    a, b = from_us(t.start, tz), from_us(t.end, tz)
    if t.precision in (Precision.EXACT, Precision.DAY):
        return f"{from_us(t.point or t.start, tz):%d/%m/%Y %H:%M}"
    if t.precision == Precision.MONTH:
        return f"{a:%m/%Y}"
    if t.precision == Precision.YEAR and a.year == b.year:
        return str(a.year)
    return f"entre le {a:%d/%m/%Y} et le {b:%d/%m/%Y}"

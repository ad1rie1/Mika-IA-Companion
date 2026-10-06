"""Le serveur MCP « jumeau » : le corpus, en lecture, pour Claude Code.

Deux usages :

- en **session** (``INJECTION/.mcp.json``) : on demande à Claude Code « qui est Paul ? »,
  « relis la séance s345 », « quand a-t-elle écrit cette note ? », et il cherche lui-même ;
- en **lot**, pour la datation par recoupement : le moteur ouvre ce serveur à la CLI, qui
  cherche dans le corpus daté de quoi ancrer un texte qui ne l'est pas.

Lecture seule par défaut. Avec ``--ecriture`` (sessions seulement), deux outils
consignent une décision : une date retrouvée (``date_fixer``), une relation ou un nom
(``personne_noter``). Les textes rendus sont des extraits bornés : un outil ne déverse
jamais le corpus entier.

    python -m twin.mcp [--racine INJECTION] [--ecriture]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from twin.corpus import Corpus
from twin.dates import fold
from twin.dating import DOCUMENT, describe, parse_manual, remember_date
from twin.mcp.protocol import Prompt, Server, Tool, ToolFailure
from twin.render import render_sessions, when_words
from twin.sessions import refresh_session_time
from twin.timing import RANK, Origin, Precision, Temps, from_us

MAX_TOOL_CHARS = 30_000


def _str(args: Mapping[str, Any], key: str, default: str = "") -> str:
    v = args.get(key, default)
    return default if v is None else str(v)


def _int(args: Mapping[str, Any], key: str, default: int, lo: int = 1, hi: int = 200) -> int:
    try:
        return max(lo, min(hi, int(args.get(key, default))))
    except (TypeError, ValueError):
        return default


def fts_query(text: str) -> str:
    """Une recherche libre en requête FTS5 sûre : chaque mot entre guillemets."""
    words = re.findall(r"\w+", fold(text))
    if not words:
        raise ToolFailure("recherche vide")
    return " ".join(f'"{w}"' for w in words[:12])


class JumeauTools:
    def __init__(self, corpus: Corpus, tz: ZoneInfo, *, write: bool = False) -> None:
        self.corpus = corpus
        self.db = corpus.db
        self.tz = tz
        self.write = write

    # -- lecture -----------------------------------------------------------------------------------------

    def stats(self, _args: Mapping[str, Any]) -> str:
        s = self.corpus.stats()
        lo, hi = s["span"]  # type: ignore[misc]
        span = (f"du {from_us(lo, self.tz):%d/%m/%Y} au {from_us(hi, self.tz):%d/%m/%Y}" if lo and hi else "—")
        return json.dumps({**{k: v for k, v in s.items() if k != "span"}, "periode": span}, ensure_ascii=False)

    def search(self, args: Mapping[str, Any]) -> str:
        q = fts_query(_str(args, "requete"))
        limit = _int(args, "limite", 20, hi=50)
        after = parse_manual(_str(args, "apres"), self.tz) if args.get("apres") else None
        before = parse_manual(_str(args, "avant"), self.tz) if args.get("avant") else None
        person = _person_id(_str(args, "personne"))
        clauses, params = [], [q]
        if after and after.start is not None:
            clauses.append("m.t_point >= ?")
            params.append(after.start)
        if before and before.end is not None:
            clauses.append("m.t_point <= ?")
            params.append(before.end)
        if person is not None:
            clauses.append("m.session IN (SELECT s.id FROM sessions s, json_each(s.persons) j WHERE j.value = ?)")
            params.append(person)
        where = (" AND " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.execute(
            "SELECT m.id, m.session, m.t_start, m.t_end, m.t_point, m.t_precision, m.t_origin, c.channel, pe.name, "
            "pe.is_me, snippet(fts_messages, 0, '«', '»', '…', 14) AS extrait FROM fts_messages "
            "JOIN messages m ON m.id = fts_messages.rowid JOIN conversations c ON c.id = m.conversation "
            "LEFT JOIN participants pa ON pa.id = m.author LEFT JOIN persons pe ON pe.id = pa.person "
            f"WHERE fts_messages MATCH ?{where} ORDER BY fts_messages.rank LIMIT ?", (*params, limit)).fetchall()
        out = [{"ref": f"m{r['id']}", "seance": f"s{r['session']}" if r["session"] else None,
                "quand": when_words(_temps(r), self.tz), "precision": r["t_precision"], "canal": r["channel"],
                "qui": "elle" if r["is_me"] else (r["name"] or "?"), "extrait": r["extrait"]} for r in rows]
        if person is None:
            docs = self.db.execute(
                "SELECT d.id, d.kind, d.t_start, d.t_end, d.t_point, d.t_precision, d.t_origin, "
                "snippet(fts_documents, 1, '«', '»', '…', 14) AS extrait FROM fts_documents "
                "JOIN documents d ON d.id = fts_documents.rowid WHERE fts_documents MATCH ? ORDER BY fts_documents.rank LIMIT ?",
                (q, limit)).fetchall()
            out += [{"ref": f"d{r['id']}", "quand": when_words(_temps(r), self.tz), "precision": r["t_precision"],
                     "canal": r["kind"], "qui": "elle", "extrait": r["extrait"]} for r in docs]
        return json.dumps(out[: limit * 2], ensure_ascii=False) if out else "aucun résultat"

    def read_session(self, args: Mapping[str, Any]) -> str:
        ref = _str(args, "ref").strip().lower()
        sid = self._session_of(ref)
        text = render_sessions(self.corpus, [sid], self.tz).text
        return text if len(text) <= MAX_TOOL_CHARS else text[:MAX_TOOL_CHARS] + "\n[… coupé]"

    def person(self, args: Mapping[str, Any]) -> str:
        pid = self._find_person(_str(args, "personne"))
        p = self.db.execute("SELECT * FROM persons WHERE id = ?", (pid,)).fetchone()
        parts = [dict(channel=r["channel"], nom=r["name"], adresse=r["address"]) for r in self.db.execute(
            "SELECT channel, name, address FROM participants WHERE person = ?", (pid,))]
        years = {str(from_us(r["t"], self.tz).year): r["n"] for r in self.db.execute(
            "SELECT MIN(m.t_point) t, COUNT(*) n FROM messages m JOIN participants pa ON pa.id = m.author "
            "WHERE pa.person = ? AND m.t_point IS NOT NULL GROUP BY strftime('%Y', m.t_point / 1000000, "
            "'unixepoch')", (pid,))}
        sessions = [f"s{r['id']} ({when_words(_temps(r), self.tz)}, {r['n_messages']} messages)" for r in self.db.execute(
            "SELECT s.* FROM sessions s, json_each(s.persons) j WHERE j.value = ? ORDER BY s.significance DESC "
            "LIMIT 8", (pid,))]
        return json.dumps({"id": f"p{pid}", "nom": p["name"], "relation": p["relation"], "adresse": p["handle"],
                           "ignoree": bool(p["ignored"]), "comptes": parts, "messages_par_an": years,
                           "seances_fortes": sessions}, ensure_ascii=False)

    def persons(self, args: Mapping[str, Any]) -> str:
        limit = _int(args, "limite", 30, hi=200)
        rows = self.db.execute(
            "SELECT p.id, p.name, p.relation, COUNT(m.id) n FROM persons p JOIN participants pa ON pa.person = p.id "
            "LEFT JOIN messages m ON m.author = pa.id WHERE p.is_me = 0 AND p.ignored = 0 GROUP BY p.id "
            "ORDER BY n DESC LIMIT ?", (limit,)).fetchall()
        return "\n".join(f"p{r['id']} · {r['name']}" + (f" ({r['relation']})" if r["relation"] else "")
                         + f" · {r['n']} messages" for r in rows) or "personne"

    def annotation(self, args: Mapping[str, Any]) -> str:
        sid = self._session_of(_str(args, "seance").strip().lower())
        row = self.db.execute("SELECT data FROM annotations WHERE session = ? ORDER BY version DESC LIMIT 1",
                              (sid,)).fetchone() if self._has_table("annotations") else None
        return row["data"] if row else "pas encore lue"

    def to_date(self, args: Mapping[str, Any]) -> str:
        limit = _int(args, "limite", 20, hi=100)
        worst = [p.value for p in Precision if RANK[p] >= RANK[Precision.YEAR]]
        rows = self.db.execute(
            f"SELECT id, kind, title, t_start, t_end, t_point, t_precision, t_origin FROM documents "
            f"WHERE t_precision IN ({','.join('?' * len(worst))}) ORDER BY id LIMIT ?", (*worst, limit)).fetchall()
        return "\n".join(f"d{r['id']} · {r['kind']} « {r['title'][:60]} » · estimé : {describe(_temps(r), self.tz)}"
                         for r in rows) or "rien à dater"

    # -- écriture (sessions seulement) -----------------------------------------------------------------------

    def fix_date(self, args: Mapping[str, Any]) -> str:
        if not self.write:
            raise ToolFailure("serveur en lecture seule")
        ref = _str(args, "ref").strip().lower()
        if not ref.startswith("d"):
            raise ToolFailure("seul un texte (d45) se date ici ; un fil de messages se date par sa source")
        did = int(ref[1:])
        row = self.db.execute("SELECT * FROM documents WHERE id = ?", (did,)).fetchone()
        if row is None:
            raise ToolFailure(f"{ref} n'existe pas")
        found = parse_manual(_str(args, "date"), self.tz)
        if found is None:
            raise ToolFailure("date illisible (formes : 2009-03-12, mars 2009, été 2009, 2009, 2008..2010)")
        anchors = [a for a in args.get("ancres") or [] if isinstance(a, str)]
        origin = Origin.CROSS if anchors else Origin.CONTENT
        found = Temps(found.start, found.end, found.point, found.precision, origin)
        current = _temps(row)
        merged = current.intersect(found) if current.start is not None or current.end is not None else found
        if merged is None:
            self.db.execute("INSERT OR IGNORE INTO conflicts (table_name, ref, reason) VALUES ('documents', ?, ?)",
                            (did, f"date proposée ({_str(args, 'date')}) incompatible avec l'estimation actuelle"))
            self.db.commit()
            raise ToolFailure(f"incompatible avec l'estimation actuelle ({describe(current, self.tz)}) : conflit noté")
        if not merged.finer_than(current) and merged == current:
            return f"rien de plus précis que l'estimation actuelle ({describe(current, self.tz)})"
        merged = Temps(merged.start, merged.end, merged.point, merged.precision, origin)
        self.db.execute("UPDATE documents SET t_start = ?, t_end = ?, t_point = ?, t_precision = ?, t_origin = ? "
                        "WHERE id = ?", (*merged.as_row(), did))
        remember_date(self.db, DOCUMENT, row["key"], merged)  # gardée : une relecture de la source ne l'efface pas
        session = self.db.execute("SELECT id FROM sessions WHERE document = ?", (did,)).fetchone()
        if session is not None:
            refresh_session_time(self.db, session["id"])
        self.db.commit()
        return f"{ref} daté : {describe(merged, self.tz)} ({origin.value})"

    def note_person(self, args: Mapping[str, Any]) -> str:
        if not self.write:
            raise ToolFailure("serveur en lecture seule")
        pid = self._find_person(_str(args, "personne"))
        name, relation = _str(args, "nom").strip(), _str(args, "relation").strip()
        if not name and not relation:
            raise ToolFailure("rien à noter : donner un nom ou une relation")
        row = self.db.execute("SELECT name, relation FROM persons WHERE id = ?", (pid,)).fetchone()
        self.db.execute("UPDATE persons SET name = ?, relation = ?, manual = 1, review = '' WHERE id = ?",
                        (name or row["name"], relation or row["relation"], pid))
        self.db.commit()
        return f"p{pid} noté (relancer `jumeau personnes` pour mettre la revue à jour)"

    # -- outils internes ----------------------------------------------------------------------------------------

    def _has_table(self, name: str) -> bool:
        return self.db.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone() is not None

    def _session_of(self, ref: str) -> int:
        m = re.fullmatch(r"([smd])(\d+)", ref)
        if not m:
            raise ToolFailure("référence attendue : s123 (séance), m123 (message) ou d45 (texte)")
        kind, n = m.group(1), int(m.group(2))
        if kind == "s":
            row = self.db.execute("SELECT id FROM sessions WHERE id = ?", (n,)).fetchone()
        elif kind == "m":
            row = self.db.execute("SELECT session AS id FROM messages WHERE id = ?", (n,)).fetchone()
        else:
            row = self.db.execute("SELECT id FROM sessions WHERE document = ?", (n,)).fetchone()
        if row is None or row["id"] is None:
            raise ToolFailure(f"{ref} introuvable (les séances se calculent avec `jumeau planifier`)")
        return int(row["id"])

    def _find_person(self, text: str) -> int:
        pid = _person_id(text)
        if pid is not None and self.db.execute("SELECT 1 FROM persons WHERE id = ?", (pid,)).fetchone():
            return pid
        key = fold(text).strip()
        rows = [r for r in self.db.execute("SELECT id, name FROM persons WHERE is_me = 0") if key and key in fold(r["name"])]
        if len(rows) == 1:
            return int(rows[0]["id"])
        if not rows:
            raise ToolFailure(f"personne inconnue : {text}")
        raise ToolFailure("plusieurs personnes : " + ", ".join(f"p{r['id']} {r['name']}" for r in rows[:10]))


def _person_id(text: str) -> int | None:
    m = re.fullmatch(r"\s*p(\d+)\s*", text or "", re.I)
    return int(m.group(1)) if m else None


def _temps(r: Any) -> Temps:
    return Temps.from_row(r["t_start"], r["t_end"], r["t_point"], r["t_precision"], r["t_origin"])


def build_server(corpus: Corpus, tz: ZoneInfo, *, write: bool = False) -> Server:
    t = JumeauTools(corpus, tz, write=write)
    obj: dict[str, Any] = {"type": "object"}

    def schema(**props: dict[str, Any]) -> dict[str, Any]:
        required = [k for k, v in props.items() if v.pop("_requis", False)]
        return {**obj, "properties": props, "required": required}

    s = Server("jumeau", "1", instructions=(
        "Le corpus des archives d'une personne (elle) : messages, mails, notes, journaux. Les références : s123 une "
        "séance, m123 un message, d45 un texte d'elle, p12 une personne. Les dates sont celles des archives, "
        "parfois imprécises : elles disent leur précision."))
    for tool in [
        Tool("corpus_stats", "Ce que contient le corpus : volumes, sources, période, précision des dates.",
             schema(), t.stats),
        Tool("corpus_chercher", "Recherche plein texte (sans accents) dans ses messages et ses textes, avec leur "
             "date. Filtres facultatifs : personne (p12), apres / avant (2009-03-12, mars 2009, 2009…).",
             schema(requete={"type": "string", "_requis": True}, limite={"type": "integer"},
                    personne={"type": "string"}, apres={"type": "string"}, avant={"type": "string"}), t.search),
        Tool("seance_lire", "Relire une séance (s123), la séance d'un message (m123) ou un de ses textes (d45).",
             schema(ref={"type": "string", "_requis": True}), t.read_session),
        Tool("personne_fiche", "Qui est cette personne : ses comptes, ses messages par an, ses séances fortes.",
             schema(personne={"type": "string", "_requis": True, "description": "p12 ou un nom"}), t.person),
        Tool("personnes_lister", "Les personnes de sa vie, des plus présentes aux moins présentes.",
             schema(limite={"type": "integer"}), t.persons),
        Tool("annotation_lire", "Ce que la lecture a retenu d'une séance (émotions, souvenirs…).",
             schema(seance={"type": "string", "_requis": True}), t.annotation),
        Tool("dates_a_revoir", "Ses textes dont la date est encore large ou inconnue.",
             schema(limite={"type": "integer"}), t.to_date),
    ]:
        s.tools[tool.name] = tool
    if write:
        s.tools["date_fixer"] = Tool(
            "date_fixer", "Consigner la date retrouvée d'un de ses textes (d45). « ancres » : les messages datés "
            "(m123) qui la prouvent. Jamais plus large que l'estimation actuelle ; une contradiction est notée.",
            schema(ref={"type": "string", "_requis": True}, date={"type": "string", "_requis": True},
                   ancres={"type": "array", "items": {"type": "string"}}, raison={"type": "string"}),
            t.fix_date, read_only=False)
        s.tools["personne_noter"] = Tool(
            "personne_noter", "Noter le vrai nom ou la relation d'une personne (mère, amie, collègue…).",
            schema(personne={"type": "string", "_requis": True}, nom={"type": "string"},
                   relation={"type": "string"}), t.note_person, read_only=False)
    for name in sorted(p.name for p in resources.files("twin.prompts").iterdir() if p.name.endswith(".md")):
        text = resources.files("twin.prompts").joinpath(name).read_text(encoding="utf-8")
        s.prompts[name[:-3]] = Prompt(name[:-3], f"la consigne « {name[:-3]} » du jumeau", lambda _a, t=text: t)
    return s


def main(argv: list[str] | None = None) -> int:
    from twin.cli import (
        default_root,  # noqa: PLC0415 — la CLI importe ce module : pas d'import circulaire au chargement
    )

    ap = argparse.ArgumentParser(prog="python -m twin.mcp")
    ap.add_argument("--racine", type=Path, default=default_root())
    ap.add_argument("--fuseau", default="Europe/Paris")
    ap.add_argument("--ecriture", action="store_true")
    args = ap.parse_args(argv)
    corpus = Corpus(args.racine / "travail" / "corpus.db")
    server = build_server(corpus, ZoneInfo(args.fuseau), write=args.ecriture)
    for line in sys.stdin:
        if not line.strip():
            continue
        reply = server.handle_line(line)
        if reply is not None:
            sys.stdout.write(reply + "\n")
            sys.stdout.flush()
    corpus.close()
    return 0

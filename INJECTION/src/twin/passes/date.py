"""La passe « dater par recoupement » : Claude Code date ce que l'ordre et les noms de fichiers n'ont pas pu dater.

Unités : ses textes (``d45``) et les séances (``s123``) dont la précision reste « année »,
« plage » ou « inconnue ». La CLI reçoit le serveur MCP « jumeau » en lecture
(recherche, relecture, fiches). Elle cherche dans le corpus daté de quoi ancrer chaque
élément, et rend des plages.

L'acceptation est prudente :

- une date qui contredit l'estimation actuelle devient un conflit, jamais un écrasement ;
- une date n'élargit jamais une plage, elle peut seulement la resserrer ;
- une ancre (``m123``) qui n'existe pas, ou qui n'est pas datée exactement, est écartée.
  Sans ancre valable, l'origine est « contenu », pas « recoupement ».

Elle travaille sur les **séances** : elle se lance donc après ``jumeau planifier``. Chaque séance
datée reprend aussitôt le temps de ses messages ; une date de texte est gardée comme décision
(une relecture de sa source ne l'efface pas). Après la passe, ``jumeau dater`` repropage par
l'ordre ce qui vient d'être fixé, puis ``jumeau planifier --garder-seances`` refait les paliers
et le budget avec les nouvelles dates.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from twin.corpus import Corpus
from twin.dating import DOCUMENT, describe, remember_date
from twin.engine.claude import CallResult, CallSpec
from twin.passes.annotate import prompt_text
from twin.render import her_name
from twin.schemas import lenient_list
from twin.sessions import refresh_session_time
from twin.timing import RANK, Origin, Precision, Temps

TO_DATE = tuple(p.value for p in Precision if RANK[p] >= RANK[Precision.YEAR])
TOOLS = ("mcp__jumeau__corpus_chercher", "mcp__jumeau__seance_lire", "mcp__jumeau__personne_fiche",
         "mcp__jumeau__corpus_stats")
MAX_EXCERPT = 3000


class Dated(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ref: str = Field(pattern=r"^[ds]\d+$")
    debut: date
    fin: date
    point: date | None = None
    ancres: list[str] = Field(default_factory=list)
    raison: str = Field(default="", max_length=500)
    certitude: float = Field(default=0.5, ge=0.0, le=1.0)


class DatedBatch(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dates: list[Dated]


def mcp_config(root: Path, path: Path) -> Path:
    """La configuration MCP du lot : le serveur « jumeau » en lecture, chemins absolus."""
    config = {"mcpServers": {"jumeau": {"type": "stdio", "command": sys.executable,
                                        "args": ["-m", "twin.mcp", "--racine", str(root)]}}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


class DatePass:
    name = "dater"
    version = 1

    def __init__(self, root: Path, tz: ZoneInfo, per_batch: int = 6, model: str = "sonnet") -> None:
        self.root = root
        self.tz = tz
        self.per_batch = per_batch
        self.model = model

    def units(self, corpus: Corpus) -> Iterable[tuple[str, dict[str, Any]]]:
        marks = ",".join("?" * len(TO_DATE))
        refs = [f"d{r['id']}" for r in corpus.db.execute(
            f"SELECT id FROM documents WHERE t_precision IN ({marks}) ORDER BY id", TO_DATE)]
        refs += [f"s{r['id']}" for r in corpus.db.execute(
            f"SELECT id FROM sessions WHERE document IS NULL AND t_precision IN ({marks}) ORDER BY id", TO_DATE)]
        for i in range(0, len(refs), self.per_batch):
            chunk = refs[i: i + self.per_batch]
            yield f"{chunk[0]}-{len(chunk)}", {"refs": chunk}

    def build(self, corpus: Corpus, payload: dict[str, Any]) -> CallSpec:
        blocks = [self._block(corpus, ref) for ref in payload["refs"]]
        prompt = "\n\n".join(b for b in blocks if b) + f"\n\n(Éléments à dater : {', '.join(payload['refs'])}.)"
        return CallSpec(prompt=prompt, system=prompt_text("dater.md").format(nom=her_name(corpus)),
                        schema=DatedBatch.model_json_schema(), model=self.model,
                        mcp_config=mcp_config(self.root, self.root / "travail" / "mcp-lot.json"),
                        allowed_tools=TOOLS, max_output_tokens=8000, timeout_s=1200)

    def _block(self, corpus: Corpus, ref: str) -> str:
        n = int(ref[1:])
        if ref.startswith("d"):
            d = corpus.db.execute("SELECT * FROM documents WHERE id = ?", (n,)).fetchone()
            t = corpus.temps_of(d)
            text = d["text"][:MAX_EXCERPT] + (" […]" if len(d["text"]) > MAX_EXCERPT else "")
            return (f"## {ref} — {d['kind']} « {d['title'][:80]} » (fichier : {d['path']})\n"
                    f"Estimation actuelle : {describe(t, self.tz)} ({t.origin.value})\n{text}")
        s = corpus.db.execute("SELECT * FROM sessions WHERE id = ?", (n,)).fetchone()
        t = Temps.from_row(s["t_start"], s["t_end"], s["t_point"], s["t_precision"], s["t_origin"])
        lines = [f"{'ELLE' if r['is_me'] else (r['name'] or '?')} : {r['text'][:300]}" for r in corpus.db.execute(
            "SELECT m.text, pe.name, pe.is_me FROM messages m LEFT JOIN participants pa ON pa.id = m.author "
            "LEFT JOIN persons pe ON pe.id = pa.person WHERE m.session = ? ORDER BY m.rank LIMIT 40", (n,))]
        return f"## {ref} — une conversation\nEstimation actuelle : {describe(t, self.tz)}\n" + "\n".join(lines)

    def accept(self, corpus: Corpus, unit: str, payload: dict[str, Any], result: CallResult) -> str | None:
        if not isinstance(result.data, dict):
            return "réponse sans objet JSON"
        items, _ = lenient_list(Dated, result.data.get("dates"))
        asked = set(payload["refs"])
        for item in items:
            if item.ref not in asked or item.fin < item.debut:
                continue
            self._apply(corpus, item)
        corpus.db.commit()
        return None

    def _apply(self, corpus: Corpus, item: Dated) -> None:
        anchors = [a for a in item.ancres if re.fullmatch(r"m\d+", a) and corpus.db.execute(
            "SELECT 1 FROM messages WHERE id = ? AND t_precision = 'exacte'", (int(a[1:]),)).fetchone()]
        origin = Origin.CROSS if anchors else Origin.CONTENT
        start = Temps.day(item.debut, self.tz, origin).start
        end = Temps.day(item.fin, self.tz, origin).end
        point = Temps.day(item.point, self.tz, origin).point if item.point else None
        if point is not None and not (start <= point <= end):  # type: ignore[operator]
            point = None
        found = Temps.span(start, end, origin, point=point)
        n = int(item.ref[1:])
        if item.ref.startswith("d"):
            rows = corpus.db.execute("SELECT * FROM documents WHERE id = ?", (n,)).fetchall()
            table = "documents"
        else:
            rows = corpus.db.execute("SELECT * FROM messages WHERE session = ? AND t_precision != 'exacte'",
                                     (n,)).fetchall()
            table = "messages"
        for r in rows:
            current = corpus.temps_of(r)
            merged = current.intersect(found) if (current.start is not None or current.end is not None) else found
            if merged is None:
                corpus.db.execute("INSERT OR IGNORE INTO conflicts (table_name, ref, reason) VALUES (?, ?, ?)",
                                  (table, r["id"], f"datation par contenu incompatible : {item.raison[:200]}"))
                continue
            if merged.width is not None and current.width is not None and merged.width >= current.width:
                continue  # rien de plus précis
            merged = Temps(merged.start, merged.end, merged.point, merged.precision, origin)
            corpus.db.execute(f"UPDATE {table} SET t_start = ?, t_end = ?, t_point = ?, t_precision = ?, "  # noqa: S608
                              "t_origin = ? WHERE id = ?", (*merged.as_row(), r["id"]))
            if table == "documents":
                remember_date(corpus.db, DOCUMENT, r["key"], merged)
        session = corpus.db.execute("SELECT id FROM sessions WHERE document = ?", (n,)).fetchone() \
            if item.ref.startswith("d") else {"id": n}
        if session is not None:
            refresh_session_time(corpus.db, session["id"])  # ses paliers et son budget se recalculent sur elle

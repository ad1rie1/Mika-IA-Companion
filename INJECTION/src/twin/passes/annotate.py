"""La passe « lire » : Claude Code annote les séances des paliers A, B et C.

Un **lot** réunit des séances d'un même palier, dans l'ordre d'une conversation, jusqu'à
environ ``jetons_par_lot`` jetons. Ses textes à elle (notes, journal) forment leurs propres
lots. La réponse est validée séance par séance :

- une séance absente repart dans une nouvelle tâche, au lieu de faire relire tout le lot ;
- un numéro de message qui n'appartient pas à la séance est écarté ;
- une émotion posée sur un message qui n'est pas d'elle est écartée.

Les annotations vont dans la table ``annotations`` (une ligne par séance et par version).
La séance passe alors à ``done``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from importlib import resources
from typing import Any
from zoneinfo import ZoneInfo

from twin.corpus import Corpus
from twin.engine.claude import CallResult, CallSpec
from twin.planning import tokens_of
from twin.render import her_name, render_sessions
from twin.schemas import BatchFull, BatchLight, SessionLight, parse_batch

ANNOTATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS annotations (
    session INTEGER NOT NULL, version INTEGER NOT NULL, tier TEXT NOT NULL, data TEXT NOT NULL,
    model TEXT DEFAULT '', PRIMARY KEY (session, version)
);
"""
#: les paliers lus à fond (C : le savoir d'archive, lu sans émotions par message)
FULL_TIERS = ("A", "C")
#: au-delà, une réponse qui oublie trop de séances est refaite d'un bloc
MAX_MISSING_SHARE = 0.5


def prompt_text(name: str) -> str:
    return resources.files("twin.prompts").joinpath(name).read_text(encoding="utf-8")


class AnnotatePass:
    name = "annoter"
    version = 1

    def __init__(self, tz: ZoneInfo, tokens_per_batch: int = 40_000, model: str = "sonnet") -> None:
        self.tz = tz
        self.tokens_per_batch = tokens_per_batch
        self.model = model

    # -- les lots -------------------------------------------------------------------------------------

    def units(self, corpus: Corpus) -> Iterable[tuple[str, dict[str, Any]]]:
        corpus.db.executescript(ANNOTATIONS_SCHEMA)
        done = {r["session"] for r in corpus.db.execute("SELECT session FROM annotations WHERE version = ?",
                                                        (self.version,))}
        queued = set()
        for r in corpus.db.execute("SELECT payload FROM jobs WHERE pass = ? AND version = ?", (self.name, self.version)):
            queued.update(json.loads(r["payload"])["sessions"])
        rows = corpus.db.execute(
            "SELECT id, tier, conversation, document, chars, t_point FROM sessions WHERE tier IN ('A', 'B', 'C') "
            "ORDER BY tier, document IS NOT NULL, conversation, t_point IS NULL, t_point, id").fetchall()
        batch: list[int] = []
        size = 0
        key: tuple[Any, ...] | None = None
        for r in rows:
            if r["id"] in done or r["id"] in queued:
                continue
            group = (r["tier"], r["document"] is not None)
            cost = tokens_of(r["chars"]) + 40
            if batch and (group != key or size + cost > self.tokens_per_batch):
                yield self._unit(key, batch)
                batch, size = [], 0
            batch.append(r["id"])
            size += cost
            key = group
        if batch and key is not None:
            yield self._unit(key, batch)

    def _unit(self, key: tuple[Any, ...] | None, sessions: list[int]) -> tuple[str, dict[str, Any]]:
        tier, docs = key if key else ("B", False)
        return f"{tier}{'-textes' if docs else ''}-{sessions[0]}-{len(sessions)}", {"tier": tier, "sessions": sessions}

    # -- l'appel --------------------------------------------------------------------------------------

    def build(self, corpus: Corpus, payload: dict[str, Any]) -> CallSpec:
        full = payload["tier"] in FULL_TIERS
        rendered = render_sessions(corpus, payload["sessions"], self.tz)
        extra = prompt_text("annoter_complet.md") if full else ""
        if payload["tier"] == "C":
            extra += ("\nCes échanges ne seront pas revécus, seulement retenus : laisse « emotions » vide, et "
                      "date chaque souvenir et chaque événement en absolu dans son texte.\n")
        system = prompt_text("annoter.md").format(nom=her_name(corpus), bloc_complet=extra)
        schema = (BatchFull if full else BatchLight).model_json_schema()
        expected = ", ".join(rendered.sessions)
        prompt = f"{rendered.text}\n\n(Séances à rendre : {expected}.)"
        return CallSpec(prompt=prompt, system=system, schema=schema, model=self.model,
                        max_output_tokens=32_000 if full else 16_000)

    # -- la réponse -----------------------------------------------------------------------------------

    def accept(self, corpus: Corpus, unit: str, payload: dict[str, Any], result: CallResult) -> str | None:
        corpus.db.executescript(ANNOTATIONS_SCHEMA)
        full = payload["tier"] in FULL_TIERS
        sessions, dropped = parse_batch(result.data, full)
        rendered = render_sessions(corpus, payload["sessions"], self.tz)
        by_key = {s.seance.strip(): s for s in sessions}
        present = [k for k in rendered.sessions if k in by_key]
        missing = [k for k in rendered.sessions if k not in by_key]
        if len(missing) > MAX_MISSING_SHARE * len(rendered.sessions):
            return f"{len(missing)} séances sur {len(rendered.sessions)} absentes de la réponse"
        for key in present:
            clean = _clean(by_key[key], rendered.her_messages[key], rendered.all_messages[key])
            sid = _session_id(key, corpus)
            corpus.db.execute("INSERT OR REPLACE INTO annotations (session, version, tier, data, model) "
                              "VALUES (?, ?, ?, ?, ?)",
                              (sid, self.version, payload["tier"], clean.model_dump_json(), result.model))
            corpus.db.execute("UPDATE sessions SET status = 'done' WHERE id = ?", (sid,))
        if missing:
            rest = [_session_id(k, corpus) for k in missing]
            corpus.db.execute("INSERT OR IGNORE INTO jobs (pass, unit, version, payload) VALUES (?, ?, ?, ?)",
                              (self.name, f"{unit}+reste{rest[0]}", self.version,
                               json.dumps({"tier": payload["tier"], "sessions": rest})))
        corpus.db.commit()
        _ = dropped
        return None


def _session_id(key: str, corpus: Corpus) -> int:
    """« s345 » → 345 ; « d45 » → la séance du document 45."""
    if key.startswith("d"):
        row = corpus.db.execute("SELECT id FROM sessions WHERE document = ?", (int(key[1:]),)).fetchone()
        return int(row["id"])
    return int(key[1:])


def _clean(s: SessionLight, hers: list[int], allowed: set[int]) -> SessionLight:
    """Écarte ce qui ne tient pas à la séance : numéros étrangers, émotions sur les messages des autres."""
    mine = set(hers)
    s.emotions = [e for e in s.emotions if e.id in mine]
    seen: set[int] = set()
    unique = []
    for e in s.emotions:  # une émotion par message
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)
    s.emotions = unique
    for field in ("souvenirs", "croyances", "promesses", "evenements", "reves"):
        for item in getattr(s, field, []):
            item.messages = [m for m in item.messages if m in allowed]
    return s

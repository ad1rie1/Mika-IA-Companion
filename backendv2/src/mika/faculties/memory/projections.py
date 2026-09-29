"""Les projections T0 de la mémoire (dans la transaction d'ajout) :

- ``memory_items`` : souvenirs, croyances, promesses, avec ce qui les fait
  durer (importance, renforcements, rappels) et leur statut ;
- ``memory_chunks`` : les échanges bruts avec chacun (sa question, sa
  réponse), retrouvables sans que la consolidation ait décidé de les garder.

L'oubli d'une personne efface ses lignes des deux.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.faculties.memory.faculty import MEMORY
from mika.kernel.faculty import Tier
from mika.ports.store import Sql
from mika.vocab.affect import strip_prosody

ITEM_COLUMNS = ("id", "kind", "text", "about", "sensitivity", "importance", "confidence", "origin", "source",
                "emotion", "born_at", "touched_at", "recalled_at", "recalls", "status", "replaces", "recipient",
                "due", "sources")
CHUNK_TEXT_MAX = 600


def _about(values: Sequence[str]) -> str:
    return json.dumps(sorted(set(values)), ensure_ascii=False)


class Items:
    def create(self, sql: Sql, sfx: str) -> None:
        sql.execute(
            f"CREATE TABLE IF NOT EXISTS {c.ITEMS_TABLE}{sfx}(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, "
            "text TEXT NOT NULL, about TEXT NOT NULL, sensitivity INTEGER NOT NULL, importance REAL NOT NULL, "
            "confidence REAL, origin TEXT, source TEXT, emotion TEXT, born_at INTEGER NOT NULL, "
            "touched_at INTEGER NOT NULL, recalled_at INTEGER NOT NULL DEFAULT 0, recalls INTEGER NOT NULL DEFAULT 0, "
            "status TEXT NOT NULL, replaces INTEGER, recipient TEXT, due INTEGER, sources TEXT NOT NULL)"
        )

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"DROP TABLE IF EXISTS {c.ITEMS_TABLE}{sfx}")

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        t = f"{c.ITEMS_TABLE}{sfx}"
        cols = ",".join(ITEM_COLUMNS)
        marks = ",".join("?" * len(ITEM_COLUMNS))
        for e in events:
            d = e.data
            name = e.type.name
            if name == c.REMEMBERED.name:
                sql.execute(f"INSERT OR REPLACE INTO {t}({cols}) VALUES({marks})", (
                    e.seq, c.SOUVENIR, d.text.text or "", _about(d.about), d.sensitivity, d.importance, None, None,
                    None, d.emotion, e.at, e.at, 0, 0, "active", None, None, None, json.dumps(list(d.sources))))
            elif name == c.BELIEVED.name:
                sql.execute(f"INSERT OR REPLACE INTO {t}({cols}) VALUES({marks})", (
                    e.seq, c.BELIEF, d.text.text or "", _about(d.about), d.sensitivity, d.importance, d.confidence,
                    d.origin, d.source, None, e.at, e.at, 0, 0, "active", d.replaces, None, None,
                    json.dumps(list(d.sources))))
                if d.replaces is not None:
                    sql.execute(f"UPDATE {t} SET status='superseded' WHERE id=?", (d.replaces,))
            elif name == c.PROMISE_NOTICED.name:
                sql.execute(f"INSERT OR REPLACE INTO {t}({cols}) VALUES({marks})", (
                    e.seq, c.PROMISE, d.text.text or "", _about([d.to]), d.sensitivity, 0.6, None, None, None, None,
                    e.at, e.at, 0, 0, "pending", None, d.to, d.due, json.dumps(list(d.sources))))
            elif name == c.PROMISE_RESOLVED.name:
                sql.execute(f"UPDATE {t} SET status=?, touched_at=? WHERE id=?", (d.status, e.at, d.promise))
            elif name == c.REINFORCED.name:
                sql.execute(f"UPDATE {t} SET touched_at=?, importance=MIN(1.0, importance + 0.05) WHERE id=?",
                            (e.at, d.item))
                if d.corroborated:
                    sql.execute(f"UPDATE {t} SET confidence=MIN(0.95, COALESCE(confidence, 0.5) + 0.1) WHERE id=?",
                                (d.item,))
            elif name == c.NIGHT_SORTED.name:
                for keep, drop in d.merges:
                    sql.execute(f"UPDATE {t} SET importance=MAX(importance, COALESCE((SELECT importance FROM {t} "
                                "WHERE id=?), 0)), touched_at=? WHERE id=?", (drop, e.at, keep))
                    sql.execute(f"UPDATE {t} SET status='merged' WHERE id=?", (drop,))
            elif name == rt.UTTERANCE.name:
                ids = [int(p.split(":", 1)[1]) for p in d.provenance if p.startswith("memory:")]
                if ids:
                    sql.executemany(f"UPDATE {t} SET recalls=recalls+1, recalled_at=?, touched_at=? WHERE id=?",
                                    [(e.at, e.at, i) for i in ids])

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        t = f"{c.ITEMS_TABLE}{sfx}"
        sql.execute(f"DELETE FROM {t} WHERE about LIKE ? OR recipient=?", (f'%"{subject}"%', subject))


class Chunks:
    def create(self, sql: Sql, sfx: str) -> None:
        sql.execute(
            f"CREATE TABLE IF NOT EXISTS {c.CHUNKS_TABLE}{sfx}(id INTEGER PRIMARY KEY, person TEXT NOT NULL, "
            "question INTEGER, user_text TEXT NOT NULL, reply_text TEXT NOT NULL, at INTEGER NOT NULL, room TEXT)"
        )
        sql.execute(f"CREATE INDEX IF NOT EXISTS {c.CHUNKS_TABLE}{sfx}_person ON {c.CHUNKS_TABLE}{sfx}(person, id)")

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"DROP TABLE IF EXISTS {c.CHUNKS_TABLE}{sfx}")

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        for e in events:
            d = e.data
            if not d.visible or not d.target or d.reply_to is None:
                continue
            row = sql.execute(f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE id=?", (d.reply_to,)).fetchone()
            user_text = (row[0] if row else "")[:CHUNK_TEXT_MAX]
            reply = strip_prosody(d.text.text or "")[:CHUNK_TEXT_MAX]
            sql.execute(f"INSERT OR REPLACE INTO {c.CHUNKS_TABLE}{sfx}(id, person, question, user_text, reply_text, at, "
                        "room) VALUES(?,?,?,?,?,?,?)", (e.seq, d.target, d.reply_to, user_text, reply, e.at, d.room))

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        sql.execute(f"DELETE FROM {c.CHUNKS_TABLE}{sfx} WHERE person=?", (subject,))


class Told:
    """À qui elle a répété quoi : ce que montrait le prompt d'un énoncé adressé
    à quelqu'un (sa provenance). Ce qu'elle a raconté à Bob, Bob le sait."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"CREATE TABLE IF NOT EXISTS {c.TOLD_TABLE}{sfx}(item INTEGER NOT NULL, handle TEXT NOT NULL, "
                    "at INTEGER NOT NULL, PRIMARY KEY(item, handle))")

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"DROP TABLE IF EXISTS {c.TOLD_TABLE}{sfx}")

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        rows = []
        for e in events:
            d = e.data
            if not d.visible or not d.target:
                continue
            rows += [(int(p.split(":", 1)[1]), d.target, e.at) for p in d.provenance if p.startswith("memory:")]
        if rows:
            sql.executemany(f"INSERT OR REPLACE INTO {c.TOLD_TABLE}{sfx}(item, handle, at) VALUES(?,?,?)", rows)

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        sql.execute(f"DELETE FROM {c.TOLD_TABLE}{sfx} WHERE handle=?", (subject,))


MEMORY.projector(c.ITEMS_TABLE, version=1, tier=Tier.T0,
                 types=[*c.ALL, rt.UTTERANCE])(Items)
MEMORY.projector(c.CHUNKS_TABLE, version=2, tier=Tier.T0, types=[rt.UTTERANCE])(Chunks)
MEMORY.projector(c.TOLD_TABLE, version=1, tier=Tier.T0, types=[rt.UTTERANCE])(Told)

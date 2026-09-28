"""Projections jouets : T0 (fil de texte), T1 (décompte), T2 (calcul lourd)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from mika.kernel.faculty import Tier
from mika.ports.store import Sql
from tests.fixtures.toys import BUMPED, COUNTER


class TextLog:
    """T0 : garde le texte des notes (pour éprouver l'oubli)."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"CREATE TABLE IF NOT EXISTS textlog{sfx}(seq INTEGER PRIMARY KEY, who TEXT, body TEXT)")

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"DROP TABLE IF EXISTS textlog{sfx}")

    def apply(self, sql: Sql, events: Sequence, sfx: str) -> None:
        for e in events:
            if e.data.note is not None:
                sql.execute(f"INSERT OR REPLACE INTO textlog{sfx}(seq, who, body) VALUES(?,?,?)",
                            (e.seq, e.data.who, e.data.note.text or ""))

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        sql.execute(f"DELETE FROM textlog{sfx} WHERE who=?", (subject,))


class Tally:
    """T1 : décompte par personne ; « poison » fait lever."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"CREATE TABLE IF NOT EXISTS tally{sfx}(who TEXT PRIMARY KEY, n INTEGER NOT NULL)")

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"DROP TABLE IF EXISTS tally{sfx}")

    def apply(self, sql: Sql, events: Sequence, sfx: str) -> None:
        for e in events:
            if e.data.who == "poison":
                raise ValueError("événement empoisonné")
            sql.execute(f"INSERT INTO tally{sfx}(who, n) VALUES(?, ?) ON CONFLICT(who) DO UPDATE SET n = n + ?",
                        (e.data.who, e.data.by, e.data.by))


class Heavy:
    """T2 : une préparation coûteuse hors de l'écrivain, une écriture légère."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"CREATE TABLE IF NOT EXISTS heavy{sfx}(seq INTEGER PRIMARY KEY, h TEXT)")

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"DROP TABLE IF EXISTS heavy{sfx}")

    def prepare(self, rows: Sequence[dict]) -> list[tuple[int, str]]:
        out = []
        for row in rows:
            h = str(row["seq"]).encode()
            for _ in range(20_000):
                h = hashlib.blake2b(h, digest_size=16).digest()
            out.append((row["seq"], h.hex()))
        return out

    def apply(self, sql: Sql, events: Sequence, sfx: str, prepared: list[tuple[int, str]]) -> None:
        sql.executemany(f"INSERT OR REPLACE INTO heavy{sfx}(seq, h) VALUES(?,?)", prepared)


def with_projectors(t0: bool = False, t1: int | None = None, t2: bool = False):
    """Une copie de la faculté ``counter`` portant les projections demandées."""
    from dataclasses import replace

    fac = replace(COUNTER, projectors=[])
    fac.events = dict(COUNTER.events)
    fac.reducers = list(COUNTER.reducers)
    fac.facts = list(COUNTER.facts)
    if t0:
        fac.projector("textlog", version=1, tier=Tier.T0, types=[BUMPED])(TextLog)
    if t1 is not None:
        fac.projector("tally", version=t1, tier=Tier.T1, types=[BUMPED])(Tally)
    if t2:
        fac.projector("heavy", version=1, tier=Tier.T2, types=[BUMPED])(Heavy)
    return fac

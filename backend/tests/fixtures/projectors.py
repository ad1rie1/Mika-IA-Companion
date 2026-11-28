"""Projections jouets : T0 (fil de texte), T1 (décompte), T2 (calcul lourd)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from sqlalchemy import BigInteger, Column, delete, update

from mika.kernel.faculty import Tier
from mika.ports.sql import HANDLE_MAX, Key, LongText, insert_ignore, projection_table, upsert
from mika.ports.store import Sql
from tests.fixtures.toys import BUMPED, COUNTER


def _textlog(sfx: str):
    return projection_table(f"textlog{sfx}", Column("seq", BigInteger, primary_key=True, autoincrement=False),
                            Column("who", Key(HANDLE_MAX)), Column("body", LongText))


def _tally(sfx: str):
    return projection_table(f"tally{sfx}", Column("who", Key(HANDLE_MAX), primary_key=True),
                            Column("n", BigInteger, nullable=False))


def _heavy(sfx: str):
    return projection_table(f"heavy{sfx}", Column("seq", BigInteger, primary_key=True, autoincrement=False),
                            Column("h", LongText))


class TextLog:
    """T0 : garde le texte des notes (pour éprouver l'oubli)."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.create(_textlog(sfx))

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.drop(_textlog(sfx))

    def apply(self, sql: Sql, events: Sequence, sfx: str) -> None:
        t = _textlog(sfx)
        for e in events:
            if e.data.note is not None:
                upsert(sql, t, {"seq": e.seq, "who": e.data.who, "body": e.data.note.text or ""}, keys=["seq"])

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        t = _textlog(sfx)
        sql.execute(delete(t).where(t.c.who == subject))


class Tally:
    """T1 : décompte par personne ; « poison » fait lever."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.create(_tally(sfx))

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.drop(_tally(sfx))

    def apply(self, sql: Sql, events: Sequence, sfx: str) -> None:
        t = _tally(sfx)
        for e in events:
            if e.data.who == "poison":
                raise ValueError("événement empoisonné")
            if not insert_ignore(sql, t, {"who": e.data.who, "n": e.data.by}):
                sql.execute(update(t).where(t.c.who == e.data.who).values(n=t.c.n + e.data.by))


class Heavy:
    """T2 : une préparation coûteuse hors de l'écrivain, une écriture légère."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.create(_heavy(sfx))

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.drop(_heavy(sfx))

    def prepare(self, rows: Sequence[dict]) -> list[tuple[int, str]]:
        out = []
        for row in rows:
            h = str(row["seq"]).encode()
            for _ in range(20_000):
                h = hashlib.blake2b(h, digest_size=16).digest()
            out.append((row["seq"], h.hex()))
        return out

    def apply(self, sql: Sql, events: Sequence, sfx: str, prepared: list[tuple[int, str]]) -> None:
        if prepared:
            upsert(sql, _heavy(sfx), [{"seq": seq, "h": h} for seq, h in prepared], keys=["seq"])


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

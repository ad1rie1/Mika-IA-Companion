"""``transcript`` : le fil de conversation.

Un message = l'événement qui l'a créé (perception reçue, énoncé visible) ;
son identifiant est le ``seq`` de cet événement. Le texte vit dans la
projection T0 ``thread`` (même transaction que l'ajout : un client qui
demande l'historique voit toujours le message qu'on vient de lui annoncer).
Les jetons prosodiques y sont retirés : ils sont pour la voix, pas pour le
fil que relisent le modèle et la personne.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from mika.contracts import expression as expression_c
from mika.contracts import runtime as rt
from mika.contracts import transcript as c
from mika.kernel.faculty import Faculty, Tier, Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import ChatTurn, SectionBody
from mika.kernel.state import FrozenDict
from mika.ports.store import Sql
from mika.vocab.affect import Declared, strip_prosody
from mika.vocab.episodes import CONVERSATIONAL, Kind

#: Messages relus au plus pour composer l'historique (le budget coupe ensuite).
THREAD_WINDOW = 60


@dataclass(frozen=True, slots=True)
class TranscriptState:
    head: int = 0
    last_from: FrozenDict[str, int] = field(default_factory=FrozenDict)
    last_to: FrozenDict[str, int] = field(default_factory=FrozenDict)


TRANSCRIPT = Faculty("transcript", state=TranscriptState, init=lambda p: TranscriptState())


@TRANSCRIPT.reducer(rt.PERCEPTION_RECEIVED)
def _received(s: TranscriptState, e, cx) -> TranscriptState:
    return replace(s, head=e.seq, last_from=s.last_from.set(e.data.handle, e.at))


@TRANSCRIPT.reducer(rt.UTTERANCE)
def _uttered(s: TranscriptState, e, cx) -> TranscriptState:
    if not e.data.visible:
        return s
    s = replace(s, head=e.seq)
    if e.data.target:
        s = replace(s, last_to=s.last_to.set(e.data.target, e.at))
    return s


@TRANSCRIPT.fact(c.LAST_FROM)
def _last_from(s: TranscriptState, cx, handle: str) -> int:
    return s.last_from.get(handle, 0)


@TRANSCRIPT.fact(c.LAST_TO)
def _last_to(s: TranscriptState, cx, handle: str) -> int:
    return s.last_to.get(handle, 0)


@TRANSCRIPT.fact(c.HEAD)
def _head(s: TranscriptState, cx) -> int:
    return s.head


# ── Le fil matérialisé ────────────────────────────────────────────────────

_COLUMNS = ("id", "at", "role", "person", "channel", "room", "source", "kind", "text", "client_msg_id",
            "reply_to", "emotion", "emotion_intensity", "attachments")


class Thread:
    """T0 : une ligne par message visible."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.execute(
            f"CREATE TABLE IF NOT EXISTS {c.THREAD_TABLE}{sfx}("
            "id INTEGER PRIMARY KEY, at INTEGER NOT NULL, role TEXT NOT NULL, person TEXT NOT NULL, "
            "channel TEXT, room TEXT, source TEXT, kind TEXT, text TEXT NOT NULL, client_msg_id TEXT, "
            "reply_to INTEGER, emotion TEXT, emotion_intensity REAL, attachments TEXT)"
        )
        sql.execute(f"CREATE INDEX IF NOT EXISTS {c.THREAD_TABLE}{sfx}_person ON {c.THREAD_TABLE}{sfx}(person, id)")

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.execute(f"DROP TABLE IF EXISTS {c.THREAD_TABLE}{sfx}")

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        rows = [row for e in events if (row := _row(e)) is not None]
        if rows:
            marks = ",".join("?" * len(_COLUMNS))
            sql.executemany(f"INSERT OR REPLACE INTO {c.THREAD_TABLE}{sfx}({','.join(_COLUMNS)}) VALUES({marks})", rows)

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        sql.execute(f"DELETE FROM {c.THREAD_TABLE}{sfx} WHERE person=?", (subject,))


def _row(e: Any) -> tuple[Any, ...] | None:
    d = e.data
    if e.type.name == rt.PERCEPTION_RECEIVED.name:
        attachments = json.dumps([a.model_dump() for a in d.attachments], ensure_ascii=False) if d.attachments else "[]"
        return (e.seq, e.at, "user", d.handle, d.channel, d.room, d.channel, "message", d.text.text or "",
                d.client_msg_id, None, None, None, attachments)
    if e.type.name == rt.UTTERANCE.name and d.visible:
        declared = Declared.decode(d.annotation(expression_c.EMOTION_ANNOTATION))
        return (e.seq, e.at, "assistant", d.target or "", d.channel, d.room, _source(d.kind), d.kind,
                strip_prosody(d.text.text or ""), None, d.reply_to,
                declared.emotion.value if declared else None, declared.intensity if declared else None, "[]")
    return None


def _source(kind: str) -> str:
    return "conscience" if kind != Kind.REPLY else "reply"


TRANSCRIPT.projector(c.THREAD_TABLE, version=1, tier=Tier.T0, types=[rt.PERCEPTION_RECEIVED, rt.UTTERANCE])(Thread)


def recent(store: Any, person: str, limit: int) -> list[dict[str, Any]]:
    """La fin du fil d'une personne, du plus ancien au plus récent."""
    rows = store.query_mind(
        f"SELECT {','.join(_COLUMNS)} FROM {c.THREAD_TABLE} WHERE person=? ORDER BY id DESC LIMIT ?",
        (person, limit),
    )
    return [dict(zip(_COLUMNS, r, strict=True)) for r in reversed(rows)]


def after(store: Any, person: str, after_id: int, limit: int) -> tuple[list[dict[str, Any]], bool]:
    """Tout ce qu'elle a manqué depuis ``after_id`` (les plus récents si ça
    dépasse ``limit``, et on le dit)."""
    rows = store.query_mind(
        f"SELECT {','.join(_COLUMNS)} FROM {c.THREAD_TABLE} WHERE person=? AND id>? ORDER BY id DESC LIMIT ?",
        (person, after_id, limit + 1),
    )
    truncated = len(rows) > limit
    rows = rows[:limit]
    return [dict(zip(_COLUMNS, r, strict=True)) for r in reversed(rows)], truncated


def thread_of(store: Any, person: str, limit: int, before: int | None = None) -> list[dict[str, Any]]:
    """Le fil avec une personne, avant ``before`` (le message en cours de
    réponse n'y est pas : il arrive comme dernier tour)."""
    bound = before if before is not None else 2**62
    rows = store.query_mind(
        f"SELECT {','.join(_COLUMNS)} FROM {c.THREAD_TABLE} WHERE person=? AND id<? ORDER BY id DESC LIMIT ?",
        (person, bound, limit),
    )
    return [dict(zip(_COLUMNS, r, strict=True)) for r in reversed(rows)]


# ── L'historique du prompt ────────────────────────────────────────────────


@TRANSCRIPT.enricher("thread", episodes=CONVERSATIONAL, deadline_ms=1500)
async def _thread(s: TranscriptState, frame: Frame, ports: Mapping[str, Any]) -> tuple[ChatTurn, ...]:
    """Le fil avec l'interlocuteur. Ce que les autres lui ont dit n'y est pas :
    cela passe par la mémoire, filtrée par la divulgation (un fil partagé
    verbatim ferait lire à Bob ce qu'Alice a écrit en privé)."""
    store = ports.get("store")
    ep = frame.episode
    if store is None or ep is None or not ep.target:
        return ()
    rows = thread_of(store, ep.target, THREAD_WINDOW, before=ep.attrs.get("reply_to"))
    return tuple(ChatTurn("assistant" if r["role"] == "assistant" else "user", r["text"], id=r["id"]) for r in rows)


@TRANSCRIPT.section("history", zone=Zone.HISTORY, episodes=CONVERSATIONAL)
def _history(s: TranscriptState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    turns = enrich.get("thread")
    if not turns:
        return None
    return SectionBody(tuple(turns))

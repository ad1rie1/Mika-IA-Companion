"""``transcript`` : le fil de conversation.

Quand le fil avec quelqu'un devient long, son début — déjà relu par la
mémoire — se replie en un résumé (``compact``) : le modèle voit le résumé puis
les derniers échanges ; le verbatim reste au journal et dans l'historique.

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

from pydantic import BaseModel, ConfigDict

from mika.contracts import expression as expression_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import transcript as c
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp, Faculty, Tier, Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import ChatTurn, SectionBody
from mika.kernel.state import FrozenDict
from mika.ports.llm import LLMRequest, Message
from mika.ports.store import Sql
from mika.vocab.affect import Declared, strip_prosody
from mika.vocab.episodes import CONVERSATIONAL, Kind

#: Messages relus au plus pour composer l'historique (le budget coupe ensuite).
THREAD_WINDOW = 60


class TranscriptParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    window: int = THREAD_WINDOW
    #: au-delà de tant de messages depuis le dernier résumé, le début se replie…
    compact_after: int = 120
    #: … en gardant les derniers tels quels
    keep: int = 60


@dataclass(frozen=True, slots=True)
class TranscriptState:
    head: int = 0
    last_from: FrozenDict[str, int] = field(default_factory=FrozenDict)
    last_to: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: personne → (dernier message résumé, référence du texte du résumé)
    summaries: FrozenDict[str, tuple[int, str]] = field(default_factory=FrozenDict)


TRANSCRIPT = Faculty("transcript", state=TranscriptState, init=lambda p: TranscriptState(), params=TranscriptParams)
TRANSCRIPT.declare(c.COMPACTED)


def _params(p: TranscriptParams | None) -> TranscriptParams:
    return p if p is not None else TranscriptParams()


@TRANSCRIPT.reducer(c.COMPACTED)
def _compacted(s: TranscriptState, e, cx) -> TranscriptState:
    ref = e.data.summary.ref or ""
    return replace(s, summaries=s.summaries.set(e.data.person, (e.data.upto, ref)))


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


def thread_of(store: Any, person: str, limit: int, before: int | None = None, after: int = 0) -> list[dict[str, Any]]:
    """Le fil avec une poignée, entre ``after`` et ``before`` (le message en
    cours de réponse n'y est pas : il arrive comme dernier tour)."""
    bound = before if before is not None else 2**62
    rows = store.query_mind(
        f"SELECT {','.join(_COLUMNS)} FROM {c.THREAD_TABLE} WHERE person=? AND id<? AND id>? ORDER BY id DESC LIMIT ?",
        (person, bound, after, limit),
    )
    return [dict(zip(_COLUMNS, r, strict=True)) for r in reversed(rows)]


def private_thread(store: Any, handles: Sequence[str], limit: int, before: int | None = None,
                   after: int = 0) -> list[dict[str, Any]]:
    """Le fil privé avec une personne, toutes ses poignées confondues (ce
    qu'elle a dit dans un salon n'y est pas : hors de son contexte)."""
    bound = before if before is not None else 2**62
    marks = ",".join("?" * len(handles))
    rows = store.query_mind(
        f"SELECT {','.join(_COLUMNS)} FROM {c.THREAD_TABLE} WHERE person IN ({marks}) AND room IS NULL AND id<? "
        "AND id>? ORDER BY id DESC LIMIT ?", (*handles, bound, after, limit),
    )
    return [dict(zip(_COLUMNS, r, strict=True)) for r in reversed(rows)]


def room_thread(store: Any, room: str, limit: int, before: int | None = None) -> list[dict[str, Any]]:
    """Ce qui s'est dit dans un salon (public pour ce salon), tous ensemble."""
    bound = before if before is not None else 2**62
    rows = store.query_mind(
        f"SELECT {','.join(_COLUMNS)} FROM {c.THREAD_TABLE} WHERE room=? AND id<? ORDER BY id DESC LIMIT ?",
        (room, bound, limit),
    )
    return [dict(zip(_COLUMNS, r, strict=True)) for r in reversed(rows)]


# ── L'historique du prompt ────────────────────────────────────────────────


@TRANSCRIPT.enricher("thread", episodes=CONVERSATIONAL, deadline_ms=1500)
async def _thread(s: TranscriptState, frame: Frame, ports: Mapping[str, Any]) -> tuple[ChatTurn, ...]:
    """Le fil avec l'interlocuteur. Ce que les autres lui ont dit en privé n'y
    est pas : cela passe par la mémoire, filtrée par la divulgation (un fil
    partagé verbatim ferait lire à Bob ce qu'Alice a écrit en privé). Dans un
    salon, le fil du salon — tout le monde l'a lu. En privé, ses poignées
    reliées s'ajoutent seulement si sa fiche est ouverte."""
    store = ports.get("store")
    ep = frame.episode
    if store is None or ep is None or not ep.target:
        return ()
    p = _params(frame.env.params_of("transcript", frame.root))
    before = ep.attrs.get("reply_to")
    room = ep.attrs.get("room")
    if room:
        rows = room_thread(store, room, p.window, before=before)
        return tuple(_turn(r, ep.target) for r in rows)
    summary = s.summaries.get(ep.target)
    since = summary[0] if summary else 0
    aud = frame.audience
    handles: tuple[str, ...] = (ep.target,)
    if aud is not None and aud.private_ok:
        person = frame.get(identity_c.PERSON(ep.target))
        handles = tuple(sorted({ep.target, *frame.get(identity_c.HANDLES(person))}))
    rows = private_thread(store, handles, p.window, before=before, after=since)
    turns = [ChatTurn("assistant" if r["role"] == "assistant" else "user", r["text"], id=r["id"]) for r in rows]
    if summary:
        text = store.content([summary[1]]).get(summary[1])
        if text:
            turns.insert(0, ChatTurn("user", f"(Plus tôt, entre vous — en résumé : {text})", id=since))
    return tuple(turns)


COMPACT_SYSTEM = """Tu aides Mika à se souvenir d'une longue conversation. On te donne le début de son fil avec \
quelqu'un (et le résumé des échanges encore plus anciens, s'il existe). Écris un résumé à la première personne, du \
point de vue de Mika (« On a parlé de… », « Il m'a dit que… »), en 5 à 10 phrases : les faits, ce qui a été promis, \
le ton de la relation. N'invente rien. Réponds seulement par le résumé."""


def _turn(r: Mapping[str, Any], target: str) -> ChatTurn:
    """Un tour du fil d'un salon : ce que disent les autres est cité avec leur
    nom d'affichage (poignée), pour qu'elle sache qui parle."""
    if r["role"] == "assistant":
        return ChatTurn("assistant", r["text"], id=r["id"])
    if r["person"] == target:
        return ChatTurn("user", r["text"], id=r["id"])
    return ChatTurn("user", f"[{r['person']}] {r['text']}", id=r["id"])


@TRANSCRIPT.process("transcript.compact", wake_on=[memory_c.CONSOLIDATED], lane="background",
                    catch_up=CatchUp.ONCE, max_quantum_s=3600)
class Compact:
    """Replie le début des fils trop longs, un fil par passage (les appels de
    modèle restent rares), et seulement ce que la mémoire a déjà relu."""

    def __init__(self) -> None:
        self.seen = -1
        self.retry_at = 0

    def next_due(self, state: TranscriptState, frame: Frame, last_run: int | None) -> int | None:
        checkpoint = frame.get(memory_c.CHECKPOINT)
        if checkpoint == self.seen:
            return None
        return max(frame.now, self.retry_at)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: TranscriptState = ctx.state
        store = ctx.ports.get("store")
        checkpoint = frame.get(memory_c.CHECKPOINT)
        if store is None or ctx.llm is None:
            self.seen = checkpoint
            return
        p = _params(frame.env.params_of("transcript", frame.root))
        for (person,) in store.query_mind(f"SELECT DISTINCT person FROM {c.THREAD_TABLE} ORDER BY person"):
            summary = state.summaries.get(person)
            since = summary[0] if summary else 0
            rows = thread_of(store, person, 10_000, after=since)
            if len(rows) <= p.compact_after:
                continue
            fold = [r for r in rows[: len(rows) - p.keep] if r["id"] <= checkpoint]
            if len(fold) < 10:
                continue
            previous = store.content([summary[1]]).get(summary[1]) if summary else None
            lines = "\n".join(f"{'Mika' if r['role'] == 'assistant' else 'Elle ou lui'} : {r['text']}" for r in fold)
            prompt = (f"Résumé précédent : {previous}\n\n" if previous else "") + f"Suite des échanges :\n{lines}"
            self.retry_at = frame.now + 600 * 1_000_000  # si l'appel lève, pas de rafale
            request = LLMRequest(role="compact", call_id=f"{ctx.run_id}#{person}", system_stable=COMPACT_SYSTEM,
                                 messages=(Message("user", prompt),), max_tokens=800, lane="background", priority=3)
            response = await ctx.llm.call(request)
            self.retry_at = 0
            text = (response.text or "").strip()
            if not text:
                self.seen = checkpoint  # rien d'utilisable : on réessaiera à la prochaine consolidation
                return
            await ctx.emit(c.COMPACTED.draft(person=person, upto=fold[-1]["id"], summary=Content.of(text, level=2),
                                             count=len(fold), call_id=request.call_id, model=response.model))
            return  # un fil par passage ; le suivant au prochain réveil
        self.seen = checkpoint


@TRANSCRIPT.section("history", zone=Zone.HISTORY, episodes=CONVERSATIONAL)
def _history(s: TranscriptState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    turns = enrich.get("thread")
    if not turns:
        return None
    return SectionBody(tuple(turns))

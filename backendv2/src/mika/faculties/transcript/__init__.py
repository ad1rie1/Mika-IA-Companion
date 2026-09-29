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
from mika.kernel.inspect import (
    Badge,
    Block,
    Cell,
    Column,
    Disclosure,
    InspectContext,
    Note,
    Pager,
    Param,
    Ref,
    Row,
    Stat,
    Stats,
    Table,
    Text,
    When,
    paginate,
)
from mika.kernel.prompt import ChatTurn, SectionBody
from mika.kernel.state import FrozenDict
from mika.ports.llm import LLMRequest, Message
from mika.ports.store import Sql
from mika.vocab.affect import Declared, emotion_cell, strip_prosody
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.people import is_internal

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


# ── Inspection ────────────────────────────────────────────────────────────

#: Tant de messages par page (curseur « avant ») ; un texte replié au-delà de
#: tant de caractères, et jamais plus que tant envoyés à la console.
PAGE = 50
INSPECT_CHARS = 300
TEXT_CAP = 4000
MAX_SUMMARIES = 100
FORGOTTEN = "(oublié)"
ROLES = (("user", "la personne"), ("assistant", "elle"))


def _clip(text: str | None, limit: int = INSPECT_CHARS) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _internal(r: Mapping[str, Any]) -> bool:
    """Adressé à personne (ou venu de sa propre tuyauterie) : pas un échange."""
    return not r["person"] or is_internal(r["person"])


def _who(frame: Frame, handle: str) -> Cell:
    """La personne derrière une poignée, en lien vers sa fiche."""
    if not handle or is_internal(handle):
        return Text("personne", "muted")
    person = frame.get(identity_c.PERSON(handle))
    name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(handle)).name
    return Ref.subject("person", person, f"{name} ({handle})" if name else handle)


def _page(store: Any, clauses: Sequence[str], args: Sequence[Any], before: int | None,
          size: int = PAGE) -> tuple[list[dict[str, Any]], Pager | None]:
    """Une page du fil, du plus récent au plus ancien, et le curseur de la suivante."""
    where, params = list(clauses), list(args)
    if before:
        where.append("id<?")
        params.append(before)
    clause = f"WHERE {' AND '.join(where)} " if where else ""
    found = store.query_mind(f"SELECT {','.join(_COLUMNS)} FROM {c.THREAD_TABLE} {clause}ORDER BY id DESC LIMIT ?",
                             (*params, size + 1))
    rows = [dict(zip(_COLUMNS, r, strict=True)) for r in found[:size]]
    more = len(found) > size and rows
    return rows, Pager(older=(("avant", str(rows[-1]["id"])),)) if more else None


def _episodes(ctx: InspectContext, rows: Sequence[Mapping[str, Any]]) -> dict[int, str]:
    """L'épisode de chaque réponse (sa corrélation) — et, par elle, celui de la
    question qu'elle règle."""
    out: dict[int, str] = {}
    for r in rows:
        if r["role"] != "assistant":
            continue
        found = ctx.events((rt.UTTERANCE,), 1, before=int(r["id"]) + 1)
        if found and found[0].seq == r["id"]:
            out[int(r["id"])] = found[0].correlation
            if r["reply_to"] is not None:
                out.setdefault(int(r["reply_to"]), found[0].correlation)
    return out


MESSAGE_COLUMNS = (Column("n°", "fit"), Column("quand", "fit"), "qui parle", "avec", "où", "texte", "émotion",
                   "réponse", "épisode")


def _messages(frame: Frame, ctx: InspectContext, rows: Sequence[Mapping[str, Any]]) -> tuple[Row, ...]:
    pending = {int(x) for x in frame.get(rt.AWAITING)}
    episodes = _episodes(ctx, rows)
    out = []
    for r in rows:
        mine = r["role"] == "assistant"
        corr = episodes.get(int(r["id"]))
        out.append(Row((
            Ref("event", str(r["id"]), str(r["id"])), When(r["at"]),
            Badge("elle", "info") if mine else Badge("la personne"), _who(frame, r["person"]),
            f"salon « {r['room']} »" if r["room"] else "en privé",
            Text(_clip(r["text"], TEXT_CAP), clamp=INSPECT_CHARS),
            emotion_cell(r["emotion"], r["emotion_intensity"]) if mine and r["emotion"] else "",
            Badge("en attente", "warn") if r["id"] in pending else "",
            Ref("episode", corr, "épisode") if corr else "—",
        ), tone="muted" if _internal(r) else ""))
    return tuple(out)


def _summaries(store: Any, s: TranscriptState, frame: Frame, handles: Sequence[str] | None) -> Block | None:
    folded = [(p, v) for p, v in sorted(s.summaries.items()) if handles is None or p in handles][:MAX_SUMMARIES]
    if not folded:
        return None
    texts = store.content([ref for _p, (_upto, ref) in folded if ref])
    rows = tuple((_who(frame, p), Ref("event", str(upto), str(upto)),
                  Text(_clip(texts[ref], TEXT_CAP), clamp=INSPECT_CHARS) if texts.get(ref) else FORGOTTEN)
                 for p, (upto, ref) in folded)
    return Disclosure("Débuts de fil repliés en résumé", (
        Table(("avec", "replié jusqu'au message", "résumé"), rows, empty="aucun fil replié"),))


def _no_store() -> list[Block]:
    return [Note("Le magasin n'est pas disponible : le fil ne peut pas être relu.", tone="muted")]


HANDLE = Param("handle", "poignée", placeholder="tg_42, user_7…")
QUERY = Param("q", "texte", placeholder="un mot…")
ROLE = Param("role", "qui parle", kind="select", choices=ROLES)


@TRANSCRIPT.inspect("messages", title="Messages", section="fil", order=10, params=[HANDLE, QUERY, ROLE],
                    description="Tout ce qui a été dit, du plus récent au plus ancien.")
def _all_messages(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    store = ctx.store
    if store is None:
        return _no_store()
    handle, q, role = str(ctx.value("handle") or ""), str(ctx.value("q") or ""), str(ctx.value("role") or "")
    clauses, args = [], []
    if handle:
        clauses.append("person=?")
        args.append(handle)
    if q:
        clauses.append("text LIKE ? ESCAPE '\\'")
        args.append(_like(q))
    if role:
        clauses.append("role=?")
        args.append(role)
    before = ctx.int_param("avant", 0) or None
    rows, pager = _page(store, clauses, args, before)
    known = handle in s.last_from or handle in s.last_to or handle in s.summaries
    if handle and not rows and not known and not before:
        return [Note(f"Aucun message avec « {handle} ».", tone="muted")]
    awaiting = frame.get(rt.AWAITING)
    scope = f" avec « {handle} »" if handle else ""
    found = f" contenant « {q} »" if q else ""
    blocks: list[Block] = [
        Stats((Stat("dernier message du fil", s.head or "—"),
               Stat("questions sans réponse", len(awaiting), tone="warn" if awaiting else "",
                    href=Ref.view("transcript", "questions", "questions")),
               Stat("fils repliés en résumé", len(s.summaries)))),
        Table(MESSAGE_COLUMNS, _messages(frame, ctx, rows), title=f"Messages{scope}{found}", pager=pager,
              filters=("handle", "q", "role"),
              empty="aucun message ne correspond" if handle or q or role else "aucun message"),
    ]
    folded = _summaries(store, s, frame, [handle] if handle else None)
    if folded is not None:
        blocks.append(folded)
    return blocks


def _awaiting(s: TranscriptState, frame: Frame) -> int:
    return len(frame.get(rt.AWAITING))


@TRANSCRIPT.inspect("questions", title="Questions sans réponse", section="fil", order=20, badge=_awaiting,
                    description="Ce qu'on lui a demandé et à quoi elle n'a pas encore répondu.")
def _questions(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    store = ctx.store
    if store is None:
        return _no_store()
    waiting = sorted((int(x) for x in frame.get(rt.AWAITING)), reverse=True)
    page, pager = paginate(waiting, ctx.pager(size=PAGE))
    marks = ",".join("?" * len(page))
    found = {int(r[0]): r for r in store.query_mind(
        f"SELECT id, at, person, text FROM {c.THREAD_TABLE} WHERE id IN ({marks})", tuple(page))} if page else {}
    rows = []
    for seq in page:
        r = found.get(seq)
        link = Ref("event", str(seq), str(seq))
        if r is None:
            rows.append(Row((link, "—", Text("—", "muted"), Text(FORGOTTEN, "muted")), href=link))
            continue
        rows.append(Row((link, When(r[1]), _who(frame, r[2]), Text(_clip(r[3], TEXT_CAP), clamp=INSPECT_CHARS)),
                        href=link))
    return [Table((Column("n°", "fit"), Column("reçue", "fit"), "de", "texte"), tuple(rows), pager=pager,
                  empty="aucune question en attente")]


def _stats(store: Any, handles: Sequence[str]) -> Stats:
    marks = ",".join("?" * len(handles))
    total, received = store.query_mind(
        f"SELECT COUNT(*), COALESCE(SUM(role='user'), 0) FROM {c.THREAD_TABLE} WHERE person IN ({marks})",
        tuple(handles))[0]
    return Stats((Stat("messages", int(total)), Stat("reçus", int(received)),
                  Stat("envoyés", int(total) - int(received))))


@TRANSCRIPT.inspect("echanges", title="Échanges", subject="person", order=40,
                    description="Ce qu'ils se sont dit, toutes ses poignées confondues, du plus récent au plus ancien.")
def _exchanges(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    person = ctx.subject
    if not person:
        return [Note("Ouvre la fiche d'une personne : Personnes, puis la personne.", tone="muted")]
    if person.startswith("name:"):
        return [Note("Connue seulement de nom : elle ne lui a jamais écrit.", tone="muted")]
    store = ctx.store
    if store is None:
        return _no_store()
    handles = sorted({person, *frame.get(identity_c.HANDLES(person))})
    marks = ",".join("?" * len(handles))
    rows, pager = _page(store, [f"person IN ({marks})"], handles, ctx.int_param("avant", 0) or None)
    blocks: list[Block] = [_stats(store, handles),
                           Table(MESSAGE_COLUMNS, _messages(frame, ctx, rows), pager=pager,
                                 empty="aucun échange pour l'instant")]
    folded = _summaries(store, s, frame, handles)
    if folded is not None:
        blocks.append(folded)
    return blocks


@TRANSCRIPT.inspect("fil", title="Fil", subject="handle", subject_param="handle", order=50,
                    description="Les messages de cette poignée seulement.")
def _handle_thread(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    handle = ctx.subject or ctx.param("handle")
    if not handle:
        return [Note("Ouvre la fiche d'une poignée : Identités, puis la poignée.", tone="muted")]
    store = ctx.store
    if store is None:
        return _no_store()
    before = ctx.int_param("avant", 0) or None
    rows, pager = _page(store, ["person=?"], [handle], before)
    if not rows and not before and not (handle in s.last_from or handle in s.last_to):
        return [Note(f"Aucun message avec « {handle} ».", tone="muted")]
    blocks: list[Block] = [_stats(store, [handle]),
                           Table(MESSAGE_COLUMNS, _messages(frame, ctx, rows), pager=pager, empty="aucun message")]
    folded = _summaries(store, s, frame, [handle])
    if folded is not None:
        blocks.append(folded)
    return blocks

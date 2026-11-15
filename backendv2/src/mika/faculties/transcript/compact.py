"""Replier le début d'un fil trop long en un résumé (processus ``transcript.compact``) : seulement ce que la
mémoire a déjà relu, un fil par passage, ce qu'on lui a demandé de garder pour soi tu ; le modèle voit le résumé
puis les derniers échanges, le verbatim reste au journal et dans l'historique."""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Collection, Mapping, Sequence
from functools import partial
from typing import Any

from sqlalchemy import select

from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import self_ as self_c
from mika.contracts import transcript as c
from mika.faculties.transcript.faculty import TRANSCRIPT, TranscriptParams, TranscriptState, _params
from mika.faculties.transcript.marks import gap_mark, opening_mark
from mika.faculties.transcript.thread import _COLUMNS, _count, _messages_of
from mika.kernel.clock import DAY
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.ports.llm import LLMRequest, Message
from mika.ports.llm_budget import fit_by_halving, halved
from mika.ports.sql import json_values
from mika.vocab.episodes import Kind
from mika.vocab.people import clean_display_name
from mika.vocab.phrasebook import phrase


def compact_system(name: str, persona: str) -> str:
    """La consigne du résumé d'un fil long, au nom de celle qui s'en souviendra (celui de sa persona : jamais écrit
    ici), puis qui elle est (``persona``, sa persona rendue : ``self.portrayed``) — le résumé est écrit à sa place, et
    épinglé dans son fil (ADR 0153)."""
    intro = phrase("self.portrayed.intro", name=name, persona=persona)
    return phrase("transcript.compact.system", name=name) + "\n\n" + intro


def _compact_request(frame: Frame, person: str, rows: Sequence[Mapping[str, Any]], previous: str | None,
                     withheld: Collection[int], p: TranscriptParams, times: int, *, system: str,
                     call_id: str) -> tuple[LLMRequest, bool]:
    """L'appel du résumé, avec le début du fil divisé par deux ``times`` fois (``fit_by_halving``) ; et s'il reste
    de quoi diviser."""
    cut = halved(rows, times, least=1)
    prompt = (phrase("transcript.compact.previous", text=previous) + "\n\n" if previous else "") + \
        phrase("transcript.compact.next") + "\n" + _compact_lines(frame, person, cut, p.mark_after_us, withheld)
    return LLMRequest(role="compact", call_id=call_id, system_stable=system, messages=(Message("user", prompt),),
                      max_tokens=p.compact_max_tokens, lane="background", priority=3), len(cut) > 1


def _compact_lines(frame: Frame, person: str, rows: Sequence[Mapping[str, Any]], after_us: int,
                   withheld: Collection[int] = ()) -> str:
    """Les échanges à replier, chacun sous le nom de qui parle et daté comme
    dans l'historique (le premier en absolu). Ce qu'on lui a demandé de garder pour soi, dit dans un salon, n'y
    entre pas : le résumé reste devant le salon bien après les messages (``withheld``, ADR 0082)."""
    tz = frame.env.tz_of(frame.root)
    name = clean_display_name(frame.get(identity_c.IDENTITY(person)).name) or phrase("transcript.compact.someone")
    her = self_c.name_of(frame.get(self_c.PERSONA))
    lines = []
    prev: int | None = None
    for r in rows:
        at = int(r["at"])
        mark = gap_mark(prev, at, tz, after_us) if prev is not None else opening_mark(at, frame.now, tz)
        prev = at
        who = (phrase("transcript.compact.her_initiative", her=her) if r.get("kind") == Kind.INITIATIVE else her) \
            if r["role"] == "assistant" else (clean_display_name(frame.get(identity_c.IDENTITY(r["person"])).name) or name)
        text = phrase("transcript.compact.withheld") if int(r["id"]) in withheld else r["text"]
        lines.append(f"{f'[{mark}] ' if mark else ''}{who} : {text}")
    return "\n".join(lines)


def secret_sources(store: Any, room: str, upto: int) -> set[int]:
    """Les messages d'un salon (jusqu'à ``upto``) d'où vient ce qu'on lui a demandé de garder pour soi — par la porte
    de la mémoire (ADR 0078). Les sources des secrets se déplient en Python (``json_values``), puis le fil dit
    lesquelles sont de ce salon."""
    sources: set[int] = set()
    v = memory_c.KNOWLEDGE
    for (raw,) in store.query_mind(select(v.c.sources).where(v.c.secret == 1)):
        for x in json_values(raw):
            try:
                seq = int(x)
            except (TypeError, ValueError):
                continue
            if seq <= upto:
                sources.add(seq)
    t = c.thread_table()
    found: set[int] = set()
    wanted = sorted(sources)
    for start in range(0, len(wanted), 500):
        chunk = wanted[start:start + 500]
        found |= {int(r[0]) for r in store.query_mind(select(t.c.id).where(t.c.room == room, t.c.id.in_(chunk)))}
    return found


@TRANSCRIPT.process("transcript.compact", wake_on=[memory_c.CONSOLIDATED],
                    catch_up=CatchUp.ONCE, max_quantum_s=3600)
class Compact:
    """Replie le début des fils trop longs, un fil par passage (les appels de
    modèle restent rares), et seulement ce que la mémoire a déjà relu."""

    def __init__(self) -> None:
        self.seen = -1
        self.retry_at = 0
        self.failures: OrderedDict[str, tuple[int, int, int]] = OrderedDict()

    def next_due(self, state: TranscriptState, frame: Frame, last_run: int | None) -> int | None:
        checkpoint = frame.get(memory_c.CHECKPOINT)
        if checkpoint == self.seen and not self.failures:
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
        t = c.thread_table()
        topics = [(str(person), None) for (person,) in store.query_mind(
            select(t.c.person).distinct().where(t.c.room.is_(None)).order_by(t.c.person))]
        topics += [(f"room:{room}", str(room)) for (room,) in store.query_mind(
            select(t.c.room).distinct().where(t.c.room.is_not(None)).order_by(t.c.room))]
        for person, room in topics:
            failed_at, cap, attempts = self.failures.get(person, (0, p.compact_batch, 0))
            if failed_at > frame.now:
                continue
            summary = state.summaries.get(person)
            if room and summary:
                kept = secret_sources(store, room, summary[0])
                fresh = sorted(kept - set(state.withheld.get(person, ())))
                if fresh:
                    # un secret dit dans ce salon (déclaré après coup) était repris : on le replie de nouveau, tu ;
                    # la clé dit les secrets qui le refont (un second, plus ancien, le refait encore)
                    commit = await ctx.emit(c.SUMMARY_RESET.draft(
                        person=person, reason="secret",
                        dedupe_key=f"résumé-refait:{person}:{','.join(map(str, fresh))}"))
                    if commit.deduped:
                        continue  # déjà refait : un salon coincé ne retient pas les autres
                    return
            since = summary[0] if summary else 0
            where = (t.c.room == room, t.c.id > since) if room else (
                t.c.person == person, t.c.room.is_(None), t.c.id > since)
            total = _count(store, *where)
            if total <= p.compact_after:
                continue
            # les plus anciens d'abord, par lots : jamais « résumé » ce qui n'a pas été lu ; ni ce qu'il faut garder
            # tel quel (``keep`` peut dépasser ``compact_after`` : une borne négative, SQLite la lisait « sans
            # borne » et repliait tout, MariaDB la refuse)
            got = _messages_of(store, *where, t.c.id <= checkpoint, newest_first=False,
                               limit=max(0, min(total - p.keep, p.compact_batch, cap)))
            folded = [dict(zip(_COLUMNS, r, strict=True)) for r in got]
            if not folded or (len(folded) < p.compact_min_fold and not attempts):
                continue
            previous = store.content([summary[1]]).get(summary[1]) if summary else None
            withheld = secret_sources(store, room, folded[-1]["id"]) & {int(r["id"]) for r in folded} if room else set()
            self.retry_at = frame.now + p.compact_retry_us  # si l'appel lève, pas de rafale
            system = compact_system(self_c.name_of(frame.get(self_c.PERSONA)), frame.get(self_c.PORTRAYED("compact")))

            # le début du fil se replie par moitiés jusqu'à tenir : la suite attend le passage d'après
            request, times = fit_by_halving(ctx.llm, partial(
                _compact_request, frame, person, folded, previous, withheld, p, system=system,
                call_id=f"{ctx.run_id}#{person}"))
            folded = halved(folded, times, least=1)
            response, text = None, ""
            try:
                response = await ctx.llm.call(request)
                text = (response.text or "").strip() if response.stop != "max_tokens" else ""
            except Exception as exc:  # noqa: BLE001 — un fil en panne ne retient pas les autres
                logging.getLogger(__name__).warning("compactage %s : %s", person, type(exc).__name__)
            if not text:
                retry = frame.now + min(DAY, p.compact_retry_us * 2 ** min(attempts, 16))
                self.failures[person] = (retry, max(1, len(folded) // 2), attempts + 1)
                self.failures.move_to_end(person)
                while len(self.failures) > 256:
                    self.failures.popitem(last=False)
                logging.getLogger(__name__).warning("compactage incomplet, lot réduit à %s message(s)",
                                                    max(1, len(folded) // 2))
                continue
            self.failures.pop(person, None)
            self.retry_at = 0
            speakers = tuple(sorted({str(r["person"]) for r in folded if r["role"] == "user" and r["person"]}))
            await ctx.emit(c.COMPACTED.draft(person=person, upto=folded[-1]["id"], summary=Content.of(text, level=2),
                                             count=len(folded), call_id=request.call_id, model=response.model,
                                             speakers=speakers if room else (),
                                             withheld=tuple(sorted(withheld & {int(r["id"]) for r in folded}))))
            return  # un fil par passage ; le suivant au prochain réveil
        self.seen = checkpoint
        self.retry_at = min((v[0] for v in self.failures.values()), default=0)

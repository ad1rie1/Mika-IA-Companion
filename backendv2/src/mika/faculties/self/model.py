"""Ce qu'elle sait d'elle (ADR 0088) : tenir parole, mener au bout, voir venir — ses réussites et ses ratés, gardés en
marques (``Mark``), et ce qu'elle en sait, en tendances (« tu tiens parole », « tes intuitions tombent souvent
juste »), jamais en nombres. Une seule promesse échue efface « tu tiens parole » ; une promesse tenue en retard ne
compte pas comme tenue ; une rêverie n'est pas mener au bout ; une date officielle ne dit rien de ce qu'elle voit
venir, et ne pas savoir comment un moment a tourné non plus. L'estime n'en est pas touchée : ce n'est pas ce qu'elle
vaut, c'est ce qu'elle sait d'elle (ADR 0046)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import select

from mika.contracts import attention as attention_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import projects as projects_c
from mika.contracts import self_ as c
from mika.faculties.self.faculty import SELF, SelfState
from mika.faculties.self.knobs import SelfParams, params
from mika.faculties.self.lines import KNOWN_LINES, passion_lines
from mika.faculties.self.records import Mark
from mika.kernel.clock import DAY
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.vocab.episodes import CONVERSATIONAL
from mika.vocab.lineage import Lineage, admits, requirement
from mika.vocab.phrasebook import phrase

#: ses marques gardées : au plus tant, et pas plus vieilles que tant de jours
RECORD_KEPT = 400
RECORD_DAYS = 90

#: les domaines d'une marque, et leurs issues
PROMISES, FINISHING, FORESIGHT = "promises", "finishing", "foresight"
KEPT, SLIPPED, FINISHED, STRUGGLED = "kept", "slipped", "finished", "struggled"
#: ses changements d'avis récents montrés dans son prompt : au plus tant
CHANGES_SHOWN = 1


@dataclass(frozen=True, slots=True)
class Change:
    """Un changement d'avis sur elle-même (memory_self_changes) : ce qu'elle pensait, ce qu'elle pense."""

    was: int
    was_text: str
    item: int
    text: str
    at: int
    sensitivity: int = 0


def _mark(s: SelfState, mark: Mark) -> SelfState:
    oldest = mark.at - RECORD_DAYS * DAY
    return replace(s, record=(*(m for m in s.record if m.at >= oldest), mark)[-RECORD_KEPT:])


def _marked(s: SelfState, domain: str, ref: int) -> bool:
    return any(m.domain == domain and m.ref == ref for m in s.record)


@SELF.reducer(attention_c.EXPECTATION_MISSED)
def _promise_late(s: SelfState, e, cx) -> SelfState:
    """Sa parole pas tenue à temps : une promesse en retard est une promesse qui a glissé, même tenue ensuite."""
    d = e.data
    if d.kind != attention_c.PROMISE or d.ref is None or _marked(s, PROMISES, d.ref):
        return s
    return _mark(s, Mark(e.at, PROMISES, SLIPPED, ref=d.ref))


@SELF.reducer(memory_c.PROMISE_RESOLVED)
def _promise_resolved(s: SelfState, e, cx) -> SelfState:
    """Tenue : elle a tenu parole ; échue sans l'avoir tenue : elle l'a laissée glisser. Une promesse à laquelle la
    personne renonce, ou qu'un rappel programmé porte, n'est ni l'un ni l'autre."""
    d = e.data
    if _marked(s, PROMISES, d.promise):
        return s
    if d.status == memory_c.HONORED:
        return _mark(s, Mark(e.at, PROMISES, KEPT, ref=d.promise))
    if d.by == memory_c.EXPIRED_BY:
        return _mark(s, Mark(e.at, PROMISES, SLIPPED, ref=d.promise))
    return s


@SELF.reducer(goals_c.GOAL_CLOSED)
def _goal_finished(s: SelfState, e, cx) -> SelfState:
    """Un but mené au bout, ou bloqué. Un rappel dit, une rêverie, une réflexion, une fin tranquille, un abandon ne
    sont ni l'un ni l'autre."""
    d = e.data
    if d.kind == goals_c.REMINDER or d.reason in goals_c.MUSINGS or goals_c.reflective(d.origin, d.source):
        return s
    outcome = {goals_c.ACHIEVED: FINISHED, goals_c.STUCK: STRUGGLED}.get(d.status)
    return _mark(s, Mark(e.at, FINISHING, outcome, ref=d.goal)) if outcome else s


@SELF.reducer(projects_c.OBJECTIVE_CLOSED)
def _objective_finished(s: SelfState, e, cx) -> SelfState:
    """Un objectif de projet, dans son mode à elle (en mode impersonnel, ce n'est pas elle qui y travaille)."""
    d = e.data
    if d.mode != projects_c.PERSONA:
        return s
    outcome = {projects_c.DONE: FINISHED, projects_c.BLOCKED: STRUGGLED}.get(d.status)
    return _mark(s, Mark(e.at, FINISHING, outcome, ref=d.objective)) if outcome else s


@SELF.reducer(memory_c.RESOLVED)
def _foreseen(s: SelfState, e, cx) -> SelfState:
    """Comment un moment a tourné, au regard de ce qu'elle en attendait (ADR 0086) : l'écart, au carré. Une date
    officielle ne dit rien de ce qu'elle voit venir ; ne pas savoir non plus."""
    d = e.data
    value = memory_c.OUTCOME_VALUE.get(d.outcome)
    if value is None or d.likelihood is None or d.nature == memory_c.OFFICIAL:
        return s
    return _mark(s, Mark(e.at, FORESIGHT, d.outcome, round((value - d.likelihood) ** 2, 4), ref=d.event))


def knows(record: Sequence[Mark], now: int, p: SelfParams) -> tuple[str, ...]:
    """Ce qu'elle sait d'elle, d'après ses marques récentes : des codes de ligne (``KNOWN_LINES``), pur."""
    recent = [m for m in record if m.at >= now - p.know_window_us]
    out: list[str] = []
    kept = sum(1 for m in recent if m.domain == PROMISES and m.outcome == KEPT)
    slipped = sum(1 for m in recent if m.domain == PROMISES and m.outcome == SLIPPED)
    if kept >= p.know_kept_from and not slipped:
        out.append(c.PROMISES_KEPT)
    elif slipped >= p.know_slipped_from and slipped > kept:
        out.append(c.PROMISES_SLIP)
    done = sum(1 for m in recent if m.domain == FINISHING and m.outcome == FINISHED)
    stuck = sum(1 for m in recent if m.domain == FINISHING and m.outcome == STRUGGLED)
    if done >= p.know_done_from and 2 * stuck <= done:
        out.append(c.FINISHING_DONE)
    elif stuck >= p.know_stuck_from and stuck > done:
        out.append(c.FINISHING_STRUGGLE)
    seen = [m.value for m in record if m.domain == FORESIGHT and m.at >= now - p.foresight_window_us]
    if len(seen) >= p.foresight_min:
        brier = sum(seen) / len(seen)
        if brier <= p.foresight_right_below:
            out.append(c.FORESIGHT_RIGHT)
        elif brier >= p.foresight_off_above:
            out.append(c.FORESIGHT_OFF)
    return tuple(out)


@SELF.fact(c.KNOWS)
def _knows(s: SelfState, cx) -> tuple[str, ...]:
    return knows(s.record, cx.now, params(cx.params))




@SELF.enricher("self_changes", episodes=CONVERSATIONAL, deadline_ms=300, reads=[identity_c.PERSON, identity_c.PRESUMED])
async def _changes(s: SelfState, frame: Frame, ports: Mapping[str, Any]) -> list[Change]:
    """Ses changements d'avis récents (la porte de la mémoire : ``memory_self_changes``), devant qui peut les
    entendre — l'avant comme le maintenant (une note qu'elle a demandé de taire ne se dit pas, même ancienne)."""
    store, p = ports.get("store"), params(frame.env.params_of("self", frame.root))
    ep, aud = frame.episode, frame.audience
    if store is None or aud is None or p.change_shown_us <= 0:
        return []
    person = frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else None
    resolve, presumed = identity_c.resolvers(frame.get)
    v = memory_c.SELF_CHANGES
    # départagés par l'élément : les mêmes huit sur les deux moteurs
    rows = store.query_mind(select(*(v.c[n] for n in memory_c.SELF_CHANGES_COLUMNS))
                            .where(v.c.changed_at >= frame.now - p.change_shown_us)
                            .order_by(v.c.changed_at.desc(), v.c.item.desc(), v.c.was.desc()).limit(8))
    out: list[Change] = []
    for was, was_text, item, text, _kind, sensitivity, secret, at in rows:
        lineage = Lineage(requirements=(requirement(was, (), int(sensitivity), secret=bool(secret)),
                                        requirement(item, (), int(sensitivity), secret=bool(secret))))
        if was_text and text and admits(lineage, person, aud, resolve=resolve, presumed=presumed).ok:
            out.append(Change(int(was), str(was_text), int(item), str(text), int(at), int(sensitivity)))
    return out[:CHANGES_SHOWN]




@SELF.enricher("passions", episodes=CONVERSATIONAL, deadline_ms=300, reads=[c.INTERESTS])
async def _passions(s: SelfState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, str]:
    """Le sujet de ses intérêts vécus (dits par elle, dicibles à tous ; ADR 0089)."""
    store = ports.get("store")
    refs = {i.key: i.label_ref for i in frame.get(c.INTERESTS) if not i.line and i.label_ref}
    texts = store.content(list(refs.values())) if store is not None and refs else {}
    return {k: texts[r] for k, r in refs.items() if texts.get(r)}


@SELF.section("self_model", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=55,
              title=phrase("self.knows.title"),
              reads=[c.KNOWS, c.INTERESTS, identity_c.PERSON, identity_c.PRESUMED])
def _self_model(s: SelfState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    lines = [KNOWN_LINES[code]() for code in frame.get(c.KNOWS) if code in KNOWN_LINES]
    lines += passion_lines(frame.get(c.INTERESTS), enrich.get("passions") or {})
    changes: list[Change] = enrich.get("self_changes") or []
    lines += [phrase("self.knows.changed", was=ch.was_text, now=ch.text) for ch in changes]
    if not lines:
        return None
    return SectionBody("\n".join(lines),
                       level=max((ch.sensitivity for ch in changes), default=0),
                       provenance=tuple(f"memory:{ch.item}" for ch in changes))

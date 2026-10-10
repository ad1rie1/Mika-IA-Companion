"""Ce qu'elle attend (ADR 0086) : un moment qui approche, de quelqu'un qui compte pour elle — ou du monde, quand elle
l'attend avec un sentiment —, se fait attendre : avec espoir, ou avec inquiétude quand ce qu'on en ressent est
sombre (une opération, un examen redouté).

Son poids : ce que le moment compte × ce que la personne lui est (sa propriétaire, une proche, une amie ; une
connaissance ne se fait pas attendre) × sa vraisemblance × sa proximité (de plus en plus fort les jours d'avant).
Un seul domine à la fois — on n'attend pas dix choses en même temps —, et se ressent une fois par jour, éveillée.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from mika.contracts import attention as c
from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import social as social_c
from mika.faculties.attention.faculty import ATTENTION, AttentionParams, AttentionState, params
from mika.kernel.clock import HOUR, local
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.vocab.affect import Appraisal, Emotion, facets_valence

#: la vraisemblance d'un moment noté avant qu'on la garde (ADR 0084)
LIKELY_UNKNOWN = 0.8
#: les jours retenus au plus (les fils les plus récents)
ANTICIPATED_KEPT = 64


def attachment(ev: memory_c.LifeEvent, person_of: Callable[[str], str], owners: frozenset[str],
               closeness: Callable[[str], str], p: AttentionParams) -> float:
    """Ce que ce moment lui est : celui de sa propriétaire, d'une proche, d'une amie ; du monde, s'il l'attend avec un
    sentiment. Le plus attaché de ses personnes."""
    if not ev.about:
        return p.anticipation_world if ev.empathy else 0.0
    best = 0.0
    for key in ev.about:
        person = person_of(key)
        if person in owners:
            best = max(best, p.anticipation_owner)
        elif closeness(person) == social_c.CLOSE:
            best = max(best, p.anticipation_close)
        elif closeness(person) == social_c.FRIEND:
            best = max(best, p.anticipation_friend)
    return best


def weight_of(ev: memory_c.LifeEvent, now: int, attached: float, p: AttentionParams) -> float:
    """Ce qu'un moment pèse dans ce qu'elle attend : ce qu'il compte × ce qu'il lui est × sa vraisemblance × sa
    proximité (pleine le jour venu, nulle à ``anticipation_ramp_us`` et au-delà)."""
    ahead = ev.when - now
    near = 1.0 if ahead <= 0 else max(0.0, 1.0 - ahead / p.anticipation_ramp_us)
    likely = ev.likelihood if ev.likelihood is not None else LIKELY_UNKNOWN
    return round(max(0.0, min(1.0, ev.importance)) * attached * likely * near, 4)


def emotion_of(ev: memory_c.LifeEvent) -> Emotion:
    """Avec quoi elle l'attend : de l'inquiétude quand ce qu'elle en ressent (sinon ce qu'en ressent la personne) est
    sombre, de l'espoir sinon."""
    return Emotion.ANXIOUS if facets_valence(ev.empathy or ev.felt) < 0 else Emotion.HOPEFUL


@ATTENTION.fact(c.ANTICIPATION, reads=[memory_c.UPCOMING, identity_c.PERSON, identity_c.OWNERS,
                                       social_c.CLOSENESS])
def _anticipation(s: AttentionState, cx) -> c.Anticipated | None:
    p = params(cx.params)
    owners = frozenset(cx.facts.get(identity_c.OWNERS) or ())

    def person_of(key: str) -> str:
        return cx.facts.get(identity_c.PERSON(key)) or key

    def closeness(person: str) -> str:
        return cx.facts.get(social_c.CLOSENESS(person))

    best: tuple[float, memory_c.LifeEvent] | None = None
    for ev in cx.facts.get(memory_c.UPCOMING) or ():
        w = weight_of(ev, cx.now, attachment(ev, person_of, owners, closeness, p), p)
        if w >= p.anticipation_from and (best is None or w > best[0]):
            best = (w, ev)
    if best is None:
        return None
    w, ev = best
    return c.Anticipated(event=ev.id, thread=ev.key, emotion=emotion_of(ev).value, weight=w, about=ev.about,
                         when=ev.when)


def today(frame: Frame) -> int:
    return frame.local().date().toordinal()


@ATTENTION.process("attention.anticipate", wake_on=[memory_c.EVENT_NOTED, memory_c.RESOLVED, c.ANTICIPATED],
                   lane="background", catch_up=CatchUp.SKIP, max_quantum_s=600)
class Anticipate:
    """Ce qu'elle attend le plus, ressenti une fois par jour, éveillée."""

    def _due(self, state: AttentionState, frame: Frame) -> c.Anticipated | None:
        if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE:
            return None
        got = frame.get(c.ANTICIPATION)
        if got is None or state.anticipated.get(got.thread or got.event) == today(frame):
            return None
        return got

    def next_due(self, state: AttentionState, frame: Frame, last_run: int | None) -> int | None:
        if self._due(state, frame) is not None:
            return frame.now
        # ce qui approche monte heure après heure : on y repense chaque heure tant qu'il y a quelque chose à venir
        return (last_run or frame.now) + HOUR if frame.get(memory_c.UPCOMING) else None

    async def run(self, ctx: Any) -> None:
        got = self._due(ctx.state, ctx.frame)
        if got is None:
            return
        key = got.thread or got.event
        await ctx.emit(c.ANTICIPATED.draft(**got.model_dump(), dedupe_key=f"attendu:{key}:{today(ctx.frame)}"))


@ATTENTION.reducer(c.ANTICIPATED)
def _anticipated(s: AttentionState, e, cx) -> AttentionState:
    kept = s.anticipated.set(e.data.thread or e.data.event, local(e.at, cx.tz).date().toordinal())
    if len(kept) > ANTICIPATED_KEPT:
        kept = FrozenDict(sorted(kept.items(), key=lambda kv: (kv[1], kv[0]))[-ANTICIPATED_KEPT:])
    return replace(s, anticipated=kept)


@ATTENTION.appraisal(c.ANTICIPATED)
def _anticipated_felt(e, cx) -> Appraisal:
    """L'attendre : de l'espoir (« impatience ») ou de l'inquiétude (« appréhension »), à la mesure de son poids."""
    p = params(cx.params)
    d = e.data
    anxious = d.emotion == Emotion.ANXIOUS.value
    return Appraisal(Emotion.ANXIOUS if anxious else Emotion.HOPEFUL,
                     round(min(p.anticipation_max, d.weight * p.anticipation_gain), 3),
                     reason="appréhension" if anxious else "impatience")

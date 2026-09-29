"""La faculté ``attention`` : sa tranche, ses réducteurs, ses faits, ce que ses
événements font ressentir.

- **Pensées** : ce qu'il en reste suit une demi-vie (``intensité ·
  ½^(Δ/demi-vie)``, lu à l'instant) ; en parler à la personne concernée la
  divise par deux ; une pensée trop faible s'éteint.
- **Un échange qui marque** (une émotion déclarée forte, ou nettement
  négative) laisse une pensée — une seule par personne à la fois : un
  deuxième tour chargé avec la même personne ravive la pensée existante au
  lieu d'en créer une autre, et il n'y a jamais plus de trois pensées nées
  d'échanges en même temps (douze insultes ne font pas douze ruminations).
- **Attentes** : écrire d'elle-même à quelqu'un fait attendre sa réponse
  (vingt minutes sur l'application, une heure par message) ; quelqu'un qui
  lui manque fait attendre son retour.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from pydantic import BaseModel, ConfigDict

from mika.contracts import attention as c
from mika.contracts import expression as expression_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.faculty import Faculty
from mika.kernel.state import FrozenDict
from mika.vocab import affect as A
from mika.vocab.affect import Appraisal, Declared, Emotion
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable


class AttentionParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    half_life_us: int = 6 * HOUR
    fade_below: float = 0.1
    max_thoughts: int = 8
    # un échange qui marque
    marking_intensity: float = 0.75
    marking_valence: float = -0.2
    marking_min_intensity: float = 0.5
    birth_factor: float = 0.7
    exchange_spacing_us: int = 30 * MINUTE
    exchange_cap: int = 3
    # une croyance révisée, un manque
    revision_intensity: float = 0.3
    missing_intensity: float = 0.3
    missing_check_us: int = 30 * MINUTE
    # y repenser
    dwell_every_us: int = 30 * MINUTE
    dwell_from: float = 0.3
    dwell_factor: float = 0.3
    birth_appraisal_factor: float = 0.5
    # attentes
    reply_window_us: int = 20 * MINUTE
    reply_window_message_us: int = HOUR
    # la nuit : les pensées de la veille s'allègent (÷3) et se calment
    digest_after_sleep_us: int = 3 * HOUR
    digest_min_age_us: int = 2 * HOUR
    digest_factor: float = 1 / 3
    reflective_from: float = 0.25
    # une pensée qui insiste pousse à en reparler (log-odds)
    thought_from: float = 0.4
    thought_evidence: float = 4.0


@dataclass(frozen=True, slots=True)
class Thought:
    id: int
    text_ref: str
    emotion: str
    intensity: float  # à ``touched_at``
    touched_at: int
    born_at: int
    origin: str
    about: tuple[str, ...] = ()
    sensitivity: int = 2


@dataclass(frozen=True, slots=True)
class Pending:
    """Un échange qui a marqué, une croyance révisée : la pensée reste à écrire."""

    source: int
    origin: str
    person: str | None
    emotion: str
    intensity: float
    at: int
    public: bool = False
    extra: int | None = None  # la croyance remplacée


@dataclass(frozen=True, slots=True)
class Expectation:
    kind: str
    person: str
    since: int
    deadline: int | None


@dataclass(frozen=True, slots=True)
class AttentionState:
    thoughts: FrozenDict[int, Thought] = field(default_factory=FrozenDict)
    pending: tuple[Pending, ...] = ()
    expectations: FrozenDict[str, Expectation] = field(default_factory=FrozenDict)
    #: les initiatives en cours (corrélation → raisons) : une salutation n'attend pas de réponse
    openings: FrozenDict[str, str] = field(default_factory=FrozenDict)
    ignored: int = 0
    #: les personnes dont la réponse n'est pas venue à temps (depuis quand) : une réponse tardive compte encore
    late: FrozenDict[str, int] = field(default_factory=FrozenDict)
    dwelt_at: int = 0
    digested_night: str = ""


ATTENTION = Faculty("attention", state=AttentionState, init=lambda p: AttentionState(), params=AttentionParams)
ATTENTION.declare(*c.ALL)


def params(p: AttentionParams | None) -> AttentionParams:
    return p if p is not None else AttentionParams()


def current(t: Thought, now: int, p: AttentionParams) -> float:
    return t.intensity * 0.5 ** (max(0, now - t.touched_at) / p.half_life_us)


def _alive(s: AttentionState, now: int, p: AttentionParams) -> FrozenDict[int, Thought]:
    """Les pensées encore vivantes, au plus ``max_thoughts`` (les plus faibles s'effacent)."""
    kept = sorted(((current(t, now, p), t) for t in s.thoughts.values() if current(t, now, p) >= p.fade_below),
                  key=lambda x: (-x[0], x[1].id))[: p.max_thoughts]
    return FrozenDict({t.id: t for _, t in kept})


def _marking(declared: Declared, p: AttentionParams) -> bool:
    if declared.intensity < p.marking_min_intensity:
        return False
    return declared.intensity >= p.marking_intensity or A.valence(declared.emotion) <= p.marking_valence


def _expect(s: AttentionState, kind: str, person: str, since: int, deadline: int | None) -> AttentionState:
    return replace(s, expectations=s.expectations.set(f"{kind}:{person}", Expectation(kind, person, since, deadline)))


# ── Réducteurs ────────────────────────────────────────────────────────────


@ATTENTION.reducer(rt.UTTERANCE, reads=[identity_c.PERSON])
def _uttered(s: AttentionState, e, cx) -> AttentionState:
    d = e.data
    if not d.visible or not d.target or not is_identifiable(d.target):
        return s
    p = params(cx.params)
    person = cx.facts.get(identity_c.PERSON(d.target))
    # y revenir avec la personne soulage — pas l'échange même qui l'a fait naître ou raviver
    thoughts = s.thoughts
    for t in s.thoughts.values():
        if person in t.about and e.at - t.touched_at >= p.exchange_spacing_us:
            thoughts = thoughts.set(t.id, replace(t, intensity=current(t, e.at, p) / 2, touched_at=e.at))
    s = replace(s, thoughts=thoughts)
    if d.kind == Kind.INITIATIVE:
        reasons = s.openings.get(e.correlation, "").split(",")
        s = replace(s, openings=s.openings.delete(e.correlation))
        if social_c.GREETING not in reasons:
            window = p.reply_window_message_us if d.channel == "telegram" else p.reply_window_us
            s = _expect(s, c.REPLY, person, e.at, e.at + window)
    declared = Declared.decode(d.annotation(expression_c.EMOTION_ANNOTATION))
    if d.kind != Kind.REPLY or declared is None or not _marking(declared, p):
        return s
    # un échange qui marque : une pensée par personne à la fois
    alive = _alive(s, e.at, p)
    same = sorted((t for t in alive.values() if t.origin == c.EXCHANGE and person in t.about
                   and e.at - t.touched_at < p.exchange_spacing_us), key=lambda t: t.id)
    if same:
        t = same[0]
        stronger = max(current(t, e.at, p), declared.intensity * p.birth_factor)
        return replace(s, thoughts=s.thoughts.set(t.id, replace(t, intensity=stronger, touched_at=e.at)))
    born = sum(1 for t in alive.values() if t.origin == c.EXCHANGE)
    queued = sum(1 for q in s.pending if q.origin == c.EXCHANGE)
    if born + queued >= p.exchange_cap or any(q.person == person for q in s.pending):
        return s
    pending = Pending(d.reply_to or e.seq, c.EXCHANGE, person, declared.emotion.value,
                      round(declared.intensity * p.birth_factor, 3), e.at, public=d.room is not None)
    return replace(s, pending=(*s.pending, pending))


@ATTENTION.reducer(memory_c.BELIEVED)
def _revised(s: AttentionState, e, cx) -> AttentionState:
    """Cesser de croire quelque chose coûte : une pensée de confusion."""
    if e.data.replaces is None:
        return s
    p = params(cx.params)
    return replace(s, pending=(*s.pending, Pending(e.seq, c.REVISION, None, Emotion.CONFUSED.value,
                                                   p.revision_intensity, e.at, extra=e.data.replaces)))


@ATTENTION.reducer(rt.EPISODE_STARTED, reads=[identity_c.PERSON])
def _reaching_out(s: AttentionState, e, cx) -> AttentionState:
    """Prendre la parole d'elle-même : on retient pourquoi (une salutation
    n'attend pas de réponse) ; relancer quelqu'un qui manque : on attend son retour."""
    d = e.data
    if d.kind != Kind.INITIATIVE or not d.target:
        return s
    openings = s.openings.set(e.correlation, d.reason)
    if len(openings) > 16:  # des épisodes qui n'ont jamais parlé (abstention, supplantés)
        openings = FrozenDict(sorted(openings.items())[-16:])  # les identifiants d'épisode sont chronologiques
    s = replace(s, openings=openings)
    if not {social_c.RECONTACT, social_c.CHAT} & set(d.reason.split(",")):
        return s
    return _expect(s, c.RETURN, cx.facts.get(identity_c.PERSON(d.target)), e.at, None)


@ATTENTION.reducer(c.THOUGHT_BORN)
def _born(s: AttentionState, e, cx) -> AttentionState:
    d = e.data
    p = params(cx.params)
    thought = Thought(e.seq, d.text.ref or "", d.emotion, d.intensity, e.at, e.at, d.origin, tuple(d.about),
                      d.sensitivity)
    s = replace(s, thoughts=_alive(replace(s, thoughts=s.thoughts.set(e.seq, thought)), e.at, p),
                pending=tuple(q for q in s.pending if q.source != d.source or q.origin != d.origin))
    if d.origin == c.MISSING and d.about:
        s = _expect(s, c.RETURN, d.about[0], e.at, None)
    return s


@ATTENTION.reducer(c.DIGESTED)
def _digested(s: AttentionState, e, cx) -> AttentionState:
    thoughts = s.thoughts
    for item in e.data.items:
        t = thoughts.get(item.thought)
        if t is not None:
            thoughts = thoughts.set(t.id, replace(t, intensity=item.after, touched_at=e.at, emotion=item.emotion))
    return replace(s, thoughts=thoughts, digested_night=e.data.night)


@ATTENTION.reducer(c.DWELT)
def _dwelt(s: AttentionState, e, cx) -> AttentionState:
    return replace(s, dwelt_at=e.at)


@ATTENTION.reducer(c.EXPECTATION_MET)
def _met(s: AttentionState, e, cx) -> AttentionState:
    d = e.data
    s = replace(s, expectations=s.expectations.delete(f"{d.kind}:{d.person}"))
    if d.kind == c.REPLY:
        return replace(s, ignored=0, late=s.late.delete(d.person))
    # quelqu'un qui manquait revient : le manque s'éteint (parce qu'il est là, pas parce que le temps a passé)
    thoughts = s.thoughts
    for t in s.thoughts.values():
        if t.origin == c.MISSING and d.person in t.about:
            thoughts = thoughts.delete(t.id)
    return replace(s, thoughts=thoughts)


@ATTENTION.reducer(c.EXPECTATION_MISSED)
def _missed(s: AttentionState, e, cx) -> AttentionState:
    d = e.data
    s = replace(s, expectations=s.expectations.delete(f"{d.kind}:{d.person}"))
    if d.kind != c.REPLY:
        return s
    return replace(s, ignored=s.ignored + 1, late=s.late.set(d.person, e.at))


# ── Faits ─────────────────────────────────────────────────────────────────


def readings(s: AttentionState, now: int, p: AttentionParams) -> tuple[c.ThoughtReading, ...]:
    out = [c.ThoughtReading(t.id, t.text_ref, t.emotion, round(current(t, now, p), 4), t.origin, t.about,
                            t.sensitivity, t.born_at)
           for t in s.thoughts.values() if current(t, now, p) >= p.fade_below]
    return tuple(sorted(out, key=lambda r: (-r.intensity, r.id)))


@ATTENTION.fact(c.THOUGHTS)
def _thoughts(s: AttentionState, cx) -> tuple[c.ThoughtReading, ...]:
    return readings(s, cx.now, params(cx.params))


@ATTENTION.fact(c.IGNORED)
def _ignored(s: AttentionState, cx) -> int:
    return s.ignored


# ── Ce que ses événements font ressentir ──────────────────────────────────


def _emotion(name: str) -> Emotion:
    return A.emotion_of(name) or Emotion.THINKING


@ATTENTION.appraisal(c.THOUGHT_BORN)
def _birth_felt(e, cx) -> Appraisal:
    p = params(cx.params)
    return Appraisal(_emotion(e.data.emotion), e.data.intensity * p.birth_appraisal_factor, reason=e.data.origin,
                     relational=e.data.origin == c.EXCHANGE)


@ATTENTION.appraisal(c.DWELT)
def _dwell_felt(e, cx) -> Appraisal:
    p = params(cx.params)
    return Appraisal(_emotion(e.data.emotion), e.data.intensity * p.dwell_factor, reason="elle y repense",
                     relational=e.data.origin == c.EXCHANGE)


@ATTENTION.appraisal(c.EXPECTATION_MET)
def _met_felt(e, cx) -> list[Appraisal]:
    if e.data.kind == c.RETURN:
        # enfin : de la joie, pour elle et envers la personne revenue
        return [Appraisal(Emotion.HAPPY, 0.4, reason="retour"),
                Appraisal(Emotion.HAPPY, 0.4, toward=e.data.person, reason="retour")]
    return [Appraisal(Emotion.RELIEVED, 0.25, reason="réponse")]


@ATTENTION.appraisal(c.DIGESTED)
def _digest_felt(e, cx) -> Appraisal | None:
    """Ce qui s'est calmé pendant la nuit : un peu de soulagement au réveil."""
    calmed = [i for i in e.data.items if i.emotion != "" and i.after < i.before]
    if not calmed:
        return None
    return Appraisal(Emotion.RELIEVED, min(0.3, 0.1 * len(calmed)), reason="digestion")


@ATTENTION.appraisal(c.EXPECTATION_MISSED)
def _missed_felt(e, cx) -> Appraisal | None:
    return Appraisal(Emotion.SAD, 0.15, reason="sans réponse") if e.data.kind == c.REPLY else None


"""``affect`` : l'humeur générale, la posture envers chacun, la chaleur.

Ce qui la fait bouger en M1 : la balise ``[EMOTION:nom:intensité]`` qu'elle
écrit en parlant à quelqu'un (répondre, prendre la parole). Pas de balise →
aucune impulsion ; ``neutral`` explicite → une impulsion vers l'origine. Ses
pas de travail et ses murmures ne la font pas vibrer (le verdict d'un
travail, oui — ce sera une évaluation déclarée par ``goals``).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from mika.contracts import affect as c
from mika.contracts import body as body_c
from mika.contracts import expression as expression_c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.affect import physics as ph
from mika.faculties.affect import prose
from mika.faculties.affect.params import AffectParams, derive
from mika.kernel.arbitration import Anyone, Candidate
from mika.kernel.faculty import Faculty, Zone
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.vocab import affect as A
from mika.vocab.affect import Declared
from mika.vocab.episodes import CONVERSATIONAL, Kind, Tag
from mika.vocab.people import is_identifiable


@dataclass(frozen=True, slots=True)
class AffectState:
    mood: ph.Osc | None = None  # None : au repos depuis toujours
    stances: FrozenDict[str, ph.Stance] = field(default_factory=FrozenDict)


AFFECT = Faculty("affect", state=AffectState, init=lambda p: AffectState(), params=AffectParams, derive=derive)


def _params(p: AffectParams | None) -> AffectParams:
    return p if p is not None else AFFECT.default_params()  # type: ignore[return-value]


def _clockwork(cx: Any) -> ph.Clockwork:
    return ph.Clockwork(cx.tz, cx.facts.get(body_c.RHYTHM))


@AFFECT.reducer(rt.UTTERANCE, reads=[identity_c.PERSON, body_c.RHYTHM, social_c.CLOSENESS])
def _declared(s: AffectState, e, cx) -> AffectState:
    d = e.data
    if d.kind not in CONVERSATIONAL:
        return s
    declared = Declared.decode(d.annotation(expression_c.EMOTION_ANNOTATION))
    if declared is None:
        return s
    p = _params(cx.params)
    cw = _clockwork(cx)
    target = A.to_pad(declared.emotion, declared.intensity)
    mood = ph.advance_mood(s.mood, e.at, p, cw)
    gain = ph.mood_gain(declared.intensity, p)
    if d.target and is_identifiable(d.target):
        # ce qu'un inconnu lui fait vivre la touche moins que ce que vit un proche
        level = cx.facts.get(social_c.CLOSENESS(cx.facts.get(identity_c.PERSON(d.target))))
        gain = min(p.mood_gain_cap, gain * p.bleed(level))
    if gain > 0:
        mood = replace(mood, position=ph.ratchet(mood.position, target, gain))
    s = replace(s, mood=mood)
    if not d.target:
        return s  # un monologue : seule l'humeur générale bouge
    key = cx.facts.get(identity_c.PERSON(d.target))
    stance = s.stances.get(key) or ph.new_stance(e.at, p, cw)
    stance = ph.advance_stance(stance, e.at, p, cw)
    osc = replace(stance.osc, position=ph.ratchet(stance.osc.position, target, ph.resonant_gain(target, p)))
    recent = (*stance.recent, (e.at, declared.emotion.value))[-ph.RECENT_IMPULSES:]
    stance = replace(stance, osc=osc, declared=declared.encode(), declared_at=e.at, recent=recent)
    if is_identifiable(d.target) and e.at - stance.folded_at >= p.anchor_fold_interval_us:
        anchor = ph.fold_anchor(stance.anchor, declared, ph.common_home(e.at, p, cw), p)
        stance = replace(stance, anchor=anchor, folded_at=e.at)
    return replace(s, stances=s.stances.set(key, stance))


@AFFECT.feels(reads=[body_c.RHYTHM])
def _feel(s: AffectState, appraisals: tuple[A.Appraisal, ...], e, cx) -> AffectState:
    """Ce que les événements des autres lui font ressentir, déclaré par leur
    propriétaire (une attente comblée, un vide, une pensée qui revient). Un
    pas vers l'émotion pleine, proportionné à l'intensité — la résonance du
    tempérament s'applique ; rien ne déborde d'une posture sur l'humeur ici."""
    p = _params(cx.params)
    cw = _clockwork(cx)
    for a in appraisals:
        if not isinstance(a, A.Appraisal):
            continue
        force = max(0.0, min(1.0, a.intensity * (p.relational_scale if a.relational else 1.0)))
        target = A.to_pad(a.emotion, 1.0)
        gain = min(0.9, ph.resonant_gain(target, p) * force)
        if gain <= 0:
            continue
        if a.toward is None:
            mood = ph.advance_mood(s.mood, e.at, p, cw)
            s = replace(s, mood=replace(mood, position=ph.ratchet(mood.position, target, gain)))
            continue
        stance = s.stances.get(a.toward) or ph.new_stance(e.at, p, cw)
        stance = ph.advance_stance(stance, e.at, p, cw)
        osc = replace(stance.osc, position=ph.ratchet(stance.osc.position, A.to_pad(a.emotion, force), gain))
        s = replace(s, stances=s.stances.set(a.toward, replace(stance, osc=osc)))
    return s


# ── Lectures ──────────────────────────────────────────────────────────────


def mood_reading(s: AffectState, now: int, p: AffectParams, cw: ph.Clockwork) -> c.MoodReading:
    osc = ph.advance_mood(s.mood, now, p, cw)
    home = ph.common_home(now, p, cw)
    felt, felt_i = A.felt(osc.position, home)
    label, intensity = A.label(osc.position)
    return c.MoodReading(osc.position, home, felt, felt_i, felt_i, label, intensity)


def stance_reading(s: AffectState, person: str, now: int, p: AffectParams, cw: ph.Clockwork) -> c.StanceReading:
    stored = s.stances.get(person)
    base = ph.common_home(now, p, cw)
    if stored is None:
        return c.StanceReading(person, base, base, A.Emotion.NEUTRAL, 0.0, None, None, True, False)
    st = ph.advance_stance(stored, now, p, cw)
    home = ph.person_home(st.anchor, base, p)
    felt, felt_i = A.felt(st.osc.position, home)
    at_rest = (not st.recent and st.anchor is None) or A.distance(st.osc.position, home) < p.rest_tolerance
    return c.StanceReading(person, st.osc.position, home, felt, felt_i, ph.fresh(st, now, p), st.anchor, at_rest,
                           ph.anchored(st, now, p))


@AFFECT.fact(c.MOOD, reads=[body_c.RHYTHM])
def _mood(s: AffectState, cx) -> c.MoodReading:
    return mood_reading(s, cx.now, _params(cx.params), _clockwork(cx))


@AFFECT.fact(c.STANCE, reads=[body_c.RHYTHM])
def _stance(s: AffectState, cx, person: str) -> c.StanceReading:
    return stance_reading(s, person, cx.now, _params(cx.params), _clockwork(cx))


def regard(s: AffectState, person: str, now: int, p: AffectParams, cw: ph.Clockwork) -> float:
    """Ce que cette personne a installé, signé : la part du chemin parcourue
    du plaisir du repos commun vers le plaisir maximal (ou minimal). Lu dans
    l'absolu, le repos (déjà positif l'après-midi) rendait chacun
    « chaleureux » dès le premier échange."""
    stored = s.stances.get(person)
    if stored is None or stored.anchor is None:
        return 0.0
    anchor = ph.heal(stored.anchor, stored.osc.at, now, p, cw)
    if anchor is None:
        return 0.0
    rest = ph.common_home(now, p, cw)[0]
    delta = anchor[0] - rest
    span = (1.0 - rest) if delta >= 0 else (1.0 + rest)
    return max(-1.0, min(1.0, delta / max(1e-6, span)))


def hostility(s: AffectState, person: str, now: int, p: AffectParams, cw: ph.Clockwork) -> float:
    stored = s.stances.get(person)
    if stored is None or stored.anchor is None:
        return 0.0
    anchor = ph.heal(stored.anchor, stored.osc.at, now, p, cw)
    if anchor is None:
        return 0.0
    rest = ph.common_home(now, p, cw)
    displeasure = max(0.0, rest[0] - anchor[0]) / max(1e-6, 1.0 + rest[0])
    dominance = max(0.0, min(1.0, (anchor[2] - rest[2]) / p.hostility_dominance))
    return max(0.0, min(1.0, displeasure * dominance))


@AFFECT.fact(c.HOSTILITY, reads=[body_c.RHYTHM])
def _hostility(s: AffectState, cx, person: str) -> float:
    return hostility(s, person, cx.now, _params(cx.params), _clockwork(cx))


@AFFECT.fact(c.WARMTH, reads=[body_c.RHYTHM])
def _warmth(s: AffectState, cx, person: str) -> float:
    return max(0.0, regard(s, person, cx.now, _params(cx.params), _clockwork(cx)))


@AFFECT.fact(c.REGARD, reads=[body_c.RHYTHM])
def _regard(s: AffectState, cx, person: str) -> float:
    return regard(s, person, cx.now, _params(cx.params), _clockwork(cx))


@AFFECT.fact(c.FACE, reads=[body_c.RHYTHM])
def _face(s: AffectState, cx, person: str) -> c.Face:
    p = _params(cx.params)
    cw = _clockwork(cx)
    m = mood_reading(s, cx.now, p, cw)
    st = stance_reading(s, person, cx.now, p, cw)
    label, intensity, parts, person_part, mood_part = ph.face(st.position, m.position, p.background)
    return c.Face(label, intensity, tuple(parts), person_part, mood_part)


# ── Prompt ────────────────────────────────────────────────────────────────


@AFFECT.section("mood", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, tags=[Tag.AFFECTIVE], trim_rank=70,
                floor_chars=200, title="TON ÉTAT ÉMOTIONNEL ACTUEL", reads=[c.MOOD])
def _mood_section(s: AffectState, frame: Frame, enrich: Any) -> str:
    p = _params(frame.env.params_of("affect", frame.root))
    return prose.mood(frame.get(c.MOOD), p)


@AFFECT.section("stance", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, tags=[Tag.AFFECTIVE], after=["who"],
                trim_rank=75, title="CE QUE TU RESSENS POUR CETTE PERSONNE", reads=[c.STANCE, identity_c.PERSON])
def _stance_section(s: AffectState, frame: Frame, enrich: Any) -> str | None:
    ep = frame.episode
    if ep is None or not ep.target:
        return None
    p = _params(frame.env.params_of("affect", frame.root))
    reading = frame.get(c.STANCE(frame.get(identity_c.PERSON(ep.target))))
    return prose.stance(reading, frame.get(c.MOOD).home, p) or None


# ── Initiative ────────────────────────────────────────────────────────────


@AFFECT.propose(kinds=[Kind.INITIATIVE], reasons={c.MOOD_OVERFLOW: (0.0, 4.0)}, reads=[c.MOOD])
def _overflow(s: AffectState, frame: Frame) -> list[Candidate]:
    """Une humeur qui déborde pousse à parler — à qui que ce soit de présent."""
    p = _params(frame.env.params_of("affect", frame.root))
    m = frame.get(c.MOOD)
    if m.overflow <= p.overflow_floor:
        return []
    span = max(1e-9, 1.0 - p.overflow_floor)
    evidence = p.overflow_max_evidence * min(1.0, (m.overflow - p.overflow_floor) / span)
    brief = f"Ton humeur déborde un peu ({A.FR[m.felt]}) : tu as envie d'en parler, ou juste de parler."
    return [Candidate(Kind.INITIATIVE, Anyone.ANY, c.MOOD_OVERFLOW, evidence,
                      args=FrozenDict({"brief:affect": brief}))]


# ── Inspection ────────────────────────────────────────────────────────────

from mika.faculties.affect import inspect as _inspect  # noqa: E402,F401 — contributions : ses vues

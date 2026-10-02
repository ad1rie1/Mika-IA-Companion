"""``affect`` : l'humeur générale, la posture envers chacun, ce qu'une relation installe.

Ce qui la fait bouger : la balise ``[EMOTION:nom:intensité]`` qu'elle écrit en
parlant à quelqu'un (répondre, prendre la parole), et ce que les événements
des autres lui font ressentir (évaluations déclarées). Pas de balise, ou
``neutral`` → aucune impulsion : « rien de particulier » ne déplace rien. Ses
pas de travail et ses murmures ne la font pas vibrer. Le sommeil gèle le fond
de sa journée et l'allège au réveil (ADR 0032).
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
from mika.vocab.affect import Declared, Emotion
from mika.vocab.episodes import CONVERSATIONAL, Kind, Tag
from mika.vocab.people import is_identifiable


@dataclass(frozen=True, slots=True)
class AffectState:
    mood: ph.Mood | None = None  # None : au repos depuis toujours
    stances: FrozenDict[str, ph.Stance] = field(default_factory=FrozenDict)


#: v2 : une humeur à trois couches (repos jumeau, émotion du moment, fond), des
#: ancres mesurées depuis le repos moyen, l'attachement (ADR 0032).
AFFECT = Faculty("affect", state=AffectState, init=lambda p: AffectState(), params=AffectParams, derive=derive,
                 state_version=2, retired_params=("declared_window_us",))

#: Ni une amie ni une proche : une hostilité forte y laisse de la méfiance.
_DISTANT = frozenset({social_c.STRANGER, social_c.ACQUAINTANCE})


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
    if declared is None or declared.emotion is Emotion.NEUTRAL:
        return s  # « rien de particulier » ne déplace rien (et ne s'écrit pas en posture)
    p = _params(cx.params)
    cw = _clockwork(cx)
    key = cx.facts.get(identity_c.PERSON(d.target)) if d.target else ""
    level = cx.facts.get(social_c.CLOSENESS(key)) if d.target and is_identifiable(d.target) else ""
    mood = ph.advance_mood(s.mood, e.at, p, cw)
    gain = ph.mood_gain(declared.intensity, p)
    if level:
        # ce qu'un inconnu lui fait vivre la touche moins que ce que vit un proche
        gain = min(p.mood_gain_cap, gain * p.bleed(level))
    if gain > 0:
        mood = ph.push_mood(mood, ph.mood_target(mood, declared.emotion, declared.intensity, p), gain, p,
                            ph.Mark(e.at, declared.emotion.value, "talk", key))
    s = replace(s, mood=mood)
    if not d.target:
        return s  # un monologue : seule l'humeur générale bouge
    stance = s.stances.get(key) or ph.new_stance(e.at, p, cw)
    stance = ph.advance_stance(stance, e.at, p, cw)
    stance = ph.push_stance(stance, ph.stance_target(stance, declared.emotion, declared.intensity),
                            ph.resonant_gain(A.ANCHORS[declared.emotion], p))
    recent = (*stance.recent, (e.at, declared.emotion.value))[-ph.RECENT_IMPULSES:]
    stance = replace(stance, declared=declared.encode(), declared_at=e.at, declared_reply=d.kind == Kind.REPLY,
                     recent=recent)
    if is_identifiable(d.target) and e.at - stance.folded_at >= p.anchor_fold_interval_us:
        ref = ph.reference(p, cw)
        stance = ph.fold(stance, declared, e.at, cx.local(e.at).date().toordinal(), ref, p)
        if level in _DISTANT and ph.hostility_of(stance.anchor, stance.bond, 0, e.at, ref, p) > p.wary_from:
            stance = replace(stance, wary_until=e.at + p.wary_us)
    return replace(s, stances=s.stances.set(key, stance))


@AFFECT.feels(reads=[body_c.RHYTHM])
def _feel(s: AffectState, appraisals: tuple[A.Appraisal, ...], e, cx) -> AffectState:
    """Ce que les événements des autres lui font ressentir, déclaré par leur
    propriétaire (une attente comblée, un vide, une pensée qui revient). Un
    pas vers l'émotion pleine, proportionné à l'intensité — l'échelle ne
    s'applique qu'une fois ; la résonance du tempérament s'applique ; rien ne
    déborde d'une posture sur l'humeur ici."""
    p = _params(cx.params)
    cw = _clockwork(cx)
    for a in appraisals:
        if not isinstance(a, A.Appraisal) or a.emotion is Emotion.NEUTRAL:
            continue
        force = max(0.0, min(1.0, a.intensity * (p.relational_scale if a.relational else 1.0)))
        target = A.ANCHORS[a.emotion]
        gain = min(0.9, ph.resonant_gain(target, p) * force)
        if gain <= 0:
            continue
        if a.toward is None:
            mood = ph.advance_mood(s.mood, e.at, p, cw)
            s = replace(s, mood=ph.push_mood(mood, target, gain, p, ph.Mark(e.at, a.emotion.value, a.reason[:40])))
            continue
        stance = s.stances.get(a.toward) or ph.new_stance(e.at, p, cw)
        stance = ph.push_stance(ph.advance_stance(stance, e.at, p, cw), target, gain)
        s = replace(s, stances=s.stances.set(a.toward, stance))
    return s


@AFFECT.reducer(body_c.FELL_ASLEEP, reads=[body_c.RHYTHM])
def _asleep(s: AffectState, e, cx) -> AffectState:
    """Pendant qu'elle dort, le fond de sa journée ne bouge plus."""
    p = _params(cx.params)
    return replace(s, mood=ph.fall_asleep(ph.advance_mood(s.mood, e.at, p, _clockwork(cx))))


@AFFECT.reducer(body_c.WOKE, reads=[body_c.RHYTHM])
def _woke(s: AffectState, e, cx) -> AffectState:
    """Le sommeil l'allège : au réveil, il en reste une part, qui colore son matin."""
    p = _params(cx.params)
    return replace(s, mood=ph.wake(ph.advance_mood(s.mood, e.at, p, _clockwork(cx)), p))


# ── Lectures ──────────────────────────────────────────────────────────────


def _cause(m: ph.Mood, toward: A.Vec3, now: int, p: AffectParams) -> tuple[str, str]:
    """La plus récente impulsion qui pousse dans le sens de ce qu'elle ressent."""
    for mark in reversed(m.marks):
        emotion = A.emotion_of(mark.emotion)
        if emotion is None or not mark.cause or now - mark.at > 2 * p.fond_tau_us:
            continue
        if A.dot(A.sub(A.ANCHORS[emotion], m.rest.position), toward) > 0:
            return mark.cause, mark.person
    return "", ""


def _lingering(m: ph.Mood, fond: A.Vec3, now: int, p: AffectParams, cw: ph.Clockwork) -> Emotion:
    """Ce que garde le fond : parmi ses émotions récentes, celle qui l'explique le
    mieux, lue contre son repos moyen. Contre le repos de l'heure, une colère de
    l'après-midi se lisait « pensive » le soir."""
    if A.norm(fond) < 1e-6:
        return Emotion.NEUTRAL
    ref = ph.reference(p, cw)
    best, score = Emotion.NEUTRAL, 0.0
    for mark in m.marks:
        emotion = A.emotion_of(mark.emotion)
        if emotion is None or now - mark.at > 2 * p.fond_tau_us:
            continue
        ray = A.sub(A.ANCHORS[emotion], ref)
        cos = A.dot(fond, ray) / max(1e-9, A.norm(fond) * A.norm(ray))
        if cos > score:
            best, score = emotion, cos
    return best if best is not Emotion.NEUTRAL else A.felt(A.add(ref, fond), ref)[0]


def mood_reading(s: AffectState, now: int, p: AffectParams, cw: ph.Clockwork) -> c.MoodReading:
    m = ph.advance_mood(s.mood, now, p, cw)
    rest = m.rest.position
    fond = ph.fond_of(m, p)
    moment = A.add(rest, m.gap)
    position = A.add(moment, fond)
    felt, felt_i = A.felt(position, rest)
    label, intensity = A.label(position)
    cause, who = _cause(m, A.sub(position, rest), now, p)
    return c.MoodReading(position, rest, felt, felt_i, A.felt(moment, rest)[1], label, intensity, fond, cause, who,
                         _lingering(m, fond, now, p, cw))


def stance_reading(s: AffectState, person: str, now: int, p: AffectParams, cw: ph.Clockwork) -> c.StanceReading:
    stored = s.stances.get(person)
    ref = ph.reference(p, cw)
    if stored is None:
        base = ph.common_home(now, p, cw)
        return c.StanceReading(person, base, base, Emotion.NEUTRAL, 0.0, None, None, True, False, ref)
    st = ph.advance_stance(stored, now, p, cw)
    rest, position = st.rest.position, st.position
    felt, felt_i = A.felt(position, rest)
    quiet = A.distance(position, rest) < p.rest_tolerance
    declared = ph.fresh(st, now, p)
    if declared is not None and not quiet and declared.intensity < felt_i:
        declared = None  # la position en dit plus que ce qui reste de la balise
    anchor = A.add(ref, st.anchor) if st.anchor is not None else None
    anchored = ph.anchored(st, now, p)
    lasting = anchored and st.anchor is not None and A.dot(st.anchor, st.gap) > 0 and \
        A.felt(A.add(ref, st.anchor), ref)[1] >= p.fond_min
    return c.StanceReading(
        person, position, rest, felt, felt_i, declared, anchor, quiet, anchored, ref,
        ph.regard_of(st.anchor, st.bond, ref, p), ph.hostility_of(st.anchor, st.bond, st.wary_until, now, ref, p),
        st.bond, st.declared_at, st.declared_reply, lasting)


@AFFECT.fact(c.MOOD, reads=[body_c.RHYTHM])
def _mood(s: AffectState, cx) -> c.MoodReading:
    return mood_reading(s, cx.now, _params(cx.params), _clockwork(cx))


@AFFECT.fact(c.STANCE, reads=[body_c.RHYTHM])
def _stance(s: AffectState, cx, person: str) -> c.StanceReading:
    return stance_reading(s, person, cx.now, _params(cx.params), _clockwork(cx))


def regard(s: AffectState, person: str, now: int, p: AffectParams, cw: ph.Clockwork) -> float:
    """Ce que cette personne a installé, signé (voir ``contracts.affect.REGARD``) :
    mesuré depuis son repos moyen, jamais depuis l'heure qu'il est."""
    stored = s.stances.get(person)
    if stored is None:
        return 0.0
    anchor, attachment = ph.relation_at(stored, now, p)
    return ph.regard_of(anchor, attachment, ph.reference(p, cw), p)


def hostility(s: AffectState, person: str, now: int, p: AffectParams, cw: ph.Clockwork) -> float:
    stored = s.stances.get(person)
    if stored is None:
        return 0.0
    anchor, attachment = ph.relation_at(stored, now, p)
    return ph.hostility_of(anchor, attachment, stored.wary_until, now, ph.reference(p, cw), p)


def bond(s: AffectState, person: str, now: int, p: AffectParams) -> float:
    stored = s.stances.get(person)
    return 0.0 if stored is None else ph.relation_at(stored, now, p)[1]


@AFFECT.fact(c.HOSTILITY, reads=[body_c.RHYTHM])
def _hostility(s: AffectState, cx, person: str) -> float:
    return hostility(s, person, cx.now, _params(cx.params), _clockwork(cx))


@AFFECT.fact(c.WARMTH, reads=[body_c.RHYTHM])
def _warmth(s: AffectState, cx, person: str) -> float:
    return max(0.0, regard(s, person, cx.now, _params(cx.params), _clockwork(cx)))


@AFFECT.fact(c.REGARD, reads=[body_c.RHYTHM])
def _regard(s: AffectState, cx, person: str) -> float:
    return regard(s, person, cx.now, _params(cx.params), _clockwork(cx))


@AFFECT.fact(c.BOND)
def _bond(s: AffectState, cx, person: str) -> float:
    return bond(s, person, cx.now, _params(cx.params))


def face_reading(s: AffectState, person: str, now: int, p: AffectParams, cw: ph.Clockwork) -> c.Face:
    m = mood_reading(s, now, p, cw)
    stored = s.stances.get(person)
    if stored is None:
        position, declared = ph.common_home(now, p, cw), None
    else:
        st = ph.advance_stance(stored, now, p, cw)
        position, declared = st.position, ph.fresh(st, now, p)
    label, intensity, parts, person_part, mood_part = ph.face(position, m.position, p.background, declared)
    return c.Face(label, intensity, tuple(parts), person_part, mood_part)


@AFFECT.fact(c.FACE, reads=[body_c.RHYTHM])
def _face(s: AffectState, cx, person: str) -> c.Face:
    return face_reading(s, person, cx.now, _params(cx.params), _clockwork(cx))


# ── Prompt ────────────────────────────────────────────────────────────────


def _target_person(frame: Frame) -> str:
    ep = frame.episode
    return frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else ""


# son humeur la suit aussi quand elle travaille, dans son mode à elle : un but (STEP), un projet (WORK, ADR 0031)
@AFFECT.section("mood", zone=Zone.VOLATILE, episodes=[*CONVERSATIONAL, Kind.WORK, Kind.STEP], tags=[Tag.AFFECTIVE],
                trim_rank=70, floor_chars=200, title="TON ÉTAT ÉMOTIONNEL ACTUEL", reads=[c.MOOD, identity_c.PERSON])
def _mood_section(s: AffectState, frame: Frame, enrich: Any) -> str:
    p = _params(frame.env.params_of("affect", frame.root))
    return prose.mood(frame.get(c.MOOD), p, current=_target_person(frame))


@AFFECT.section("stance", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, tags=[Tag.AFFECTIVE], after=["who"],
                trim_rank=75, title="CE QUE TU RESSENS POUR CETTE PERSONNE",
                reads=[c.STANCE, identity_c.PERSON, identity_c.IDENTITY])
def _stance_section(s: AffectState, frame: Frame, enrich: Any) -> str | None:
    person = _target_person(frame)
    if not person:
        return None
    p = _params(frame.env.params_of("affect", frame.root))
    name = frame.get(identity_c.IDENTITY(person)).name
    return prose.stance(frame.get(c.STANCE(person)), p, name=name, now=frame.now) or None


# ── Initiative ────────────────────────────────────────────────────────────


@AFFECT.propose(kinds=[Kind.INITIATIVE], reasons={c.MOOD_OVERFLOW: (0.0, 4.0)}, reads=[c.MOOD])
def _overflow(s: AffectState, frame: Frame) -> list[Candidate]:
    """Une émotion du moment qui déborde pousse à parler — à qui que ce soit de
    présent. Le fond d'une journée, lui, colore ; il ne pousse pas."""
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

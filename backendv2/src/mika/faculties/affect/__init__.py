"""``affect`` : l'humeur générale, la posture envers chacun, ce qu'une relation installe.

Ce qui la fait bouger : la balise ``[EMOTION:nom:intensité]`` qu'elle écrit en
parlant à quelqu'un (répondre, prendre la parole), et ce que les événements
des autres lui font ressentir (évaluations déclarées). Pas de balise, ou
``neutral`` → aucune impulsion : « rien de particulier » ne déplace rien. Ses
pas de travail et ses murmures ne la font pas vibrer. Le sommeil gèle le fond
de sa journée et l'allège au réveil (ADR 0032).

Des excuses sincères (``self.touched``, une fois par jour et par personne)
ôtent une part de ce que la relation a installé d'hostile — davantage venant
d'une amie que d'une inconnue, dont la méfiance plancher reste (ADR 0047).

Son tempérament (ADR 0100) agit sur ce qu'elle déclare : blessée (le modèle a lu des mots qui la blessent, ou une
déception — un oubli, de la froideur, un rejet, ADR 0107), sa réaction pèse (la colère, la tristesse, la peur) ou
elle se referme ; touchée (un compliment, un merci), son visage se défend ; sa jalousie pèse ce qu'elle pèse ; son
masque règle ce que son visage montre selon l'intimité.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from mika.contracts import affect as c
from mika.contracts import agency as agency_c
from mika.contracts import body as body_c
from mika.contracts import expression as expression_c
from mika.contracts import identity as identity_c
from mika.contracts import needs as needs_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.faculties.affect import physics as ph
from mika.faculties.affect import prose
from mika.faculties.affect.params import AffectParams, derive
from mika.kernel.arbitration import Anyone, Candidate, Modulation, RowView
from mika.kernel.faculty import Faculty, Zone
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.vocab import affect as A
from mika.vocab import causes, reading
from mika.vocab.affect import Declared, Emotion
from mika.vocab.episodes import CONVERSATIONAL, Kind, Tag
from mika.vocab.people import is_identifiable
from mika.vocab.phrasebook import phrase


@dataclass(frozen=True, slots=True)
class AffectState:
    mood: ph.Mood | None = None  # None : au repos depuis toujours
    stances: FrozenDict[str, ph.Stance] = field(default_factory=FrozenDict)


#: v2 : une humeur à trois couches (repos jumeau, émotion du moment, fond), des
#: ancres mesurées depuis le repos moyen, l'attachement (ADR 0032). v3 : des excuses pardonnent (ADR 0047).
AFFECT = Faculty("affect", state=AffectState, init=lambda p: AffectState(), params=AffectParams, derive=derive,
                 # 4 : ses réducteurs lisent la proximité, dont la règle a changé (ADR 0058) — instantané et genèse
                 # ne donnaient plus la même tranche sur une installation existante (audit du lot L2)
                 # 5 : ses balises ont des facettes, qui visent ensemble (ADR 0093) ; ce qu'une personne lui fait
                 # vivre touche sa posture envers elle ; des excuses pardonnent sous chacune de ses adresses (ADR 0094)
                 # 6 : la matrice de personnalité — tout ce que les autres lui font vivre suit la contagion, le biais
                 # négatif pèse sur chaque impulsion (ADR 0100)
                 # 7 : blessée, sa réaction pèse et la relation se refroidit (jamais de tendresse) ; refermée, touchée :
                 # sa posture le retient (ADR 0100)
                 # 8 : un message qui la tire du sommeil la réveille aussi ici (une nuit coupée allège en deux fois),
                 # ses nuits datées de l'instant du croisement (ADR 0102)
                 # 9 : sa propriétaire la touche davantage (``social.WEIGHT``, ADR 0107)
                 # 10 : blessée ou touchée en répondant seulement — une initiative ne lit aucun geste (ADR 0093)
                 state_version=10, retired_params=("declared_window_us",))
#: ni une connaissance ni une inconnue : sa tendresse s'y cache (le masque, au-dessus du milieu)
_TENDER_TO = frozenset({social_c.FRIEND, social_c.CLOSE})

#: Ni une amie ni une proche : une hostilité forte y laisse de la méfiance.
_DISTANT = frozenset({social_c.STRANGER, social_c.ACQUAINTANCE})


def _params(p: AffectParams | None) -> AffectParams:
    return p if p is not None else AFFECT.default_params()  # type: ignore[return-value]


def _clockwork(cx: Any) -> ph.Clockwork:
    return ph.Clockwork(cx.tz, cx.facts.get(body_c.RHYTHM))


@AFFECT.reducer(rt.UTTERANCE, reads=[identity_c.PERSON, body_c.RHYTHM, social_c.CLOSENESS, social_c.WEIGHT])
def _declared(s: AffectState, e, cx) -> AffectState:
    d = e.data
    if d.visible:
        s = _awake_now(s, e.at, cx)  # parler en dormant la réveille (son corps aussi : ``body._uttered``)
    if d.kind not in CONVERSATIONAL:
        return s
    declared = Declared.decode(d.annotation(expression_c.EMOTION_ANNOTATION))
    if declared is None or declared.emotion is Emotion.NEUTRAL:
        return s  # « rien de particulier » ne déplace rien (et ne s'écrit pas en posture)
    p = _params(cx.params)
    cw = _clockwork(cx)
    key = cx.facts.get(identity_c.PERSON(d.target)) if d.target else ""
    # quelqu'un qu'elle ne peut pas reconnaître (une adresse jetable) la touche comme une inconnue, jamais davantage
    level = (cx.facts.get(social_c.CLOSENESS(key)) if is_identifiable(d.target) else social_c.STRANGER) \
        if d.target else ""
    # ce que la personne compte au-delà de leur lien (``social.WEIGHT``) : sa propriétaire la touche davantage, son
    # humeur comme sa posture envers elle (ADR 0107)
    counts = cx.facts.get(social_c.WEIGHT(key)) if d.target and is_identifiable(d.target) else 1.0
    # ce que le modèle a lu de la personne (ADR 0093) : des mots qui la blessent ou une déception (ADR 0107), un
    # compliment, un merci — lu en répondant à un message seulement, comme ``others`` et ``self`` : une initiative
    # ne lit aucun nouveau geste, et une blessure déjà comptée ne se recompte pas
    their = reading.Reading.decode(d.annotation(expression_c.READING_ANNOTATION)) \
        if d.kind == Kind.REPLY and d.reply_to is not None else None
    hurt = their is not None and their.gesture in reading.HURTING
    touched = their is not None and their.gesture in (reading.COMPLIMENTED, reading.THANKED)
    # son tempérament sur ce qu'elle déclare (ADR 0100) : sa jalousie pèse ; blessée, sa réaction aussi
    declared = ph.weighed(declared, {Emotion.JEALOUS: p.jealous_weight})
    if hurt:
        declared = ph.reacting(declared, p.reaction, p.reaction_weight, p.reaction_share)
    mood = ph.advance_mood(s.mood, e.at, p, cw)
    # le biais négatif (ADR 0100) : le mauvais et le bon ne pèsent pas pareil (au milieu, 1)
    weight = p.valence_gain(declared.emotion)
    gain = min(p.mood_gain_cap, ph.mood_gain(declared.intensity, p) * weight)
    if level:
        # ce qu'un inconnu lui fait vivre la touche moins que ce que vit un proche
        gain = min(p.mood_gain_cap, gain * p.bleed(level) * counts)
    if gain > 0:
        # toutes ses facettes (« triste 0,6, anxieuse 0,3 »), pas seulement la plus forte (ADR 0093)
        mood = ph.push_mood(mood, ph.mood_target_of(mood, declared, p), gain, p,
                            ph.Mark(e.at, declared.emotion.value, "talk", key))
    s = replace(s, mood=mood)
    if not d.target:
        return s  # un monologue : seule l'humeur générale bouge
    stance = s.stances.get(key) or ph.new_stance(e.at, p, cw)
    stance = ph.advance_stance(stance, e.at, p, cw)
    stance = ph.push_stance(stance, ph.stance_target_of(stance, declared),
                            ph.resonant_gain(ph.blend(A.ORIGIN, declared.all), p) * weight * counts)
    recent = (*stance.recent, (e.at, declared.emotion.value))[-ph.RECENT_IMPULSES:]
    stance = replace(stance, declared=declared.encode(), declared_at=e.at, declared_reply=d.kind == Kind.REPLY,
                     recent=recent)
    if hurt and p.reaction == ph.WITHDRAWAL:
        stance = replace(stance, withdrawn_until=max(stance.withdrawn_until, e.at + p.withdraw_us))
    if touched and p.defense and ph.tender(declared, p.touched_from):
        stance = replace(stance, defended_at=e.at)  # prise en flagrant délit de tendresse : son visage se défend
    if is_identifiable(d.target) and e.at - stance.folded_at >= p.anchor_fold_interval_us:
        ref = ph.reference(p, cw)
        stance = ph.fold(stance, declared, e.at, cx.local(e.at).date().toordinal(), ref, p, hurt=hurt)
        if level in _DISTANT and ph.hostility_of(stance.anchor, stance.bond, 0, e.at, ref, p) > p.wary_from:
            stance = replace(stance, wary_until=e.at + p.wary_us)
    if hurt and p.reaction == ph.FEAR and is_identifiable(d.target):
        # la peur : elle se méfie de qui l'a blessée (moins longtemps d'une amie que d'une inconnue)
        lasting = p.wary_us if level in _DISTANT else round(p.wary_us * p.fear_wary_close)
        stance = replace(stance, wary_until=max(stance.wary_until, e.at + lasting))
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
        gain = min(0.9, ph.resonant_gain(target, p) * force * p.valence_gain(a.emotion))
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


#: ni une amie ni une proche : ses excuses comptent moins (``apology_distant``)
_FORGIVEN_FULLY = frozenset({social_c.FRIEND, social_c.CLOSE})


@AFFECT.reducer(self_c.TOUCHED, reads=[body_c.RHYTHM, social_c.CLOSENESS, identity_c.HANDLES])
def _apologized(s: AffectState, e, cx) -> AffectState:
    """Des excuses (lues par ``self`` dans la forme, une fois par jour et par
    personne, quand il y avait de quoi pardonner) : ce que la relation avait
    installé d'hostile en perd une part — moins venant de quelqu'un de peu
    proche, dont la méfiance plancher reste. Un troll qui écrit « pardon mdr »
    dix fois n'obtient rien (``self`` ne l'a pas lu comme des excuses)."""
    d = e.data
    if d.kind != self_c.APOLOGIZED or not d.person:
        return s
    p = _params(cx.params)
    share = p.apology_heal * (1.0 if cx.facts.get(social_c.CLOSENESS(d.person)) in _FORGIVEN_FULLY
                              else p.apology_distant)
    # ce qu'elle lui gardait sous chacune de ses adresses (reliées depuis à elle)
    for key in sorted({d.person, *_handles(cx, d.person)}):
        stored = s.stances.get(key)
        if stored is not None:
            stance = ph.forgive(ph.advance_stance(stored, e.at, p, _clockwork(cx)), share, e.at)
            s = replace(s, stances=s.stances.set(key, stance))
    return s


@AFFECT.reducer(body_c.FELL_ASLEEP, reads=[body_c.RHYTHM])
def _asleep(s: AffectState, e, cx) -> AffectState:
    """Pendant qu'elle dort, le fond de sa journée ne bouge plus — depuis l'instant où elle s'est endormie (un
    rattrapage après un arrêt le date au passé)."""
    p = _params(cx.params)
    cw = _clockwork(cx)
    return replace(s, mood=ph.fall_asleep(ph.advance_mood(s.mood, e.data.at, p, cw), e.data.at, cw))


@AFFECT.reducer(body_c.WOKE, reads=[body_c.RHYTHM])
def _woke(s: AffectState, e, cx) -> AffectState:
    """Le sommeil l'allège : au réveil, il en reste une part, qui colore son matin."""
    p = _params(cx.params)
    cw = _clockwork(cx)
    return replace(s, mood=ph.woke(ph.advance_mood(s.mood, e.data.at, p, cw), e.data.at, p, cw))


@AFFECT.reducer(body_c.ROUSED, reads=[body_c.RHYTHM])
def _roused(s: AffectState, e, cx) -> AffectState:
    """Un message la tire du sommeil : elle est éveillée. Son corps ne dira pas toujours « réveillée » ensuite (une
    conversation qui dépasse l'heure de son lever ne la rendort pas) — son humeur ne reste pas figée pour autant."""
    return _awake_now(s, e.at, cx)


def _awake_now(s: AffectState, at: int, cx: Any) -> AffectState:
    if s.mood is None or not s.mood.asleep:
        return s
    p = _params(cx.params)
    cw = _clockwork(cx)
    return replace(s, mood=ph.roused(ph.advance_mood(s.mood, at, p, cw), at, p, cw))


# ── Lectures ──────────────────────────────────────────────────────────────


#: en deçà, ce qu'elle ressent n'a pas de sens (agréable ou non) qui départage les causes
_VALENCE_SAID = 0.02


def _cause(m: ph.Mood, toward: A.Vec3, now: int, p: AffectParams) -> tuple[str, str, int]:
    """La plus récente impulsion qui pousse dans le sens de ce qu'elle ressent (cause, personne, quand) — et du
    même côté : un soulagement n'explique pas qu'il lui reste de la mélancolie."""
    for mark in reversed(m.marks):
        emotion = A.emotion_of(mark.emotion)
        if emotion is None or not mark.cause or now - mark.at > 2 * p.fond_tau_us:
            continue
        ray = A.sub(A.ANCHORS[emotion], m.rest.position)
        if abs(toward[0]) > _VALENCE_SAID and A.ANCHORS[emotion][0] * toward[0] < 0:
            continue
        if A.dot(ray, toward) > 0:
            return mark.cause, mark.person, mark.at
    return "", "", 0


#: les causes qui sont des états, et ce qui y met fin : « personne ne t'a parlé » cesse d'être vrai dès qu'on lui
#: parle ; « il ne se passe pas grand-chose », dès que quelque chose se passe (HUM-5)
ENDED_BY_SOMEONE, ENDED_BY_ANYTHING = frozenset({"lonely"}), frozenset({"bored"})


def over(cause: str, at: int, needs: Any) -> bool:
    """La cause d'une humeur est-elle un état qui a pris fin depuis ?"""
    if needs is None or not at:
        return False
    if cause in ENDED_BY_SOMEONE:
        return needs.heard_at > at
    if cause in ENDED_BY_ANYTHING:
        return needs.idle_since > at
    return False


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


def mood_reading(s: AffectState, now: int, p: AffectParams, cw: ph.Clockwork, needs: Any = None) -> c.MoodReading:
    m = ph.advance_mood(s.mood, now, p, cw)
    rest = m.rest.position
    fond = ph.fond_of(m, p)
    moment = A.add(rest, m.gap)
    position = A.add(moment, fond)
    felt, felt_i = A.felt(position, rest)
    label, intensity = A.label(position)
    cause, who, at = _cause(m, A.sub(position, rest), now, p)
    return c.MoodReading(position, rest, felt, felt_i, A.felt(moment, rest)[1], label, intensity, fond, cause, who,
                         _lingering(m, fond, now, p, cw), over(cause, at, needs))


def stored_stances(s: AffectState, person: str, handles: tuple[str, ...] = ()) -> list[ph.Stance]:
    """Ses postures envers une personne, sous chacune de ses adresses (``identity.HANDLES``) : une adresse reliée
    depuis à elle garde ce qu'elle avait vécu avec elle (comme ``others.model_of``)."""
    return [s.stances[k] for k in sorted({person, *handles}) if k in s.stances]


def _now_toward(s: AffectState, person: str, handles: tuple[str, ...], now: int, p: AffectParams,
                cw: ph.Clockwork) -> ph.Stance | None:
    parts = stored_stances(s, person, handles)
    return ph.joined([ph.advance_stance(st, now, p, cw) for st in parts]) if parts else None


def stance_reading(s: AffectState, person: str, now: int, p: AffectParams, cw: ph.Clockwork,
                   handles: tuple[str, ...] = ()) -> c.StanceReading:
    ref = ph.reference(p, cw)
    st = _now_toward(s, person, handles, now, p, cw)
    if st is None:
        base = ph.common_home(now, p, cw)
        return c.StanceReading(person, base, base, Emotion.NEUTRAL, 0.0, None, None, True, False, ref)
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
        st.bond, st.declared_at, st.declared_reply, lasting, st.apologized_at, withdrawn_until=st.withdrawn_until)


@AFFECT.fact(c.MOOD, reads=[body_c.RHYTHM, needs_c.NEEDS])
def _mood(s: AffectState, cx) -> c.MoodReading:
    return mood_reading(s, cx.now, _params(cx.params), _clockwork(cx), cx.facts.get(needs_c.NEEDS))


def _handles(cx: Any, person: str) -> tuple[str, ...]:
    return tuple(cx.facts.get(identity_c.HANDLES(person)) or ())


@AFFECT.fact(c.STANCE, reads=[body_c.RHYTHM, identity_c.HANDLES])
def _stance(s: AffectState, cx, person: str) -> c.StanceReading:
    return stance_reading(s, person, cx.now, _params(cx.params), _clockwork(cx), _handles(cx, person))


def regard(s: AffectState, person: str, now: int, p: AffectParams, cw: ph.Clockwork,
           handles: tuple[str, ...] = ()) -> float:
    """Ce que cette personne a installé, signé (voir ``contracts.affect.REGARD``) :
    mesuré depuis son repos moyen, jamais depuis l'heure qu'il est — toutes ses adresses réunies."""
    parts = stored_stances(s, person, handles)
    if not parts:
        return 0.0
    anchor, attachment, _wary = ph.relation_joined(parts, now, p)
    return ph.regard_of(anchor, attachment, ph.reference(p, cw), p)


def hostility(s: AffectState, person: str, now: int, p: AffectParams, cw: ph.Clockwork,
              handles: tuple[str, ...] = ()) -> float:
    parts = stored_stances(s, person, handles)
    if not parts:
        return 0.0
    anchor, attachment, wary = ph.relation_joined(parts, now, p)
    return ph.hostility_of(anchor, attachment, wary, now, ph.reference(p, cw), p)


def bond(s: AffectState, person: str, now: int, p: AffectParams, handles: tuple[str, ...] = ()) -> float:
    parts = stored_stances(s, person, handles)
    return ph.relation_joined(parts, now, p)[1] if parts else 0.0


@AFFECT.fact(c.HOSTILITY, reads=[body_c.RHYTHM, identity_c.HANDLES])
def _hostility(s: AffectState, cx, person: str) -> float:
    return hostility(s, person, cx.now, _params(cx.params), _clockwork(cx), _handles(cx, person))


@AFFECT.fact(c.WARMTH, reads=[body_c.RHYTHM, identity_c.HANDLES])
def _warmth(s: AffectState, cx, person: str) -> float:
    return max(0.0, regard(s, person, cx.now, _params(cx.params), _clockwork(cx), _handles(cx, person)))


@AFFECT.fact(c.REGARD, reads=[body_c.RHYTHM, identity_c.HANDLES])
def _regard(s: AffectState, cx, person: str) -> float:
    return regard(s, person, cx.now, _params(cx.params), _clockwork(cx), _handles(cx, person))


@AFFECT.fact(c.BOND, reads=[identity_c.HANDLES])
def _bond(s: AffectState, cx, person: str) -> float:
    return bond(s, person, cx.now, _params(cx.params), _handles(cx, person))


def shown_factor(p: AffectParams, closeness: str, withdrawn: bool, defended: bool = False) -> Any:
    """Ce que son visage montre de chaque émotion, devant cette personne (ADR 0100) : son expressivité ; son masque
    (une inconnue en voit moins quand elle s'ouvre à mesure qu'elle connaît, une proche voit moins sa tendresse quand
    elle pique d'autant plus qu'elle aime — une connaissance, une amie : à mi-chemin) ; refermée, presque rien. Au
    milieu de tout : 1 partout. Son visage qui se défend (``defended``) montre déjà ce qu'il laisse passer de sa
    tendresse — la rougeur de celle qui pique : le masque ne la cache pas une seconde fois."""
    base = p.face_expressiveness * (p.withdrawn_shown if withdrawn else 1.0)
    if closeness == social_c.STRANGER:
        base *= p.stranger_shown
    elif closeness == social_c.ACQUAINTANCE:
        base *= 1.0 - (1.0 - p.stranger_shown) / 2
    tender = 1.0
    if closeness == social_c.CLOSE and not defended:
        tender = p.tender_shown
    elif closeness == social_c.FRIEND and not defended:
        tender = 1.0 - (1.0 - p.tender_shown) / 2

    def factor(emotion: Emotion) -> float:
        return base * (tender if emotion in ph.TENDER else 1.0)

    return factor


def face_reading(s: AffectState, person: str, now: int, p: AffectParams, cw: ph.Clockwork,
                 handles: tuple[str, ...] = (), closeness: str = "") -> c.Face:
    m = mood_reading(s, now, p, cw)  # le visage ne dit pas de cause
    st = _now_toward(s, person, handles, now, p, cw)
    if st is None:
        position, declared = ph.common_home(now, p, cw), None
    else:
        position, declared = st.position, ph.fresh(st, now, p)
    label, intensity, parts, person_part, mood_part = ph.face(position, m.position, p.background, declared)
    defended: list[tuple[Emotion, float]] = []
    if st is not None and declared is not None and p.defense and st.defended_at and st.defended_at == st.declared_at:
        # prise en flagrant délit de tendresse : son visage se défend (ce qu'elle ressent ne change pas)
        defended = ph.defended(declared, p.defense)
        if defended:
            (label, intensity), parts, person_part = defended[0], defended, defended[0]
    withdrawn = st is not None and st.withdrawn_until > now
    factor = shown_factor(p, closeness, withdrawn, defended=bool(defended))
    if any(factor(e) != 1.0 for e in (label, person_part[0], mood_part[0], *(e for e, _w in parts))):
        # jamais au-delà du plein
        def shown(e: Emotion, x: float) -> float:
            return round(min(1.0, x * factor(e)), 2)

        intensity, parts = shown(label, intensity), [(e, shown(e, w)) for e, w in parts]
        person_part = (person_part[0], shown(*person_part))
        mood_part = (mood_part[0], shown(*mood_part))
    return c.Face(label, intensity, tuple(parts), person_part, mood_part)


@AFFECT.fact(c.FACE, reads=[body_c.RHYTHM, identity_c.HANDLES, social_c.CLOSENESS])
def _face(s: AffectState, cx, person: str) -> c.Face:
    closeness = cx.facts.get(social_c.CLOSENESS(person)) if is_identifiable(person) else social_c.STRANGER
    return face_reading(s, person, cx.now, _params(cx.params), _clockwork(cx), _handles(cx, person), closeness)


# ── Prompt ────────────────────────────────────────────────────────────────


def _target_person(frame: Frame) -> str:
    ep = frame.episode
    return frame.get(identity_c.PERSON(ep.target)) if ep is not None and ep.target else ""


# son humeur la suit aussi quand elle travaille, dans son mode à elle : un but (STEP), un projet (WORK, ADR 0031),
# un réveil par API (WAKE, ADR 0068)
@AFFECT.section("mood", zone=Zone.VOLATILE, episodes=[*CONVERSATIONAL, Kind.WORK, Kind.STEP, Kind.WAKE],
                tags=[Tag.AFFECTIVE],
                trim_rank=70, floor_chars=200, title=phrase("affect.mood_line.title"),
                reads=[c.MOOD, identity_c.PERSON])
def _mood_section(s: AffectState, frame: Frame, enrich: Any) -> str:
    p = _params(frame.env.params_of("affect", frame.root))
    return prose.mood(frame.get(c.MOOD), p, current=_target_person(frame))


@AFFECT.section("stance", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, tags=[Tag.AFFECTIVE], after=["who"],
                trim_rank=75, title=phrase("affect.stance.title"),
                reads=[c.STANCE, identity_c.PERSON, identity_c.IDENTITY])
def _stance_section(s: AffectState, frame: Frame, enrich: Any) -> str | None:
    person = _target_person(frame)
    if not person:
        return None
    p = _params(frame.env.params_of("affect", frame.root))
    name = frame.get(identity_c.IDENTITY(person)).name
    return prose.stance(frame.get(c.STANCE(person)), p, name=name, now=frame.now) or None


# ── Initiative ────────────────────────────────────────────────────────────


def overflow_evidence(m: c.MoodReading, p: AffectParams) -> float:
    """Ce que pousse à parler une émotion du moment qui déborde (0 : elle ne déborde pas)."""
    if m.overflow <= p.overflow_floor:
        return 0.0
    span = max(1e-9, 1.0 - p.overflow_floor)
    return p.overflow_max_evidence * min(1.0, (m.overflow - p.overflow_floor) / span)


@AFFECT.propose(kinds=[Kind.INITIATIVE], reasons={c.MOOD_OVERFLOW: (0.0, 4.0)}, reads=[c.MOOD])
def _overflow(s: AffectState, frame: Frame) -> list[Candidate]:
    """Une émotion du moment qui déborde pousse à parler — à qui que ce soit de
    présent. Le fond d'une journée, lui, colore ; il ne pousse pas."""
    p = _params(frame.env.params_of("affect", frame.root))
    m = frame.get(c.MOOD)
    evidence = overflow_evidence(m, p)
    if evidence <= 0:
        return []
    brief = phrase("affect.overflow.brief", feeling=A.FR[m.felt])
    return [Candidate(Kind.INITIATIVE, Anyone.ANY, c.MOOD_OVERFLOW, evidence,
                      args=FrozenDict({"brief:affect": brief}))]


@AFFECT.modulate(kinds=[Kind.INITIATIVE], reads=[c.MOOD, identity_c.PERSON])
def _not_to_whom_upset_her(s: AffectState, frame: Frame, row: RowView) -> Modulation:
    """Ce qu'un échange avec quelqu'un lui a laissé de sombre (colère, peine) déborde vers qui est là — pas vers
    cette personne-là : son humeur ne la pousse pas à lui réécrire (la posture envers elle dit déjà ce qu'elle en
    ressent ; une autre raison de lui écrire, une inquiétude, un rappel, garde son poids). Une joie qu'elle lui doit,
    elle, peut aller vers elle."""
    if c.MOOD_OVERFLOW not in row.reasons or row.target in (Anyone.ANY, Anyone.NONE):
        return Modulation()
    m = frame.get(c.MOOD)
    if m.cause != causes.TALK or not m.cause_person or A.valence(m.felt) >= 0:
        return Modulation()
    if (frame.get(identity_c.PERSON(row.target)) or row.target) != m.cause_person:
        return Modulation()
    cut = overflow_evidence(m, _params(frame.env.params_of("affect", frame.root)))
    return Modulation(shift=-cut) if cut > 0 else Modulation()


@AFFECT.modulate(kinds=[Kind.INITIATIVE], reads=[c.STANCE, identity_c.PERSON])
def _withdrawn(s: AffectState, frame: Frame, row: RowView) -> Modulation:
    """Blessée par quelqu'un, et se refermer est sa réaction (ADR 0100) : un moment, elle ne lui écrit plus d'elle-même
    — ce qui prévient (un rappel promis, une nouvelle à donner) passe quand même."""
    if row.target in (Anyone.ANY, Anyone.NONE) or (agency_c.INFORMS | agency_c.OWED) & set(row.reasons):
        return Modulation()
    person = frame.get(identity_c.PERSON(row.target)) or row.target
    if frame.get(c.STANCE(person)).withdrawn_until <= frame.now:
        return Modulation()
    return Modulation(shift=-_params(frame.env.params_of("affect", frame.root)).withdrawn_shift)


# ── Inspection ────────────────────────────────────────────────────────────

from mika.faculties.affect import inspect as _inspect  # noqa: E402,F401 — contributions : ses vues

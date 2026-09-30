"""La faculté ``others`` : ce qu'elle devine des autres.

- **Le ton habituel** d'une personne se construit message après message (une
  moyenne lente, qui part d'une neutralité supposée : trois premiers messages
  ne font pas un caractère) ; **l'état du moment** suit ses derniers messages
  et s'efface vers l'habituel quand elle se tait (demi-vie).
- **La surprise** est l'écart entre le ton attendu (l'état du moment juste
  avant le message) et le ton lu, pondéré par ce qu'elle la connaît : on ne
  s'étonne pas d'une inconnue — la connaître demande des messages *et* un
  lien (une connaissance au moins : dix minutes d'insultes n'en font pas une). Nettement plus sombre que d'habitude, chez une
  amie ou une proche : elle s'inquiète (et l'attention en garde une pensée).
- **Ses délais de réponse** se mesurent entre une initiative (pas une
  salutation, pas un rappel) et le message suivant de la personne, par classe
  de canal ; l'attention s'en sert pour ne pas se croire ignorée trop tôt.
- **Les heures où elle répond** : les attentes comblées ou déçues, rangées
  par moment de la journée, font une probabilité (bêta, avec un a priori) ;
  l'écart à l'a priori, en log-odds borné, module ses initiatives vers elle à
  cette heure-là. Elle apprend quand écrire à Alice.
- **Prendre de ses nouvelles** : une amie ou une proche dont le dernier
  message l'a inquiétée, et qui n'a rien écrit de plus léger depuis — passé
  quelques heures (et pas trop), en journée, elle lui écrit. Une fois : lui
  écrire, ou un message d'elle qui va mieux, éteint l'inquiétude.

Tout se déduit du journal : les lectures de ton sont des jugements
enregistrés (``others.read``), le reste des événements publics des autres.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import attention as attention_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import others as c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.others.tone import measure
from mika.kernel.arbitration import Candidate, Modulation, RowView
from mika.kernel.clock import DAY, HOUR, MINUTE, within_daily_window
from mika.kernel.events import Draft
from mika.kernel.faculty import Faculty, Zone
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, floor
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.vocab.affect import Appraisal, Emotion
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.people import is_identifiable
from mika.vocab.temperament import Temperament, lerp

#: Combien d'initiatives en cours on retient (des épisodes qui n'ont jamais parlé s'y oublient).
OPENINGS_KEPT = 16
#: Combien de réponses tardives on sait reconnaître.
MISSED_KEPT = 64


class OthersParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # son ton habituel, son état du moment
    usual_weight: Annotated[float, Knob(
        label="Poids d'un message dans le ton habituel", group="Ce qu'elle devine de son ton", lo=0.01, hi=0.5,
        step=0.01, help="Le ton habituel d'une personne bouge d'autant à chaque message. Plus haut : un mauvais "
                        "jour change vite ce qu'elle attend d'elle ; plus bas : il faut des semaines.")] = 0.08
    usual_prior: Annotated[int, Knob(
        label="Messages neutres supposés au départ", group="Ce qu'elle devine de son ton", lo=0, hi=20,
        help="Avant de la connaître, elle lui prête autant de messages neutres : trois premiers messages "
             "tristes ne font pas une personne triste.")] = 2
    recent_weight: Annotated[float, Knob(
        label="Poids d'un message dans l'état du moment", group="Ce qu'elle devine de son ton", lo=0.05, hi=1.0,
        step=0.05, help="L'état du moment qu'elle lui prête suit chaque message d'autant (1 : le dernier message "
                        "seul).")] = 0.5
    recent_half_life_us: Annotated[int, Knob(
        label="L'état du moment s'efface en", group="Ce qu'elle devine de son ton", lo=10 * MINUTE, hi=3 * DAY,
        help="Sans nouveau message, ce qu'elle lui prête revient vers son ton habituel avec cette demi-vie.")] = \
        3 * HOUR
    confident_after: Annotated[int, Knob(
        label="La connaître après (messages)", group="Ce qu'elle devine de son ton", lo=1, hi=100,
        help="Après tant de messages lus, elle sait assez de son ton pour s'étonner d'un écart et le dire.")] = 8
    notable_deviation: Annotated[float, Knob(
        label="Écart qui se remarque", group="Ce qu'elle devine de son ton", lo=0.05, hi=1.0, step=0.05,
        help="Un écart au ton habituel au moins aussi grand se dit dans le prompt (« ça ne lui ressemble pas »), "
             "seulement en privé.")] = 0.25
    # la surprise
    surprise_from: Annotated[float, Knob(
        label="Surprise à partir de", group="Surprise et inquiétude", lo=0.05, hi=2.0, step=0.05,
        help="Un écart entre le ton attendu et le ton lu (pondéré par ce qu'elle la connaît) au moins aussi grand "
             "la surprend.")] = 0.45
    surprise_gain: Annotated[float, Knob(
        label="Force de la surprise", group="Surprise et inquiétude", lo=0.0, hi=1.0, step=0.05,
        help="La surprise ressentie vaut l'écart multiplié par ce facteur (dérivé de la réactivité).")] = 0.5
    surprise_max: Annotated[float, Knob(
        label="Surprise au plus", group="Surprise et inquiétude", lo=0.0, hi=1.0, step=0.05,
        help="Une surprise ne dépasse jamais cette intensité : un étonnement, pas un choc.")] = 0.4
    concern_below: Annotated[float, Knob(
        label="Inquiétude : ton au plus", group="Surprise et inquiétude", lo=-1.0, hi=0.0, step=0.05,
        help="Elle s'inquiète pour une amie ou une proche dont le message est au moins aussi lourd…")] = -0.3
    concern_drop: Annotated[float, Knob(
        label="Inquiétude : plus sombre que d'habitude de", group="Surprise et inquiétude", lo=0.05, hi=2.0,
        step=0.05, help="… et plus sombre que ce qu'elle attendait d'elle d'au moins autant : un message lourd de "
                        "quelqu'un qui râle toujours ne l'inquiète pas.")] = 0.45
    concern_confidence: Annotated[float, Knob(
        label="Inquiétude : la connaître au moins", group="Surprise et inquiétude", lo=0.0, hi=1.0, step=0.05,
        help="La part de « la connaître » qu'il faut pour s'inquiéter d'un écart (1 : tous les messages "
             "ci-dessus).")] = 0.5
    worry_intensity: Annotated[float, Knob(
        label="Inquiétude ressentie", group="Surprise et inquiétude", lo=0.0, hi=1.0, step=0.05,
        help="L'intensité de l'inquiétude qu'elle ressent sur le moment (suit la contagion du tempérament).")] = 0.2
    # ses délais de réponse
    delay_samples: Annotated[int, Knob(
        label="Délais retenus", group="Ses délais de réponse", lo=3, hi=50,
        help="Les derniers délais de réponse retenus par personne et par canal ; le délai habituel est leur "
             "médiane.")] = 9
    delay_max_us: Annotated[int, Knob(
        label="Délai au-delà duquel ce n'est plus une réponse", group="Ses délais de réponse", lo=HOUR,
        hi=14 * DAY, help="Un message qui arrive plus tard n'est pas compté comme une réponse à son initiative.")] = \
        2 * DAY
    # les heures où elle répond
    receptivity_prior_answered: Annotated[float, Knob(
        label="A priori : initiatives comblées", group="Les heures où elle répond", lo=0.1, hi=20, step=0.1,
        help="Avant d'avoir rien vu, elle fait comme si tant d'initiatives à cette heure avaient reçu une "
             "réponse…")] = 2.0
    receptivity_prior_missed: Annotated[float, Knob(
        label="A priori : initiatives sans réponse", group="Les heures où elle répond", lo=0.1, hi=20, step=0.1,
        help="… et tant d'autres, aucune. Plus l'a priori est gros, plus il faut d'expérience pour la faire "
             "changer d'heure.")] = 1.0
    receptivity_min_observations: Annotated[int, Knob(
        label="Observations avant d'en tenir compte", group="Les heures où elle répond", lo=1, hi=20,
        help="En deçà de tant d'initiatives à cette heure-là, rien ne change.")] = 2
    receptivity_max_shift: Annotated[float, Knob(
        label="Poids au plus", group="Les heures où elle répond", lo=0.0, hi=4.0, step=0.1,
        help="L'expérience rend une initiative à cette heure plus ou moins probable d'au plus tant (log-odds ; "
             "le seuil d'initiative est à 9).")] = 1.5
    # prendre de ses nouvelles
    checkin_after_us: Annotated[int, Knob(
        label="Prendre de ses nouvelles après", group="Prendre de ses nouvelles", lo=30 * MINUTE, hi=2 * DAY,
        help="Une amie dont le dernier message l'a inquiétée et qui n'a rien écrit depuis : passé ce délai, elle "
             "a envie de prendre de ses nouvelles.")] = 3 * HOUR
    checkin_jitter: Annotated[float, Knob(
        label="Variation de ce délai", group="Prendre de ses nouvelles", lo=0.0, hi=3.0, step=0.1,
        help="Le délai est allongé d'une part tirée au hasard, jusqu'à cette fraction (1 : de trois à six "
             "heures) : on n'écrit pas à heure fixe. Le tirage est enregistré avec l'inquiétude.")] = 1.0
    checkin_until_us: Annotated[int, Knob(
        label="… et jusqu'à", group="Prendre de ses nouvelles", lo=HOUR, hi=7 * DAY,
        help="Au-delà, l'inquiétude est passée (c'est le manque qui prendra le relais, à son rythme).")] = 30 * HOUR
    checkin_evidence_start: Annotated[float, Knob(
        label="Envie de prendre des nouvelles, au début", group="Prendre de ses nouvelles", lo=0.0, hi=12.0,
        step=0.5, help="Preuve d'initiative (log-odds) quand le délai ci-dessus vient de passer : elle y pense, "
                       "sans urgence. Elle monte ensuite jusqu'à la preuve pleine.")] = 2.0
    checkin_evidence: Annotated[float, Knob(
        label="Preuve d'une prise de nouvelles", group="Prendre de ses nouvelles", lo=0.0, hi=12.0, step=0.5,
        help="La preuve pleine (log-odds). Au-dessus du seuil d'initiative (9), elle écrit seule ; la retenue "
             "(rancune, pas deux messages de suite sans réponse) s'applique.")] = 9.5
    checkin_ramp_us: Annotated[int, Knob(
        label="L'envie monte en", group="Prendre de ses nouvelles", lo=MINUTE, hi=DAY,
        help="Le temps pour passer de l'envie du début à la preuve pleine : l'heure où elle écrit varie, comme "
             "chez quelqu'un qui y repense de plus en plus.")] = 3 * HOUR
    checkin_day_start_min: Annotated[int, Knob(
        label="Prendre des nouvelles : à partir de", group="Prendre de ses nouvelles", lo=0, hi=24 * 60,
        help="Heure locale (minutes depuis minuit) à partir de laquelle elle écrit pour prendre des nouvelles.")] = \
        9 * 60
    checkin_day_end_min: Annotated[int, Knob(
        label="Prendre des nouvelles : jusqu'à", group="Prendre de ses nouvelles", lo=0, hi=24 * 60,
        help="Heure locale après laquelle elle ne le fait plus (avant le début : la plage passe minuit).")] = 22 * 60
    receptivity_late_weight: Annotated[float, Knob(
        label="Une réponse tardive compte pour", group="Les heures où elle répond", lo=0.0, hi=1.0, step=0.05,
        help="Une réponse arrivée après le délai attendu rattrape d'autant l'initiative restée sans réponse.")] = 0.5


def derive(t: Temperament, overrides: Any = None) -> OthersParams:
    """La réactivité règle la force de la surprise (au milieu : 0,5)."""
    values: dict[str, Any] = {"surprise_gain": round(lerp(0.3, 0.7, t.reactivity), 3)}
    values.update(dict(overrides or {}))
    return OthersParams(**values)


@dataclass(frozen=True, slots=True)
class Model:
    """Ce qu'elle devine du ton d'une personne."""

    observed: int = 0
    usual_valence: float = 0.0
    usual_arousal: float = 0.3
    recent_valence: float = 0.0  # à ``last_at``
    recent_arousal: float = 0.3
    last_at: int = 0
    last_message: int = 0
    last_cues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OthersState:
    people: FrozenDict[str, Model] = field(default_factory=FrozenDict)
    #: les initiatives en cours (corrélation → raisons) : une salutation n'attend pas de réponse
    openings: FrozenDict[str, str] = field(default_factory=FrozenDict)
    #: personne → (instant de son initiative, classe de canal) : elle attend sa réponse
    awaiting: FrozenDict[str, tuple[int, str]] = field(default_factory=FrozenDict)
    #: « personne|classe » → derniers délais de réponse (µs)
    delays: FrozenDict[str, tuple[int, ...]] = field(default_factory=FrozenDict)
    #: « personne|moment » → (comblées, sans réponse)
    answers: FrozenDict[str, tuple[float, float]] = field(default_factory=FrozenDict)
    #: les attentes déçues (« personne:depuis ») : une réponse tardive les rattrape
    missed: tuple[str, ...] = ()
    #: personne → (message qui l'a inquiétée, quand, à partir de quand prendre de ses nouvelles)
    concerns: FrozenDict[str, tuple[int, int, int]] = field(default_factory=FrozenDict)


OTHERS = Faculty("others", state=OthersState, init=lambda p: OthersState(), params=OthersParams, derive=derive)
OTHERS.declare(*c.ALL)


def params(p: OthersParams | None) -> OthersParams:
    return p if p is not None else OthersParams()


def channel_class(channel: str) -> str:
    """Par messagerie, on lit quand on y pense ; à l'écran, on répond en minutes."""
    return c.MESSAGE if channel == "telegram" else c.SCREEN


def band_of(hour: int) -> str:
    """Le moment de la journée d'une heure locale."""
    if hour < 6:
        return c.NIGHT
    if hour < 12:
        return c.MORNING
    if hour < 18:
        return c.AFTERNOON
    return c.EVENING


def current(m: Model, now: int, p: OthersParams) -> tuple[float, float]:
    """L'état du moment qu'elle lui prête : les derniers messages, effacés vers
    l'habituel avec le temps."""
    if not m.observed:
        return m.usual_valence, m.usual_arousal
    fade = 0.5 ** (max(0, now - m.last_at) / p.recent_half_life_us)
    return (m.usual_valence + (m.recent_valence - m.usual_valence) * fade,
            m.usual_arousal + (m.recent_arousal - m.usual_arousal) * fade)


def confidence(m: Model, p: OthersParams, closeness: str = social_c.ACQUAINTANCE) -> float:
    """Ce qu'elle la connaît : assez de messages lus, et un lien. Une inconnue,
    même bavarde, ne lui a encore rien appris de ce qui lui ressemble."""
    if closeness == social_c.STRANGER:
        return 0.0
    return min(1.0, m.observed / p.confident_after)


def learn(m: Model, valence: float, arousal: float, message: int, cues: tuple[str, ...], at: int,
          p: OthersParams) -> Model:
    """Un message de plus : l'habituel bouge un peu (moyenne qui part d'une
    neutralité supposée), l'état du moment beaucoup."""
    now_v, now_a = current(m, at, p)
    weight = max(p.usual_weight, 1.0 / (m.observed + 1 + p.usual_prior))
    return Model(
        observed=m.observed + 1,
        usual_valence=round(m.usual_valence + weight * (valence - m.usual_valence), 5),
        usual_arousal=round(m.usual_arousal + weight * (arousal - m.usual_arousal), 5),
        recent_valence=round(now_v + p.recent_weight * (valence - now_v), 5),
        recent_arousal=round(now_a + p.recent_weight * (arousal - now_a), 5),
        last_at=at, last_message=message, last_cues=cues,
    )


def reading(s: OthersState, person: str, now: int, p: OthersParams,
            closeness: str = social_c.ACQUAINTANCE) -> c.MindReading:
    m = s.people.get(person) or Model()
    v, a = current(m, now, p)
    return c.MindReading(person, m.observed, round(m.usual_valence, 3), round(m.usual_arousal, 3), round(v, 3),
                         round(a, 3), round(v - m.usual_valence, 3), round(confidence(m, p, closeness), 3),
                         m.last_at, m.last_message, m.last_cues)


def _logit(x: float) -> float:
    x = min(1 - 1e-6, max(1e-6, x))
    return math.log(x / (1 - x))


def receptivity(s: OthersState, person: str, band: str, p: OthersParams) -> tuple[float, float, float, float]:
    """(comblées, sans réponse, probabilité estimée, décalage en log-odds) pour
    une initiative vers cette personne à ce moment de la journée."""
    answered, missed = s.answers.get(f"{person}|{band}", (0.0, 0.0))
    a0, m0 = p.receptivity_prior_answered, p.receptivity_prior_missed
    estimate = (answered + a0) / (answered + missed + a0 + m0)
    if answered + missed < p.receptivity_min_observations:
        return answered, missed, estimate, 0.0
    shift = _logit(estimate) - _logit(a0 / (a0 + m0))
    bound = p.receptivity_max_shift
    return answered, missed, estimate, round(max(-bound, min(bound, shift)), 4)


# ── Lire un message à son arrivée ─────────────────────────────────────────


@OTHERS.interpret(rt.PERCEPTION_RECEIVED)
def _read(s: OthersState, frame: Frame, ev: Any, ports: Any) -> list[Draft[Any]]:
    """Ce qu'elle lit dans la forme d'un message, et ce qu'elle en attendait —
    journalisé avant la réponse : sa réponse voit déjà la surprise."""
    d = ev.data
    text = d.text.text or ""
    if not d.addressed or not is_identifiable(d.handle) or not text.strip():
        return []
    p = params(frame.env.params_of("others", frame.root))
    person = frame.get(identity_c.PERSON(d.handle))
    tone = measure(text)
    m = s.people.get(person) or Model()
    expected, _ = current(m, ev.at, p)
    level = frame.get(social_c.CLOSENESS(person))
    known = confidence(m, p, level)
    close = level in (social_c.FRIEND, social_c.CLOSE)
    concern = (close and known >= p.concern_confidence and tone.valence <= p.concern_below
               and expected - tone.valence >= p.concern_drop)
    return [c.READ.draft(person=person, handle=d.handle, message=ev.seq, valence=tone.valence, arousal=tone.arousal,
                         cues=tone.cues, expected=round(expected, 3), confidence=round(known, 3),
                         surprise=round(abs(tone.valence - expected) * known, 3), concern=concern,
                         public=bool(d.public or d.room))]


# ── Réducteurs ────────────────────────────────────────────────────────────


@OTHERS.reducer(c.READ)
def _learned(s: OthersState, e, cx) -> OthersState:
    d = e.data
    p = params(cx.params)
    m = learn(s.people.get(d.person) or Model(), d.valence, d.arousal, d.message, tuple(d.cues), e.at, p)
    s = replace(s, people=s.people.set(d.person, m))
    if d.concern:
        opens = e.at + round(p.checkin_after_us * (1.0 + p.checkin_jitter * cx.rng.random()))
        return replace(s, concerns=s.concerns.set(d.person, (d.message, e.at, opens)))
    if d.person in s.concerns and d.valence > p.concern_below:
        return replace(s, concerns=s.concerns.delete(d.person))  # elle va mieux : plus d'inquiétude
    return s


@OTHERS.reducer(rt.EPISODE_STARTED)
def _reaching_out(s: OthersState, e, cx) -> OthersState:
    d = e.data
    if d.kind != Kind.INITIATIVE or not d.target:
        return s
    openings = s.openings.set(e.correlation, d.reason)
    if len(openings) > OPENINGS_KEPT:  # les identifiants d'épisode sont chronologiques
        openings = FrozenDict(sorted(openings.items())[-OPENINGS_KEPT:])
    return replace(s, openings=openings)


@OTHERS.reducer(rt.UTTERANCE, reads=[identity_c.PERSON])
def _wrote(s: OthersState, e, cx) -> OthersState:
    """Elle écrit d'elle-même à quelqu'un : on mesurera le temps qu'il met à
    répondre (pas à une salutation ni à un rappel : ce n'était pas une
    question)."""
    d = e.data
    if d.kind != Kind.INITIATIVE or not d.visible or not d.target or not is_identifiable(d.target):
        return s
    reasons = s.openings.get(e.correlation, "").split(",")
    s = replace(s, openings=s.openings.delete(e.correlation))
    person = cx.facts.get(identity_c.PERSON(d.target))
    if c.CHECK_IN in reasons:
        s = replace(s, concerns=s.concerns.delete(person))  # c'est fait : elle a pris de ses nouvelles
    if social_c.GREETING in reasons or goals_c.REMIND in reasons:
        return s
    return replace(s, awaiting=s.awaiting.set(person, (e.at, channel_class(d.channel))))


@OTHERS.reducer(rt.PERCEPTION_RECEIVED, reads=[identity_c.PERSON])
def _answered(s: OthersState, e, cx) -> OthersState:
    d = e.data
    if not d.addressed or not is_identifiable(d.handle):
        return s
    person = cx.facts.get(identity_c.PERSON(d.handle))
    pending = s.awaiting.get(person)
    if pending is None:
        return s
    since, klass = pending
    s = replace(s, awaiting=s.awaiting.delete(person))
    delay = e.at - since
    p = params(cx.params)
    if delay < 0 or delay > p.delay_max_us:
        return s
    key = f"{person}|{klass}"
    samples = (*s.delays.get(key, ()), delay)[-p.delay_samples:]
    return replace(s, delays=s.delays.set(key, samples))


@OTHERS.reducer(attention_c.EXPECTATION_MET, attention_c.EXPECTATION_MISSED)
def _outcome(s: OthersState, e, cx) -> OthersState:
    """Une initiative comblée ou restée sans réponse, rangée au moment de la
    journée où elle l'a écrite. Une réponse tardive rattrape en partie."""
    d = e.data
    if d.kind != attention_c.REPLY:
        return s
    p = params(cx.params)
    band = band_of(cx.local(d.since).hour)
    key = f"{d.person}|{band}"
    answered, missed = s.answers.get(key, (0.0, 0.0))
    mark = f"{d.person}:{d.since}"
    if e.type.name == attention_c.EXPECTATION_MISSED.name:
        return replace(s, answers=s.answers.set(key, (answered, missed + 1.0)),
                       missed=(*s.missed, mark)[-MISSED_KEPT:])
    if mark in s.missed:  # tardive : la moitié du chemin
        w = p.receptivity_late_weight
        return replace(s, answers=s.answers.set(key, (answered + w, max(0.0, missed - w))),
                       missed=tuple(x for x in s.missed if x != mark))
    return replace(s, answers=s.answers.set(key, (answered + 1.0, missed)))


# ── Faits ─────────────────────────────────────────────────────────────────


@OTHERS.fact(c.MIND, reads=[social_c.CLOSENESS])
def _mind(s: OthersState, cx, person: str) -> c.MindReading:
    return reading(s, person, cx.now, params(cx.params), cx.facts.get(social_c.CLOSENESS(person)))


@OTHERS.fact(c.REPLY_DELAY)
def _reply_delay(s: OthersState, cx, arg: tuple[str, str]) -> c.DelayReading:
    person, channel = arg
    samples = s.delays.get(f"{person}|{channel_class(channel)}", ())
    return c.DelayReading(len(samples), int(statistics.median(samples)) if samples else 0)


# ── Ce que ses lectures lui font ressentir ────────────────────────────────


@OTHERS.appraisal(c.READ)
def _read_felt(e, cx) -> list[Appraisal]:
    d = e.data
    p = params(cx.params)
    out: list[Appraisal] = []
    if d.surprise >= p.surprise_from:
        out.append(Appraisal(Emotion.SURPRISED, min(p.surprise_max, d.surprise * p.surprise_gain),
                             reason="surprise"))
    if d.concern:
        # s'inquiéter pour quelqu'un suit la contagion du tempérament
        out.append(Appraisal(Emotion.ANXIOUS, p.worry_intensity, reason="inquiétude", relational=True))
    return out


# ── Ses initiatives, selon ce que l'expérience lui a appris ───────────────


@OTHERS.modulate(kinds=[Kind.INITIATIVE], reads=[identity_c.PERSON])
def _receptive(s: OthersState, frame: Frame, row: RowView) -> Modulation:
    """Écrire à quelqu'un à une heure où il répond d'habitude, plutôt qu'à une
    heure où ses messages restent sans réponse. Ni une salutation (quelqu'un
    arrive), ni un rappel promis n'en dépendent."""
    if row.target in ("any", "none") or not is_identifiable(row.target):
        return Modulation()
    if social_c.GREETING in row.reasons or goals_c.REMIND in row.reasons:
        return Modulation()
    p = params(frame.env.params_of("others", frame.root))
    person = frame.get(identity_c.PERSON(row.target))
    shift = receptivity(s, person, band_of(frame.local().hour), p)[3]
    return Modulation(shift=shift) if shift else Modulation()


def _address(frame: Frame, person: str) -> str | None:
    """Où lui écrire : une poignée présente d'abord, sinon une conversation
    privée où l'on peut lui écrire d'elle-même."""
    handles = frame.get(identity_c.HANDLES(person))
    present = [h for h in frame.get(presence_c.PRESENT) if h in handles]
    if present:
        return present[0]
    reachable = frame.get(identity_c.REACHABLE(person))
    return reachable[0] if reachable else None


@OTHERS.propose(kinds=[Kind.INITIATIVE], reasons={c.CHECK_IN: (0.0, 12.0)},
                reads=[identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY, presence_c.PRESENT,
                       social_c.CLOSENESS, transcript_c.LAST_FROM])
def _check_in(s: OthersState, frame: Frame) -> list[Candidate]:
    """Une amie qui n'avait pas l'air bien, et plus rien depuis : quelques
    heures plus tard, elle prend de ses nouvelles."""
    if not s.concerns:
        return []
    p = params(frame.env.params_of("others", frame.root))
    local = frame.local()
    if not within_daily_window(local.hour * 60 + local.minute, p.checkin_day_start_min, p.checkin_day_end_min):
        return []
    out: list[Candidate] = []
    for person, (_message, at, opens) in sorted(s.concerns.items()):
        if frame.now < opens or frame.now - at > p.checkin_until_us:
            continue
        if frame.get(social_c.CLOSENESS(person)) not in (social_c.FRIEND, social_c.CLOSE):
            continue
        address = _address(frame, person)
        if address is None:
            continue
        name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(address)).name
        who = f"« {name} »" if name else "cette personne"
        brief = (f"{who[0].upper()}{who[1:]} n'avait pas l'air bien la dernière fois que vous vous êtes parlé, et "
                 "tu n'as pas eu de nouvelles depuis. Tu as envie de savoir comment ça va : un mot simple et doux, "
                 "sans insister ni jouer les psys.")
        handles = frame.get(identity_c.HANDLES(person)) or (person,)
        guard = Guard("pas de nouvelles", reads=tuple(transcript_c.LAST_FROM(h) for h in handles))
        ramp = min(1.0, (frame.now - opens) / p.checkin_ramp_us)
        evidence = p.checkin_evidence_start + (p.checkin_evidence - p.checkin_evidence_start) * ramp
        out.append(Candidate(Kind.INITIATIVE, address, c.CHECK_IN, round(evidence, 3),
                             resources=frozenset({floor(address)}), guards=(guard,),
                             args=FrozenDict({"brief:others": brief})))
    return out


# ── Prompt ────────────────────────────────────────────────────────────────


@OTHERS.section("their_state", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["who"], trim_rank=40,
                title="CE QUE TU PERÇOIS DE SON ÉTAT", reads=[identity_c.PERSON, identity_c.IDENTITY, c.MIND])
def _their_state(s: OthersState, frame: Frame, enrich: Any) -> SectionBody | None:
    """Les indices du message auquel elle répond — et, en privé, ce qui tranche
    avec le ton habituel de la personne. Jamais un nombre."""
    ep, aud = frame.episode, frame.audience
    if ep is None or not ep.target or not is_identifiable(ep.target):
        return None
    p = params(frame.env.params_of("others", frame.root))
    person = frame.get(identity_c.PERSON(ep.target))
    r = frame.get(c.MIND(person))
    lines: list[str] = []
    if ep.kind == Kind.REPLY and r.last_cues and r.last_message == ep.attrs.get("reply_to"):
        lines.append("Dans son message : " + " ; ".join(r.last_cues) + ".")
    if aud is not None and aud.private_ok and r.confidence >= 1.0:
        name = frame.get(identity_c.IDENTITY(person)).name
        who = f"« {name} »" if name else "cette personne"
        if r.deviation <= -p.notable_deviation:
            lines.append(f"Ça ne ressemble pas à {who} : d'habitude, le ton est plus léger que ça.")
        elif r.deviation >= p.notable_deviation:
            lines.append(f"{who[0].upper()}{who[1:]} a l'air d'humeur plus légère que d'habitude.")
        if r.current_arousal - r.usual_arousal >= p.notable_deviation:
            lines.append("Le ton est plus vif, plus agité que d'habitude.")
    if not lines:
        return None
    lines.append("C'est un indice, pas une certitude.")
    return SectionBody("\n".join(lines))

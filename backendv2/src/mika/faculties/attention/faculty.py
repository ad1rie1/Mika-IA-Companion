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
from typing import Annotated

from pydantic import BaseModel, ConfigDict

from mika.contracts import attention as c
from mika.contracts import expression as expression_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict
from mika.vocab import affect as A
from mika.vocab.affect import Appraisal, Declared, Emotion
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable


class AttentionParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    half_life_us: Annotated[int, Knob(
        label="Demi-vie d'une pensée", group="Pensées", lo=30 * MINUTE, hi=3 * DAY,
        help="Une pensée perd la moitié de son intensité en ce temps. Plus long : des ruminations qui durent des "
             "jours ; plus court : rien ne lui reste en tête.")] = 6 * HOUR
    fade_below: Annotated[float, Knob(
        label="Seuil d'extinction", group="Pensées", lo=0.01, hi=0.5, step=0.01,
        help="Une pensée dont l'intensité passe sous ce seuil s'éteint : elle ne se lit plus nulle part.")] = 0.1
    max_thoughts: Annotated[int, Knob(
        label="Pensées vivantes au plus", group="Pensées", lo=1, hi=30,
        help="Au-delà, les plus faibles s'effacent quand une nouvelle naît.")] = 8
    # un échange qui marque
    marking_intensity: Annotated[float, Knob(
        label="Intensité qui marque", group="Un échange qui marque", lo=0.0, hi=1.0, step=0.05,
        help="Une réponse qu'elle donne avec une émotion déclarée au moins aussi intense laisse une pensée sur "
             "la personne.")] = 0.75
    marking_valence: Annotated[float, Knob(
        label="Valence qui marque", group="Un échange qui marque", lo=-1.0, hi=0.0, step=0.05,
        help="Une réponse dont l'émotion déclarée est au moins aussi négative (valence) marque aussi, dès "
             "l'intensité minimale. Près de 0 : presque tout échange un peu tendu laisse une pensée.")] = -0.2
    marking_min_intensity: Annotated[float, Knob(
        label="Intensité minimale", group="Un échange qui marque", lo=0.0, hi=1.0, step=0.05,
        help="Sous cette intensité déclarée, aucun échange ne marque, même négatif.")] = 0.5
    birth_factor: Annotated[float, Knob(
        label="Force à la naissance", group="Un échange qui marque", lo=0.0, hi=1.0, step=0.05,
        help="La pensée naît à cette fraction de l'intensité déclarée ; un nouvel échange marquant avec la même "
             "personne la ravive jusque-là.")] = 0.7
    exchange_spacing_us: Annotated[int, Knob(
        label="Espacement des échanges", group="Un échange qui marque", lo=MINUTE, hi=6 * HOUR,
        help="Dans ce délai, un nouvel échange marquant avec la même personne ravive sa pensée au lieu d'en créer "
             "une ; au-delà, lui reparler divise par deux ce qui la concerne.")] = 30 * MINUTE
    exchange_cap: Annotated[int, Knob(
        label="Pensées d'échanges à la fois", group="Un échange qui marque", lo=0, hi=10,
        help="Jamais plus de pensées nées d'échanges en même temps (une par personne) : douze insultes ne font "
             "pas douze ruminations.")] = 3
    # une croyance révisée, un manque, un but bloqué
    revision_intensity: Annotated[float, Knob(
        label="Croyance révisée", group="Révision, manque, blocage", lo=0.0, hi=1.0, step=0.05,
        help="L'intensité de la pensée de confusion quand une croyance en remplace une autre (« je croyais "
             "que… »).")] = 0.3
    blocked_intensity: Annotated[float, Knob(
        label="But bloqué", group="Révision, manque, blocage", lo=0.0, hi=1.0, step=0.05,
        help="L'intensité de la pensée de frustration (« je bloque sur… ») quand un de ses buts bloque.")] = 0.35
    missing_intensity: Annotated[float, Knob(
        label="Quelqu'un qui manque", group="Révision, manque, blocage", lo=0.0, hi=1.0, step=0.05,
        help="L'intensité de la pensée nostalgique pour une personne qui lui manque et qu'elle ne peut pas "
             "joindre (une à la fois).")] = 0.3
    missing_check_us: Annotated[int, Knob(
        label="Vérifier les manques toutes les", group="Révision, manque, blocage", lo=5 * MINUTE, hi=12 * HOUR,
        help="Éveillée, elle se demande à ce rythme qui lui manque sans qu'elle puisse le joindre.")] = 30 * MINUTE
    # y repenser
    dwell_every_us: Annotated[int, Knob(
        label="Y repenser au plus toutes les", group="Y repenser", lo=5 * MINUTE, hi=12 * HOUR,
        help="Éveillée, elle revient à sa pensée la plus forte au plus à ce rythme, et en ressent un peu "
             "l'émotion à chaque fois.")] = 30 * MINUTE
    dwell_from: Annotated[float, Knob(
        label="Y repenser dès", group="Y repenser", lo=0.0, hi=1.0, step=0.05,
        help="Seule une pensée au moins aussi intense lui revient en tête.")] = 0.3
    dwell_factor: Annotated[float, Knob(
        label="Émotion en y repensant", group="Y repenser", lo=0.0, hi=1.0, step=0.05,
        help="La fraction de l'intensité de la pensée qu'elle ressent quand elle y repense.")] = 0.3
    birth_appraisal_factor: Annotated[float, Knob(
        label="Émotion quand une pensée naît", group="Y repenser", lo=0.0, hi=1.0, step=0.05,
        help="La fraction de l'intensité d'une pensée qu'elle ressent au moment où elle naît.")] = 0.5
    # attentes
    reply_window_us: Annotated[int, Knob(
        label="Délai de réponse attendu", group="Attentes", lo=MINUTE, hi=6 * HOUR,
        help="Après une initiative (pas une salutation ni un rappel), elle attend une réponse ; passé ce délai, "
             "elle compte comme ignorée : son estime baisse et elle se fait plus réservée.")] = 20 * MINUTE
    reply_window_message_us: Annotated[int, Knob(
        label="Délai de réponse (messagerie)", group="Attentes", lo=5 * MINUTE, hi=DAY,
        help="Le même délai sur Telegram, où un message se lit quand on y pense, pas quand il arrive.")] = HOUR
    # la nuit : les pensées de la veille s'allègent (÷3) et se calment
    digest_after_sleep_us: Annotated[int, Knob(
        label="Digérer après", group="La nuit", lo=0, hi=10 * HOUR,
        help="Une fois par nuit, ce temps après l'endormissement, ses pensées s'allègent et leur couleur se calme. "
             "Plus long que son sommeil : pas de digestion cette nuit-là.")] = 3 * HOUR
    digest_min_age_us: Annotated[int, Knob(
        label="Âge minimal pour digérer", group="La nuit", lo=0, hi=DAY,
        help="Une pensée plus récente que ça n'est pas digérée cette nuit (elle attend la suivante).")] = 2 * HOUR
    digest_factor: Annotated[float, Knob(
        label="Ce qu'il en reste au matin", group="La nuit", lo=0.0, hi=1.0, step=0.01,
        help="L'intensité d'une pensée digérée est multipliée par ce facteur (1 : la nuit n'allège rien).")] = 1 / 3
    reflective_from: Annotated[float, Knob(
        label="Souvenir réfléchi dès", group="La nuit", lo=0.0, hi=1.0, step=0.05,
        help="Une pensée encore au moins aussi forte à la digestion devient un souvenir réfléchi (« après y avoir "
             "repensé cette nuit… »).")] = 0.25
    # ce que signalent les sources extérieures : l'habituation (la même source,
    # la même sorte, à répétition, se remarque de moins en moins) et le dosage
    # (une source ne fait pas plus qu'une petite émotion en dix minutes)
    habituation_window_us: Annotated[int, Knob(
        label="Fenêtre d'habituation", group="Signaux extérieurs", lo=MINUTE, hi=2 * HOUR,
        help="Les signaux d'une même source et d'une même sorte répétés dans cette fenêtre se remarquent de moins "
             "en moins ; c'est aussi la fenêtre du dosage de l'émotion.")] = 10 * MINUTE
    habituation_factor: Annotated[float, Knob(
        label="Facteur d'habituation", group="Signaux extérieurs", lo=0.0, hi=1.0, step=0.01,
        help="Le poids d'un signal est multiplié par ce facteur à chaque répétition dans la fenêtre (1 : aucune "
             "habituation).")] = 0.85
    habituation_floor: Annotated[float, Knob(
        label="Plancher d'habituation", group="Signaux extérieurs", lo=0.0, hi=1.0, step=0.05,
        help="Le poids d'un signal répété ne descend jamais sous ce plancher : le quarantième titre est un bruit "
             "de fond, pas rien.")] = 0.4
    dose_cap: Annotated[float, Knob(
        label="Émotion par source au plus", group="Signaux extérieurs", lo=0.0, hi=2.0, step=0.05,
        help="L'émotion cumulée qu'une même source peut lui faire ressentir dans la fenêtre : un flux est une "
             "source d'émotion, pas quinze.")] = 0.6
    signal_thought_from: Annotated[float, Knob(
        label="Pensée née d'un signal dès", group="Signaux extérieurs", lo=0.0, hi=1.0, step=0.05,
        help="Un signal dont la pertinence (après habituation) atteint ce seuil devient une pensée : ce qu'elle a "
             "lu ou vu lui reste en tête.")] = 0.6
    signal_thought_factor: Annotated[float, Knob(
        label="Force d'une pensée de signal", group="Signaux extérieurs", lo=0.0, hi=1.0, step=0.05,
        help="Son intensité : la pertinence retenue multipliée par ce facteur, dans la limite du plafond.")] = 0.7
    signal_thought_max: Annotated[float, Knob(
        label="Plafond d'une pensée de signal", group="Signaux extérieurs", lo=0.0, hi=1.0, step=0.05,
        help="Une pensée née d'un signal ne dépasse jamais cette intensité.")] = 0.6
    signals_kept: Annotated[int, Knob(
        label="Signaux en attente au plus", group="Signaux extérieurs", lo=4, hi=256,
        help="Au plus autant de signaux attendent d'être remarqués ; au-delà, les plus anciens sont oubliés sans "
             "avoir été vus.")] = 32
    # une pensée qui insiste pousse à en reparler (log-odds)
    thought_from: Annotated[float, Knob(
        label="Envie d'en reparler dès", group="Relancer", lo=0.0, hi=0.95, step=0.05,
        help="Une pensée négative (inquiétude, peine, colère…) sur une personne qui n'est pas une étrangère, au "
             "moins aussi intense, lui donne envie de lui en reparler.")] = 0.4
    thought_evidence: Annotated[float, Knob(
        label="Poids de l'envie d'en reparler", group="Relancer", lo=0.0, hi=4.0, step=0.1,
        help="La preuve (log-odds) qu'une telle pensée apporte à une initiative, pleine à mi-chemin entre le seuil "
             "et 1. L'arbitrage la plafonne à 4, loin du seuil d'initiative (9).")] = 4.0


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
    bundle: str = ""


@dataclass(frozen=True, slots=True)
class SignalHeard:
    """Un signal qui attend d'être remarqué."""

    seq: int
    source: str
    kind: str
    summary_ref: str
    pertinence: float
    emotion: str
    intensity: float
    about: tuple[str, ...]
    sensitivity: int
    bundle: str
    at: int


@dataclass(frozen=True, slots=True)
class Heard:
    """Un signal remarqué récemment (habituation, dosage)."""

    at: int
    source: str
    kind: str
    intensity: float
    #: pour l'inspecteur : le signal, ce que la source en estimait, le poids après habituation
    signal: int = 0
    pertinence: float = 0.0
    weight: float = 1.0


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
    ref: str = ""  # un texte déjà écrit (le titre d'un but bloqué)
    about: tuple[str, ...] = ()
    sensitivity: int = 2


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
    signals: tuple[SignalHeard, ...] = ()
    heard: tuple[Heard, ...] = ()


ATTENTION = Faculty("attention", state=AttentionState, init=lambda p: AttentionState(), params=AttentionParams,
                    state_version=2)
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
        # saluer, rappeler : ce n'est pas prendre la parole pour qu'on lui réponde
        if social_c.GREETING not in reasons and goals_c.REMIND not in reasons:
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


@ATTENTION.reducer(goals_c.GOAL_CLOSED)
def _goal_closed(s: AttentionState, e, cx) -> AttentionState:
    """Ce qu'elle a mené à bout apaise la pensée d'où c'était venu (elle
    l'oublie parce qu'elle l'a fait, pas parce que le temps a passé). Bloquer
    n'apaise rien : l'ancienne pensée reste ce qu'elle est, et le blocage en
    devient une autre."""
    d = e.data
    p = params(cx.params)
    source = int(d.source.split(":", 1)[1]) if d.source.startswith("thought:") and d.source[8:].isdigit() else None
    if source is not None and source in s.thoughts and d.status == goals_c.ACHIEVED:
        s = replace(s, thoughts=s.thoughts.delete(source))
    if d.status != goals_c.STUCK or d.kind == goals_c.REMINDER:
        return s
    pending = Pending(e.seq, c.BLOCKED, d.owner, Emotion.FRUSTRATED.value, p.blocked_intensity, e.at,
                      ref=d.title.ref or "", about=tuple(d.about), sensitivity=d.sensitivity)
    return replace(s, pending=(*s.pending, pending))


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
                      d.sensitivity, d.bundle)
    s = replace(s, thoughts=_alive(replace(s, thoughts=s.thoughts.set(e.seq, thought)), e.at, p),
                pending=tuple(q for q in s.pending if q.source != d.source or q.origin != d.origin))
    if d.origin == c.MISSING and d.about:
        s = _expect(s, c.RETURN, d.about[0], e.at, None)
    return s


@ATTENTION.reducer(shapes=[c.Signal])
def _signaled(s: AttentionState, e, cx) -> AttentionState:
    """Une source extérieure lui signale quelque chose : elle le remarquera
    (la veille dose l'émotion et l'habituation)."""
    d = e.data
    p = params(cx.params)
    heard = SignalHeard(e.seq, d.source, d.kind, d.summary.ref or "", d.pertinence, d.emotion, d.intensity,
                        tuple(d.about), d.sensitivity, d.bundle, e.at)
    return replace(s, signals=(*s.signals, heard)[-p.signals_kept:])


@ATTENTION.reducer(c.NOTICED)
def _noticed(s: AttentionState, e, cx) -> AttentionState:
    d = e.data
    p = params(cx.params)
    heard = tuple(h for h in s.heard if e.at - h.at < p.habituation_window_us)
    pertinence = next((x.pertinence for x in s.signals if x.seq == d.signal), 0.0)
    return replace(s, signals=tuple(x for x in s.signals if x.seq != d.signal),
                   heard=(*heard, Heard(e.at, d.source, d.kind, d.intensity, d.signal, pertinence, d.weight))[-64:])


def habituation(s: AttentionState, source: str, kind: str, now: int, p: AttentionParams,
                extra: tuple[Heard, ...] = ()) -> tuple[float, float]:
    """(poids, émotion encore permise) pour un signal de cette source, maintenant."""
    recent = [h for h in (*s.heard, *extra) if now - h.at < p.habituation_window_us]
    n = sum(1 for h in recent if h.source == source and h.kind == kind)
    used = sum(h.intensity for h in recent if h.source == source)
    return max(p.habituation_floor, p.habituation_factor ** n), max(0.0, p.dose_cap - used)


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
                            t.sensitivity, t.born_at, t.bundle)
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


@ATTENTION.appraisal(c.NOTICED)
def _noticed_felt(e, cx) -> Appraisal | None:
    """Ce qu'elle remarque la touche un peu — déjà dosé, habitué."""
    d = e.data
    if not d.emotion or d.intensity <= 0:
        return None
    return Appraisal(_emotion(d.emotion), d.intensity, reason=d.source)


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


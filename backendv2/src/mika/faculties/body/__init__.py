"""``body`` : le rythme circadien, l'énergie, le sommeil.

- le rythme (profil décalé par le chronotype), la phase et l'énergie à
  l'instant — l'énergie est la vigilance de l'heure, que la **proximité du
  sommeil** fait chuter : on est fatigué dans l'heure qui précède le moment où
  l'on s'endort (ou passé ce moment, tenu éveillé), pas « parce qu'il est
  22 h » ;
- le sommeil (``sleep``) : endormissement et réveil au croisement exact des
  seuils (qui bougent un peu d'une nuit à l'autre), cycles de 90 min ; on ne
  s'endort pas en pleine conversation ;
- la nuit, **seul un message d'une amie ou d'une proche, ou quelque chose
  d'urgent, la réveille** (``body.roused``) ; les autres attendent son réveil
  (``body.waited``) — la réponse part le matin, et elle sait qu'elle dormait ;
- elle ne prend pas la parole en dormant, et moins quand elle est fatiguée ;
- ses nuits (les sept dernières) : quand elle s'est endormie et réveillée, ce
  qu'elle a dormi, qui l'a tirée du sommeil, si elle s'est couchée tard — au
  réveil, elle sait comment s'est passée sa nuit (``body.last_night``) ;
- ses sections : son rythme (la date, l'heure, ce qu'elle ressent ; « ce
  message t'a réveillée » ; sa nuit, le matin), et le brouillard de la fatigue.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import body as c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.contracts import wakeup as wakeup_c
from mika.faculties.body import sleep as sl
from mika.kernel.arbitration import Modulation, RowView
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.clock import local as to_local
from mika.kernel.events import Draft
from mika.kernel.faculty import CatchUp, Faculty, Zone
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.ports.delivery import Delivery, EmotionView
from mika.vocab import circadian
from mika.vocab.episodes import CONVERSATIONAL, Kind, Tag
from mika.vocab.people import is_identifiable
from mika.vocab.phrasebook import phrase
from mika.vocab.temperament import Temperament
from mika.vocab.words import fold


class BodyParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Décalage du rythme, en minutes (chronotype : ±2 h autour du profil type).
    shift_minutes: Annotated[int, Knob(
        label="Décalage du rythme (minutes)", group="Rythme", lo=-360, hi=360,
        help="Décale tout son rythme (phases de la journée, pic d'énergie, seuils de sommeil) ; positif : plus "
             "tard. Dérivé du chronotype (±2 h autour du profil type).")] = 0
    sleep: Annotated[sl.SleepParams, Knob(
        label="Sommeil", group="Sommeil",
        help="La pression de sommeil qui monte en veille et retombe la nuit, les seuils circadiens qu'elle "
             "croise pour s'endormir et se réveiller, les cycles.")] = sl.SleepParams()
    #: la fatigue : la proximité du moment où elle s'endormirait
    drowsy_hours: Annotated[float, Knob(
        label="Somnolente dans les … heures avant de s'endormir", group="Énergie", lo=0.25, hi=6, step=0.25,
        help="Son énergie commence à baisser quand elle n'est plus qu'à tant d'heures du moment où elle "
             "s'endormirait si personne ne la tenait éveillée — et non à heure fixe chaque soir.")] = 1.25
    drowsy_depth: Annotated[float, Knob(
        label="Ce que la somnolence retire", group="Énergie", lo=0, hi=1, step=0.05,
        help="La part de sa vigilance qu'elle a perdue au moment où elle s'endormirait (et pendant son "
             "sommeil).")] = 0.65
    overtired_slope: Annotated[float, Knob(
        label="Tenue éveillée : énergie perdue par heure", group="Énergie", lo=0, hi=1, step=0.05,
        help="Passé le moment où elle se serait endormie (une conversation qui se prolonge), elle perd encore "
             "autant d'énergie par heure : elle finit par tomber de sommeil.")] = 0.1
    night_waking_energy: Annotated[float, Knob(
        label="Tirée du sommeil la nuit : énergie au plus", group="Énergie", lo=0, hi=1, step=0.05,
        help="Réveillée par un message au milieu de sa nuit, elle est dans le brouillard : son énergie ne dépasse "
             "pas ce niveau.")] = 0.25
    #: fatigue : sous ce niveau d'énergie, prendre la parole d'elle-même se fait plus rare
    tired_below: Annotated[float, Knob(
        label="Fatiguée sous (énergie)", group="Fatigue", lo=0, hi=1, step=0.05,
        help="Sous ce niveau d'énergie, ses initiatives et ses séances de travail reculent de (seuil − énergie) × "
             "recul par unité.")] = 0.35
    tired_shift_per_unit: Annotated[float, Knob(
        label="Recul par unité de fatigue", group="Fatigue", lo=0, hi=50, step=0.5,
        help="Recul (log-odds) par point d'énergie manquant sous le seuil : plus grand, fatiguée, elle ne prend "
             "presque plus la parole d'elle-même.")] = 10.0
    #: au réveil (naturel), un moment d'inertie : elle émerge avant d'aller vers les autres —
    #: rien la première demi-heure, puis une retenue qui s'efface en une demi-heure
    inertia_veto_us: Annotated[int, Knob(
        label="Au réveil : rien pendant", group="Réveil", lo=0, hi=3 * HOUR,
        help="Après un réveil naturel, ni initiative ni séance de travail pendant cette durée — sauf une raison "
             "assez forte pour passer la barre de réveil (un rappel urgent).")] = 30 * 60 * 1_000_000
    inertia_us: Annotated[int, Knob(
        label="Au réveil : retenue pendant", group="Réveil", lo=0, hi=3 * HOUR,
        help="Ensuite, une retenue qui s'efface linéairement sur cette durée.")] = 30 * 60 * 1_000_000
    inertia_shift: Annotated[float, Knob(
        label="Au réveil : retenue initiale", group="Réveil", lo=-20, hi=0, step=0.5,
        help="Le recul (log-odds) au début de cette retenue.")] = -6.0
    #: qui la réveille la nuit
    woken_by: Annotated[tuple[str, ...], Knob(
        label="La nuit, réveillée par", group="Réveil",
        help="Les proximités dont un message privé la réveille la nuit (« friend », « close ») ; les autres "
             "attendent son réveil — sauf quelque chose d'urgent, qui la réveille toujours.")] = \
        (social_c.FRIEND, social_c.CLOSE)
    #: ses nuits : ce qu'elle en sait au réveil (« bien dormi ? »)
    usual_night_hours: Annotated[float, Knob(
        label="Une nuit ordinaire (heures)", group="Ses nuits", lo=4, hi=12, step=0.25,
        help="Ce qu'elle dort d'habitude, tant qu'elle n'a pas encore trois nuits derrière elle ; ensuite, une nuit "
             "se juge contre la médiane de ses dernières nuits.")] = 7.75
    short_night_ratio: Annotated[float, Knob(
        label="Nuit courte sous (part d'une nuit ordinaire)", group="Ses nuits", lo=0.5, hi=1, step=0.05,
        help="Une nuit plus courte que cette part de ses nuits d'habitude est « un peu courte » : elle le sait au "
             "réveil, et peut le dire si on lui demande si elle a bien dormi.")] = 0.9
    late_hours: Annotated[float, Knob(
        label="Couchée tard : endormie … heures après son seuil", group="Ses nuits", lo=0.25, hi=6, step=0.25,
        help="Endormie au moins tant d'heures après le moment où elle se serait endormie seule (une conversation "
             "l'a tenue éveillée), elle sait au réveil qu'elle a veillé tard.")] = 1.0


def derive(t: Temperament, overrides: Mapping[str, Any] | None = None) -> BodyParams:
    return BodyParams(shift_minutes=round((t.chronotype - 0.5) * 240), **dict(overrides or {}))


@dataclass(frozen=True, slots=True)
class Waiting:
    """Un message arrivé pendant sa nuit, qui attend son réveil."""

    message: int
    at: int
    handle: str


@dataclass(frozen=True, slots=True)
class Night:
    """Une de ses nuits, de l'endormissement à son dernier réveil (``end`` nul : elle dort dedans). Tirée du
    sommeil par un message puis rendormie avant la fin de sa nuit, c'est la même nuit qui reprend : le réveil
    s'ajoute à ``rousings``, le temps passé éveillée à ``awake_us``."""

    start: int
    end: int = 0
    rousings: tuple[c.Rousing, ...] = ()
    #: endormie bien après son seuil : une conversation l'a tenue éveillée
    late: bool = False
    awake_us: int = 0


@dataclass(frozen=True, slots=True)
class BodyState:
    sleep: sl.Sleep = field(default_factory=sl.Sleep)
    #: le message qui l'a tirée du sommeil en dernier (0 : aucun), et d'où il venait
    roused_by: int = 0
    roused_handle: str = ""
    #: les messages arrivés pendant sa nuit qui ne l'ont pas réveillée, pas encore répondus
    waiting: tuple[Waiting, ...] = ()
    #: ses dernières nuits, de la plus ancienne à la plus récente
    nights: tuple[Night, ...] = ()


#: un message en attente plus vieux est oublié de la liste (la reprise le juge comme les autres)
WAITING_KEPT_US = 2 * DAY
WAITING_MAX = 64
#: les nuits gardées (une semaine), les réveils gardés par nuit
NIGHTS_KEPT = 7
ROUSINGS_MAX = 16
#: une nuit se juge contre la médiane de ses nuits d'avant dès qu'elle en a autant (avant : la nuit ordinaire)
USUAL_FROM = 3
#: ce qu'elle sait de sa nuit vaut du réveil jusqu'au milieu de sa journée — pas une excuse traînée jusqu'au soir
NIGHT_TOLD_US = 6 * HOUR
#: les issues d'épisode après lesquelles un message attend encore sa réponse (un arrêt, une
#: supplantation) ou la trouvera avec un autre (lu avec le suivant : « abstained »)
_KEPT = frozenset({"interrupted", "cancelled", "superseded", "preempted", "abstained"})

BODY = Faculty("body", state=BodyState, init=lambda p: BodyState(), params=BodyParams, derive=derive,
               state_version=3, retired_params=("pressure_drag_from", "pressure_drag"))
BODY.declare(*c.ALL, c.WAITED)


def params(p: BodyParams | None) -> BodyParams:
    return p if p is not None else BodyParams()


def night(p: BodyParams | None) -> tuple[int, int]:
    """Sa nuit, en minutes locales : du début de la phase de nuit au matin."""
    profile = rhythm(p)
    return profile.start_of(circadian.Phase.NIGHT), profile.start_of(circadian.Phase.MORNING)


def rhythm(p: BodyParams | None) -> circadian.Profile:
    shift = p.shift_minutes if p is not None else 0
    return circadian.DEFAULT.shifted(shift) if shift else circadian.DEFAULT


def night_waking(s: BodyState, now: int, p: BodyParams, tz: Any) -> bool:
    """Tirée du sommeil par un message au milieu de cette nuit-ci : elle va se
    rendormir. Un réveil d'une nuit passée (un message à 6 h 40, puis debout
    toute la journée) ne compte plus le soir venu."""
    return not s.sleep.asleep and s.sleep.woken_by_message and sl.same_night(s.sleep.since, now, tz, night(p))


def in_her_night(s: BodyState, now: int, p: BodyParams, tz: Any) -> bool:
    """Elle dort, ou n'est réveillée que le temps de répondre à qui l'a tirée du sommeil."""
    return s.sleep.asleep or night_waking(s, now, p, tz)


# ── Ce qui la réveille la nuit ────────────────────────────────────────────

#: Des mots qui disent l'urgence (repliés, sans accents ni ponctuation).
_URGENT = ("urgent", "urgence", "au secours", "a l aide", "aide moi", "aidez moi", "sos", "help",
           "c est grave", "reveille toi", "besoin de toi", "hopital", "accident", "reponds moi", "repond moi")
_NEGATIONS = frozenset({"pas", "rien", "aucune", "aucun", "jamais", "sans"})
#: Combien de mots avant l'indice peuvent le nier : « rien de super urgent », « pas du tout urgent ».
_NEGATION_REACH = 3
#: Ce qui ferme une proposition : une négation ne la traverse pas (« j'ai pas dormi, c'est urgent »).
_CLAUSE = re.compile(r"[.,;:!?\n]+")
_PUNCT = re.compile(r"[^a-z0-9]+")


def urgent(text: str) -> bool:
    """Un message qui dit l'urgence (« c'est urgent », « au secours »…) — pas
    « rien d'urgent », « sans urgence » ni « c'est pas grave »."""
    for clause in _CLAUSE.split(fold(text)):
        low = " " + _PUNCT.sub(" ", clause).strip() + " "
        for cue in _URGENT:
            for m in re.finditer(rf" {re.escape(cue)} ", low):
                before = low[: m.start()].split()[-_NEGATION_REACH:]
                if not _NEGATIONS & set(before):
                    return True
    return False


@BODY.interpret(rt.PERCEPTION_RECEIVED)
def _rouse_or_wait(s: BodyState, frame: Frame, ev: Any, ports: Any) -> list[Draft[Any]]:
    """Un message pendant sa nuit : il la réveille (une amie, une proche, en
    privé ; ou quelque chose d'urgent, d'où qu'il vienne) — ou il attend son
    réveil. Un jugement enregistré : le rejeu retombe sur le même sommeil."""
    d = ev.data
    if not d.addressed:
        return []
    p = params(frame.env.params_of("body", frame.root))
    tz = frame.env.tz_of(frame.root)
    if not in_her_night(s, ev.at, p, tz):
        return []
    person = frame.get(identity_c.PERSON(d.handle)) if is_identifiable(d.handle) else ""
    close = bool(person) and not d.room and frame.get(social_c.CLOSENESS(person)) in p.woken_by
    reason = c.URGENT if urgent(d.text.text or "") else c.CLOSE_ONE if close else ""
    if reason and is_identifiable(d.handle):
        if not s.sleep.asleep:
            return []  # déjà tirée du sommeil : elle répond
        return [c.ROUSED.draft(message=ev.seq, handle=d.handle, person=person, reason=reason)]
    return [c.WAITED.draft(message=ev.seq, handle=d.handle, person=person)]


@BODY.interpret(wakeup_c.CALLED)
def _called(s: BodyState, frame: Frame, ev: Any, ports: Any) -> list[Draft[Any]]:
    """Un réveil par API qui passe outre son rythme la tire du sommeil, comme le message d'une proche : elle
    émerge pour le traiter, puis se rendort au calme (ADR 0068). Les autres attendent son réveil (leur épisode le
    dit, pas son corps)."""
    if not ev.data.rouse or not s.sleep.asleep:
        return []
    return [c.ROUSED.draft(message=ev.seq, handle="", person="", reason=c.CALL)]


# ── Réducteurs ────────────────────────────────────────────────────────────


def _night_begins(s: BodyState, at: int, p: BodyParams, tz: Any) -> tuple[Night, ...]:
    """S'endormir ouvre une nuit — ou reprend la même : tirée du sommeil par un message, elle se rendort avant la
    fin de sa nuit (le temps passé éveillée ne compte pas comme dormi). Endormie bien après le moment où elle se
    serait endormie seule, elle a veillé tard."""
    last = s.nights[-1] if s.nights else None
    if (last is not None and s.sleep.woken_by_message and last.end == s.sleep.since
            and sl.same_night(s.sleep.since, at, tz, night(p))):
        return (*s.nights[:-1], replace(last, end=0, awake_us=last.awake_us + max(0, at - last.end)))
    late = -sl.hours_to_sleep(s.sleep, at, p.sleep, tz, p.shift_minutes) >= p.late_hours
    return (*s.nights, Night(start=at, late=late))[-NIGHTS_KEPT:]


def _night_ends(nights: tuple[Night, ...], at: int) -> tuple[Night, ...]:
    """Elle se réveille : sa nuit s'arrête là — pour de bon, ou le temps d'un message (elle la reprendra en se
    rendormant cette nuit-ci)."""
    if not nights or nights[-1].end:
        return nights
    return (*nights[:-1], replace(nights[-1], end=at))


@BODY.reducer(c.FELL_ASLEEP)
def _fell_asleep(s: BodyState, e, cx) -> BodyState:
    if s.sleep.asleep:
        return s
    p = params(cx.params)
    return replace(s, sleep=sl.fall_asleep(s.sleep, e.data.at, p.sleep, cx.tz),
                   nights=_night_begins(s, e.data.at, p, cx.tz))


@BODY.reducer(c.WOKE)
def _woke(s: BodyState, e, cx) -> BodyState:
    if not s.sleep.asleep:
        return s
    return replace(s, sleep=sl.wake(s.sleep, e.data.at, params(cx.params).sleep, cx.tz),
                   nights=_night_ends(s.nights, e.data.at))


@BODY.reducer(c.ROUSED)
def _roused(s: BodyState, e, cx) -> BodyState:
    """Un message l'a tirée du sommeil : elle émerge pour lui répondre — et sa nuit garde qui l'a réveillée."""
    current = s.sleep
    nights = s.nights
    if current.asleep:
        current = sl.wake(current, e.at, params(cx.params).sleep, cx.tz, by_message=True)
        nights = _night_ends(nights, e.at)
        if nights:
            d = e.data
            last = nights[-1]
            rousing = c.Rousing(at=e.at, handle=d.handle, person=d.person, reason=d.reason)
            nights = (*nights[:-1], replace(last, rousings=(*last.rousings, rousing)[-ROUSINGS_MAX:]))
    return replace(s, sleep=replace(current, active_at=e.at), roused_by=e.data.message,
                   roused_handle=e.data.handle, nights=nights)


@BODY.reducer(c.WAITED)
def _waited(s: BodyState, e, cx) -> BodyState:
    kept = tuple(w for w in s.waiting if e.at - w.at < WAITING_KEPT_US and w.message != e.data.message)
    return replace(s, waiting=(*kept, Waiting(e.data.message, e.at, e.data.handle))[-WAITING_MAX:])


@BODY.reducer(rt.PERCEPTION_RECEIVED)
def _perceived(s: BodyState, e, cx) -> BodyState:
    """Un message adressé la tient éveillée — en journée. La nuit, c'est son
    réveil (``body.roused``) qui en décide, jamais le message seul."""
    d = e.data
    if not d.addressed or not is_identifiable(d.handle) or s.sleep.asleep:
        return s
    if night_waking(s, e.at, params(cx.params), cx.tz):
        return s
    return replace(s, sleep=replace(s.sleep, active_at=e.at))


@BODY.reducer(rt.UTTERANCE)
def _uttered(s: BodyState, e, cx) -> BodyState:
    """Parler la tient éveillée ; parler en dormant (une raison assez forte pour
    passer la barre de réveil) la réveille — elle se rendormira ensuite. Une
    réponse à quelqu'un règle les messages de lui qui attendaient son réveil
    (un rappel qu'elle lui dit, non : ce n'est pas lui répondre)."""
    d = e.data
    if not d.visible:
        return s
    current = s.sleep
    if current.asleep:
        current = sl.wake(current, e.at, params(cx.params).sleep, cx.tz, by_message=True)
        s = replace(s, roused_by=0, roused_handle="", nights=_night_ends(s.nights, e.at))
    answered = d.target if d.target and d.reply_to is not None else None
    waiting = tuple(w for w in s.waiting if w.handle != answered) if answered else s.waiting
    return replace(s, sleep=replace(current, active_at=e.at), waiting=waiting)


@BODY.reducer(rt.EPISODE_ENDED)
def _ended(s: BodyState, e, cx) -> BodyState:
    """Une question abandonnée (trop tard, en panne) ne l'attend plus. Une
    question lue avec la suivante reste jusqu'à la réponse, qui sait qu'elles
    sont arrivées pendant qu'elle dormait."""
    d = e.data
    if d.reply_to is None or d.outcome in _KEPT or not any(w.message == d.reply_to for w in s.waiting):
        return s
    return replace(s, waiting=tuple(w for w in s.waiting if w.message != d.reply_to))


# ── Faits ─────────────────────────────────────────────────────────────────


def energy(s: BodyState, now: int, p: BodyParams, tz: Any) -> float:
    """La vigilance de l'heure, moins la somnolence : celle-ci ne vient qu'à
    l'approche du moment où elle s'endormirait (``drowsy_hours``), et
    continue de creuser si on la tient éveillée au-delà."""
    base = circadian.energy(to_local(now, tz), rhythm(p))
    if s.sleep.asleep:
        return round(max(0.0, base * (1.0 - p.drowsy_depth)), 4)
    left = sl.hours_to_sleep(s.sleep, now, p.sleep, tz, p.shift_minutes)
    drowsy = 0.0 if math.isinf(left) else max(0.0, 1.0 - left / p.drowsy_hours)
    value = base * (1.0 - p.drowsy_depth * min(1.0, drowsy)) - p.overtired_slope * max(0.0, -left)
    if night_waking(s, now, p, tz):
        value = min(value, p.night_waking_energy)
    return round(max(0.0, min(1.0, value)), 4)


@BODY.fact(c.RHYTHM)
def _rhythm(s: BodyState, cx) -> circadian.Profile:
    return rhythm(cx.params)


@BODY.fact(c.PHASE)
def _phase(s: BodyState, cx) -> circadian.Phase:
    return circadian.phase_of(cx.local(), rhythm(cx.params))


@BODY.fact(c.ENERGY)
def _energy(s: BodyState, cx) -> float:
    return energy(s, cx.now, params(cx.params), cx.tz)


@BODY.fact(c.SLEEP)
def _sleep(s: BodyState, cx) -> c.SleepPhase:
    return sl.phase(s.sleep, cx.now, params(cx.params).sleep)


@BODY.fact(c.AWAKE_SINCE)
def _awake_since(s: BodyState, cx) -> int:
    return 0 if s.sleep.asleep else s.sleep.since


@BODY.fact(c.ASLEEP_SINCE)
def _asleep_since(s: BodyState, cx) -> int:
    return s.sleep.since if s.sleep.asleep else 0


@BODY.fact(c.EPOCH)
def _epoch(s: BodyState, cx) -> tuple[Any, ...]:
    return (s.sleep.asleep, s.sleep.since, s.sleep.active_at)


@BODY.fact(c.NIGHT_WAKING)
def _night_waking(s: BodyState, cx) -> bool:
    return night_waking(s, cx.now, params(cx.params), cx.tz)


@BODY.fact(c.REPLY_WAIT)
def _reply_wait(s: BodyState, cx, message: int) -> int | None:
    """La réponse à ce message attend-elle son réveil ? ``0`` tant qu'elle est
    dans sa nuit ; ensuite, l'instant d'où elle est due (son réveil)."""
    w = next((w for w in s.waiting if w.message == message), None)
    if w is None:
        return None
    if s.sleep.asleep:
        return 0
    p = params(cx.params)
    if night_waking(s, cx.now, p, cx.tz) and w.handle != s.roused_handle:
        return 0  # tirée du sommeil par quelqu'un d'autre : elle ne répond qu'à lui
    return max(w.at, s.sleep.since)


def _slept(n: Night) -> int:
    """Ce qu'elle a vraiment dormi cette nuit-là : sans les moments où un message l'a tenue éveillée."""
    return max(0, n.end - n.start - n.awake_us)


def last_night(s: BodyState, now: int, p: BodyParams, tz: Any) -> c.NightReading | None:
    """Sa dernière nuit, une fois finie, jusqu'au milieu de sa journée (``NIGHT_TOLD_US`` après son réveil). Courte
    contre la médiane de ses nuits d'avant (dès qu'elle en a ``USUAL_FROM``), sinon contre une nuit ordinaire."""
    if not s.nights or in_her_night(s, now, p, tz):
        return None
    last = s.nights[-1]
    if not last.end or now - last.end >= NIGHT_TOLD_US:
        return None
    slept = _slept(last)
    before = [_slept(n) for n in s.nights[:-1] if n.end]
    usual = statistics.median(before) if len(before) >= USUAL_FROM else p.usual_night_hours * HOUR
    return c.NightReading(start=last.start, end=last.end, duration_us=slept, rousings=last.rousings,
                          short=slept < p.short_night_ratio * usual, broken=bool(last.rousings), late=last.late)


@BODY.fact(c.LAST_NIGHT)
def _last_night(s: BodyState, cx) -> c.NightReading | None:
    return last_night(s, cx.now, params(cx.params), cx.tz)


# ── Endormissement et réveil ──────────────────────────────────────────────


@BODY.process("body.sleep", wake_on=[rt.PERCEPTION_RECEIVED, rt.UTTERANCE, *c.ALL], lane="background",
              catch_up=CatchUp.ONCE, max_quantum_s=6 * 3600, priority=20)
class Rest:
    """Émet les transitions à l'instant exact du croisement ; après un arrêt,
    celles qu'elle a manquées, datées (une nuit ne se saute pas)."""

    @staticmethod
    def _from(state: BodyState, now: int) -> int:
        """Rien n'a pu changer avant son dernier état connu : après un arrêt, on
        rejoue la nuit depuis là (et non depuis le redémarrage)."""
        last = max(state.sleep.since, state.sleep.active_at)
        return last if last else now

    def __init__(self) -> None:
        self._memo: tuple[Any, int | None] | None = None

    def next_due(self, state: BodyState, frame: Frame, last_run: int | None) -> int | None:
        """Le prochain croisement : une recherche coûteuse, dont le résultat ne
        dépend que de l'état du sommeil, de son point de départ et des
        paramètres — mémorisé tant qu'ils ne changent pas."""
        p = params(frame.env.params_of("body", frame.root))
        start = self._from(state, frame.now)
        tz = frame.env.tz_of(frame.root)
        key = (state.sleep, start, p, str(tz))
        if self._memo is not None and self._memo[0] == key:
            return self._memo[1]
        due = sl.next_transition(state.sleep, start, p.sleep, tz, p.shift_minutes, night(p))
        self._memo = (key, due)
        return due

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        p = params(frame.env.params_of("body", frame.root))
        tz = frame.env.tz_of(frame.root)
        steps = sl.transitions(ctx.state.sleep, self._from(ctx.state, frame.now), ctx.now, p.sleep, tz,
                               p.shift_minutes, night=night(p))
        if not steps:
            return
        drafts = [(c.WOKE if kind == "woke" else c.FELL_ASLEEP).draft(at=at, pressure=round(after.pressure, 4))
                  for kind, at, after in steps]
        # si un message la réveille entre-temps, ces transitions ne valent plus
        await ctx.emit(*drafts, guard=Guard("sommeil", reads=(c.EPOCH,)))


@BODY.effect(c.FELL_ASLEEP)
async def _asleep_shown(ev: Any, ports: Mapping[str, Any]) -> None:
    await _show(ev, ports)


@BODY.effect(c.WOKE)
async def _awake_shown(ev: Any, ports: Mapping[str, Any]) -> None:
    await _show(ev, ports)


@BODY.effect(c.ROUSED)
async def _roused_shown(ev: Any, ports: Mapping[str, Any]) -> None:
    await _show(ev, ports)


async def _show(ev: Any, ports: Mapping[str, Any]) -> None:
    """Le visage s'endort ou s'éveille : les clients reçoivent l'état (sans parole)."""
    port = ports.get("delivery")
    if port is None:
        return
    frame: Frame = ports["frame"]()
    await port.deliver(Delivery(
        key=ev.id, target=None, channel=None, room=None, text="", persona="inner",
        emotion=EmotionView("neutral", 0.0), message_id=ev.seq, sleep_phase=frame.get(c.SLEEP).value,
        local_hour=frame.local().hour, kind="state"))


# ── Arbitrage ─────────────────────────────────────────────────────────────


@BODY.modulate(kinds=[Kind.INITIATIVE, Kind.STEP, Kind.TASK, Kind.WORK, Kind.WAKE],
               reads=[c.SLEEP, c.ENERGY, c.AWAKE_SINCE])
def _night(s: BodyState, frame: Frame, row: RowView) -> Modulation:
    """Elle ne prend pas la parole ni ne travaille en dormant ; tirée du
    sommeil en pleine nuit, pas davantage (elle va se rendormir) ; juste
    réveillée le matin, pas encore ; fatiguée, plus rarement. Une raison qui
    passe à elle seule la barre de réveil (un rappel urgent) passe outre."""
    if row.strongest >= c.WAKE_BAR:
        return Modulation()
    return gate(s, frame)


def gate(s: BodyState, frame: Frame) -> Modulation:
    """Ce que son corps fait à une raison ordinaire à l'instant (sous la barre
    de réveil) : le veto ou le décalage."""
    if frame.get(c.SLEEP) is not c.SleepPhase.AWAKE:
        return Modulation(veto=c.ASLEEP)
    p = params(frame.env.params_of("body", frame.root))
    if night_waking(s, frame.now, p, frame.env.tz_of(frame.root)):
        return Modulation(veto=c.WOKEN_AT_NIGHT)
    shift = 0.0
    since = frame.get(c.AWAKE_SINCE)
    if since and not s.sleep.woken_by_message:
        awake_for = frame.now - since
        if awake_for < p.inertia_veto_us:
            return Modulation(veto=c.WAKING)
        if awake_for < p.inertia_veto_us + p.inertia_us:
            shift += p.inertia_shift * (1.0 - (awake_for - p.inertia_veto_us) / p.inertia_us)
    e = frame.get(c.ENERGY)
    if e < p.tired_below:
        shift -= (p.tired_below - e) * p.tired_shift_per_unit
    return Modulation(shift=shift) if shift else Modulation()


# ── Prompt ────────────────────────────────────────────────────────────────

#: tant de minutes après avoir été tirée du sommeil, elle émerge encore
WAKING_WINDOW_US = 20 * MINUTE


def _minutes(n: int) -> str:
    if n < 1:
        return phrase("body.rhythm.an_instant")
    return phrase("body.rhythm.minutes", n=n) if n > 1 else phrase("body.rhythm.minute", n=n)


def _woke_line(s: BodyState, frame: Frame) -> str:
    """Ce que son sommeil fait à cette réponse-ci : dite une fois, au bon tour."""
    ep = frame.episode
    if ep is None or ep.kind not in CONVERSATIONAL:
        return ""
    if s.sleep.asleep:
        return phrase("body.rhythm.asleep")
    reply_to = ep.attrs.get("reply_to") if ep.kind == Kind.REPLY else None
    if reply_to is not None:
        if reply_to == s.roused_by and s.sleep.woken_by_message:
            return phrase("body.rhythm.roused")
        held = [w for w in s.waiting if w.handle == ep.target]
        if any(w.message == reply_to for w in held):
            first = frame.local(min(w.at for w in held))
            when = phrase("body.rhythm.around", hour=first.hour, minute=f"{first.minute:02d}")
            if len(held) > 1:
                return phrase("body.rhythm.waited_many", when=when)
            return phrase("body.rhythm.waited_one", when=when)
    if s.sleep.woken_by_message and frame.now - s.sleep.since < WAKING_WINDOW_US:
        ago = _minutes(int((frame.now - s.sleep.since) // MINUTE))
        # un réveil par API la tire du sommeil sans adresse (``roused_by`` : l'appel) ; parler en dormant, lui,
        # efface les deux — ce n'est pas un appel qui l'a réveillée
        who = phrase("body.rhythm.by_their_message") if s.roused_handle and s.roused_handle == ep.target else \
            phrase("body.rhythm.by_api") if not s.roused_handle and s.roused_by else phrase("body.rhythm.by_a_message")
        return phrase("body.rhythm.emerging", who=who, ago=ago)
    return ""


#: éveillée au moins autant au milieu de sa nuit avant de se rendormir, elle a mis du temps à retrouver le sommeil
LONG_AWAKE_US = 45 * MINUTE


def _around(at: int, frame: Frame) -> str:
    """« vers 3 h » : l'heure ronde la plus proche, comme on la dit au réveil."""
    dt = frame.local(at)
    hour = (dt.hour + (dt.minute >= 30)) % 24
    return phrase("body.rhythm.night.midnight") if hour == 0 else phrase("body.rhythm.night.around", hour=hour)


def _night_line(s: BodyState, frame: Frame) -> str:
    """Comment s'est passée sa nuit, dit comme un ressenti, du réveil jusqu'au milieu de sa journée : à « bien
    dormi ? », elle répond vrai. « Son message » seulement à qui l'a réveillée, en tête-à-tête ; à toute autre
    personne, « un message » — jamais le nom d'un tiers. Juste tirée du sommeil, la ligne du réveil le dit déjà."""
    ep = frame.episode
    if ep is None or ep.kind not in CONVERSATIONAL:
        return ""
    if s.sleep.woken_by_message and frame.now - s.sleep.since < WAKING_WINDOW_US:
        return ""
    reading: c.NightReading | None = frame.get(c.LAST_NIGHT)
    if reading is None:
        return ""
    private = frame.audience is not None and not frame.audience.public
    person = frame.get(identity_c.PERSON(ep.target)) if private and ep.target and is_identifiable(ep.target) else ""

    def theirs(r: c.Rousing) -> bool:
        return private and bool(ep.target) and (r.handle == ep.target or bool(person) and r.person == person)

    parts = []
    if len(reading.rousings) == 1:
        r = reading.rousings[0]
        who = phrase("body.rhythm.night.by_their_message") if theirs(r) else \
            phrase("body.rhythm.night.by_api") if r.reason == c.CALL else phrase("body.rhythm.night.by_a_message")
        parts.append(phrase("body.rhythm.night.roused_once", who=who, when=_around(r.at, frame)))
    elif reading.rousings:
        mine = next((r for r in reading.rousings if theirs(r)), None)
        parts.append(phrase("body.rhythm.night.roused_many") if mine is None else
                     phrase("body.rhythm.night.roused_many_theirs", when=_around(mine.at, frame)))
    if parts and reading.end - reading.start - reading.duration_us >= LONG_AWAKE_US:
        parts[-1] += ", " + phrase("body.rhythm.night.slow_to_sleep")
    if reading.late:
        parts.append(phrase("body.rhythm.night.late_and_short") if reading.short else
                     phrase("body.rhythm.night.late"))
    elif reading.short:
        parts.append(phrase("body.rhythm.night.short"))
    return ". ".join(parts) + "." if parts else phrase("body.rhythm.night.slept_well")


@BODY.section("rhythm", zone=Zone.VOLATILE, episodes=[*CONVERSATIONAL, Kind.STEP, Kind.WORK, Kind.WAKE],
              trim_rank=40, title=phrase("body.rhythm.title"))
def _rhythm_section(s: BodyState, frame: Frame, enrich: Any) -> str:
    profile = frame.get(c.RHYTHM)
    text = circadian.describe(frame.local(), profile, frame.get(c.ENERGY))
    lines = [line for line in (_woke_line(s, frame), _night_line(s, frame)) if line]
    return " ".join((text, *lines))


#: le brouillard de la fatigue : sous tant d'énergie, sa phrase (``body.fog.…`` dans sa voix)
FOG = (
    (0.12, "falling_asleep"),
    (0.2, "very_tired"),
    (0.3, "tired"),
)


def fog(energy: float) -> str | None:
    """Ce que la fatigue fait à sa façon de parler, à ce niveau d'énergie (``None`` : rien)."""
    for limit, key in FOG:
        if energy < limit:
            return phrase(f"body.fog.{key}")
    return None


@BODY.section("fog", zone=Zone.VOLATILE, episodes=[*CONVERSATIONAL, Kind.STEP, Kind.WORK, Kind.WAKE],
              after=["rhythm"],
              trim_rank=45, tags=[Tag.AFFECTIVE], title=phrase("body.fog.title"), reads=[c.ENERGY])
def _fog(s: BodyState, frame: Frame, enrich: Any) -> str | None:
    return fog(frame.get(c.ENERGY))


# ── Inspection ────────────────────────────────────────────────────────────

from mika.faculties.body import inspect as _inspect  # noqa: E402,F401 — contributions : ses vues

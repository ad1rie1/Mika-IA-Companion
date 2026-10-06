"""Le sommeil, en fonctions pures : pression, seuils, croisements, phases.

**Pression** S : pendant la veille, elle monte vers 1 (constante ``tau_wake``) ;
pendant le sommeil, elle retombe vers 0 (``tau_sleep``). Forme close à tout
instant depuis la dernière transition.

**Seuils** : haut (s'endormir) et bas (se réveiller), modulés par un cosinus
circadien dont le maximum est l'après-midi (décalé par le chronotype), et
par une petite **gigue** tirée de la date (rejouable) : on ne s'endort pas à
la minute près chaque soir. Avec les valeurs par défaut, sans personne pour
la tenir éveillée, elle s'endort vers 23 h et se réveille vers 7 h, l'un et
l'autre à une demi-heure près (un écart type d'environ 20 min).

**Croisements** : trouvés exactement (balayage par pas de 5 min puis
bissection à la seconde), jamais à la cadence d'une boucle. On ne s'endort
pas en pleine conversation : pas avant un quart d'heure de calme.

**Phases** : des cycles de 90 min — sommeil léger, profond (long en début de
nuit), paradoxal (long en fin de nuit).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from mika.contracts import body as c
from mika.kernel.clock import HOUR, MINUTE, US, local, next_local
from mika.kernel.codec import h64
from mika.kernel.forms import Knob

SECOND = US
STEP = 5 * MINUTE
HORIZON = 48 * HOUR


class SleepParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tau_wake_h: Annotated[float, Knob(
        label="Montée de la pression (veille)", lo=2, hi=48,
        help="Constante de temps de la montée de la pression de sommeil pendant la veille : plus courte, elle "
             "s'endort plus tôt.")] = 18.2
    tau_sleep_h: Annotated[float, Knob(
        label="Descente de la pression (sommeil)", lo=0.5, hi=24,
        help="Constante de temps de sa descente pendant le sommeil : plus courte, la nuit est plus courte.")] = 4.2
    upper: Annotated[float, Knob(
        label="Seuil d'endormissement", lo=0, hi=1, step=0.01,
        help="Elle s'endort quand la pression dépasse ce seuil (modulé par le cosinus circadien). La pression "
             "tend vers 1 sans l'atteindre : trop près de 1, elle ne s'endort plus.")] = 0.66
    lower: Annotated[float, Knob(
        label="Seuil de réveil", lo=0, hi=1, step=0.01,
        help="Elle se réveille quand la pression retombe sous ce seuil (modulé par le cosinus circadien).")] = 0.17
    amplitude: Annotated[float, Knob(
        label="Amplitude circadienne des seuils", lo=0, hi=0.5, step=0.01,
        help="De combien les deux seuils montent et descendent au fil de la journée.")] = 0.10
    acrophase_h: Annotated[float, Knob(
        label="Heure du pic des seuils", lo=0, hi=24,
        help="L'heure locale (avant décalage du rythme) où les seuils culminent : c'est l'après-midi qu'il lui "
             "est le plus dur de s'endormir.")] = 16.0
    jitter: Annotated[float, Knob(
        label="Variation d'une nuit à l'autre", lo=0, hi=0.1, step=0.005,
        help="Les deux seuils bougent chaque nuit d'au plus autant (un tirage dérivé de la date : le rejeu "
             "retombe sur les mêmes nuits). 0,02 : elle s'endort et se réveille à une demi-heure près ; "
             "0 : à la minute près, chaque soir.")] = 0.02
    #: pas d'endormissement moins d'un quart d'heure après la dernière interaction
    settle_us: Annotated[int, Knob(
        label="Calme avant de s'endormir", lo=0, hi=2 * HOUR,
        help="Pas d'endormissement moins de ce délai après la dernière interaction ; réveillée par un message "
             "en pleine nuit, elle se rendort après ce calme.")] = 15 * MINUTE
    cycle_us: Annotated[int, Knob(
        label="Durée d'un cycle", lo=30 * MINUTE, hi=3 * HOUR,
        help="Un cycle de sommeil : léger, profond (long en début de nuit), paradoxal.")] = 90 * MINUTE
    light_us: Annotated[int, Knob(
        label="Sommeil léger en début de cycle", lo=0, hi=HOUR,
        help="La durée du sommeil léger au début de chaque cycle.")] = 15 * MINUTE
    #: fraction de pression au réveil d'une nuit normale (point de départ sans historique)
    morning_pressure: Annotated[float, Knob(
        label="Pression au réveil (sans historique)", lo=0, hi=1, step=0.01,
        help="La pression supposée à 7 h, au réveil d'une nuit normale : point de départ tant qu'aucun "
             "endormissement ni réveil n'a été observé.")] = 0.2


@dataclass(frozen=True, slots=True)
class Sleep:
    asleep: bool = False
    since: int = 0  # la dernière transition (0 : jamais observée)
    pressure: float = 0.2  # S à ``since``
    active_at: int = 0  # la dernière interaction
    woken_by_message: bool = False


def _morning(t: int, tz: ZoneInfo) -> int:
    """Le dernier 7 h local avant ``t`` (point de départ sans historique)."""
    dt = local(t, tz)
    anchor = dt.replace(hour=7, minute=0, second=0, microsecond=0)
    if anchor > dt:
        anchor -= timedelta(days=1)
    return round(anchor.timestamp() * SECOND)


def pressure(s: Sleep, t: int, p: SleepParams, tz: ZoneInfo) -> float:
    since, s0 = s.since, s.pressure
    if since == 0:
        since, s0 = _morning(t, tz), p.morning_pressure
    dt_h = max(0, t - since) / HOUR
    if s.asleep:
        return s0 * math.exp(-dt_h / p.tau_sleep_h)
    return 1.0 - (1.0 - s0) * math.exp(-dt_h / p.tau_wake_h)


def _hour(dt: datetime) -> float:
    return dt.hour + dt.minute / 60 + dt.second / 3600


def _circadian(dt: datetime, p: SleepParams, shift_minutes: int) -> float:
    return math.cos(2 * math.pi * (_hour(dt) - p.acrophase_h - shift_minutes / 60) / 24)


@lru_cache(maxsize=512)
def _draw(kind: str, day: date) -> float:
    """Un tirage dans [−1, 1] pour la nuit de ``day`` (dérivé de la date)."""
    return h64("nuit", kind, day.isoformat()) / 2**63 - 1.0


def nightly(dt: datetime, kind: str, amplitude: float) -> float:
    """La gigue d'un seuil : un tirage par jour, posé à minuit et interpolé
    jusqu'au minuit suivant — une nuit diffère de la veille, sans jamais de
    saut (un saut ferait une transition à heure ronde)."""
    if amplitude <= 0:
        return 0.0
    day = dt.date()
    a, b = _draw(kind, day), _draw(kind, day + timedelta(days=1))
    return amplitude * (a + (b - a) * _hour(dt) / 24)


def thresholds(t: int, p: SleepParams, tz: ZoneInfo, shift_minutes: int = 0) -> tuple[float, float]:
    dt = local(t, tz)
    c_ = _circadian(dt, p, shift_minutes)
    return (p.upper + p.amplitude * c_ + nightly(dt, "endormissement", p.jitter),
            p.lower + p.amplitude * c_ + nightly(dt, "réveil", p.jitter))


def hours_to_sleep(s: Sleep, t: int, p: SleepParams, tz: ZoneInfo, shift_minutes: int = 0) -> float:
    """Éveillée : dans combien d'heures elle s'endormirait si rien ne la tenait
    éveillée — négatif : elle a passé son seuil depuis autant d'heures. Une
    estimation locale (l'écart au seuil ÷ la vitesse à laquelle il se referme),
    juste à quelques minutes près, ce qui suffit à un ressenti."""
    up, _ = thresholds(t, p, tz, shift_minutes)
    value = pressure(s, t, p, tz)
    margin = up - value
    rise = (1.0 - value) / p.tau_wake_h
    phase = 2 * math.pi * (_hour(local(t, tz)) - p.acrophase_h - shift_minutes / 60) / 24
    slope = -p.amplitude * (2 * math.pi / 24) * math.sin(phase)
    closing = rise - slope
    if closing <= 0.005:
        return math.inf if margin > 0 else margin / 0.03
    return margin / closing


def _gap(s: Sleep, t: int, p: SleepParams, tz: ZoneInfo, shift: int) -> float:
    """Positif quand la transition est due."""
    up, down = thresholds(t, p, tz, shift)
    value = pressure(s, t, p, tz)
    return down - value if s.asleep else value - up


def in_night(t: int, tz: ZoneInfo, night: tuple[int, int] | None) -> bool:
    """``night`` : (début, fin) de sa nuit en minutes locales."""
    if night is None:
        return False
    dt = local(t, tz)
    minute = dt.hour * 60 + dt.minute
    start, end = night
    return minute >= start or minute < end if start > end else start <= minute < end


def _night_of(t: int, tz: ZoneInfo, night: tuple[int, int] | None) -> date | None:
    """La date du soir où commence la nuit qui contient ``t`` (``None`` : hors de sa nuit)."""
    if night is None or not in_night(t, tz, night):
        return None
    dt = local(t, tz)
    start, end = night
    if start > end and dt.hour * 60 + dt.minute < end:
        return dt.date() - timedelta(days=1)
    return dt.date()


def same_night(a: int, b: int, tz: ZoneInfo, night: tuple[int, int] | None) -> bool:
    """``a`` et ``b`` tombent-ils dans la même nuit ? Un réveil par message ne
    vaut que pour la nuit où il a eu lieu : tirée du sommeil à 6 h 40 et restée
    debout, elle n'est pas « réveillée en pleine nuit » le soir venu."""
    n = _night_of(a, tz, night)
    return n is not None and n == _night_of(b, tz, night)


def night_end(t: int, tz: ZoneInfo, night: tuple[int, int] | None) -> int | None:
    """Le matin qui clôt la nuit contenant ``t`` (``None`` : ``t`` est hors de sa nuit). Tirée du sommeil par
    un message et restée debout jusque-là, c'est son vrai réveil."""
    if night is None or not in_night(t, tz, night):
        return None
    return next_local(t, night[1] // 60, night[1] % 60, tz)


def next_transition(s: Sleep, t0: int, p: SleepParams, tz: ZoneInfo, shift: int = 0,
                    night: tuple[int, int] | None = None) -> int | None:
    """Le prochain instant ≥ ``t0`` où elle s'endort (ou se réveille).

    Réveillée par un message au milieu de sa nuit, elle se rendort après un
    quart d'heure de calme tant que c'est encore cette nuit-là — quelle que
    soit la pression (le modèle à deux processus seul la laisserait éveillée
    jusqu'au lendemain soir)."""
    start = t0
    if not s.asleep and s.active_at:
        start = max(start, s.active_at + p.settle_us)
    if not s.asleep and s.woken_by_message and same_night(s.since, start, tz, night):
        return start
    if _gap(s, start, p, tz, shift) >= 0:
        return start
    lo = start
    t = start + STEP
    while t <= start + HORIZON:
        if _gap(s, t, p, tz, shift) >= 0:
            hi = t
            while hi - lo > SECOND:
                mid = (lo + hi) // 2
                if _gap(s, mid, p, tz, shift) >= 0:
                    hi = mid
                else:
                    lo = mid
            return hi
        lo = t
        t += STEP
    return None


def fall_asleep(s: Sleep, at: int, p: SleepParams, tz: ZoneInfo) -> Sleep:
    return replace(s, asleep=True, since=at, pressure=pressure(s, at, p, tz), woken_by_message=False)


def wake(s: Sleep, at: int, p: SleepParams, tz: ZoneInfo, *, by_message: bool = False) -> Sleep:
    return replace(s, asleep=False, since=at, pressure=pressure(s, at, p, tz), woken_by_message=by_message)


def phase(s: Sleep, t: int, p: SleepParams) -> c.SleepPhase:
    if not s.asleep:
        return c.SleepPhase.AWAKE
    elapsed = max(0, t - s.since)
    k, pos = divmod(elapsed, p.cycle_us)
    if pos < p.light_us:
        return c.SleepPhase.LIGHT_SLEEP
    deep = max(10 * MINUTE, 55 * MINUTE - k * 12 * MINUTE)  # le profond raccourcit au fil de la nuit
    if pos < p.light_us + deep:
        return c.SleepPhase.DEEP_SLEEP
    return c.SleepPhase.REM


def transitions(s: Sleep, t0: int, until: int, p: SleepParams, tz: ZoneInfo, shift: int = 0,
                limit: int = 8, night: tuple[int, int] | None = None) -> list[tuple[str, int, Sleep]]:
    """Toutes les transitions de ``]t0, until]`` (un rattrapage après un arrêt)."""
    out: list[tuple[str, int, Sleep]] = []
    cursor = t0
    for _ in range(limit):
        at = next_transition(s, cursor, p, tz, shift, night)
        if at is None or at > until:
            break
        s = wake(s, at, p, tz) if s.asleep else fall_asleep(s, at, p, tz)
        out.append(("woke" if not s.asleep else "fell_asleep", at, s))
        cursor = at + SECOND
    return out

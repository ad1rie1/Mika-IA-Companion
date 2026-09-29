"""Le sommeil, en fonctions pures : pression, seuils, croisements, phases.

**Pression** S : pendant la veille, elle monte vers 1 (constante ``tau_wake``) ;
pendant le sommeil, elle retombe vers 0 (``tau_sleep``). Forme close à tout
instant depuis la dernière transition.

**Seuils** : haut (s'endormir) et bas (se réveiller), modulés par un cosinus
circadien dont le maximum est l'après-midi (décalé par le chronotype). Avec
les valeurs par défaut, sans personne pour la tenir éveillée, elle s'endort
vers 23 h et se réveille vers 7 h.

**Croisements** : trouvés exactement (balayage par pas de 5 min puis
bissection à la seconde), jamais à la cadence d'une boucle. On ne s'endort
pas en pleine conversation : pas avant un quart d'heure de calme.

**Phases** : des cycles de 90 min — sommeil léger, profond (long en début de
nuit), paradoxal (long en fin de nuit).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from mika.contracts import body as c
from mika.kernel.clock import HOUR, MINUTE, US, local
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


def _circadian(t: int, p: SleepParams, tz: ZoneInfo, shift_minutes: int) -> float:
    dt = local(t, tz)
    hour = dt.hour + dt.minute / 60 + dt.second / 3600
    return math.cos(2 * math.pi * (hour - p.acrophase_h - shift_minutes / 60) / 24)


def thresholds(t: int, p: SleepParams, tz: ZoneInfo, shift_minutes: int = 0) -> tuple[float, float]:
    c_ = _circadian(t, p, tz, shift_minutes)
    return p.upper + p.amplitude * c_, p.lower + p.amplitude * c_


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


def next_transition(s: Sleep, t0: int, p: SleepParams, tz: ZoneInfo, shift: int = 0,
                    night: tuple[int, int] | None = None) -> int | None:
    """Le prochain instant ≥ ``t0`` où elle s'endort (ou se réveille).

    Réveillée par un message au milieu de sa nuit, elle se rendort après un
    quart d'heure de calme tant que c'est encore la nuit — quelle que soit
    la pression (le modèle à deux processus seul la laisserait éveillée
    jusqu'au lendemain soir)."""
    start = t0
    if not s.asleep and s.active_at:
        start = max(start, s.active_at + p.settle_us)
    if not s.asleep and s.woken_by_message and in_night(start, tz, night):
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

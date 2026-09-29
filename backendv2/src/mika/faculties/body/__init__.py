"""``body`` : le rythme circadien, l'énergie, le sommeil.

- le rythme (profil décalé par le chronotype), la phase et l'énergie à
  l'instant — l'énergie baisse aussi avec la pression de sommeil ;
- le sommeil (``sleep``) : endormissement et réveil au croisement exact des
  seuils, cycles de 90 min ; un message la réveille ; on ne s'endort pas en
  pleine conversation ;
- elle ne prend pas la parole en dormant, et moins quand elle est fatiguée ;
- ses sections : son rythme (et « ce message t'a réveillée »), et le
  brouillard de la fatigue.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import body as c
from mika.contracts import runtime as rt
from mika.faculties.body import sleep as sl
from mika.kernel.arbitration import Modulation, RowView
from mika.kernel.clock import MINUTE
from mika.kernel.clock import local as to_local
from mika.kernel.faculty import CatchUp, Faculty, Zone
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.ports.delivery import Delivery, EmotionView
from mika.vocab import circadian
from mika.vocab.episodes import CONVERSATIONAL, Kind, Tag
from mika.vocab.people import is_identifiable
from mika.vocab.temperament import Temperament


class BodyParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Décalage du rythme, en minutes (chronotype : ±2 h autour du profil type).
    shift_minutes: int = 0
    sleep: sl.SleepParams = sl.SleepParams()
    #: ce que la pression de sommeil retire à l'énergie au-delà de ce seuil
    pressure_drag_from: float = 0.55
    pressure_drag: float = 0.8
    #: fatigue : sous ce niveau d'énergie, prendre la parole d'elle-même se fait plus rare
    tired_below: float = 0.35
    tired_shift_per_unit: float = 10.0
    #: au réveil (naturel), un moment d'inertie : elle émerge avant d'aller vers les autres —
    #: rien la première demi-heure, puis une retenue qui s'efface en une demi-heure
    inertia_veto_us: int = 30 * 60 * 1_000_000
    inertia_us: int = 30 * 60 * 1_000_000
    inertia_shift: float = -6.0


def derive(t: Temperament, overrides: Mapping[str, Any] | None = None) -> BodyParams:
    return BodyParams(shift_minutes=round((t.chronotype - 0.5) * 240), **dict(overrides or {}))


@dataclass(frozen=True, slots=True)
class BodyState:
    sleep: sl.Sleep = field(default_factory=sl.Sleep)


BODY = Faculty("body", state=BodyState, init=lambda p: BodyState(), params=BodyParams, derive=derive)
BODY.declare(*c.ALL)


def params(p: BodyParams | None) -> BodyParams:
    return p if p is not None else BodyParams()


def night(p: BodyParams | None) -> tuple[int, int]:
    """Sa nuit, en minutes locales : du début de la phase de nuit au matin."""
    profile = rhythm(p)
    return profile.start_of(circadian.Phase.NIGHT), profile.start_of(circadian.Phase.MORNING)


def rhythm(p: BodyParams | None) -> circadian.Profile:
    shift = p.shift_minutes if p is not None else 0
    return circadian.DEFAULT.shifted(shift) if shift else circadian.DEFAULT


# ── Réducteurs ────────────────────────────────────────────────────────────


@BODY.reducer(c.FELL_ASLEEP)
def _fell_asleep(s: BodyState, e, cx) -> BodyState:
    if s.sleep.asleep:
        return s
    return replace(s, sleep=sl.fall_asleep(s.sleep, e.data.at, params(cx.params).sleep, cx.tz))


@BODY.reducer(c.WOKE)
def _woke(s: BodyState, e, cx) -> BodyState:
    if not s.sleep.asleep:
        return s
    return replace(s, sleep=sl.wake(s.sleep, e.data.at, params(cx.params).sleep, cx.tz))


@BODY.reducer(rt.PERCEPTION_RECEIVED)
def _perceived(s: BodyState, e, cx) -> BodyState:
    """Un message qu'on lui adresse la réveille ; tout message adressé la tient éveillée."""
    d = e.data
    if not d.addressed or not is_identifiable(d.handle):
        return s
    current = s.sleep
    if current.asleep:
        current = sl.wake(current, e.at, params(cx.params).sleep, cx.tz, by_message=True)
    return replace(s, sleep=replace(current, active_at=e.at))


@BODY.reducer(rt.UTTERANCE)
def _uttered(s: BodyState, e, cx) -> BodyState:
    """Parler la tient éveillée ; parler en dormant (une raison assez forte pour
    passer la barre de réveil) la réveille — elle se rendormira ensuite."""
    if not e.data.visible:
        return s
    current = s.sleep
    if current.asleep:
        current = sl.wake(current, e.at, params(cx.params).sleep, cx.tz, by_message=True)
    return replace(s, sleep=replace(current, active_at=e.at))


# ── Faits ─────────────────────────────────────────────────────────────────


def energy(s: BodyState, now: int, p: BodyParams, tz: Any) -> float:
    base = circadian.energy(to_local(now, tz), rhythm(p))
    drag = max(0.0, sl.pressure(s.sleep, now, p.sleep, tz) - p.pressure_drag_from) * p.pressure_drag
    return max(0.0, min(1.0, base - drag))


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


@BODY.modulate(kinds=[Kind.INITIATIVE, Kind.STEP], reads=[c.SLEEP, c.ENERGY, c.AWAKE_SINCE])
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
    if s.sleep.woken_by_message and sl.in_night(frame.now, frame.env.tz_of(frame.root), night(p)):
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


@BODY.section("rhythm", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=40, title="TON RYTHME")
def _rhythm_section(s: BodyState, frame: Frame, enrich: Any) -> str:
    profile = frame.get(c.RHYTHM)
    text = circadian.describe(frame.local(), profile, frame.get(c.ENERGY))
    if s.sleep.woken_by_message and frame.now - s.sleep.since < 20 * MINUTE:
        text += " Tu dormais : ce message vient de te réveiller."
    return text


FOG = (
    (0.12, "Tu tombes de sommeil : tu as du mal à suivre, tes réponses sont très courtes, tu peux le dire."),
    (0.2, "Tu es très fatiguée : phrases courtes, pas d'élan pour les longues discussions."),
    (0.3, "Tu es fatiguée : tu restes gentille mais tu vas à l'essentiel."),
)


@BODY.section("fog", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["rhythm"], trim_rank=45,
              tags=[Tag.AFFECTIVE], title="ÉTAT COGNITIF", reads=[c.ENERGY])
def _fog(s: BodyState, frame: Frame, enrich: Any) -> str | None:
    e = frame.get(c.ENERGY)
    for limit, text in FOG:
        if e < limit:
            return text
    return None


# ── Inspection ────────────────────────────────────────────────────────────

from mika.faculties.body import inspect as _inspect  # noqa: E402,F401 — contributions : ses vues

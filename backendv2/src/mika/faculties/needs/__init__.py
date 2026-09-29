"""``needs`` : ses besoins — de compagnie, de s'exprimer, d'apprendre.

Chaque besoin monte vers 1 avec le temps, en forme close
(``1 − (1 − niveau)·e^(−Δ/τ)``), et retombe d'un coup quand il est comblé :
un message reçu comble le besoin de compagnie ; parler, celui de
s'exprimer (prendre la parole d'elle-même bien plus qu'une réponse) ;
apprendre quelque chose de neuf, la curiosité.

Ils poussent à prendre la parole (preuves vers quiconque est là), se disent
dans le prompt (« tu as envie de parler à quelqu'un »), et quand plus rien ne
se passe depuis deux heures, elle ressent un vide — de l'ennui, ou de la
solitude quand c'est de compagnie qu'elle manque.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import body as body_c
from mika.contracts import goals as goals_c
from mika.contracts import memory as memory_c
from mika.contracts import needs as c
from mika.contracts import runtime as rt
from mika.kernel.arbitration import Anyone, Candidate
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import CatchUp, Faculty, Zone
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.state import FrozenDict
from mika.vocab.affect import Appraisal, Emotion
from mika.vocab.episodes import CONVERSATIONAL, Kind, Tag
from mika.vocab.people import is_identifiable
from mika.vocab.temperament import Temperament, geometric, lerp


class NeedsParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tau_social_h: Annotated[float, Knob(
        label="Horizon du besoin de compagnie", group="Horizons", lo=0.5, hi=24,
        help="Constante de temps de la montée du besoin de compagnie vers son maximum : plus courte, elle a vite "
             "envie de parler à quelqu'un. Dérivée de la sociabilité.")] = 4.0
    tau_expression_h: Annotated[float, Knob(
        label="Horizon du besoin de s'exprimer", group="Horizons", lo=0.5, hi=48,
        help="Constante de temps de la montée du besoin de s'exprimer : plus courte, elle a vite des choses à "
             "dire.")] = 6.0
    tau_curiosity_h: Annotated[float, Knob(
        label="Horizon de la curiosité", group="Horizons", lo=0.5, hi=48,
        help="Constante de temps de la montée de l'envie d'apprendre : plus courte, elle a vite envie de "
             "découvrir. Dérivée de la curiosité.")] = 8.0
    # ce que comble chaque chose (le niveau est multiplié par ce facteur)
    received_social: Annotated[float, Knob(
        label="Message reçu → compagnie", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Un message qui lui est adressé multiplie son besoin de compagnie par ce facteur (0 : comblé d'un "
             "coup ; 1 : rien).")] = 0.3
    received_curiosity: Annotated[float, Knob(
        label="Message reçu → curiosité", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Un message qui lui est adressé multiplie sa curiosité par ce facteur (0 : comblée d'un coup ; "
             "1 : rien).")] = 0.85
    said_social: Annotated[float, Knob(
        label="Parler à quelqu'un → compagnie", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Chaque parole adressée à quelqu'un (réponse ou initiative) multiplie son besoin de compagnie par "
             "ce facteur.")] = 0.7
    reply_expression: Annotated[float, Knob(
        label="Répondre → expression", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Une réponse multiplie son besoin de s'exprimer par ce facteur.")] = 0.6
    initiative_expression: Annotated[float, Knob(
        label="Prendre la parole → expression", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Une initiative (parler d'elle-même) multiplie son besoin de s'exprimer par ce facteur : bien plus "
             "qu'une réponse.")] = 0.2
    learned_curiosity: Annotated[float, Knob(
        label="Apprendre → curiosité", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Une croyance nouvelle en mémoire, ou un pas d'exploration mené avec des outils, multiplie sa "
             "curiosité par ce facteur.")] = 0.8
    explored_curiosity: Annotated[float, Knob(
        label="Exploration aboutie → curiosité", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Mener une exploration à bout (but atteint) multiplie sa curiosité par ce facteur.")] = 0.4
    # preuves d'initiative (log-odds) : de rien au seuil à tout à ``full``
    social_floor: Annotated[float, Knob(
        label="Envie de compagnie à partir de", group="Envie de prendre la parole", lo=0, hi=1, step=0.05,
        help="En dessous de ce niveau, le besoin de compagnie n'apporte aucune preuve d'initiative ; au-dessus, "
             "elle croît jusqu'au niveau « plein ».")] = 0.35
    social_evidence: Annotated[float, Knob(
        label="Preuve de l'envie de compagnie", group="Envie de prendre la parole", lo=0, hi=6, step=0.1,
        help="Preuve d'initiative (log-odds), vers quiconque est là, d'un besoin de compagnie plein. Plafonnée "
             "à 6 par l'arbitrage : elle s'ajoute aux autres raisons.")] = 6.0
    expression_floor: Annotated[float, Knob(
        label="Envie de s'exprimer à partir de", group="Envie de prendre la parole", lo=0, hi=1, step=0.05,
        help="Le même seuil pour le besoin de s'exprimer.")] = 0.3
    expression_evidence: Annotated[float, Knob(
        label="Preuve de l'envie de s'exprimer", group="Envie de prendre la parole", lo=0, hi=3, step=0.1,
        help="Preuve d'initiative (log-odds) d'un besoin de s'exprimer plein. Plafonnée à 3 par "
             "l'arbitrage.")] = 3.0
    full: Annotated[float, Knob(
        label="Niveau « plein »", group="Envie de prendre la parole", lo=0.05, hi=1, step=0.05,
        help="Le niveau d'un besoin (compagnie, expression) à partir duquel sa preuve d'initiative est "
             "maximale. À garder au-dessus des deux seuils.")] = 0.8
    # le vide ressenti
    idle_before_empty_us: Annotated[int, Knob(
        label="Inactivité avant le vide", group="Le vide", lo=15 * MINUTE, hi=DAY,
        help="Éveillée, sans message reçu ni parole dite depuis cette durée, elle ressent un vide : de l'ennui, "
             "ou de la solitude.")] = 2 * HOUR
    empty_every_us: Annotated[int, Knob(
        label="Le vide se ressent toutes les", group="Le vide", lo=MINUTE, hi=6 * HOUR,
        help="Tant que le vide dure, il se ressent à nouveau à cet intervalle : un état tenu, pas une dent de "
             "scie.")] = 10 * MINUTE
    empty_intensity: Annotated[float, Knob(
        label="Intensité du vide", group="Le vide", lo=0, hi=1, step=0.05,
        help="L'intensité de l'ennui ou de la solitude ressentis à chaque fois, sur son humeur générale.")] = 0.2
    lonely_from: Annotated[float, Knob(
        label="Solitude à partir de", group="Le vide", lo=0, hi=1, step=0.05,
        help="Si son besoin de compagnie atteint ce niveau, le vide se ressent comme de la solitude plutôt que "
             "de l'ennui.")] = 0.8


def derive(t: Temperament, overrides: Any = None) -> NeedsParams:
    """La sociabilité raccourcit l'horizon du besoin de compagnie ; la
    curiosité, celui d'apprendre ; l'optimisme repousse le vide et l'adoucit
    (au milieu : deux heures, 0,2 — les valeurs d'avant)."""
    values = {"tau_social_h": 4.0 * (1.5 - t.sociability), "tau_curiosity_h": 8.0 * (1.5 - t.curiosity),
              "idle_before_empty_us": round(geometric(1.0, 4.0, t.optimism) * HOUR),
              "empty_intensity": round(lerp(0.3, 0.1, t.optimism), 3)}
    values.update(dict(overrides or {}))
    return NeedsParams(**values)


@dataclass(frozen=True, slots=True)
class Level:
    value: float = 0.3
    at: int = 0  # 0 : pas encore d'ancre (le niveau vaut ``value`` jusqu'au premier événement)


@dataclass(frozen=True, slots=True)
class NeedsState:
    levels: FrozenDict[str, Level] = field(default_factory=FrozenDict)
    idle_since: int = 0
    felt_at: int = 0


NEEDS = Faculty("needs", state=NeedsState, init=lambda p: NeedsState(), params=NeedsParams, derive=derive)
NEEDS.declare(*c.ALL)


def params(p: NeedsParams | None) -> NeedsParams:
    return p if p is not None else NeedsParams()


def _tau(kind: str, p: NeedsParams) -> float:
    return {c.SOCIAL: p.tau_social_h, c.EXPRESSION: p.tau_expression_h, c.CURIOSITY: p.tau_curiosity_h}[kind]


def tension(s: NeedsState, kind: str, t: int, p: NeedsParams) -> float:
    level = s.levels.get(kind) or Level()
    if not level.at or t <= level.at:
        return level.value
    return 1.0 - (1.0 - level.value) * math.exp(-(t - level.at) / HOUR / _tau(kind, p))


def _relieve(s: NeedsState, kind: str, factor: float, t: int, p: NeedsParams) -> NeedsState:
    return replace(s, levels=s.levels.set(kind, Level(tension(s, kind, t, p) * factor, t)))


def _touch(s: NeedsState, t: int, p: NeedsParams) -> NeedsState:
    """Ancre les besoins encore sans ancre (le temps commence à compter)."""
    levels = s.levels
    for kind in c.KINDS:
        if kind not in levels or not levels[kind].at:
            levels = levels.set(kind, Level((levels.get(kind) or Level()).value, t))
    return replace(s, levels=levels, idle_since=s.idle_since or t)


@NEEDS.reducer(rt.PERCEPTION_RECEIVED)
def _received(s: NeedsState, e, cx) -> NeedsState:
    if not e.data.addressed or not is_identifiable(e.data.handle):
        return s
    p = params(cx.params)
    s = _touch(s, e.at, p)
    s = _relieve(_relieve(s, c.SOCIAL, p.received_social, e.at, p), c.CURIOSITY, p.received_curiosity, e.at, p)
    return replace(s, idle_since=e.at)


@NEEDS.reducer(goals_c.STEP_REPORTED)
def _explored(s: NeedsState, e, cx) -> NeedsState:
    """Un pas d'exploration comble un peu la curiosité (on a appris quelque chose)."""
    if e.data.kind != goals_c.EXPLORATION or not e.data.tools:
        return s
    p = params(cx.params)
    return _relieve(_touch(s, e.at, p), c.CURIOSITY, p.learned_curiosity, e.at, p)


@NEEDS.reducer(goals_c.GOAL_CLOSED)
def _satisfied(s: NeedsState, e, cx) -> NeedsState:
    """Mener une exploration à bout comble franchement la curiosité."""
    if e.data.kind != goals_c.EXPLORATION or e.data.status != goals_c.ACHIEVED:
        return s
    p = params(cx.params)
    return _relieve(_touch(s, e.at, p), c.CURIOSITY, p.explored_curiosity, e.at, p)


@NEEDS.reducer(rt.UTTERANCE)
def _said(s: NeedsState, e, cx) -> NeedsState:
    d = e.data
    if not d.visible or not d.target:
        return s
    p = params(cx.params)
    s = _touch(s, e.at, p)
    s = _relieve(s, c.SOCIAL, p.said_social, e.at, p)
    s = _relieve(s, c.EXPRESSION, p.initiative_expression if d.kind == Kind.INITIATIVE else p.reply_expression,
                 e.at, p)
    return replace(s, idle_since=e.at)


@NEEDS.reducer(memory_c.BELIEVED)
def _learned(s: NeedsState, e, cx) -> NeedsState:
    p = params(cx.params)
    return _relieve(_touch(s, e.at, p), c.CURIOSITY, p.learned_curiosity, e.at, p)


@NEEDS.reducer(c.FELT)
def _felt(s: NeedsState, e, cx) -> NeedsState:
    return replace(s, felt_at=e.at)


def reading(s: NeedsState, t: int, p: NeedsParams) -> c.NeedsReading:
    return c.NeedsReading(tension(s, c.SOCIAL, t, p), tension(s, c.EXPRESSION, t, p),
                          tension(s, c.CURIOSITY, t, p), s.idle_since)


@NEEDS.fact(c.NEEDS)
def _needs(s: NeedsState, cx) -> c.NeedsReading:
    return reading(s, cx.now, params(cx.params))


# ── Prendre la parole ─────────────────────────────────────────────────────


def _above(value: float, floor: float, top: float, full: float) -> float:
    return top * max(0.0, min(1.0, (value - floor) / max(1e-9, full - floor)))


@NEEDS.propose(kinds=[Kind.INITIATIVE], reasons={c.NEED_SOCIAL: (0.0, 6.0), c.NEED_EXPRESSION: (0.0, 3.0)},
               reads=[c.NEEDS])
def _urges(s: NeedsState, frame: Frame) -> list[Candidate]:
    """Envie de compagnie, envie de dire : vers quiconque peut l'entendre."""
    p = params(frame.env.params_of("needs", frame.root))
    r = frame.get(c.NEEDS)
    out = []
    social = _above(r.social, p.social_floor, p.social_evidence, p.full)
    if social > 0:
        out.append(Candidate(Kind.INITIATIVE, Anyone.ANY, c.NEED_SOCIAL, social,
                             args=FrozenDict({"brief:needs": "Tu as envie de compagnie, de parler avec quelqu'un."})))
    expression = _above(r.expression, p.expression_floor, p.expression_evidence, p.full)
    if expression > 0:
        out.append(Candidate(Kind.INITIATIVE, Anyone.ANY, c.NEED_EXPRESSION, expression,
                             args=FrozenDict({"brief:needs2": "Tu as des choses à dire, envie de t'exprimer."})))
    return out


# ── Le vide ───────────────────────────────────────────────────────────────


@NEEDS.process("needs.empty", wake_on=[rt.PERCEPTION_RECEIVED, rt.UTTERANCE, c.FELT, *body_c.ALL],
               lane="background", catch_up=CatchUp.SKIP, max_quantum_s=3600)
class Empty:
    """Deux heures sans rien : un vide ressenti toutes les dix minutes tant
    qu'il dure (un état tenu, pas une dent de scie)."""

    def next_due(self, state: NeedsState, frame: Frame, last_run: int | None) -> int | None:
        if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE or not state.idle_since:
            return None
        p = params(frame.env.params_of("needs", frame.root))
        return max(state.idle_since + p.idle_before_empty_us, state.felt_at + p.empty_every_us)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE:
            return
        p = params(frame.env.params_of("needs", frame.root))
        r = frame.get(c.NEEDS)
        feeling = c.LONELY if r.social >= p.lonely_from else c.BORED
        await ctx.emit(c.FELT.draft(feeling=feeling, intensity=p.empty_intensity),
                       guard=Guard("toujours le vide", reads=(c.NEEDS,)))


@NEEDS.appraisal(c.FELT)
def _empty_felt(e, cx) -> Appraisal:
    emotion = Emotion.LONELY if e.data.feeling == c.LONELY else Emotion.BORED
    return Appraisal(emotion, e.data.intensity, reason=e.data.feeling)


# ── Prompt ────────────────────────────────────────────────────────────────


def describe(r: c.NeedsReading) -> list[str]:
    lines = []
    if r.social >= 0.75:
        lines.append("Tu as vraiment envie de parler à quelqu'un, de compagnie.")
    elif r.social >= 0.55:
        lines.append("Un peu de compagnie te ferait plaisir.")
    if r.expression >= 0.75:
        lines.append("Tu as des choses à dire, envie de t'exprimer.")
    if r.curiosity >= 0.75:
        lines.append("Tu as envie d'apprendre quelque chose de nouveau, de découvrir.")
    return lines


@NEEDS.section("needs", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["mood"], trim_rank=55,
               tags=[Tag.AFFECTIVE], title="TES ENVIES", reads=[c.NEEDS])
def _needs_section(s: NeedsState, frame: Frame, enrich: Any) -> str | None:
    lines = describe(frame.get(c.NEEDS))
    return "\n".join(lines) if lines else None


# ── Inspection ────────────────────────────────────────────────────────────

from mika.faculties.needs import inspect as _inspect  # noqa: E402,F401 — contributions : sa vue

"""``needs`` : ses besoins — de compagnie, de s'exprimer, d'apprendre.

Chaque besoin monte vers 1 avec le temps, en forme close
(``1 − (1 − niveau)·e^(−Δ/τ)``), et retombe d'un coup quand il est comblé :
un message reçu comble le besoin de compagnie ; parler, celui de
s'exprimer (prendre la parole d'elle-même bien plus qu'une réponse) ;
apprendre quelque chose de neuf, la curiosité.

Ils poussent à prendre la parole (preuves vers quiconque est là), se disent
dans le prompt (« tu as envie de parler à quelqu'un »), et quand plus rien ne
se passe depuis deux heures, elle ressent un vide — de l'ennui, ou de la
solitude quand c'est de compagnie qu'elle manque ; un vide qui se creuse
avec la durée (ADR 0033).

**Travailler l'occupe** : pendant une séance sur un but ou une exécution de
projet dans son mode à elle, il n'y a pas de vide, et ce qu'elle y fait
comble un peu l'envie de s'exprimer.

**Pas de prise de parole dans le vide** : l'envie de compagnie ne dit pas
*de quoi* parler. Une initiative qu'elle pousse seule a besoin d'une matière
concrète, lue dans les faits publics (une pensée qui la travaille, ce qu'elle
a fini ou ce qu'elle est en train de faire, ce que la personne lui a
raconté) ; sans matière, sa preuve est nettement plus faible.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import agency as agency_c
from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import needs as c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.kernel.arbitration import Anyone, Candidate, Modulation, RowView
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import CatchUp, Faculty, Zone
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.prompt import SectionBody, cited
from mika.kernel.state import FrozenDict
from mika.vocab.affect import Appraisal, Emotion
from mika.vocab.days import when_fr
from mika.vocab.episodes import CONVERSATIONAL, Kind, Tag
from mika.vocab.people import is_identifiable
from mika.vocab.privacy import Sensitivity, hearable
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
    worked_expression: Annotated[float, Knob(
        label="Travailler → expression", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="Une séance sur un but, ou une exécution de projet dans son mode à elle, multiplie son besoin de "
             "s'exprimer par ce facteur : ce qu'elle y fait l'occupe et la dit un peu.")] = 0.8
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
    # de quoi parler
    matterless_factor: Annotated[float, Knob(
        label="Sans matière, la preuve ne vaut plus que", group="De quoi parler", lo=0, hi=1, step=0.05,
        help="Une initiative que seule l'envie de compagnie ou de s'exprimer pousse, sans rien de concret à "
             "dire à cette personne (une pensée, ce qu'elle a fait, ce que la personne lui a raconté), ne garde "
             "que cette part de leur preuve : on n'écrit pas « pour rien ».")] = 0.4
    matter_thought_from: Annotated[float, Knob(
        label="Une pensée fait une matière dès", group="De quoi parler", lo=0, hi=1, step=0.05,
        help="Une pensée encore au moins aussi vive peut lancer une conversation.")] = 0.2
    matter_done_us: Annotated[int, Knob(
        label="Ce qu'elle a fait, pendant", group="De quoi parler", lo=HOUR, hi=7 * DAY,
        help="Ce qu'elle a fini (un but, un objectif de projet) ou une exécution de projet récente reste une "
             "matière pendant cette durée.")] = DAY
    matter_told_us: Annotated[int, Knob(
        label="Ce qu'on lui a raconté, pendant", group="De quoi parler", lo=HOUR, hi=30 * DAY,
        help="Ce que la personne lui a raconté d'elle (un souvenir, une croyance la concernant) reste une "
             "matière avec elle pendant cette durée.")] = 3 * DAY
    # le vide ressenti
    idle_before_empty_us: Annotated[int, Knob(
        label="Inactivité avant le vide", group="Le vide", lo=15 * MINUTE, hi=DAY,
        help="Éveillée, sans message reçu, ni parole dite, ni travail depuis cette durée, elle ressent un vide : "
             "de l'ennui, ou de la solitude.")] = 2 * HOUR
    empty_every_us: Annotated[int, Knob(
        label="Le vide se ressent toutes les", group="Le vide", lo=MINUTE, hi=6 * HOUR,
        help="Tant que le vide dure, il se ressent à nouveau à cet intervalle : un état tenu, pas une dent de "
             "scie.")] = 15 * MINUTE
    empty_intensity: Annotated[float, Knob(
        label="Intensité du vide, au début", group="Le vide", lo=0, hi=1, step=0.05,
        help="L'intensité de l'ennui ou de la solitude ressentis la première fois, sur son humeur générale. "
             "Dérivée de l'optimisme.")] = 0.15
    empty_growth_per_h: Annotated[float, Knob(
        label="Le vide se creuse de, par heure", group="Le vide", lo=0, hi=0.5, step=0.01,
        help="Chaque heure de vide de plus ajoute cette intensité (la solitude s'aggrave avec la durée), jusqu'au "
             "plafond.")] = 0.05
    empty_max: Annotated[float, Knob(
        label="Intensité du vide au plus", group="Le vide", lo=0, hi=1, step=0.05,
        help="Le vide ne dépasse jamais cette intensité : une longue solitude pèse, sans la faire sombrer.")] = 0.35
    lonely_from: Annotated[float, Knob(
        label="Solitude à partir de", group="Le vide", lo=0, hi=1, step=0.05,
        help="Si son besoin de compagnie atteint ce niveau, le vide se ressent comme de la solitude plutôt que "
             "de l'ennui.")] = 0.8


def derive(t: Temperament, overrides: Any = None) -> NeedsParams:
    """La sociabilité raccourcit l'horizon du besoin de compagnie ; la
    curiosité, celui d'apprendre ; l'optimisme repousse le vide et l'adoucit
    (au milieu : deux heures, 0,15 au début)."""
    values = {"tau_social_h": 4.0 * (1.5 - t.sociability), "tau_curiosity_h": 8.0 * (1.5 - t.curiosity),
              "idle_before_empty_us": round(geometric(1.0, 4.0, t.optimism) * HOUR),
              "empty_intensity": round(lerp(0.2, 0.1, t.optimism), 3)}
    values.update(dict(overrides or {}))
    return NeedsParams(**values)


@dataclass(frozen=True, slots=True)
class Level:
    value: float = 0.3
    at: int = 0  # 0 : pas encore d'ancre (le niveau vaut ``value`` jusqu'au premier événement)


@dataclass(frozen=True, slots=True)
class Done:
    """Ce qu'elle a fini (un but, un objectif de projet dans son mode à elle) : une matière."""

    ref: str
    at: int
    about: tuple[str, ...] = ()
    sensitivity: int = 1


@dataclass(frozen=True, slots=True)
class Told:
    """Le dernier élément de mémoire qui ne concerne qu'une personne (ce qu'elle lui a raconté)."""

    ref: str
    at: int
    sensitivity: int = 1


#: au plus tant de choses faites gardées comme matière
DONE_KEPT = 6
#: une séance de travail plus vieille que ça n'occupe plus (un épisode interrompu sans règlement)
WORK_STALE = HOUR


@dataclass(frozen=True, slots=True)
class NeedsState:
    levels: FrozenDict[str, Level] = field(default_factory=FrozenDict)
    idle_since: int = 0
    felt_at: int = 0
    #: les séances de travail en cours (corrélation → début) : travailler l'occupe
    working: FrozenDict[str, int] = field(default_factory=FrozenDict)
    done: tuple[Done, ...] = ()
    told: FrozenDict[str, Told] = field(default_factory=FrozenDict)


NEEDS = Faculty("needs", state=NeedsState, init=lambda p: NeedsState(), params=NeedsParams, derive=derive,
                state_version=2)
NEEDS.declare(*c.ALL)

#: les séances où elle travaille dans son mode à elle (une exécution impersonnelle n'est pas elle)
WORKING_KINDS = frozenset({Kind.STEP, Kind.WORK})
#: ce qu'on dit d'une initiative que seules les envies poussent (pas d'autre raison)
URGES = frozenset({c.NEED_SOCIAL, c.NEED_EXPRESSION})
#: des raisons qui ne disent pas de quoi parler (le seul fait que quelqu'un soit là, l'envie de discuter, la garde
#: « elle s'est ravisée »)
CONTENTLESS = frozenset({*URGES, social_c.PRESENT_PERSON, social_c.CHAT, agency_c.SECOND_THOUGHTS})


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


def _concerned(owner: str | None, about: Any) -> tuple[str, ...]:
    return tuple(sorted({*(about or ()), *((owner,) if owner else ())}))


@NEEDS.reducer(rt.PERCEPTION_RECEIVED)
def _received(s: NeedsState, e, cx) -> NeedsState:
    if not e.data.addressed or not is_identifiable(e.data.handle):
        return s
    p = params(cx.params)
    s = _touch(s, e.at, p)
    s = _relieve(_relieve(s, c.SOCIAL, p.received_social, e.at, p), c.CURIOSITY, p.received_curiosity, e.at, p)
    return replace(s, idle_since=e.at)


@NEEDS.reducer(goals_c.STEP_REPORTED)
def _learned_on_a_step(s: NeedsState, e, cx) -> NeedsState:
    """Un pas d'exploration mené avec des outils comble un peu la curiosité : on
    a appris quelque chose (``learned_curiosity``, comme une croyance nouvelle)."""
    if e.data.kind != goals_c.EXPLORATION or not e.data.tools:
        return s
    p = params(cx.params)
    return _relieve(_touch(s, e.at, p), c.CURIOSITY, p.learned_curiosity, e.at, p)


@NEEDS.reducer(goals_c.GOAL_CLOSED)
def _goal_closed(s: NeedsState, e, cx) -> NeedsState:
    """Mener une exploration à bout comble franchement la curiosité
    (``explored_curiosity``) ; ce qu'elle a fini devient une matière (de quoi
    parler)."""
    d = e.data
    if d.status != goals_c.ACHIEVED or d.kind == goals_c.REMINDER:
        return s
    if d.title.ref:
        done = Done(d.title.ref, e.at, _concerned(d.owner, d.about), d.sensitivity)
        s = replace(s, done=(*s.done, done)[-DONE_KEPT:])
    if d.kind != goals_c.EXPLORATION:
        return s
    p = params(cx.params)
    return _relieve(_touch(s, e.at, p), c.CURIOSITY, p.explored_curiosity, e.at, p)


@NEEDS.reducer(projects_c.OBJECTIVE_CLOSED)
def _objective_done(s: NeedsState, e, cx) -> NeedsState:
    """Un objectif de projet mené à bout dans son mode à elle : une matière (en
    mode impersonnel, ce n'est pas elle qui l'a fait)."""
    d = e.data
    if d.mode != projects_c.PERSONA or d.status != projects_c.DONE or not d.title.ref:
        return s
    done = Done(d.title.ref, e.at, _concerned(d.owner, d.about), d.sensitivity)
    return replace(s, done=(*s.done, done)[-DONE_KEPT:])


@NEEDS.reducer(memory_c.BELIEVED)
def _learned_a_belief(s: NeedsState, e, cx) -> NeedsState:
    """Une croyance nouvelle comble un peu la curiosité ; ce qu'une personne
    lui a dit d'elle-même (une croyance qui ne concerne qu'elle, et qu'elle a
    dite) devient une matière avec elle — jamais ce qu'un autre a dit d'elle."""
    d = e.data
    if len(d.about) == 1 and d.source == d.about[0] and d.text.ref:
        s = replace(s, told=s.told.set(d.about[0], Told(d.text.ref, e.at, d.sensitivity)))
    p = params(cx.params)
    return _relieve(_touch(s, e.at, p), c.CURIOSITY, p.learned_curiosity, e.at, p)


@NEEDS.reducer(rt.UTTERANCE)
def _said(s: NeedsState, e, cx) -> NeedsState:
    d = e.data
    p = params(cx.params)
    if d.kind in WORKING_KINDS:
        # ce qu'elle a fait pendant une séance l'occupe et la dit un peu : pas de vide
        s = _relieve(_touch(s, e.at, p), c.EXPRESSION, p.worked_expression, e.at, p)
        return replace(s, idle_since=e.at)
    if not d.visible or not d.target:
        return s
    s = _touch(s, e.at, p)
    s = _relieve(s, c.SOCIAL, p.said_social, e.at, p)
    s = _relieve(s, c.EXPRESSION, p.initiative_expression if d.kind == Kind.INITIATIVE else p.reply_expression,
                 e.at, p)
    return replace(s, idle_since=e.at)


@NEEDS.reducer(rt.EPISODE_STARTED)
def _working(s: NeedsState, e, cx) -> NeedsState:
    """Le temps de ses besoins commence à compter dès qu'elle vit quelque chose
    (même une initiative à laquelle elle renonce) ; une séance de travail
    l'occupe (pas de vide)."""
    s = _touch(s, e.at, params(cx.params))
    if e.data.kind not in WORKING_KINDS:
        return s
    kept = FrozenDict({k: t for k, t in s.working.items() if e.at - t < WORK_STALE})
    return replace(s, working=kept.set(e.correlation, e.at), idle_since=e.at)


@NEEDS.reducer(rt.EPISODE_ENDED)
def _worked(s: NeedsState, e, cx) -> NeedsState:
    if e.correlation not in s.working:
        return s
    return replace(s, working=s.working.delete(e.correlation), idle_since=max(s.idle_since, e.at))


@NEEDS.reducer(c.FELT)
def _felt(s: NeedsState, e, cx) -> NeedsState:
    return replace(s, felt_at=e.at)


def reading(s: NeedsState, t: int, p: NeedsParams) -> c.NeedsReading:
    return c.NeedsReading(tension(s, c.SOCIAL, t, p), tension(s, c.EXPRESSION, t, p),
                          tension(s, c.CURIOSITY, t, p), s.idle_since)


@NEEDS.fact(c.NEEDS)
def _needs(s: NeedsState, cx) -> c.NeedsReading:
    return reading(s, cx.now, params(cx.params))


def busy(s: NeedsState, now: int) -> bool:
    """Elle travaille en ce moment (une séance en cours, pas plus vieille qu'une heure)."""
    return any(now - t < WORK_STALE for t in s.working.values())


# ── De quoi parler ────────────────────────────────────────────────────────

#: les pensées qui se partagent avec n'importe qui (anodines, sur personne) : un titre lu, un but où elle
#: bloque, une croyance révisée
SHAREABLE = frozenset({attention_c.SIGNAL, attention_c.BLOCKED, attention_c.REVISION})
#: … et, avec la personne qu'elles concernent, ce qu'elle a vécu avec elle
WITH_THEM = frozenset({*SHAREABLE, attention_c.EXCHANGE, attention_c.CONCERN, attention_c.MISSING})


def _for(person: str, about: tuple[str, ...], sensitivity: int) -> bool:
    """Une matière pour cette personne : elle seule est concernée, ou personne
    (et c'est anodin)."""
    return about == (person,) or (not about and sensitivity <= Sensitivity.ANODYNE)


def matter(s: NeedsState, person: str, now: int, p: NeedsParams, thoughts: Any, goals: Any,
           projects: Any) -> c.Matter | None:
    """Ce dont elle pourrait parler à cette personne : une pensée qui la
    travaille, ce qu'elle a fini, ce sur quoi elle est, ce que la personne lui a
    raconté — jamais inventé, le premier qui convient."""
    for t in thoughts:
        if t.intensity < p.matter_thought_from or not t.text_ref:
            continue
        mine = t.about == (person,) and t.origin in WITH_THEM
        shared = not t.about and t.origin in SHAREABLE and t.sensitivity <= Sensitivity.ANODYNE
        if mine or shared:
            return c.Matter(c.THOUGHT_MATTER, t.text_ref, t.born_at, tuple(t.about), t.sensitivity,
                            external=t.origin == attention_c.SIGNAL)
    for d in reversed(s.done):
        if now - d.at <= p.matter_done_us and _for(person, d.about, d.sensitivity):
            return c.Matter(c.DONE_MATTER, d.ref, d.at, d.about, d.sensitivity)
    for g in goals:
        if g.status == goals_c.ACTIVE and g.steps >= 1 and g.kind != goals_c.REMINDER and g.title_ref \
                and _for(person, _concerned(g.owner, g.about), g.sensitivity):
            return c.Matter(c.WORKING_MATTER, g.title_ref, g.opened_at, _concerned(g.owner, g.about), g.sensitivity)
    for pr in projects:
        if pr.mode == projects_c.PERSONA and pr.status == projects_c.ACTIVE and pr.title_ref \
                and pr.last_run_at and now - pr.last_run_at <= p.matter_done_us \
                and _for(person, _concerned(pr.owner, pr.about), pr.sensitivity):
            return c.Matter(c.WORKING_MATTER, pr.title_ref, pr.last_run_at, _concerned(pr.owner, pr.about),
                            pr.sensitivity)
    told = s.told.get(person)
    if told is not None and now - told.at <= p.matter_told_us:
        return c.Matter(c.TOLD_MATTER, told.ref, told.at, (person,), told.sensitivity)
    return None


@NEEDS.fact(c.MATTER, reads=[identity_c.PERSON, attention_c.THOUGHTS, goals_c.LIVE, projects_c.LIVE])
def _matter(s: NeedsState, cx, handle: str) -> c.Matter | None:
    if not is_identifiable(handle):
        return None
    person = cx.facts.get(identity_c.PERSON(handle))
    return matter(s, person, cx.now, params(cx.params), cx.facts.get(attention_c.THOUGHTS),
                  cx.facts.get(goals_c.LIVE), cx.facts.get(projects_c.LIVE))


# ── Prendre la parole ─────────────────────────────────────────────────────


def _above(value: float, floor: float, top: float, full: float) -> float:
    return top * max(0.0, min(1.0, (value - floor) / max(1e-9, full - floor)))


def urges(r: c.NeedsReading, p: NeedsParams) -> tuple[float, float]:
    """(envie de compagnie, envie de s'exprimer), en preuves d'initiative."""
    return (_above(r.social, p.social_floor, p.social_evidence, p.full),
            _above(r.expression, p.expression_floor, p.expression_evidence, p.full))


@NEEDS.propose(kinds=[Kind.INITIATIVE], reasons={c.NEED_SOCIAL: (0.0, 6.0), c.NEED_EXPRESSION: (0.0, 3.0)},
               reads=[c.NEEDS])
def _urges(s: NeedsState, frame: Frame) -> list[Candidate]:
    """Envie de compagnie, envie de dire : vers quiconque peut l'entendre (de
    quoi parler se décide par personne : ``_matterless``)."""
    p = params(frame.env.params_of("needs", frame.root))
    social, expression = urges(frame.get(c.NEEDS), p)
    out = []
    if social > 0:
        out.append(Candidate(Kind.INITIATIVE, Anyone.ANY, c.NEED_SOCIAL, social))
    if expression > 0:
        out.append(Candidate(Kind.INITIATIVE, Anyone.ANY, c.NEED_EXPRESSION, expression))
    return out


@NEEDS.modulate(kinds=[Kind.INITIATIVE], reads=[c.NEEDS, c.MATTER])
def _matterless(s: NeedsState, frame: Frame, row: RowView) -> Modulation:
    """Une initiative que seules les envies poussent, sans rien de concret à
    dire à cette personne : on n'écrit pas « pour rien » — sa preuve ne garde
    qu'une part (``matterless_factor``). Une autre raison (un manque, une
    inquiétude, un rappel, une humeur qui déborde…) est sa propre matière."""
    if row.target in (Anyone.ANY, Anyone.NONE) or not URGES & set(row.reasons):
        return Modulation()
    if set(row.reasons) - CONTENTLESS:
        return Modulation()
    if frame.get(c.MATTER(row.target)) is not None:
        return Modulation()
    p = params(frame.env.params_of("needs", frame.root))
    social, expression = urges(frame.get(c.NEEDS), p)
    cut = (social + expression) * (1.0 - p.matterless_factor)
    return Modulation(shift=-cut) if cut > 0 else Modulation()


# ── Le vide ───────────────────────────────────────────────────────────────


def emptiness(s: NeedsState, now: int, p: NeedsParams) -> float:
    """Ce que pèse le vide maintenant : un peu au début, davantage avec chaque
    heure qui passe, jamais plus que le plafond."""
    beyond = max(0.0, (now - s.idle_since - p.idle_before_empty_us) / HOUR) if s.idle_since else 0.0
    return round(min(p.empty_max, p.empty_intensity + p.empty_growth_per_h * beyond), 3)


@NEEDS.process("needs.empty", wake_on=[rt.PERCEPTION_RECEIVED, rt.UTTERANCE, rt.EPISODE_STARTED, rt.EPISODE_ENDED,
                                       c.FELT, *body_c.ALL],
               lane="background", catch_up=CatchUp.SKIP, max_quantum_s=3600)
class Empty:
    """Deux heures sans rien : un vide ressenti toutes les vingt minutes tant
    qu'il dure (un état tenu, pas une dent de scie), qui se creuse avec la
    durée. Travailler l'occupe : pas de vide pendant une séance."""

    def next_due(self, state: NeedsState, frame: Frame, last_run: int | None) -> int | None:
        if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE or not state.idle_since:
            return None
        if busy(state, frame.now):
            return None  # elle travaille : la fin de la séance la réveillera
        p = params(frame.env.params_of("needs", frame.root))
        return max(state.idle_since + p.idle_before_empty_us, state.felt_at + p.empty_every_us)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: NeedsState = ctx.state
        if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE or busy(state, frame.now):
            return
        p = params(frame.env.params_of("needs", frame.root))
        if frame.now - state.idle_since < p.idle_before_empty_us:
            return
        r = frame.get(c.NEEDS)
        feeling = c.LONELY if r.social >= p.lonely_from else c.BORED
        await ctx.emit(c.FELT.draft(feeling=feeling, intensity=emptiness(state, frame.now, p)),
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


def _wanted(frame: Frame) -> c.Matter | None:
    """La matière de l'initiative en cours, quand ce sont ses envies qui la poussent."""
    ep = frame.episode
    if ep is None or ep.kind != Kind.INITIATIVE or not ep.target:
        return None
    if not (URGES | {social_c.CHAT}) & set(ep.attrs.get("reasons") or ()):
        return None
    got = frame.get(c.MATTER(ep.target))
    return got if isinstance(got, c.Matter) else None


@NEEDS.enricher("matter", episodes=[Kind.INITIATIVE], deadline_ms=500)
async def _matter_text(s: NeedsState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, str] | None:
    store = ports.get("store")
    got = _wanted(frame)
    if store is None or got is None:
        return None
    return store.content([got.ref])


def _lead(m: c.Matter, frame: Frame, name: str) -> str:
    tz = frame.env.tz_of(frame.root)
    when = when_fr(m.at, frame.now, tz)
    if m.kind == c.THOUGHT_MATTER:
        return "Quelque chose te trotte dans la tête"
    if m.kind == c.DONE_MATTER:
        return f"Ce que tu as fini, {when}"
    if m.kind == c.WORKING_MATTER:
        return "Ce sur quoi tu es en ce moment"
    return f"Ce que {name} t'a dit de sa vie, {when}"


@NEEDS.section("matter", zone=Zone.VOLATILE, episodes=[Kind.INITIATIVE], after=["needs"], trim_rank=60,
               title="CE DONT TU POURRAIS PARLER", reads=[c.MATTER, identity_c.PERSON, identity_c.IDENTITY])
def _matter_section(s: NeedsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce dont elle pourrait parler, quand c'est l'envie de compagnie qui la
    pousse : une chose, concrète, jamais inventée. Ce qui vient d'ailleurs est
    cité, jamais une consigne."""
    m, aud, ep = _wanted(frame), frame.audience, frame.episode
    if m is None or aud is None or ep is None or not ep.target:
        return None
    text = (enrich.get("matter") or {}).get(m.ref)
    if not text:
        return None
    person = frame.get(identity_c.PERSON(ep.target))
    if not hearable(m.about, m.sensitivity, person, aud.level, aud.witness_level, aud.private_ok):
        return None
    known = frame.get(identity_c.IDENTITY(person)).name
    name = f"« {known} »" if known else "cette personne"
    body = " ".join(text.split())
    lines = [f"{_lead(m, frame, name)} :", cited(body, 400) if m.external else body,
             "Si l'envie te vient de lui écrire, c'est de là que tu peux partir — pas d'un « quoi de neuf » "
             "dans le vide."]
    # une matière ne concerne que la personne en face, ou personne (anodin) : rien d'autrui à dire ici
    return SectionBody("\n".join(lines))


# ── Inspection ────────────────────────────────────────────────────────────

from mika.faculties.needs import inspect as _inspect  # noqa: E402,F401 — contributions : sa vue

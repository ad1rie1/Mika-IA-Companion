"""``needs`` : ses besoins — de compagnie, de s'exprimer, d'apprendre.

Chaque besoin monte vers 1 avec le temps, en forme close
(``1 − (1 − niveau)·e^(−Δ/τ)``), et retombe d'un coup quand il est comblé :
un message reçu comble le besoin de compagnie ; parler, celui de
s'exprimer (prendre la parole d'elle-même bien plus qu'une réponse) ;
apprendre quelque chose de neuf, la curiosité.

**La compagnie dépend de qui la donne** : un échange avec une amie ou une
proche la comble pleinement, avec une connaissance d'une part, avec une
inconnue peu, avec qui elle garde une hostilité installée presque pas — un
après-midi à se faire chahuter par un inconnu ne remplace pas une amie.

Ils poussent à prendre la parole (preuves vers quiconque est là), se disent
dans le prompt (« tu as envie de parler à quelqu'un »), et quand plus rien ne
se passe depuis deux heures, elle ressent un vide — de l'ennui, ou de la
solitude quand c'est de compagnie qu'elle manque ; un vide qui se creuse
avec la durée (ADR 0033).

**Travailler l'occupe** : pendant une séance sur un but ou une exécution de
projet dans son mode à elle, il n'y a pas de vide, et ce qu'elle y fait
comble un peu l'envie de s'exprimer.

**Retrouver quelqu'un** : après un vide ressenti, le premier message d'une
amie ou d'une proche lui fait du bien (``needs.reunited``) — une inconnue n'y
change rien de tel.

**Pas de prise de parole dans le vide** : l'envie de compagnie ne dit pas
*de quoi* parler. Une initiative qu'elle pousse seule a besoin d'une matière
concrète, lue dans les faits publics ; ce qui concerne la personne passe
d'abord (une pensée sur elle, ce qui se passe dans sa vie, ce qu'elle lui a
raconté de plus important), ses choses à elle ensuite (ce qu'elle a fini, ce
sur quoi elle est — jamais une rêverie : rien de neuf n'est arrivé). Une
matière déjà dite dans une initiative ne resert pas. Sans matière, sa preuve
est nettement plus faible.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import affect as affect_c
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
from mika.kernel.clock import DAY, HOUR, MINUTE, local
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
from mika.vocab.words import elided


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
    # qui comble la compagnie : une amie ou une proche pleinement, les autres d'une part seulement (le facteur
    # effectif est ``1 − (1 − facteur) × part``)
    acquaintance_company: Annotated[float, Knob(
        label="Compagnie d'une connaissance", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="La part de ce que comble un échange (message reçu, parole dite) quand c'est avec quelqu'un qu'elle "
             "connaît un peu. Une amie ou une proche comble pleinement.")] = 0.6
    stranger_company: Annotated[float, Knob(
        label="Compagnie d'une inconnue", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="La même part, avec quelqu'un qu'elle ne connaît pas : un après-midi avec des inconnus ne remplace "
             "pas une amie.")] = 0.3
    hostile_company: Annotated[float, Knob(
        label="Compagnie de qui elle en veut", group="Ce qui comble", lo=0, hi=1, step=0.05,
        help="La même part, au plus, avec quelqu'un envers qui elle garde une hostilité installée (seuil "
             "ci-dessous) : se faire chahuter ne tient pas compagnie.")] = 0.1
    hostile_from: Annotated[float, Knob(
        label="Hostilité qui ne tient plus compagnie", group="Ce qui comble", lo=0.05, hi=1, step=0.05,
        help="À partir de cette hostilité installée envers la personne (affect, du même ordre que le seuil de "
             "rancune), ses échanges ne comblent plus que la part ci-dessus.")] = 0.2
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
    reunited_gain: Annotated[float, Knob(
        label="Retrouver une amie après le vide", group="Le vide", lo=0, hi=2, step=0.05,
        help="Après un vide ressenti, le premier message d'une amie ou d'une proche lui fait du bien : un "
             "soulagement (après la solitude) ou de la joie (après l'ennui), d'autant plus que le vide pesait — "
             "son intensité multipliée par ce facteur. 0 : ça ne lui fait rien. Une inconnue n'y change rien de "
             "tel.")] = 0.8
    matter_moment_ahead_us: Annotated[int, Knob(
        label="Ce qui va lui arriver, dans les", group="De quoi parler", lo=0, hi=7 * DAY,
        help="Un moment de sa vie qu'une personne lui a annoncé (un entretien, un départ) devient une matière "
             "pour lui écrire (un mot d'encouragement) dans cette durée avant qu'il arrive — et jusqu'à « ce "
             "qu'on lui a raconté, pendant » après. Jamais ce qu'un tiers lui en a dit.")] = 2 * DAY


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
    """Un élément de mémoire qui ne concerne qu'une personne (ce qu'elle lui a raconté), et ce qu'il pèse."""

    ref: str
    at: int
    sensitivity: int = 1
    importance: float = 0.5


#: au plus tant de choses faites gardées comme matière
DONE_KEPT = 6
#: au plus tant de choses racontées gardées par personne (les plus importantes)
TOLD_KEPT = 4
#: au plus tant de matières déjà dites retenues (pour ne pas en reprendre une deux fois)
USED_KEPT = 64
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
    #: personne → ce qu'elle lui a raconté d'elle (les plus importants)
    told: FrozenDict[str, tuple[Told, ...]] = field(default_factory=FrozenDict)
    #: la dernière fois que quelqu'un lui a parlé, et la fois d'avant (retrouver quelqu'un après le vide)
    heard_at: int = 0
    heard_before: int = 0
    #: le dernier vide ressenti : ``BORED`` | ``LONELY``, et son intensité
    felt: str = ""
    felt_level: float = 0.0
    #: les matières déjà dites dans une initiative (référence → quand) : elles ne resservent pas
    used: FrozenDict[str, int] = field(default_factory=FrozenDict)


#: v3 : ce qu'on lui a raconté se classe par importance (plusieurs par personne), les matières déjà dites, qui lui
#: a parlé en dernier et le vide ressenti (retrouver quelqu'un) ; une rêverie n'est plus une matière.
#: v4 : la compagnie qui comble dépend de qui la donne (une règle, pas une forme : reconstruite depuis la genèse)
NEEDS = Faculty("needs", state=NeedsState, init=lambda p: NeedsState(), params=NeedsParams, derive=derive,
                state_version=4)
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


def _company(cx: Any, handle: str, p: NeedsParams) -> float:
    """La part de compagnie qu'apporte un échange avec cette adresse : pleine avec une amie ou une proche, une
    part avec une connaissance, peu avec une inconnue (une adresse jetable en est une), presque rien avec qui
    elle garde une hostilité installée — un après-midi à se faire chahuter par un inconnu ne remplace pas une
    amie, le soir."""
    if not is_identifiable(handle):
        return p.stranger_company
    person = cx.facts.get(identity_c.PERSON(handle))
    closeness = cx.facts.get(social_c.CLOSENESS(person))
    share = 1.0 if closeness in REUNITING else (
        p.acquaintance_company if closeness == social_c.ACQUAINTANCE else p.stranger_company)
    if cx.facts.get(affect_c.HOSTILITY(person)) >= p.hostile_from:
        share = min(share, p.hostile_company)
    return share


def _shared(factor: float, share: float) -> float:
    """Le facteur d'un échange qui ne comble qu'une part : ``1`` ne comble rien, ``factor`` comble tout."""
    return 1.0 - (1.0 - factor) * share


@NEEDS.reducer(rt.PERCEPTION_RECEIVED, reads=[identity_c.PERSON, social_c.CLOSENESS, affect_c.HOSTILITY])
def _received(s: NeedsState, e, cx) -> NeedsState:
    """Un message adressé : la compagnie, selon qui l'écrit ; la curiosité, de
    n'importe qui. Le vide, lui, est rompu par n'importe quel message
    (« personne ne m'a parlé » cesse d'être vrai)."""
    if not e.data.addressed or not is_identifiable(e.data.handle):
        return s
    p = params(cx.params)
    s = _touch(s, e.at, p)
    social = _shared(p.received_social, _company(cx, e.data.handle, p))
    s = _relieve(_relieve(s, c.SOCIAL, social, e.at, p), c.CURIOSITY, p.received_curiosity, e.at, p)
    return replace(s, idle_since=e.at, heard_at=e.at, heard_before=s.heard_at)


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
    # une rêverie n'est pas « ce qu'elle a fini » : rien de neuf n'est arrivé, il n'y a rien à raconter (HUM-3)
    if d.title.ref and d.reason not in goals_c.MUSINGS:
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
        person = d.about[0]
        kept = (*(t for t in s.told.get(person, ()) if t.ref != d.text.ref),
                Told(d.text.ref, e.at, d.sensitivity, round(d.importance, 4)))
        # les plus importantes, puis les plus récentes : « mon chat est malade » ne cède pas sa place à « j'ai
        # mangé des pâtes »
        kept = tuple(sorted(kept, key=lambda t: (-t.importance, -t.at, t.ref))[:TOLD_KEPT])
        s = replace(s, told=s.told.set(person, kept))
    p = params(cx.params)
    return _relieve(_touch(s, e.at, p), c.CURIOSITY, p.learned_curiosity, e.at, p)


@NEEDS.reducer(rt.UTTERANCE, reads=[identity_c.PERSON, social_c.CLOSENESS, affect_c.HOSTILITY])
def _said(s: NeedsState, e, cx) -> NeedsState:
    d = e.data
    p = params(cx.params)
    if d.kind in WORKING_KINDS:
        # ce qu'elle a fait pendant une séance l'occupe et la dit un peu : pas de vide
        s = _relieve(_touch(s, e.at, p), c.EXPRESSION, p.worked_expression, e.at, p)
        return replace(s, idle_since=e.at)
    if not d.visible or not d.target:
        return s
    if d.kind == Kind.INITIATIVE:
        # la matière qu'elle avait sous les yeux en écrivant d'elle-même : dite, elle ne resert pas
        shown = [ref[len(MATTER_PROVENANCE):] for ref in d.provenance if ref.startswith(MATTER_PROVENANCE)]
        if shown:
            used = s.used
            for ref in shown:
                used = used.set(ref, e.at)
            if len(used) > USED_KEPT:
                used = FrozenDict(sorted(used.items(), key=lambda kv: (kv[1], kv[0]))[-USED_KEPT:])
            s = replace(s, used=used)
    s = _touch(s, e.at, p)
    s = _relieve(s, c.SOCIAL, _shared(p.said_social, _company(cx, d.target, p)), e.at, p)
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


@NEEDS.reducer(body_c.WOKE)
def _woke(s: NeedsState, e, cx) -> NeedsState:
    """Le vide ne se ressent qu'éveillée : au réveil, il recommence à compter
    (la nuit n'a pas creusé de vide). ``felt_at`` ne bouge pas : un réveil n'est
    pas un vide ressenti, il ne prépare pas de retrouvailles."""
    if not s.idle_since:
        return s
    return replace(s, idle_since=max(s.idle_since, e.data.at))


@NEEDS.reducer(c.FELT)
def _felt(s: NeedsState, e, cx) -> NeedsState:
    return replace(s, felt_at=e.at, felt=e.data.feeling, felt_level=e.data.intensity)


def reading(s: NeedsState, t: int, p: NeedsParams) -> c.NeedsReading:
    return c.NeedsReading(tension(s, c.SOCIAL, t, p), tension(s, c.EXPRESSION, t, p),
                          tension(s, c.CURIOSITY, t, p), s.idle_since, s.heard_at)


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
#: la provenance d'une matière montrée dans une initiative (``matter:<référence>``) : dite, elle ne resert pas
MATTER_PROVENANCE = "matter:"


def _for(person: str, about: tuple[str, ...], sensitivity: int) -> bool:
    """Une matière pour cette personne : elle seule est concernée, ou personne
    (et c'est anodin)."""
    return about == (person,) or (not about and sensitivity <= Sensitivity.ANODYNE)


def _their_moment(m: Any, person: str, now: int, p: NeedsParams) -> bool:
    """Un moment de sa vie qu'elle lui a annoncé elle-même (jamais ce qu'un tiers en a dit : le demander
    trahirait le tiers), pas un secret, bientôt ou tout juste passé."""
    if tuple(m.about) != (person,) or m.secret or not m.text_ref or set(m.told_by) - {person}:
        return False
    if getattr(m, "followed_at", 0):
        return False  # elles en ont déjà reparlé (ce que la personne en raconte le jour même compte : ADR 0052)
    return -p.matter_moment_ahead_us <= now - m.when <= p.matter_told_us


def matter(s: NeedsState, person: str, now: int, p: NeedsParams, thoughts: Any, goals: Any,
           projects: Any, moments: Any = (), hard: bool = False) -> c.Matter | None:
    """Ce dont elle pourrait parler à cette personne — jamais inventé, jamais déjà dit dans une initiative. **Ce
    qui la concerne d'abord** : une pensée sur elle (une inquiétude, ce qu'elles ont vécu), puis **ce qui pèse le
    plus dans sa vie** parmi un moment de sa vie (bientôt, ou tout juste passé) et ce qu'elle lui a raconté — à
    poids égal, le moment (il a son heure) ; **ses choses à elle ensuite** : une pensée anodine à partager, ce
    qu'elle a fini, ce sur quoi elle est (jamais une rêverie : rien de neuf n'est arrivé). Un humain écrit à une
    amie pour elle avant d'écrire pour lui (HUM-10) — et part de ce qui pèse, pas du prochain rendez-vous banal
    (sonde réelle du 2026-10-03 : « un mot pour l'encourager » pour le dentiste, le soir où son chat était au plus
    mal). Ce qui se fête n'en est pas une (ses vœux, le jour même, sont une raison à part) ; quand quelque chose
    de grave la touche ces jours-ci (``hard``), un moment ordinaire non plus."""
    used = s.used
    live = [t for t in thoughts if t.intensity >= p.matter_thought_from and t.text_ref and t.text_ref not in used]
    for t in live:
        if t.about == (person,) and t.origin in WITH_THEM:
            return c.Matter(c.THOUGHT_MATTER, t.text_ref, t.born_at, tuple(t.about), t.sensitivity,
                            external=t.origin == attention_c.SIGNAL)
    weighed: list[tuple[tuple[float, int, int, str], c.Matter]] = []
    for m in moments:
        weight = float(getattr(m, "importance", memory_c.IMPORTANT_MOMENT))
        if getattr(m, "festive", False) or (hard and weight < memory_c.IMPORTANT_MOMENT):
            continue
        if _their_moment(m, person, now, p) and m.text_ref not in used:
            weighed.append(((-weight, 0, abs(now - m.when), m.text_ref),
                            c.Matter(c.MOMENT_MATTER, m.text_ref, m.when, (person,), m.sensitivity,
                                     ongoing=bool(getattr(m, "ongoing", False)))))
    for t in s.told.get(person, ()):
        if now - t.at <= p.matter_told_us and t.ref not in used:
            weighed.append(((-t.importance, 1, now - t.at, t.ref),
                            c.Matter(c.TOLD_MATTER, t.ref, t.at, (person,), t.sensitivity)))
    if weighed:
        return min(weighed, key=lambda w: w[0])[1]
    for t in live:
        if not t.about and t.origin in SHAREABLE and t.sensitivity <= Sensitivity.ANODYNE:
            return c.Matter(c.THOUGHT_MATTER, t.text_ref, t.born_at, (), t.sensitivity,
                            external=t.origin == attention_c.SIGNAL)
    for d in reversed(s.done):
        if now - d.at <= p.matter_done_us and _for(person, d.about, d.sensitivity) and d.ref not in used:
            return c.Matter(c.DONE_MATTER, d.ref, d.at, d.about, d.sensitivity)
    for g in goals:
        if g.status == goals_c.ACTIVE and g.steps >= 1 and g.kind != goals_c.REMINDER and g.title_ref \
                and not g.musing and g.title_ref not in used \
                and _for(person, _concerned(g.owner, g.about), g.sensitivity):
            return c.Matter(c.WORKING_MATTER, g.title_ref, g.opened_at, _concerned(g.owner, g.about), g.sensitivity)
    for pr in projects:
        if pr.mode == projects_c.PERSONA and pr.status == projects_c.ACTIVE and pr.title_ref \
                and pr.last_run_at and now - pr.last_run_at <= p.matter_done_us \
                and _for(person, _concerned(pr.owner, pr.about), pr.sensitivity):
            return c.Matter(c.WORKING_MATTER, pr.title_ref, pr.last_run_at, _concerned(pr.owner, pr.about),
                            pr.sensitivity)
    return None


@NEEDS.fact(c.MATTER, reads=[identity_c.PERSON, attention_c.THOUGHTS, goals_c.LIVE, projects_c.LIVE,
                             memory_c.LIFE_EVENTS, memory_c.HARD_TIMES])
def _matter(s: NeedsState, cx, handle: str) -> c.Matter | None:
    if not is_identifiable(handle):
        return None
    person = cx.facts.get(identity_c.PERSON(handle))
    return matter(s, person, cx.now, params(cx.params), cx.facts.get(attention_c.THOUGHTS),
                  cx.facts.get(goals_c.LIVE), cx.facts.get(projects_c.LIVE),
                  cx.facts.get(memory_c.LIFE_EVENTS(person)) or (),
                  hard=cx.facts.get(memory_c.HARD_TIMES(person)) > 0)


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


#: qui elle est contente de retrouver après le vide (une inconnue ne comble pas une solitude)
REUNITING = frozenset({social_c.FRIEND, social_c.CLOSE})


@NEEDS.interpret(rt.PERCEPTION_RECEIVED)
def _reunited(s: NeedsState, frame: Frame, ev: Any, ports: Any) -> list[Any]:
    """Le premier message d'une amie ou d'une proche après un vide ressenti (depuis que quelqu'un lui a parlé
    pour la dernière fois) : ça lui fait du bien, d'autant plus que le vide pesait. Le rendez-vous de chaque
    soir après une journée creuse, pas seulement le retour de quelqu'un qui manquait (HUM-5)."""
    d = ev.data
    if not d.addressed or not is_identifiable(d.handle) or s.heard_at != ev.at:
        return []
    if not s.felt or s.felt_at <= s.heard_before:
        return []  # pas de vide ressenti depuis la dernière fois qu'on lui a parlé
    if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE:
        return []  # un message de nuit attend son réveil : ce n'est pas un moment partagé
    person = frame.get(identity_c.PERSON(d.handle))
    if frame.get(social_c.CLOSENESS(person)) not in REUNITING:
        return []
    p = params(frame.env.params_of("needs", frame.root))
    intensity = round(min(1.0, p.reunited_gain * s.felt_level), 3)
    if intensity <= 0:
        return []
    return [c.REUNITED.draft(person=person, handle=d.handle, message=ev.seq, after=s.felt, intensity=intensity)]


@NEEDS.appraisal(c.REUNITED)
def _reunited_felt(e, cx) -> Appraisal:
    """Après la solitude, un soulagement ; après l'ennui, de la joie : sa compagnie lui fait du bien."""
    emotion = Emotion.RELIEVED if e.data.after == c.LONELY else Emotion.HAPPY
    return Appraisal(emotion, e.data.intensity, reason="compagnie")


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
    r = frame.get(c.NEEDS)
    lines = describe(r)
    if r.social >= 0.55:
        # le manque se sent dans l'envie de parler, il ne se fait pas payer à l'autre (sonde réelle du 2026-10-02 :
        # « je me sentais un peu seule cet après-midi » à qui rentre du travail, « enfin tu es là ! »)
        lines.append("Ça se sent dans ton envie de parler ; tu ne le fais pas peser sur l'autre — pas de reproche, "
                     "pas de « enfin tu es là », pas de « je me sentais seule » à qui avait sa journée.")
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


#: un jour à venir, en mots
_AHEAD = ("aujourd'hui", "demain", "après-demain")
_WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def ahead_fr(at: int, now: int, tz: Any) -> str:
    """« aujourd'hui », « demain », « jeudi » — ou, passé, « hier soir », « avant-hier »."""
    if at <= now:
        return when_fr(at, now, tz)
    days = (local(at, tz).date() - local(now, tz).date()).days
    return _AHEAD[days] if days < len(_AHEAD) else _WEEKDAYS[local(at, tz).weekday()]


def _lead(m: c.Matter, frame: Frame, name: str) -> str:
    tz = frame.env.tz_of(frame.root)
    when = when_fr(m.at, frame.now, tz)
    if m.kind == c.THOUGHT_MATTER:
        return "Quelque chose te trotte dans la tête"
    if m.kind == c.DONE_MATTER:
        return f"Ce que tu as fini, {when}"
    if m.kind == c.WORKING_MATTER:
        return "Ce sur quoi tu es en ce moment"
    if m.kind == c.MOMENT_MATTER:
        if m.ongoing:
            # une situation qui dure n'est ni « à venir » ni « passée » : elle la vit encore
            since = when[len("il y a "):] if when.startswith("il y a ") else when  # « depuis 4 jours », « depuis hier »
            return (f"Ce {elided(name, 'que')} vit en ce moment, depuis {since} — {name} te l'avait raconté (prends de "
                    "ses nouvelles)")
        if m.at > frame.now:
            return (f"Ce qui l'attend, {ahead_fr(m.at, frame.now, tz)} — {name} te l'avait annoncé (un mot pour "
                    "l'encourager, si tu veux)")
        return (f"Ce qui lui est arrivé, {ahead_fr(m.at, frame.now, tz)} — {name} te l'avait annoncé (comment ça "
                "s'est passé ?)")
    return f"Ce {elided(name, 'que')} t'a dit de sa vie, {when}"


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
    # une matière ne concerne que la personne en face, ou personne (anodin) : rien d'autrui à dire ici ; sa
    # provenance voyage dans l'énoncé (dite, elle ne resert pas)
    return SectionBody("\n".join(lines), provenance=(f"{MATTER_PROVENANCE}{m.ref}",))


# ── Inspection ────────────────────────────────────────────────────────────

from mika.faculties.needs import inspect as _inspect  # noqa: E402,F401 — contributions : sa vue

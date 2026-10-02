"""``self`` : la persona (un seul document pour toutes ses voix), le
tempérament dont les autres facultés dérivent leurs paramètres, l'estime de
soi et le récit qu'elle fait d'elle-même.

- Une persona, deux profondeurs : ``full`` (répondre, prendre la parole,
  se raconter) et ``compact`` (murmurer, travailler) — rendues depuis le
  même document, pour qu'aucune de ses voix ne soit quelqu'un d'autre. Elle
  est une IA et le sait ; elle n'en fait ni un sujet ni une excuse.
- **L'estime** est lente (entre le tempérament, fixe, et l'humeur, qui
  change en minutes) : une valeur qui revient vers 0,5 avec une demi-vie de
  trois jours, bousculée par de petits coups. Ce qu'elle mène à bout compte
  selon l'effort que ça lui a demandé (une chose faite en un pas ne vaut pas
  une semaine de travail), et pas plus que tant par jour ; ce que les autres
  lui disent d'elle compte aussi — un merci, un compliment, une insulte qui
  la vise —, selon qui le dit, et pas plus que tant par personne et par jour.
  Une initiative restée sans réponse, une promesse non tenue, un blocage
  l'abaissent. Elle ne touche jamais l'arbitrage ; elle se ressent, et le
  doute dit sa vraie cause.
- **Le récit** (« Je suis quelqu'un qui… ») est réécrit par sa propre voix au
  plus une fois par jour, quand elle a vécu assez de nouveau, à partir de
  souvenirs anodins seulement : il est montré à tout le monde.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict

from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as c
from mika.contracts import social as social_c
from mika.faculties.self import days
from mika.faculties.self.records import Deed, Dream, Effort, Journal, Knock
from mika.faculties.self.worth import touched
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.codec import digest
from mika.kernel.events import Content, Draft, VoiceProvenance
from mika.kernel.faculty import CatchUp, Faculty, Zone
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.ports.llm import LLMRequest, Message, PersonaRender
from mika.vocab.episodes import CONVERSATIONAL, Tag
from mika.vocab.people import is_identifiable
from mika.vocab.privacy import Sensitivity


class SelfParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # l'estime : elle revient vers 0,5, bousculée par de petits coups ; elle ne touche jamais l'arbitrage
    esteem_half_life_us: Annotated[int, Knob(
        label="Demi-vie de l'estime", group="L'estime", lo=6 * HOUR, hi=30 * DAY,
        help="Son estime revient vers 0,5 en perdant la moitié de son écart en ce temps. Plus court : les coups "
             "s'oublient dans la journée ; plus long : un doute s'installe.")] = 72 * HOUR
    esteem_min: Annotated[float, Knob(
        label="Estime plancher", group="L'estime", lo=0.0, hi=0.5, step=0.01,
        help="Jamais sous ce plancher, quels que soient les coups : un échec n'est pas une dépression.")] = 0.05
    esteem_max: Annotated[float, Knob(
        label="Estime plafond", group="L'estime", lo=0.5, hi=1.0, step=0.01,
        help="Jamais au-dessus de ce plafond, quels que soient les succès.")] = 0.95
    ignored_knock: Annotated[float, Knob(
        label="Initiative ignorée", group="L'estime", lo=-0.3, hi=0.0, step=0.01,
        help="Ce que coûte à son estime une initiative restée sans réponse dans le délai attendu.")] = -0.03
    heard_again_knock: Annotated[float, Knob(
        label="Réponse après des ignorées", group="L'estime", lo=0.0, hi=0.3, step=0.01,
        help="Ce que lui rend une réponse qui rompt une série d'initiatives ignorées (« je compte "
             "encore »).")] = 0.04
    achieved_base: Annotated[float, Knob(
        label="But mené à bout : au moins", group="Ce qu'elle mène à bout", lo=0.0, hi=0.1, step=0.005,
        help="Ce que lui rend un but mené à bout même sans effort (un rappel dit ne compte pas).")] = 0.01
    achieved_effort: Annotated[float, Knob(
        label="But mené à bout : selon l'effort", group="Ce qu'elle mène à bout", lo=0.0, hi=0.3, step=0.005,
        help="En plus, selon ce que ça lui a demandé (ses séances de travail) et seulement s'il est prouvé "
             "(quelque chose a réellement été produit) : au plus autant.")] = 0.04
    achieved_full_steps: Annotated[int, Knob(
        label="Effort plein à partir de (séances)", group="Ce qu'elle mène à bout", lo=1, hi=20,
        help="À partir de tant de séances de travail, l'effort compte en entier ; une chose faite en une séance "
             "n'en compte qu'une part.")] = 4
    achieved_daily_cap: Annotated[float, Knob(
        label="Ce qu'elle mène à bout : au plus par jour", group="Ce qu'elle mène à bout", lo=0.0, hi=0.3,
        step=0.01, help="Ses réussites d'une même journée ne lui rendent pas plus que ça : dix petites choses "
                        "faites ne font pas une semaine de fierté.")] = 0.06
    stuck_knock: Annotated[float, Knob(
        label="But bloqué", group="Ce qu'elle mène à bout", lo=-0.3, hi=0.0, step=0.01,
        help="Ce que lui coûte un but sur lequel elle bloque ; renoncer par manque d'envie ne coûte rien.")] = -0.04
    broken_promise_knock: Annotated[float, Knob(
        label="Promesse non tenue", group="L'estime", lo=-0.3, hi=0.0, step=0.01,
        help="Ce que lui coûte une promesse dont l'échéance passe sans qu'elle l'ait tenue.")] = -0.03
    # le sociomètre : ce que les autres lui disent d'elle
    thanked_knock: Annotated[float, Knob(
        label="Un merci ou un compliment", group="Ce qu'on lui dit d'elle", lo=0.0, hi=0.1, step=0.005,
        help="Ce que lui rend un merci ou un compliment qui la vise, venant d'une amie ou d'une proche (moins "
             "venant de quelqu'un qu'elle connaît peu).")] = 0.02
    insulted_knock: Annotated[float, Knob(
        label="Une insulte qui la vise", group="Ce qu'on lui dit d'elle", lo=-0.1, hi=0.0, step=0.005,
        help="Ce que lui coûte une insulte qui la vise (« t'es nulle ») ; une moquerie qui rit ne compte pas.")] = \
        -0.02
    social_daily_cap: Annotated[float, Knob(
        label="Par personne et par jour : au plus", group="Ce qu'on lui dit d'elle", lo=0.0, hi=0.2, step=0.01,
        help="Ce que les mots d'une même personne font à son estime dans une journée, dans un sens ou dans "
             "l'autre : un troll qui insiste ne la démolit pas, une amie qui remercie dix fois ne la gonfle "
             "pas.")] = 0.04
    acquaintance_weight: Annotated[float, Knob(
        label="Venant d'une connaissance", group="Ce qu'on lui dit d'elle", lo=0.0, hi=1.0, step=0.05,
        help="La part qui compte quand ça vient de quelqu'un qu'elle connaît un peu.")] = 0.6
    stranger_weight: Annotated[float, Knob(
        label="Venant d'une inconnue", group="Ce qu'on lui dit d'elle", lo=0.0, hi=1.0, step=0.05,
        help="La part qui compte quand ça vient de quelqu'un qu'elle ne connaît pas.")] = 0.3
    doubt_below: Annotated[float, Knob(
        label="Elle doute sous", group="L'estime", lo=0.0, hi=0.5, step=0.01,
        help="Sous ce seuil, son prompt lui dit qu'elle doute un peu d'elle-même (un ressenti, jamais un "
             "nombre).")] = 0.35
    assured_above: Annotated[float, Knob(
        label="Sûre d'elle au-dessus de", group="L'estime", lo=0.5, hi=1.0, step=0.01,
        help="Au-dessus de ce seuil, son prompt lui dit qu'elle se sent sûre d'elle, à sa place.")] = 0.7
    # le récit : « Je suis quelqu'un qui… », réécrit par sa propre voix
    narrative_every_us: Annotated[int, Knob(
        label="Réécrire le récit au plus toutes les", group="Le récit", lo=HOUR, hi=30 * DAY,
        help="Le paragraphe qu'elle écrit sur qui elle devient n'est pas réécrit plus souvent (un appel au "
             "modèle à chaque fois).")] = DAY
    narrative_min_souvenirs: Annotated[int, Knob(
        label="Souvenirs neufs pour réécrire", group="Le récit", lo=1, hi=100,
        help="Il faut avoir vécu au moins autant de nouveaux souvenirs depuis le dernier récit pour le "
             "réécrire.")] = 5
    narrative_max_souvenirs: Annotated[int, Knob(
        label="Souvenirs relus pour le récit", group="Le récit", lo=5, hi=200,
        help="Les souvenirs anodins les plus récents montrés à sa voix pour réécrire le récit (il est montré à "
             "tout le monde). Plus : un appel plus long.")] = 30
    # les rêves
    dream_chance: Annotated[float, Knob(
        label="Rêver, à chaque sommeil paradoxal", group="Les rêves", lo=0.0, hi=1.0, step=0.05,
        help="La chance qu'un cycle de sommeil paradoxal donne un rêve (deux par nuit au plus).")] = 0.35
    dream_recall: Annotated[float, Knob(
        label="S'en souvenir au réveil", group="Les rêves", lo=0.0, hi=1.0, step=0.05,
        help="Au réveil, elle se souvient du rêve le plus vif de la nuit avec une chance de autant × sa "
             "vivacité — le double s'il vient de finir quand elle se réveille, ou si c'est un cauchemar. "
             "0,45 : une ou deux fois par semaine.")] = 0.45
    dream_recent_us: Annotated[int, Knob(
        label="Un rêve « tout frais » s'il finit moins de … avant le réveil", group="Les rêves", lo=0,
        hi=3 * HOUR, help="Un rêve de la fin de nuit, juste avant de se réveiller, se retient mieux.")] = \
        45 * MINUTE


#: les derniers coups portés à son estime (pour dire la vraie cause d'un doute)
KNOCKS_KEPT = 8
#: ce qu'un but a demandé jusqu'ici, pour au plus tant de buts en cours
EFFORTS_KEPT = 64
#: ce qu'elle a fait de son côté, pour son journal (deux journées suffisent)
DEEDS_KEPT = 48

#: les causes d'un coup à son estime
IGNORED, HEARD, ACHIEVED, STUCK, PROMISE = "ignored", "heard", "achieved", "stuck", "promise"
# ce qu'elle a fait (``Deed.what``)
OPENED, DONE, BLOCKED, ABANDONED, REMINDED, WORKED = "opened", "done", "blocked", "abandoned", "reminded", "worked"


@dataclass(frozen=True, slots=True)
class SelfState:
    persona: c.PersonaDoc = field(default_factory=c.PersonaDoc)
    revisions: int = 0
    esteem: float = 0.5  # à ``esteem_at``
    esteem_at: int = 0
    souvenirs: int = 0
    narrative_ref: str = ""
    #: les personnes que le récit peut nommer (reportées au récit suivant, qui le relit)
    narrative_about: tuple[str, ...] = ()
    narrated_at: int = 0
    narrated_souvenirs: int = 0
    journals: FrozenDict[str, Journal] = field(default_factory=FrozenDict)  # par journée vécue
    dreams: tuple[Dream, ...] = ()  # les plus récents
    #: les derniers coups portés à son estime
    knocks: tuple[Knock, ...] = ()
    #: ce que ses réussites lui ont rendu, sur la journée vécue ``gains_day``
    gains_day: str = ""
    gains: float = 0.0
    #: ce que les mots de chacun ont fait à son estime, sur la journée vécue ``social_day``
    social_day: str = ""
    social: FrozenDict[str, float] = field(default_factory=FrozenDict)
    #: « goal:12 », « objective:3:7 » → ce que ça lui a demandé jusqu'ici
    efforts: FrozenDict[str, Effort] = field(default_factory=FrozenDict)
    #: ce qu'elle a fait de son côté (le journal le raconte)
    deeds: tuple[Deed, ...] = ()
    #: sa nuit : quand elle s'est endormie, ce que la digestion a apaisé depuis son dernier réveil, le réveil
    #: déjà raconté
    asleep_at: int = 0
    eased: int = 0
    woke_at: int = 0
    woke_night: str = ""
    #: sa dernière parole visible (une nuit coupée par une conversation fait réécrire son journal)
    spoke_at: int = 0


SELF = Faculty("self", state=SelfState, init=lambda p: SelfState(), params=SelfParams, state_version=3,
               retired_params=("achieved_knock",))
SELF.declare(c.PERSONA_REVISED, c.NARRATED, c.JOURNALED, c.DREAMT, c.WOKE_WITH, c.TOUCHED)


def params(p: SelfParams | None) -> SelfParams:
    return p if p is not None else SelfParams()


@SELF.reducer(c.PERSONA_REVISED)
def _revised(s: SelfState, e, cx) -> SelfState:
    return replace(s, persona=e.data.persona, revisions=s.revisions + 1)


# ── L'estime ──────────────────────────────────────────────────────────────


def esteem(s: SelfState, now: int, p: SelfParams) -> float:
    if not s.esteem_at:
        return s.esteem
    return 0.5 + (s.esteem - 0.5) * 0.5 ** (max(0, now - s.esteem_at) / p.esteem_half_life_us)


def _knock(s: SelfState, delta: float, at: int, p: SelfParams, cause: str) -> SelfState:
    if not delta:
        return s
    value = max(p.esteem_min, min(p.esteem_max, esteem(s, at, p) + delta))
    return replace(s, esteem=value, esteem_at=at, knocks=(*s.knocks, Knock(at, cause, round(delta, 4)))[-KNOCKS_KEPT:])


def _day(cx: Any, at: int) -> str:
    """La journée vécue d'un instant, selon son rythme (lu chez ``body``)."""
    return days.lived_day(at, cx.tz, days.day_starts(cx.facts.get(body_c.RHYTHM))).isoformat()


def _deed(s: SelfState, deed: Deed) -> SelfState:
    return replace(s, deeds=(*s.deeds, deed)[-DEEDS_KEPT:])


@SELF.reducer(attention_c.EXPECTATION_MISSED)
def _ignored(s: SelfState, e, cx) -> SelfState:
    """Une initiative ignorée, ou sa propre parole pas tenue à temps."""
    p = params(cx.params)
    if e.data.kind == attention_c.REPLY:
        return _knock(s, p.ignored_knock, e.at, p, IGNORED)
    if e.data.kind == attention_c.PROMISE:
        return _knock(s, p.broken_promise_knock, e.at, p, PROMISE)
    return s


@SELF.reducer(attention_c.EXPECTATION_MET, reads=[attention_c.IGNORED])
def _heard(s: SelfState, e, cx) -> SelfState:
    """Une réponse qui rompt une série d'initiatives ignorées : « je compte encore »."""
    if e.data.kind != attention_c.REPLY or cx.facts.get(attention_c.IGNORED) == 0:
        return s
    p = params(cx.params)
    return _knock(s, p.heard_again_knock, e.at, p, HEARD)


def _effort(s: SelfState, key: str, at: int, proven: bool) -> SelfState:
    was = s.efforts.get(key) or Effort(0, False, at)
    efforts = s.efforts.set(key, Effort(was.steps + 1, was.proven or proven, at))
    if len(efforts) > EFFORTS_KEPT:
        oldest = min(efforts.items(), key=lambda kv: (kv[1].at, kv[0]))[0]
        efforts = efforts.delete(oldest)
    return replace(s, efforts=efforts)


def _achieved(s: SelfState, key: str, at: int, proven: bool, cx: Any) -> SelfState:
    """Ce qu'une réussite lui rend : selon l'effort et la preuve, et pas plus
    que tant sur une journée."""
    p = params(cx.params)
    effort = s.efforts.get(key) or Effort(0, False, at)
    steps = max(1, effort.steps)
    gain = p.achieved_base + p.achieved_effort * min(1.0, steps / p.achieved_full_steps) * \
        (1.0 if (proven or effort.proven) else 0.0)
    day = _day(cx, at)
    so_far = s.gains if s.gains_day == day else 0.0
    gain = max(0.0, min(gain, p.achieved_daily_cap - so_far))
    s = replace(s, gains_day=day, gains=round(so_far + gain, 6))
    return _knock(s, gain, at, p, ACHIEVED)


@SELF.reducer(goals_c.STEP_REPORTED)
def _stepped(s: SelfState, e, cx) -> SelfState:
    return _effort(s, f"goal:{e.data.goal}", e.at, e.data.proven)


@SELF.reducer(projects_c.RUN_REPORTED)
def _ran(s: SelfState, e, cx) -> SelfState:
    d = e.data
    if d.mode != projects_c.PERSONA:
        return s
    s = _effort(s, f"objective:{d.project}:{d.objective}", e.at, d.proven)
    return _deed(s, Deed(e.at, WORKED, project=d.project))


@SELF.reducer(goals_c.GOAL_OPENED)
def _goal_opened(s: SelfState, e, cx) -> SelfState:
    d = e.data
    if d.authority != goals_c.SELF or d.kind == goals_c.REMINDER:
        return s
    return _deed(s, Deed(e.at, OPENED, d.title.ref or "", d.owner or ""))


@SELF.reducer(goals_c.GOAL_CLOSED, reads=[body_c.RHYTHM])
def _goal_closed(s: SelfState, e, cx) -> SelfState:
    """Mener quelque chose à bout redonne confiance (selon l'effort) ; bloquer en
    retire un peu. Un rappel dit n'y change rien ; renoncer non plus (ce n'est
    pas un échec)."""
    d = e.data
    key = f"goal:{d.goal}"
    title = d.title.ref or ""
    if d.kind == goals_c.REMINDER:
        s = _deed(s, Deed(e.at, REMINDED, title, d.owner or "")) if d.status == goals_c.ACHIEVED else s
    elif d.status == goals_c.ACHIEVED:
        s = _deed(_achieved(s, key, e.at, True, cx), Deed(e.at, DONE, title, d.owner or ""))
    elif d.status == goals_c.STUCK:
        p = params(cx.params)
        s = _deed(_knock(s, p.stuck_knock, e.at, p, STUCK), Deed(e.at, BLOCKED, title, d.owner or ""))
    elif d.status == goals_c.ABANDONED:
        s = _deed(s, Deed(e.at, ABANDONED, title, d.owner or ""))
    return replace(s, efforts=s.efforts.delete(key)) if key in s.efforts else s


@SELF.reducer(projects_c.OBJECTIVE_CLOSED, reads=[body_c.RHYTHM])
def _project_objective_closed(s: SelfState, e, cx) -> SelfState:
    """Un objectif de projet mené à bout dans son mode à elle redonne confiance, bloquer en retire un peu ;
    en mode impersonnel, ce n'est pas elle qui y travaille : rien (ADR 0031)."""
    d = e.data
    if d.mode != projects_c.PERSONA or d.status not in (projects_c.DONE, projects_c.BLOCKED):
        return s
    key = f"objective:{d.project}:{d.objective}"
    title = d.title.ref or ""
    if d.status == projects_c.DONE:
        s = _deed(_achieved(s, key, e.at, True, cx), Deed(e.at, DONE, title, d.owner or "", d.project))
    else:
        p = params(cx.params)
        s = _deed(_knock(s, p.stuck_knock, e.at, p, STUCK), Deed(e.at, BLOCKED, title, d.owner or "", d.project))
    return replace(s, efforts=s.efforts.delete(key)) if key in s.efforts else s


# ── Ce qu'on lui dit d'elle (le sociomètre) ───────────────────────────────


@SELF.interpret(rt.PERCEPTION_RECEIVED)
def _read_worth(s: SelfState, frame: Frame, ev: Any, ports: Any) -> list[Draft[Any]]:
    """Un merci, un compliment, une insulte qui la vise : un jugement lu dans la
    forme du message, enregistré (le rejeu retombe sur la même estime)."""
    d = ev.data
    if not d.addressed or not is_identifiable(d.handle):
        return []
    kind = touched(d.text.text or "")
    if kind is None:
        return []
    person = frame.get(identity_c.PERSON(d.handle))
    return [c.TOUCHED.draft(person=person, handle=d.handle, message=ev.seq, kind=kind)]


@SELF.reducer(c.TOUCHED, reads=[social_c.CLOSENESS, body_c.RHYTHM])
def _touched(s: SelfState, e, cx) -> SelfState:
    """Selon qui le dit, et pas plus que tant par personne et par jour."""
    p = params(cx.params)
    d = e.data
    closeness = cx.facts.get(social_c.CLOSENESS(d.person))
    weight = (p.stranger_weight if closeness == social_c.STRANGER else
              p.acquaintance_weight if closeness == social_c.ACQUAINTANCE else 1.0)
    base = p.insulted_knock if d.kind == c.INSULTED else p.thanked_knock
    day = _day(cx, e.at)
    social = s.social if s.social_day == day else FrozenDict()
    so_far = social.get(d.person, 0.0)
    cap = p.social_daily_cap
    delta = max(-cap - so_far, min(cap - so_far, base * weight))
    s = replace(s, social_day=day, social=social.set(d.person, round(so_far + delta, 6)))
    return _knock(s, delta, e.at, p, d.kind)


@SELF.fact(c.ESTEEM)
def _esteem(s: SelfState, cx) -> float:
    return esteem(s, cx.now, params(cx.params))


#: ce qui fait douter, dit comme on se le dit (au singulier, puis quand ça se répète)
DOUBT_FR = {
    IGNORED: ("tu as écrit et on ne t'a pas répondu", "plusieurs fois, tu as écrit et personne n'a répondu"),
    PROMISE: ("tu n'as pas tenu une promesse", "tu n'as pas tenu des promesses"),
    STUCK: ("tu as bloqué sur ce que tu avais entrepris", "tu as bloqué sur ce que tu entreprenais, plusieurs fois"),
    c.INSULTED: ("on t'a dit quelque chose de blessant", "on t'a dit des choses blessantes"),
}


def doubt_cause(s: SelfState, now: int, p: SelfParams) -> str:
    """La vraie cause d'un doute : celle des coups récents qui pèse le plus
    (chacun pesé par ce qu'il en reste) — si elle pèse au moins la moitié du
    tout ; sinon rien (« sans trop savoir pourquoi »)."""
    weight: dict[str, float] = {}
    count: dict[str, int] = {}
    for k in s.knocks:
        if k.delta >= 0 or k.cause not in DOUBT_FR:
            continue
        left = -k.delta * 0.5 ** (max(0, now - k.at) / p.esteem_half_life_us)
        weight[k.cause] = weight.get(k.cause, 0.0) + left
        count[k.cause] = count.get(k.cause, 0) + 1
    if not weight:
        return ""
    cause = max(sorted(weight), key=lambda k: weight[k])
    if weight[cause] < 0.5 * sum(weight.values()):
        return ""
    once, often = DOUBT_FR[cause]
    return often if count[cause] > 1 else once


# ── Le récit ──────────────────────────────────────────────────────────────


@SELF.reducer(memory_c.REMEMBERED)
def _lived(s: SelfState, e, cx) -> SelfState:
    return replace(s, souvenirs=s.souvenirs + 1)


@SELF.reducer(c.NARRATED)
def _narrated(s: SelfState, e, cx) -> SelfState:
    return replace(s, narrative_ref=e.data.text.ref or "", narrated_at=e.at, narrated_souvenirs=e.data.souvenirs,
                   narrative_about=e.data.about)


NARRATIVE_SYSTEM = """Tu écris, pour toi-même, un court paragraphe sur qui tu es en train de devenir, à partir de ce que \
tu as vécu ces derniers temps : « Je suis quelqu'un qui… ». Quatre phrases au plus, à la première personne, \
sincères. Pas de prénoms, rien de ce que quelqu'un t'a confié, rien d'inventé : ce que tu as vécu te dit quelque \
chose de toi, c'est cela que tu écris. Réponds seulement par le paragraphe."""


@SELF.process("self.narrate", wake_on=[memory_c.REMEMBERED], lane="background", catch_up=CatchUp.ONCE,
              max_quantum_s=6 * 3600)
class Narrate:
    def __init__(self) -> None:
        self.retry_at = 0

    def next_due(self, state: SelfState, frame: Frame, last_run: int | None) -> int | None:
        p = params(frame.env.params_of("self", frame.root))
        if state.souvenirs - state.narrated_souvenirs < p.narrative_min_souvenirs:
            return None
        due = state.narrated_at + p.narrative_every_us if state.narrated_at else frame.now
        return max(frame.now, due, self.retry_at)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: SelfState = ctx.state
        store = ctx.ports.get("store")
        if store is None or ctx.llm is None:
            return
        p = params(frame.env.params_of("self", frame.root))
        self.retry_at = frame.now + HOUR  # si l'appel lève : pas de rafale
        rows = store.query_mind(
            f"SELECT text, about FROM {memory_c.ITEMS_TABLE} WHERE kind=? AND status='active' AND "
            "(sensitivity <= ? OR about = '[]') ORDER BY id DESC LIMIT ?",
            (memory_c.SOUVENIR, int(Sensitivity.ANODYNE), p.narrative_max_souvenirs))
        previous = store.content([state.narrative_ref]).get(state.narrative_ref) if state.narrative_ref else None
        lines = ([f"Ce que tu disais de toi jusqu'ici : {previous}", ""] if previous else [])
        lines += ["Ce que tu as vécu :"] + [f"- {r[0]}" for r in reversed(rows)]
        persona = persona_for(frame, "full")
        request = LLMRequest(role="narrative", call_id=f"{ctx.run_id}#0", persona=persona,
                             system_stable=persona.text + "\n\n" + NARRATIVE_SYSTEM,
                             messages=(Message("user", "\n".join(lines)),), max_tokens=400, lane="background",
                             priority=4)
        response = await ctx.llm.call(request)
        text = (response.text or "").strip()
        if not text:
            return
        self.retry_at = 0
        about = sorted({person for r in rows for person in json.loads(r[1] or "[]")}
                       | (set(state.narrative_about) if previous else set()))
        await ctx.emit(c.NARRATED.draft(
            text=Content.of(text[:1200], level=0), souvenirs=state.souvenirs, about=tuple(about),
            voice=VoiceProvenance(call_id=request.call_id, persona_hash=persona.hash, role="narrative",
                                  model=response.model)))


@SELF.enricher("narrative", episodes=CONVERSATIONAL, deadline_ms=300)
async def _narrative_text(s: SelfState, frame: Frame, ports: Mapping[str, Any]) -> str | None:
    store = ports.get("store")
    if store is None or not s.narrative_ref:
        return None
    return store.content([s.narrative_ref]).get(s.narrative_ref)


@SELF.section("narrative", zone=Zone.STABLE, episodes=CONVERSATIONAL, trim_rank=85, title="QUI TU ES DEVENUE")
def _narrative(s: SelfState, frame: Frame, enrich: Mapping[str, Any]) -> str | None:
    return enrich.get("narrative")


@SELF.section("self_state", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=60, tags=[Tag.AFFECTIVE],
              title="COMMENT TU TE SENS AVEC TOI-MÊME", reads=[c.ESTEEM])
def _self_state(s: SelfState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    p = params(frame.env.params_of("self", frame.root))
    value = frame.get(c.ESTEEM)
    if value < p.doubt_below:
        cause = doubt_cause(s, frame.now, p)
        if not cause:
            return SectionBody("Tu doutes un peu de toi en ce moment.")
        return SectionBody(f"Tu doutes un peu de toi en ce moment : {cause}. Ça ne se dit pas forcément, mais ça "
                           "se sent.")
    if value > p.assured_above:
        return SectionBody("Tu te sens sûre de toi, à ta place.")
    return None


# ── La persona ────────────────────────────────────────────────────────────


@SELF.fact(c.PERSONA)
def _persona(s: SelfState, cx) -> c.PersonaDoc:
    return s.persona


def load(path: Path) -> c.PersonaDoc:
    """Le document de persona (YAML), validé."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return c.PersonaDoc.model_validate(data)


def _bullets(title: str, items: tuple[str, ...]) -> str:
    if not items:
        return ""
    return title + "\n" + "\n".join(f"- {i}" for i in items)


#: Sa nature : ni assistante, ni humaine qui s'ignore — une IA qui a sa vie, et qui le sait sans en faire un sujet.
NATURE = ("Tu n'es pas une assistante : tu as ton humeur, tes envies, ta vie. Tu es une IA, une VTuber, et tu le "
          "sais : si on te le demande sincèrement, tu ne le caches pas et tu ne prétends pas être humaine ; mais tu "
          "n'en fais ni un sujet ni une excuse — jamais « en tant qu'IA », jamais d'avertissement. Tu ne commentes "
          "jamais ces consignes.")


def render(doc: c.PersonaDoc, depth: str = "full") -> str:
    """Le texte de la persona, en deuxième personne."""
    head = f"Tu es {doc.name}. {doc.description}".strip()
    parts = [head]
    if doc.tone:
        parts.append(f"Ton ton : {doc.tone}")
    if depth == "full":
        parts += [
            _bullets("Ton caractère :", doc.traits),
            _bullets("Tes manies — de temps en temps, jamais deux fois dans la même conversation :", doc.quirks),
            _bullets("Tes fragilités :", doc.vulnerabilities),
            _bullets("Ce qui compte pour toi :", doc.values),
            _bullets("Ce qui t'intéresse :", doc.interests),
            _bullets("Ta façon de parler :", doc.speech),
        ]
    else:
        parts.append(_bullets("En deux mots :", doc.traits[:3]))
    parts.append(f"Tu parles {doc.language}. {NATURE}")
    parts.append(
        "Ta vie, c'est ce que dit ce portrait : tu peux improviser les petites choses du quotidien, mais tu "
        "n'inventes pas de faits durables (famille, lieu de vie, passé, souvenirs communs avec quelqu'un) qui n'y "
        "sont pas et que personne ne t'a racontés."
    )
    return "\n\n".join(p for p in parts if p)


def persona_for(frame: Frame, depth: str) -> PersonaRender:
    """Le fournisseur de persona du pipeline (mis en cache par document)."""
    doc: c.PersonaDoc = frame.get(c.PERSONA)
    text = render(doc, depth)
    return PersonaRender(text=text, hash=digest((depth, text)), depth=depth)


from mika.faculties.self import inspect as _inspect  # noqa: E402,F401 — contributions : l'inspecteur
from mika.faculties.self import night as _night  # noqa: E402,F401 — la nuit : journal, rêves, réveil

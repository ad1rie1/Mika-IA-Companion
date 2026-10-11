"""L'estime, et ce qu'elle a fait de son côté.

**L'estime** est lente (entre le tempérament, fixe, et l'humeur, qui change en minutes) : une valeur qui revient vers
0,5 avec une demi-vie de trois jours, bousculée par de petits coups. Ce qu'elle mène à bout compte selon l'effort que
ça lui a demandé (une chose faite en un pas ne vaut pas une semaine de travail), et pas plus que tant par jour ; ce
que les autres lui disent d'elle compte aussi — un merci, un compliment, une insulte qui la vise —, selon qui le dit,
et pas plus que tant par personne et par jour ; des excuses sincères (une fois par jour et par personne, quand il y a
de quoi pardonner) adoucissent ce que ses mots avaient fait. Une initiative restée sans réponse, une promesse non
tenue, un blocage l'abaissent. Une rêverie n'est pas une réussite : elle ne la relève pas. Elle ne touche jamais
l'arbitrage ; elle se ressent, et le doute dit sa vraie cause.

**Ses actes** (``Deed``) — ce qu'elle a ouvert, mené à bout, laissé, travaillé — se lisent dans les mêmes événements :
son journal les raconte.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from mika.contracts import affect as affect_c
from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import expression as expression_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as c
from mika.contracts import social as social_c
from mika.faculties.self.faculty import SELF, SelfState, day_of, lived_day_of
from mika.faculties.self.knobs import SelfParams, params
from mika.faculties.self.records import (
    ABANDONED,
    BLOCKED,
    DONE,
    MUSED,
    OPENED,
    REFLECTED,
    REMINDED,
    WORKED,
    Deed,
    Effort,
    Knock,
)
from mika.kernel.events import Draft
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.vocab import reading
from mika.vocab.episodes import CONVERSATIONAL, Kind, Tag
from mika.vocab.people import is_identifiable
from mika.vocab.phrasebook import phrase

#: les derniers coups portés à son estime (pour dire la vraie cause d'un doute)
KNOCKS_KEPT = 8
#: ce qu'un but a demandé jusqu'ici, pour au plus tant de buts en cours
EFFORTS_KEPT = 64
#: ce qu'elle a fait de son côté, pour son journal (deux journées suffisent)
DEEDS_KEPT = 48

#: les causes d'un coup à son estime
IGNORED, HEARD, ACHIEVED, STUCK, PROMISE = "ignored", "heard", "achieved", "stuck", "promise"


def esteem(s: SelfState, now: int, p: SelfParams) -> float:
    if not s.esteem_at:
        return p.esteem_rest  # jamais bousculée : là où elle revient (ADR 0100)
    return p.esteem_rest + (s.esteem - p.esteem_rest) * 0.5 ** (max(0, now - s.esteem_at) / p.esteem_half_life_us)


def _knock(s: SelfState, delta: float, at: int, p: SelfParams, cause: str) -> SelfState:
    if not delta:
        return s
    value = max(p.esteem_min, min(p.esteem_max, esteem(s, at, p) + delta))
    return replace(s, esteem=value, esteem_at=at, knocks=(*s.knocks, Knock(at, cause, round(delta, 4)))[-KNOCKS_KEPT:])


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
    day = day_of(cx, at)
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
    if d.authority != goals_c.SELF or d.kind == goals_c.REMINDER or d.musing:
        return s  # se laisser rêvasser n'est pas « se lancer dans » quelque chose
    return _deed(s, Deed(e.at, OPENED, d.title.ref or "", d.owner or "", about=tuple(d.about),
                         sensitivity=d.sensitivity))


@SELF.reducer(goals_c.GOAL_CLOSED, reads=[body_c.RHYTHM])
def _goal_closed(s: SelfState, e, cx) -> SelfState:
    """Mener quelque chose à bout redonne confiance (selon l'effort, et seulement
    s'il est prouvé) ; bloquer en retire un peu. Un rappel dit n'y change rien ;
    renoncer non plus (ce n'est pas un échec) ; rêvasser non plus — ce n'est pas
    un exploit (HUM-19), son journal le dit comme une rêverie."""
    d = e.data
    key = f"goal:{d.goal}"
    title = d.title.ref or ""
    who = {"about": tuple(d.about), "sensitivity": d.sensitivity}
    if d.kind == goals_c.REMINDER:
        s = _deed(s, Deed(e.at, REMINDED, title, d.owner or "", **who)) if d.status == goals_c.ACHIEVED else s
    elif d.status == goals_c.ACHIEVED and d.reason in goals_c.MUSINGS:
        s = _deed(s, Deed(e.at, MUSED, title, d.owner or "", **who))
    elif goals_c.reflective(d.origin, d.source) and d.status in (goals_c.ACHIEVED, goals_c.STUCK):
        # repenser à ce qu'une amie lui a confié n'est ni un exploit ni un échec : son estime n'y gagne ni n'y perd
        if d.status == goals_c.ACHIEVED:
            s = _deed(s, Deed(e.at, REFLECTED, title, d.owner or "", **who))
    elif d.status == goals_c.ACHIEVED:
        # l'effort ne compte que s'il a été prouvé pendant ses séances (un but clos à la main n'en a pas)
        s = _deed(_achieved(s, key, e.at, False, cx), Deed(e.at, DONE, title, d.owner or "", **who))
    elif d.status == goals_c.STUCK:
        p = params(cx.params)
        s = _deed(_knock(s, p.stuck_knock, e.at, p, STUCK), Deed(e.at, BLOCKED, title, d.owner or "", **who))
    # une rêverie qui s'efface, une réflexion sans suite : ce n'est pas un acte
    elif d.status == goals_c.ABANDONED and d.reason not in goals_c.QUIET_ENDS:
        s = _deed(s, Deed(e.at, ABANDONED, title, d.owner or "", **who))
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
        s = _deed(_achieved(s, key, e.at, True, cx), Deed(e.at, DONE, title, d.owner or "", d.project,
                                                          tuple(d.about), d.sensitivity))
    else:
        p = params(cx.params)
        s = _deed(_knock(s, p.stuck_knock, e.at, p, STUCK), Deed(e.at, BLOCKED, title, d.owner or "", d.project,
                                                                tuple(d.about), d.sensitivity))
    return replace(s, efforts=s.efforts.delete(key)) if key in s.efforts else s

# ── Ce qu'on lui dit d'elle (le sociomètre) ───────────────────────────────


#: une hostilité en deçà de laquelle il n'y a rien à pardonner (des excuses tombent à plat, sans rien consommer)
FORGIVABLE_FROM = 0.05


@SELF.interpret(rt.UTTERANCE)
def _read_worth(s: SelfState, frame: Frame, ev: Any, ports: Any) -> list[Draft[Any]]:
    """Un merci, un compliment, des mots qui la blessent, des excuses : ce que le modèle qui lui a répondu a lu du
    geste de la personne envers elle (sa balise ``[EN_FACE: … | geste : …]``, ADR 0093) — jamais une liste de mots ;
    enregistré (le rejeu retombe sur la même estime). Des excuses ne comptent qu'une fois par jour et par personne,
    et seulement s'il y a quelque chose à pardonner (une rancune, des mots qui l'ont blessée ce jour-là) : un troll
    qui s'excuse dix fois ne s'excuse qu'une."""
    d = ev.data
    if d.kind != Kind.REPLY or not d.target or d.reply_to is None or not is_identifiable(d.target):
        return []
    their = reading.Reading.decode(d.annotation(expression_c.READING_ANNOTATION))
    kind = their.gesture if their is not None else ""
    if not kind:
        return []
    person = frame.get(identity_c.PERSON(d.target))
    if kind == c.APOLOGIZED:
        day = lived_day_of(frame, ev.at)
        if s.apologies.get(person) == day:
            return []
        hurt = s.social_day == day and s.social.get(person, 0.0) < 0
        if not hurt and frame.get(affect_c.HOSTILITY(person)) < FORGIVABLE_FROM:
            return []
    return [c.TOUCHED.draft(person=person, handle=d.target, message=d.reply_to, kind=kind)]


@SELF.reducer(c.TOUCHED, reads=[social_c.CLOSENESS, body_c.RHYTHM])
def _touched(s: SelfState, e, cx) -> SelfState:
    """Selon qui le dit, et pas plus que tant par personne et par jour. Des
    excuses lui rendent une part de ce que les mots de cette personne lui
    avaient coûté ce jour-là — une fois par jour."""
    p = params(cx.params)
    d = e.data
    day = day_of(cx, e.at)
    social = s.social if s.social_day == day else FrozenDict()
    so_far = social.get(d.person, 0.0)
    if d.kind == c.APOLOGIZED:
        if s.apologies.get(d.person) == day:
            return s
        s = replace(s, apologies=_kept_days(s.apologies.set(d.person, day), day))
        mend = round(-so_far * p.apology_mend, 6) if so_far < 0 else 0.0
        s = replace(s, social_day=day, social=social.set(d.person, round(so_far + mend, 6)))
        return _knock(s, mend, e.at, p, d.kind)
    closeness = cx.facts.get(social_c.CLOSENESS(d.person))
    weight = (p.stranger_weight if closeness == social_c.STRANGER else
              p.acquaintance_weight if closeness == social_c.ACQUAINTANCE else 1.0)
    base = p.insulted_knock if d.kind == c.INSULTED else p.thanked_knock
    cap = p.social_daily_cap
    delta = max(-cap - so_far, min(cap - so_far, base * weight))
    s = replace(s, social_day=day, social=social.set(d.person, round(so_far + delta, 6)))
    return _knock(s, delta, e.at, p, d.kind)


def _kept_days(apologies: FrozenDict[str, str], day: str) -> FrozenDict[str, str]:
    """Seules les excuses du jour comptent pour « une fois par jour » : les autres s'effacent."""
    return FrozenDict({k: v for k, v in apologies.items() if v == day})


@SELF.fact(c.ESTEEM)
def _esteem(s: SelfState, cx) -> float:
    return esteem(s, cx.now, params(cx.params))


#: ce qui fait douter (dit comme on se le dit, au singulier puis quand ça se répète : ``self.esteem.cause_once``,
#: ``self.esteem.cause_often`` dans sa voix)
DOUBTS = frozenset({IGNORED, PROMISE, STUCK, c.INSULTED})


def doubt_cause(s: SelfState, now: int, p: SelfParams) -> str:
    """La vraie cause d'un doute : celle des coups récents qui pèse le plus
    (chacun pesé par ce qu'il en reste) — si elle pèse au moins la moitié du
    tout ; sinon rien (« sans trop savoir pourquoi »)."""
    weight: dict[str, float] = {}
    count: dict[str, int] = {}
    for k in s.knocks:
        if k.delta >= 0 or k.cause not in DOUBTS:
            continue
        left = -k.delta * 0.5 ** (max(0, now - k.at) / p.esteem_half_life_us)
        weight[k.cause] = weight.get(k.cause, 0.0) + left
        count[k.cause] = count.get(k.cause, 0) + 1
    if not weight:
        return ""
    cause = max(sorted(weight), key=lambda k: weight[k])
    if weight[cause] < 0.5 * sum(weight.values()):
        return ""
    if count[cause] > 1:
        return phrase(f"self.esteem.cause_often.{cause}")
    return phrase(f"self.esteem.cause_once.{cause}")


@SELF.section("self_state", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=60, tags=[Tag.AFFECTIVE],
              title=phrase("self.esteem.title"), reads=[c.ESTEEM])
def _self_state(s: SelfState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    p = params(frame.env.params_of("self", frame.root))
    value = frame.get(c.ESTEEM)
    if value < p.doubt_below:
        cause = doubt_cause(s, frame.now, p)
        if not cause:
            return SectionBody(phrase("self.esteem.doubt"))
        return SectionBody(phrase("self.esteem.doubt_because", cause=cause))
    if value > p.assured_above:
        return SectionBody(phrase("self.esteem.assured"))
    return None

"""La faculté ``needs`` : l'état (``NeedsState``) et ce qu'il garde, la faculté (``NEEDS``), la tension de chaque
besoin (``tension``), les réducteurs qui les comblent, le fait ``needs.needs``, ce qu'elle en dit dans son prompt
(``describe``, la section ``needs``) et ce qu'en efface l'oubli d'une personne."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

from mika.contracts import affect as affect_c
from mika.contracts import agency as agency_c
from mika.contracts import body as body_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import needs as c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.needs.params import NeedsParams, derive, params
from mika.kernel.builtin import BOOT, SUBJECT_FORGOTTEN
from mika.kernel.clock import HOUR
from mika.kernel.faculty import Faculty, Zone
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.vocab.episodes import CONVERSATIONAL, Kind, Tag
from mika.vocab.people import is_identifiable, key_concerns
from mika.vocab.phrasebook import phrase


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
    #: la croyance d'où elle vient : remplacée, ou devenue secrète, elle n'est plus une matière
    item: int = 0


@dataclass(frozen=True, slots=True)
class Occupation:
    """Ce qu'elle fait dans sa chambre et qui nourrit un besoin, tel que le monde l'a enregistré quand elle s'y est
    mise : l'activité, son début, sa fin prévue (``None`` : jusqu'à ce qu'elle s'arrête) et ce qu'elle nourrit."""

    name: str
    since: int
    until: int | None = None
    nourishes: tuple[str, ...] = ()
    #: depuis quand le vide courait quand elle s'y est mise (0 : un journal d'avant) — s'occuper l'efface au prorata
    #: de ce que l'occupation a comblé, il ne le remet pas à zéro (ADR 0098) ; et quand ses besoins l'ont appris
    void_from: int = 0
    noted: int = 0


#: au plus tant de choses faites gardées comme matière
DONE_KEPT = 6
#: au plus tant de choses racontées gardées par personne (les plus importantes)
TOLD_KEPT = 4
#: au plus tant de matières déjà dites retenues (pour ne pas en reprendre une deux fois)
USED_KEPT = 64
#: une séance de travail plus vieille que ça n'occupe plus (un épisode interrompu sans règlement)
WORK_STALE = HOUR
#: une occupation sans fin prévue plus vieille que ça ne l'occupe plus (le monde l'arrête bien avant : son réglage
#: ne la laisse pas dépasser huit heures)
OCCUPATION_STALE = 8 * HOUR


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
    #: ce qu'elle fait de ses mains et qui la nourrit (dessiner, feuilleter un livre) : ça l'occupe, pas de vide
    occupied: Occupation | None = None
    #: la dernière occupation qui l'a nourrie, ``until`` à sa fin réelle (la console date le soulagement)
    nourished: Occupation | None = None
    #: depuis quand elle est sans personne : le dernier message qu'on lui a adressé, sa dernière parole à quelqu'un,
    #: son réveil, une séance de travail qui l'absorbe (PSY-18) — ce qu'elle fait de ses mains n'y change rien : ça
    #: tient l'ennui à distance, pas le manque de quelqu'un (0 : un journal d'avant, ``idle_since`` en tient lieu ;
    #: ADR 0098)
    lonely_since: int = 0


#: v3 : ce qu'on lui a raconté se classe par importance (plusieurs par personne), les matières déjà dites, qui lui
#: a parlé en dernier et le vide ressenti (retrouver quelqu'un) ; une rêverie n'est plus une matière.
#: v4 : la compagnie qui comble dépend de qui la donne (une règle, pas une forme : reconstruite depuis la genèse)
#: v5 : ce qu'elle fait de ses mains dans sa chambre l'occupe et la nourrit (les occupations du monde, réduites
#: désormais : reconstruite depuis la genèse)
#: v6 : ce qu'on lui a raconté garde la croyance d'où il vient : remplacée, ou devenue secrète, elle n'est plus une
#: matière ; ni un secret, ni un avis, ni un surnom n'en deviennent une (ADR 0078)
#: v7 : sa propriétaire la comble davantage (``social.WEIGHT``, ADR 0094) ; s'occuper efface le vide au prorata de ce
#: que l'occupation a comblé, et jamais la solitude (``lonely_since``, ADR 0098)
NEEDS = Faculty("needs", state=NeedsState, init=lambda p: NeedsState(), params=NeedsParams, derive=derive,
                state_version=7)
NEEDS.declare(*c.ALL)

#: Ce qui l'absorbe, sans vide : les séances où elle travaille dans son mode à elle (une exécution impersonnelle
#: n'est pas elle), et un réveil par API, qui ne l'envoie pas à son bureau — world, ``DESK_KINDS``.
ABSORBING_KINDS = frozenset({Kind.STEP, Kind.WORK, Kind.WAKE})
#: ce qu'on dit d'une initiative que seules les envies poussent (pas d'autre raison)
URGES = frozenset({c.NEED_SOCIAL, c.NEED_EXPRESSION})
#: des raisons qui ne disent pas de quoi parler (le seul fait que quelqu'un soit là, l'envie de discuter, la garde
#: « elle s'est ravisée »)
CONTENTLESS = frozenset({*URGES, social_c.PRESENT_PERSON, social_c.CHAT, agency_c.SECOND_THOUGHTS})
#: la provenance d'une matière montrée dans une initiative (``matter:<référence>``) : dite, elle ne resert pas
MATTER_PROVENANCE = "matter:"


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


def _company(get: Any, handle: str, p: NeedsParams) -> float:
    """La part de compagnie qu'apporte un échange avec cette adresse : pleine avec une amie ou une proche, une
    part avec une connaissance, peu avec une inconnue (une adresse jetable en est une), presque rien avec qui
    elle garde une hostilité installée — un après-midi à se faire chahuter par un inconnu ne remplace pas une
    amie, le soir."""
    if not is_identifiable(handle):
        return p.stranger_company
    person = get(identity_c.PERSON(handle))
    closeness = get(social_c.CLOSENESS(person))
    share = 1.0 if closeness in (social_c.FRIEND, social_c.CLOSE) else (
        p.acquaintance_company if closeness == social_c.ACQUAINTANCE else p.stranger_company)
    if get(affect_c.HOSTILITY(person)) >= p.hostile_from:
        return min(share, p.hostile_company)
    return share * get(social_c.WEIGHT(person))  # sa propriétaire la comble davantage


def _shared(factor: float, share: float) -> float:
    """Le facteur d'un échange qui ne comble qu'une part : ``1`` ne comble rien, ``factor`` comble tout (au-delà,
    sa propriétaire : un peu plus, jamais au-delà de tout)."""
    return max(0.0, 1.0 - (1.0 - factor) * share)


@NEEDS.reducer(rt.PERCEPTION_RECEIVED, reads=[identity_c.PERSON, social_c.CLOSENESS, social_c.WEIGHT, affect_c.HOSTILITY])
def _received(s: NeedsState, e, cx) -> NeedsState:
    """Un message adressé : la compagnie, selon qui l'écrit ; la curiosité, de
    n'importe qui. Le vide, lui, est rompu par n'importe quel message
    (« personne ne m'a parlé » cesse d'être vrai)."""
    if not e.data.addressed or not is_identifiable(e.data.handle):
        return s
    p = params(cx.params)
    s = _touch(s, e.at, p)
    social = _shared(p.received_social, _company(cx.facts.get, e.data.handle, p))
    s = _relieve(_relieve(s, c.SOCIAL, social, e.at, p), c.CURIOSITY, p.received_curiosity, e.at, p)
    return replace(s, idle_since=e.at, heard_at=e.at, heard_before=s.heard_at, lonely_since=e.at)


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
    if d.replaces is not None:
        s = _unlearned(s, d.replaces)
    p = params(cx.params)
    # ce qu'elle tient de sa bouche, sur elle-même : pas un secret (qui ne s'ouvre pas en initiative), ni un avis ou
    # une hypothèse (ce qu'elle pense, pas ce qui lui arrive), ni ce qui n'appartient qu'à elles deux (un surnom)
    mine = not d.secret and d.knowledge_kind in ("claim", "preference") and not d.between_us and not d.about_self
    if mine and len(d.about) == 1 and d.source == d.about[0] and d.text.ref:
        person = d.about[0]
        # ce qui n'est plus une matière (raconté il y a plus de ``matter_told_us``) ne garde pas une place : quatre
        # vieilles confidences importantes évinceraient pour toujours ce qu'elle raconte aujourd'hui (#614, #647)
        kept = (*(t for t in s.told.get(person, ()) if t.ref != d.text.ref and e.at - t.at <= p.matter_told_us),
                Told(d.text.ref, e.at, d.sensitivity, round(d.importance, 4), item=e.seq))
        # les plus importantes, puis les plus récentes : « mon chat est malade » ne cède pas sa place à « j'ai
        # mangé des pâtes »
        kept = tuple(sorted(kept, key=lambda t: (-t.importance, -t.at, t.ref))[:TOLD_KEPT])
        s = replace(s, told=s.told.set(person, kept))
    return _relieve(_touch(s, e.at, p), c.CURIOSITY, p.learned_curiosity, e.at, p)


def _unlearned(s: NeedsState, item: int) -> NeedsState:
    """Une croyance remplacée, ou devenue secrète, n'est plus une matière (audit du 2026-10-09)."""
    if not item:
        return s
    out = s.told
    for person, ts in s.told.items():
        kept = tuple(t for t in ts if t.item != item)
        if kept != ts:
            out = out.set(person, kept) if kept else out.delete(person)
    return s if out is s.told else replace(s, told=out)


@NEEDS.reducer(memory_c.REINFORCED, memory_c.ATTESTED, memory_c.JOINED)
def _belief_changed(s: NeedsState, e, cx) -> NeedsState:
    """Ce qu'on lui a demandé de garder pour soi, ou ce qu'une autre croyance remplace : plus une matière. Une
    croyance jointe la nuit à une autre (ADR 0080) : la matière suit la gardée."""
    d = e.data
    if e.type.name == memory_c.JOINED.name:
        for keep, drop in d.pairs:
            s = replace(s, told=s.told.update({p: tuple(replace(t, item=keep) if t.item == drop else t for t in ts)
                                                for p, ts in s.told.items() if any(t.item == drop for t in ts)}))
        return s
    if d.secret:
        s = _unlearned(s, d.item)
    return _unlearned(s, d.replaces) if d.replaces is not None else s


@NEEDS.reducer(rt.UTTERANCE, reads=[identity_c.PERSON, social_c.CLOSENESS, social_c.WEIGHT, affect_c.HOSTILITY])
def _said(s: NeedsState, e, cx) -> NeedsState:
    d = e.data
    p = params(cx.params)
    if d.kind in ABSORBING_KINDS:
        # ce qu'elle a fait pendant une séance l'occupe et la dit un peu : pas de vide
        s = _relieve(_touch(s, e.at, p), c.EXPRESSION, p.worked_expression, e.at, p)
        return replace(s, idle_since=e.at, lonely_since=e.at)
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
    s = _relieve(s, c.SOCIAL, _shared(p.said_social, _company(cx.facts.get, d.target, p)), e.at, p)
    s = _relieve(s, c.EXPRESSION, p.initiative_expression if d.kind == Kind.INITIATIVE else p.reply_expression,
                 e.at, p)
    return replace(s, idle_since=e.at, lonely_since=e.at)


@NEEDS.reducer(rt.EPISODE_STARTED)
def _working(s: NeedsState, e, cx) -> NeedsState:
    """Le temps de ses besoins commence à compter dès qu'elle vit quelque chose
    (même une initiative à laquelle elle renonce) ; une séance de travail
    l'occupe (pas de vide)."""
    s = _touch(s, e.at, params(cx.params))
    if e.data.kind not in ABSORBING_KINDS:
        return s
    kept = FrozenDict({k: t for k, t in s.working.items() if e.at - t < WORK_STALE})
    return replace(s, working=kept.set(e.correlation, e.at), idle_since=e.at, lonely_since=e.at)


@NEEDS.reducer(rt.EPISODE_ENDED)
def _worked(s: NeedsState, e, cx) -> NeedsState:
    if e.correlation not in s.working:
        return s
    return replace(s, working=s.working.delete(e.correlation), idle_since=max(s.idle_since, e.at),
                   lonely_since=max(s.lonely_since, e.at))


@NEEDS.reducer(body_c.WOKE)
def _woke(s: NeedsState, e, cx) -> NeedsState:
    """Le vide ne se ressent qu'éveillée : au réveil, il recommence à compter
    (la nuit n'a pas creusé de vide). ``felt_at`` ne bouge pas : un réveil n'est
    pas un vide ressenti, il ne prépare pas de retrouvailles."""
    if not s.idle_since:
        return s
    return replace(s, idle_since=max(s.idle_since, e.data.at), lonely_since=max(s.lonely_since, e.data.at))


@NEEDS.reducer(BOOT)
def _back(s: NeedsState, e, cx) -> NeedsState:
    """Elle revient d'un arrêt : le temps où elle n'était pas là n'a rien creusé. Ses besoins reprennent au
    niveau de son dernier instant vécu (``Boot.last_at``), et l'inactivité qui mène au vide ne compte pas
    l'absence — on revient d'une anesthésie avec un blanc, pas avec trois jours de solitude."""
    p = params(cx.params)
    last = e.data.last_at
    if not p.absence_paused or not last or e.at <= last:
        return s
    levels = s.levels
    for kind, level in s.levels.items():
        if level.at:
            levels = levels.set(kind, Level(tension(s, kind, last, p), e.at))
    idle_since = s.idle_since + (e.at - last) if 0 < s.idle_since <= last else s.idle_since
    return replace(s, levels=levels, idle_since=idle_since)


@NEEDS.reducer(c.FELT)
def _felt(s: NeedsState, e, cx) -> NeedsState:
    return replace(s, felt_at=e.at, felt=e.data.feeling, felt_level=e.data.intensity)


def reading(s: NeedsState, t: int, p: NeedsParams) -> c.NeedsReading:
    return c.NeedsReading(tension(s, c.SOCIAL, t, p), tension(s, c.EXPRESSION, t, p),
                          tension(s, c.CURIOSITY, t, p), s.idle_since, s.heard_at)


@NEEDS.fact(c.NEEDS)
def _needs(s: NeedsState, cx) -> c.NeedsReading:
    return reading(s, cx.now, params(cx.params))


# ── Prompt ────────────────────────────────────────────────────────────────


#: au-delà, un besoin se dit dans le prompt (``describe``), et la console le montre pressant
PRESSING = 0.75


def describe(r: c.NeedsReading) -> list[str]:
    lines = []
    if r.social >= PRESSING:
        lines.append(phrase("needs.wants.company_much"))
    elif r.social >= 0.55:
        lines.append(phrase("needs.wants.company"))
    if r.expression >= PRESSING:
        lines.append(phrase("needs.wants.express"))
    if r.curiosity >= PRESSING:
        lines.append(phrase("needs.wants.learn"))
    return lines


@NEEDS.section("needs", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=55,
               tags=[Tag.AFFECTIVE], title=phrase("needs.wants.title"), reads=[c.NEEDS])
def _needs_section(s: NeedsState, frame: Frame, enrich: Any) -> str | None:
    """Ses envies, des faits : ce qu'elle fait de son envie de compagnie (la dire, ou non), son caractère le dit."""
    lines = describe(frame.get(c.NEEDS))
    return "\n".join(lines) if lines else None


# ── L'oubli d'une personne, l'expiration d'une inconnue de passage (audit du 2026-10-26) ──────────────


def _without_person(s: NeedsState, person: str) -> NeedsState:
    return replace(s, told=s.told.without(lambda k: key_concerns(k, person)))


@NEEDS.reducer(identity_c.EXPIRED)
def _stranger_expired(s: NeedsState, e, cx) -> NeedsState:
    return _without_person(s, e.data.person)


@NEEDS.reducer(SUBJECT_FORGOTTEN)
def _person_forgotten(s: NeedsState, e, cx) -> NeedsState:
    return _without_person(s, e.data.subject)

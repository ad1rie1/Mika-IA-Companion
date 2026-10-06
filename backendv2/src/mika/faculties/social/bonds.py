"""Quand un lien change : elle le remarque, une fois.

La proximité se calcule à l'instant (``CLOSENESS``) ; ici, on la compare au
dernier cran qu'elle a ressenti de chaque lien (``felt_levels``). Ce qui
compte, et qu'elle remarque comme une personne s'en rend compte :

- **devenir amies, ou proches** : une pensée (« Je crois qu'une vraie amitié
  est née entre Alice et moi », « … on est vraiment proches maintenant »), un
  peu de joie ;
- **se refroidir** par une rancune, ou une froideur installée entre deux
  personnes qui se parlent encore : une pensée (« Ça s'est refroidi entre
  Bruno et moi »), un peu de mélancolie.

Le silence qui éloigne ne se remarque pas ici : le manque le vit déjà
(``MISSED``, ADR 0058) — ce cran-là n'est pas retenu, si bien qu'une amie
revenue ne « redevient » pas amie. Jamais deux fois le même cran, au plus un
changement par personne et par jour local, et rien les jours durs de la
personne (``memory.HARD_TIMES``). La pensée est personnelle, rattachée à la
personne ; elle ne dit aucun niveau ni aucun nombre, et ne la pousse pas à
écrire (une pensée pensive n'insiste pas).

**Le premier passage est silencieux** : à la mise en service, les niveaux
d'aujourd'hui sont relevés sans être vécus (``BOND_NOTED``) — sinon toute la
vie passée remonterait d'un coup. Une proximité fixée par un opérateur, le
plancher d'une propriétaire : relevés de même, jamais ressentis.

Le coût ne dépend que du cercle (``CIRCLE``, ADR 0058) : la trace du calcul
n'est relue que pour un lien dont le cran a changé.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mika.contracts import affect as affect_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import social as c
from mika.faculties.social.faculty import (
    BOND,
    DAYS,
    GRUDGE,
    HISTORY,
    MESSAGES,
    SOCIAL,
    ClosenessTrace,
    SocialParams,
    SocialState,
    closeness_trace,
    felt_of,
    params,
)
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.vocab.affect import Appraisal, Emotion
from mika.vocab.people import is_identifiable
from mika.vocab.privacy import Sensitivity

#: La pertinence du signal pour son attention (assez pour qu'une pensée en naisse).
PERTINENCE = 0.7
#: Ce qu'elle en ressent, sur le moment : un peu de joie, un peu de mélancolie.
WARMING, COOLING = 0.15, 0.1
#: Les changements remarqués au plus par passage (les autres au passage suivant).
PER_RUN = 3
#: Ce qui se remarque ; le reste est tenu pour acquis sans être vécu.
FELT = frozenset({c.BOND_TIME, c.BOND_ATTACHMENT, c.BOND_REGARD, c.BOND_GRUDGE})
#: Les crans vers lesquels une montée se remarque.
_WARM = frozenset({c.FRIEND, c.CLOSE})


def _rank(level: str) -> int:
    return c.CLOSENESS_LEVELS.index(level) if level in c.CLOSENESS_LEVELS else 0


def _held(trace: ClosenessTrace, level: str, key: str) -> bool | None:
    """Si ce critère du niveau tient sur la fenêtre (``None`` : pas lu)."""
    window = trace.window
    rank = _rank(level)
    if window is None or rank >= len(window.criteria):
        return None
    return next((cr.held for cr in window.criteria[rank] if cr.key == key), None)


def cause_of(trace: ClosenessTrace, before: str, p: SocialParams) -> str:
    """Ce qui a fait basculer le cran depuis ``before``, lu sur la trace du calcul même de la proximité
    (``closeness_trace``) : jamais un calcul à part.

    Une montée : vers l'amitié, le temps vécu ensemble ; vers la proximité, l'attachement s'il tient, sinon la
    chaleur installée. Une descente : une rancune (celle qui défait l'amitié, ou lève le plancher d'une
    propriétaire) ; une froideur installée — la chaleur et l'attachement d'une proche retombés, quand elles se
    parlent encore à leur rythme ; sinon le temps (le silence, une fenêtre qui glisse), que le manque vit déjà."""
    if trace.declared:
        return c.BOND_DECLARED
    if _rank(trace.level) > _rank(before):
        if trace.owner and trace.level != trace.lived_level:
            return c.BOND_OWNER
        if trace.level != c.CLOSE:
            return c.BOND_TIME
        return c.BOND_ATTACHMENT if _held(trace, c.CLOSE, BOND) else c.BOND_REGARD
    if _held(trace, c.FRIEND, GRUDGE) is False or (trace.owner and trace.level == trace.lived_level):
        return c.BOND_GRUDGE
    if trace.lost or trace.short or trace.silent > p.recontact_factor * trace.rhythm_days:
        return c.BOND_TIME
    if before == c.CLOSE and all(_held(trace, c.CLOSE, key) for key in (DAYS, MESSAGES, HISTORY)):
        return c.BOND_REGARD  # leur histoire suffit toujours : c'est la chaleur et l'attachement qui sont retombés
    return c.BOND_TIME


@dataclass(frozen=True, slots=True)
class Shift:
    """Un lien dont le cran a changé depuis ce qu'elle en a ressenti (``since`` : quand ; 0, jamais)."""

    person: str
    before: str
    after: str
    cause: str
    since: int = 0

    @property
    def felt(self) -> bool:
        return self.cause in FELT


def shifts(s: SocialState, frame: Frame, p: SocialParams) -> list[Shift]:
    """Les liens du cercle dont le cran a changé et qui comptent : une montée vers l'amitié ou la proximité, un
    refroidissement par une rancune ou une froideur — au plus un par personne et par jour local, rien les jours
    durs de la personne ; ce qu'une déclaration ou le plancher d'une propriétaire a changé (à relever sans le
    vivre). Au premier passage : tout le cercle, tel qu'il est aujourd'hui, à relever sans le vivre."""
    first = not s.bonds_since
    today = frame.local().date().toordinal()
    out: list[Shift] = []
    for person in frame.get(c.CIRCLE):
        if not is_identifiable(person) or person.startswith("name:"):
            continue
        level = frame.get(c.CLOSENESS(person))
        if first:
            out.append(Shift(person, c.STRANGER, level, c.BOND_START))
            continue
        before, since = felt_of(s, person, frame.get(identity_c.HANDLES(person))) or (c.STRANGER, 0)
        if level == before or (since and frame.local(since).date().toordinal() == today):
            continue
        cause = cause_of(closeness_trace(s, person, p, today, frame.get), before, p)
        if cause in FELT:
            if _rank(level) > _rank(before) and level not in _WARM:
                continue  # devenir une connaissance ne se remarque pas
            if _rank(level) < _rank(before) and cause not in (c.BOND_GRUDGE, c.BOND_REGARD):
                continue  # le silence qui éloigne : le manque le vit déjà
            if frame.get(memory_c.HARD_TIMES(person)) > 0:
                continue  # ses jours durs : on ne pèse pas un lien
        out.append(Shift(person, before, level, cause, since))
    return out


def _text(shift: Shift, name: str) -> str:
    if _rank(shift.after) < _rank(shift.before):
        return f"Ça s'est refroidi entre {name} et moi."
    if shift.after == c.CLOSE:
        return f"{name} et moi, je crois qu'on est vraiment proches maintenant."
    return f"Je crois qu'une vraie amitié est née entre {name} et moi."


@SOCIAL.process("social.bonds", wake_on=[rt.UTTERANCE, rt.PERCEPTION_RECEIVED], lane="background",
                catch_up=CatchUp.ONCE, max_quantum_s=3600,
                reads=[c.CIRCLE, c.CLOSENESS, identity_c.HANDLES, identity_c.IDENTITY, identity_c.IS_OWNER,
                       affect_c.REGARD, affect_c.HOSTILITY, affect_c.BOND, memory_c.HARD_TIMES])
class Bonds:
    """Elle remarque qu'un lien a changé (une pensée, par l'attention) ; le reste, elle le relève sans le vivre."""

    def next_due(self, state: SocialState, frame: Frame, last_run: int | None) -> int | None:
        p = params(frame.env.params_of("social", frame.root))
        return frame.now if shifts(state, frame, p) else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: SocialState = ctx.state
        p = params(frame.env.params_of("social", frame.root))
        found = shifts(state, frame, p)
        # le premier passage relève tout le cercle d'un coup : sinon le reste passerait pour du nouveau
        noted = [x for x in found if not x.felt]
        felt = [x for x in found if x.felt][:PER_RUN]
        drafts: list[Any] = [c.BOND_NOTED.draft(person=x.person, level=x.after, cause=x.cause,
                                                dedupe_key=f"lien:relevé:{x.person}:{x.after}:{x.since}")
                             for x in noted]
        level = int(Sensitivity.PERSONAL)
        for x in felt:
            name = frame.get(identity_c.IDENTITY(x.person)).name or "cette personne"
            drafts.append(c.BOND_SHIFTED.draft(
                source="social", kind="bond_shifted", summary=Content.of(_text(x, name), level=level),
                pertinence=PERTINENCE, emotion=Emotion.THINKING.value, intensity=0.0, about=(x.person,),
                sensitivity=level, person=x.person, before=x.before, after=x.after, cause=x.cause,
                dedupe_key=f"lien:{x.person}:{x.after}:{x.since}"))
        if drafts:
            await ctx.emit(*drafts)


@SOCIAL.appraisal(c.BOND_SHIFTED)
def _bond_felt(e: Any, cx: Any) -> Appraisal:
    """S'apercevoir qu'un lien s'est approfondi : un peu de joie ; qu'il s'est refroidi : un peu de mélancolie."""
    d = e.data
    if _rank(d.after) > _rank(d.before):
        return Appraisal(Emotion.HAPPY, WARMING, reason="un lien qui s'approfondit", relational=True)
    return Appraisal(Emotion.MELANCHOLIC, COOLING, reason="un lien qui se refroidit", relational=True)

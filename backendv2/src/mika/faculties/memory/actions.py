"""Corriger sa mémoire depuis la console (ADR 0230, qui révise 0025 en partie) : l'opératrice voit qu'une promesse a
été tenue sans que la relecture le voie, qu'une situation est finie, comment un moment a tourné, ou qu'un souvenir ou
une croyance est faux — et le corrige sans oublier toute la personne.

Chaque correction est un événement ajouté au journal, confirmé et audité comme toute action (``runtime.operated``) :
les mêmes que ceux de la relecture, sous ``by=OPERATOR_BY`` — ``promise_resolved``, ``situation_ended``,
``resolved`` —, et ``retracted`` pour un démenti. Rien ne réécrit ni n'efface un texte, et rien n'écrit ce qu'elle
croit. Une correction n'est pas un moment de sa vie : une issue posée ici ne porte ni attente, ni annonceur, ni
surprise, ni valence (ni émotion, ni calibration, ni leçon sur qui annonce, ni marque « voir venir ») ; une promesse
abandonnée ici n'est pas « laissée filer » ; tenue, elle compte pour « tenir parole ».

Les formulaires se posent sur la carte de l'élément (``inline``), qui dit lequel par un champ caché ; une action
n'est offerte que si sa tranche a de quoi la servir, et refuse un élément où elle n'a pas de sens."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from mika.contracts import memory as c
from mika.faculties.memory import tables as tb
from mika.faculties.memory.archive import decode
from mika.faculties.memory.faculty import MEMORY, MemoryState
from mika.faculties.memory.inspect import OUTCOME_FR
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.operate import ActionContext, Done, Refused

SECTION = "memoire"
#: ce que l'opératrice peut dire d'un moment : il a eu lieu, il est annulé, reporté — « sans nouvelles » n'est pas
#: une correction
SETTLED = (c.HAPPENED, c.CANCELLED, c.MOVED)
OUTCOME_CHOICES = tuple((k, OUTCOME_FR[k][0]) for k in SETTLED)
#: ce qui se dément : un souvenir, une croyance
DENIABLE = (c.EPISODE_MEMORY, c.BELIEF)


class PromiseArgs(BaseModel):
    promise: Annotated[int, Knob(widget="hidden")] = Field(gt=0)


class MomentArgs(BaseModel):
    event: Annotated[int, Knob(widget="hidden")] = Field(gt=0)


class OutcomeArgs(BaseModel):
    event: Annotated[int, Knob(widget="hidden")] = Field(gt=0)
    outcome: Annotated[Literal["happened", "cancelled", "moved"],
                       Knob(label="Comment ça a tourné", choices=OUTCOME_CHOICES, advanced=False)] = c.HAPPENED


class ItemArgs(BaseModel):
    item: Annotated[int, Knob(widget="hidden")] = Field(gt=0)


# ── Offertes seulement si la tranche a de quoi les servir (lu à chaque carte : rien que la tranche) ──


def _promises_pending(s: MemoryState, frame: Frame, subject: str) -> bool:
    return bool(s.promises)


def _situations_lasting(s: MemoryState, frame: Frame, subject: str) -> bool:
    """Une situation qui dure encore : la tranche les garde toutes tant qu'elles ne sont pas finies."""
    return any(ev.ongoing and not ev.ended_at for ev in s.events.values())


def _moments_noted(s: MemoryState, frame: Frame, subject: str) -> bool:
    """Un moment noté un jour : l'archive garde ceux que la tranche a laissés (passés depuis longtemps)."""
    return s.life_seen


def _items_kept(s: MemoryState, frame: Frame, subject: str) -> bool:
    return s.items > 0


# ── Ses promesses ─────────────────────────────────────────────────────────


def _still_pending(promise: c.PendingPromise) -> Guard:
    """La correction ne vaut que si la promesse est encore en cours quand elle s'écrit : réglée entre-temps (tenue
    en le disant, échue), elle n'a plus rien à régler."""
    return Guard("promesse en cours", predicate=lambda view, pid=promise.id, to=promise.to: any(
        p.id == pid for p in view.get(c.PROMISES_TO(to))))


def _settle(s: MemoryState, args: PromiseArgs, status: str, message: str) -> Done:
    promise = s.promises.get(args.promise)
    if promise is None:
        raise Refused("Cette promesse n'est plus en cours : tenue, abandonnée ou oubliée.")
    draft = c.PROMISE_RESOLVED.draft(promise=promise.id, status=status, by=c.OPERATOR_BY,
                                     dedupe_key=f"promesse-opératrice:{promise.id}")
    return Done(drafts=(draft,), message=message, guard=_still_pending(promise))


@MEMORY.action("tenir", title="Marquer tenue", args=PromiseArgs, emits=[c.PROMISE_RESOLVED], section=SECTION,
               inline=True, available=_promises_pending, order=10,
               confirm="Marquer cette promesse tenue ? Elle comptera comme une parole tenue.",
               description="Elle l'a tenue sans que la relecture le voie : la promesse sort de ce qu'elle doit, et "
                           "compte comme une parole tenue.")
def _keep(s: MemoryState, frame: Frame, args: PromiseArgs, ctx: ActionContext) -> Done:
    return _settle(s, args, c.HONORED, "Promesse marquée tenue.")


@MEMORY.action("abandonner", title="Abandonner", args=PromiseArgs, emits=[c.PROMISE_RESOLVED], section=SECTION,
               inline=True, available=_promises_pending, order=11,
               confirm="Abandonner cette promesse ? Elle n'aura plus à la tenir, sans que ce soit une parole "
                       "laissée filer.",
               description="Elle n'a plus à la tenir (la personne n'en veut plus, ce n'en était pas une) : la "
                           "promesse sort de ce qu'elle doit, sans compter comme une parole laissée filer.")
def _drop(s: MemoryState, frame: Frame, args: PromiseArgs, ctx: ActionContext) -> Done:
    return _settle(s, args, c.DROPPED, "Promesse abandonnée.")


# ── La vie des autres ─────────────────────────────────────────────────────


def _moment(s: MemoryState, store: Any, event: int) -> c.LifeEvent | None:
    """Le moment tel qu'il est gardé : l'archive, qui garde tout (un moment passé depuis longtemps compris) ; la
    tranche seulement pour celui que l'archive n'a pas."""
    life = tb.life()
    if store is not None and tb.has_table(store, life):
        rows = store.query_mind(select(life.c.payload).where(life.c.id == event))
        if rows:
            return decode(rows[0][0])
    return s.events.get(event)


@MEMORY.action("finir", title="C'est fini", args=MomentArgs, emits=[c.SITUATION_ENDED], section=SECTION,
               inline=True, available=_situations_lasting, order=20,
               confirm="Cette situation est-elle finie ? Elle n'en prendra plus de nouvelles comme d'une chose en "
                       "cours.",
               description="La situation est finie : elle reste notée, mais elle n'en parle plus au présent.")
def _end(s: MemoryState, frame: Frame, args: MomentArgs, ctx: ActionContext) -> Done:
    ev = _moment(s, ctx.store, args.event)
    if ev is None or not ev.ongoing:
        raise Refused("Ce n'est pas une situation en cours : un moment daté, remplacé depuis, ou oublié.")
    if ev.ended_at:
        raise Refused("Cette situation est déjà finie.")
    # la même clé que la fin dite par la personne : la première fin compte, l'autre ne s'écrit pas
    draft = c.SITUATION_ENDED.draft(event=ev.id, dedupe_key=f"situation-finie:{ev.id}")
    return Done(drafts=(draft,), message="Situation marquée finie.")


@MEMORY.action("issue", title="Comment ça a tourné", args=OutcomeArgs, emits=[c.RESOLVED], section=SECTION,
               inline=True, available=_moments_noted, order=21,
               confirm="Dire comment ce moment a tourné ? Une issue ne se change plus ensuite.",
               description="Il a eu lieu, il est annulé ou reporté : elle le sait, une fois pour toutes — sans "
                           "émotion, et sans rien en apprendre sur qui l'avait annoncé ni sur ce qu'elle en "
                           "attendait.")
def _settle_moment(s: MemoryState, frame: Frame, args: OutcomeArgs, ctx: ActionContext) -> Done:
    ev = _moment(s, ctx.store, args.event)
    if ev is None:
        raise Refused("Ce moment n'est plus noté : remplacé depuis, ou oublié.")
    if ev.ongoing or ev.yearly:
        raise Refused("Seul un moment daté a une issue : une situation se finit, une date qui revient chaque année "
                      "n'en a pas.")
    if ev.outcome:
        raise Refused("Ce moment a déjà une issue : elle ne se change pas.")
    if args.outcome == c.HAPPENED and ev.when > frame.now:
        raise Refused("Ce moment n'a pas encore commencé : il ne peut pas avoir eu lieu.",
                      {"outcome": "Annulé ou reporté seulement, avant qu'il commence."})
    # ni attente, ni annonceur, ni surprise, ni valence : une correction ne se ressent pas et n'apprend rien ; la
    # même clé que l'issue dite par la personne (``life.resolution``) : un moment se tranche une fois
    draft = c.RESOLVED.draft(event=ev.id, thread=ev.key, outcome=args.outcome, by=c.OPERATOR_BY,
                             importance=ev.importance, about=ev.about, dedupe_key=f"issue:{ev.key}:{ev.when}")
    return Done(drafts=(draft,), message=f"Issue notée : {OUTCOME_FR[args.outcome][0]}.")


# ── Ce qu'elle sait ───────────────────────────────────────────────────────


@MEMORY.action("dementir", title="Ce n'est pas vrai", args=ItemArgs, emits=[c.RETRACTED], section=SECTION,
               inline=True, available=_items_kept, danger=True, order=30,
               confirm="Le démentir ? Elle ne le tiendra plus pour vrai et il ne lui reviendra plus ; son texte "
                       "reste au journal.",
               description="Ce qu'elle tient pour vrai ne l'est pas : l'élément sort de ce qu'elle sait et de ce "
                           "qui lui revient. Rien ne s'efface : son texte reste au journal, et la liste le montre "
                           "estompé.")
def _deny(s: MemoryState, frame: Frame, args: ItemArgs, ctx: ActionContext) -> Done:
    t = tb.items()
    rows = ctx.store.query_mind(select(t.c.kind, t.c.status).where(t.c.id == args.item)) \
        if ctx.store is not None and tb.has_table(ctx.store, t) else []
    if not rows or rows[0][0] not in DENIABLE:
        raise Refused("Seul un souvenir ou une croyance se dément, et celui-ci n'est plus noté.")
    if rows[0][1] != c.ACTIVE_STATUS:
        raise Refused("Elle ne le tient déjà plus pour sien : remplacé, fondu, joint, constaté ou démenti.")
    draft = c.RETRACTED.draft(item=args.item, dedupe_key=f"démenti:{args.item}")
    return Done(drafts=(draft,), message="Démenti : elle ne le tient plus pour vrai.")

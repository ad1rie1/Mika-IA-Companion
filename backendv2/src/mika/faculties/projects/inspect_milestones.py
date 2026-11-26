"""Les jalons d'un objectif dans la console (ADR 0273) — le nécessaire : sur la ligne de l'objectif, où il en est
(« jalons 2/4 », un point d'arrêt qui t'attend) ; dans son détail, ses jalons avec leur vérification, leur état et
leur preuve, et ce que le propriétaire y fait : ajouter un jalon, valider ou refuser un point d'arrêt. Un constant y
montre sa liste de passage (elle se règle par « Modifier l'objectif »). L'onglet Objectifs (``inspect.py``) appelle
``progress`` et ``detail`` ; la refonte de l'interface des projets est un autre lot.

Ses actions : ``projects.jalon_ajouter``, ``projects.jalon_trancher``, et (ADR 0290) ``projects.jalon_modifier``,
``projects.jalon_retirer`` — un jalon encore ouvert ; un point d'arrêt et un jalon tenu (ADR 0278) seulement par qui
tranche (``milestones.undoing``, ``tracker.frames`` ; leurs mots : ``HELD_WORDS``). La fiche dessinée et l'API par
personne passent par elles."""

from __future__ import annotations

import shlex
from collections.abc import Iterable, Mapping
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mika.contracts import projects as c
from mika.faculties.projects import milestones, reaching, tracker
from mika.faculties.projects.actions import can_edit
from mika.faculties.projects.faculty import (
    MILESTONE_ADDED,
    MILESTONE_CHANGED,
    PROJECTS,
    Milestone,
    Objective,
    ProjectsState,
    awaiting,
    inherited_for,
    milestone_at,
    milestones_of,
    written_for,
)
from mika.faculties.projects.inspect_common import (
    LIVE,
    acting_person,
    target_objective,
    target_project,
    unchanged,
)
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import ActionSlot, Badge, Column, Disclosure, Prose, Row, Table, Text
from mika.kernel.operate import ActionContext, Done, Refused

CHECK_CHOICES = ((c.CHECK_PROSE, "elle dit comment il est rempli"),
                 (c.CHECK_COMMAND, "une commande dans l'atelier, qui doit réussir"),
                 (c.CHECK_OWNER, "un point d'arrêt : tu le valides avant qu'elle continue"),
                 (c.CHECK_ITEM, "un ticket ou un élément du registre dans un statut donné"))
#: comment un jalon se vérifie, en court (« vérifié par une commande ») : les mots que disent l'écran Projets (par
#: l'API par personne) et la fiche de la console
CHECK_WORDS = {c.CHECK_PROSE: "sa parole", c.CHECK_COMMAND: "une commande", c.CHECK_OWNER: "un point d'arrêt",
               c.CHECK_ITEM: "un élément d'une liste"}
STATE_FR = {c.OPEN: "à faire", c.REACHED: "atteint", c.DROPPED: "retiré"}
STATE_TONE = {c.OPEN: "", c.REACHED: "ok", c.DROPPED: "muted"}
WAITING = Badge("t'attend", "warn")
VERDICTS = ((reaching.VALIDATE, "valider : le jalon est atteint, elle reprend"),
            (reaching.REFUSE, "refuser, avec ta raison : il lui revient"))
COLUMNS = (Column("n°", "fit"), Column("jalon"), Column("vérifié par"), Column("état", "fit"),
           Column("comment, et sa preuve"), Column("commit", "fit"))
FORGOTTEN = "(oublié)"
#: les titres de ce que le détail d'un objectif porte : la page dessinée les y retrouve (``app/handmade``)
TITLE, ROUTINE_TITLE = "Ses jalons", "À chaque passage"
REFUSALS = {"no_text": "Un jalon a un texte.", "bad_check": "Vérification inconnue.",
            "no_command": "Une vérification par commande demande sa commande.",
            "no_item": "Une vérification par élément demande sa liste, l'élément et le statut attendu."}
#: pourquoi un jalon ne se défait pas (``milestones.undoing``), en mots
HELD_WORDS = {
    milestones.SETTLED: "Ce jalon est atteint ou retiré : il ne bouge plus.",
    "breakpoint": "C'est un point d'arrêt : seul le propriétaire du projet, ou qui s'occupe d'elle, le défait.",
    "other": "Ce jalon a été posé par une personne : seul le propriétaire du projet, ou qui s'occupe d'elle, le "
             "défait.",
    "agreed": "Ce jalon vient d'un plan validé : seul le propriétaire du projet, ou qui s'occupe d'elle, le défait.",
    "refused": "Le propriétaire a refusé ce jalon : lui seul, ou qui s'occupe d'elle, le défait.",
}


def refs(objectives: Iterable[Objective]) -> list[str]:
    """Les textes des jalons (et des listes de passage) de ces objectifs, à lire avec ceux de l'onglet."""
    return [r for o in objectives for r in milestones.refs(o)]


def progress(o: Objective) -> str:
    """Où en est un objectif, pour sa ligne : « jalons 2/4 », et si un point d'arrêt t'attend (rien : sans jalon)."""
    alive = milestones_of(o)
    if not alive:
        return ""
    reached = sum(1 for m in alive if m.status == c.REACHED)
    return f"jalons {reached}/{len(alive)}" + (" · un point d'arrêt t'attend" if awaiting(o) is not None else "")


def _check(m: Milestone, texts: Mapping[str, str]) -> str:
    if m.check == c.CHECK_COMMAND:
        argv = milestones.decoded(texts.get(m.command_ref))
        return "la commande : " + (shlex.join(argv) if argv else FORGOTTEN)
    if m.check == c.CHECK_ITEM:
        return f"« {m.item_key} » de la liste « {m.item_list} » au statut « {m.item_status} »"
    return "toi (un point d'arrêt)" if m.check == c.CHECK_OWNER else "ce qu'elle en dit"


def _said(m: Milestone, texts: Mapping[str, str]) -> str:
    """Comment elle dit l'avoir rempli, sa preuve, et la raison d'un refus ou d'un retrait."""
    parts = []
    if m.how_ref and (m.status == c.REACHED or m.ready_at):
        parts.append(texts.get(m.how_ref) or FORGOTTEN)
    if m.proof_ref:
        parts.append("preuve : " + (texts.get(m.proof_ref) or FORGOTTEN))
    if m.reason_ref and (m.refused_at or m.status == c.DROPPED or m.revised):
        why = "refusé" if m.refused_at and m.status == c.OPEN else "retiré" if m.status == c.DROPPED else "révisé"
        parts.append(f"{why} : " + (texts.get(m.reason_ref) or FORGOTTEN))
    return " — ".join(parts) or "—"


def detail(o: Objective, texts: Mapping[str, str], editable: bool) -> list[Any]:
    """Ce que le détail d'un objectif montre de ses jalons, et ce qu'on y fait."""
    out: list[Any] = []
    if o.kind == c.CONSTANT:
        if texts.get(o.routine_ref):
            out.append(Prose(texts[o.routine_ref], title=ROUTINE_TITLE))
        return out
    if o.milestones:
        rows = [Row((m.id, Text(texts.get(m.text_ref) or FORGOTTEN, clamp=300), _check(m, texts),
                     WAITING if m.status == c.OPEN and m.ready_at else
                     Badge(STATE_FR.get(m.status, m.status), STATE_TONE.get(m.status, "")),
                     Text(_said(m, texts), clamp=400), m.commit[:12] or "—"),
                    tone="muted" if m.status == c.DROPPED else "")
                for m in o.milestones]
        out.append(Table(COLUMNS, tuple(rows), title=TITLE,
                         caption="« Fait » attend que chacun soit atteint. Un jalon atteint ne se défait pas."))
    if not editable:
        return out
    held = awaiting(o)
    if held is not None:
        out.append(Disclosure(f"Valider ou refuser le point d'arrêt n° {held.id}", (
            ActionSlot("projects.jalon_trancher", (("objective", str(o.id)), ("milestone", str(held.id)),
                                                   ("verdict", reaching.VALIDATE)), title="Trancher", compact=True),),
            open=True))
    if o.status in (c.OPEN, c.BLOCKED) and len(milestones_of(o)) < c.MILESTONES_MAX:
        out.append(Disclosure("Ajouter un jalon", (
            ActionSlot("projects.jalon_ajouter", (("objective", str(o.id)),), title="Ajouter un jalon",
                       compact=True),)))
    return out


class AddArgs(BaseModel):
    objective: Annotated[str, Knob(label="Objectif", widget="hidden")] = Field(min_length=1, max_length=12)
    text: Annotated[str, Knob(label="Jalon", widget="textarea", advanced=False, order=1,
                              help="En une phrase : ce qui sera vrai quand il sera atteint.")
                    ] = Field(min_length=1, max_length=milestones.TEXT_MAX)
    check: Annotated[str, Knob(label="Vérifié par", choices=CHECK_CHOICES, advanced=False, order=2)] = c.CHECK_PROSE
    command: Annotated[str, Knob(label="Sa commande", advanced=False, order=3,
                                 help="Pour une vérification par commande : telle qu'on la taperait (« pytest -q "
                                      "tests »). Elle la lance dans l'atelier, sans réseau, quand elle dit le jalon "
                                      "atteint.")] = Field(default="", max_length=2000)
    item_list: Annotated[str, Knob(label="Liste de l'élément", advanced=False, order=4,
                                   help="Pour une vérification par élément : « tickets », ou une liste de suivi.")
                         ] = Field(default="", max_length=40)
    item: Annotated[str, Knob(label="Élément", advanced=False, order=5,
                              help="Sa clé, ou le numéro du ticket.")] = Field(default="", max_length=61)
    item_status: Annotated[str, Knob(label="Statut attendu", advanced=False, order=6)] = Field(default="",
                                                                                               max_length=24)


@PROJECTS.action("jalon_ajouter", title="Ajouter un jalon", args=AddArgs, emits=[MILESTONE_ADDED], subject="project",
                 order=33, available=can_edit, inline=True,
                 description="Un jalon de plus sur un objectif ponctuel : elle le verra à sa prochaine exécution, et "
                             "« fait » l'attendra.")
def _add(s: ProjectsState, frame: Frame, args: AddArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    o = target_objective(p, args.objective)
    if o.kind != c.ONCE:
        raise Refused("Un objectif constant n'a pas de jalons : donne-lui ce que chaque passage doit faire "
                      "(« Modifier l'objectif »).")
    if o.status not in (c.OPEN, c.BLOCKED):
        raise Refused("Cet objectif n'est plus ouvert : rouvre-le avant de lui ajouter un jalon.")
    if len(milestones_of(o)) >= c.MILESTONES_MAX:
        raise Refused(f"Cet objectif a déjà {c.MILESTONES_MAX} jalons : elle doit en retirer un d'abord.")
    try:
        argv = tuple(shlex.split(args.command))
    except ValueError as exc:
        raise Refused("Cette commande ne se lit pas (un guillemet n'est pas fermé).",
                      {"command": "commande illisible"}) from exc
    spec = milestones.Spec(args.text, args.check, argv, args.item_list, args.item, args.item_status)
    if why := milestones.problem(spec):
        field = {"no_command": "command", "no_item": "item", "bad_check": "check"}.get(why, "text")
        raise Refused(REFUSALS[why], {field: "valeur requise"})
    draft = milestones.adding(p, o.id, o.milestone_seq + 1, spec, level=written_for(p, o),
                              inherited=inherited_for(p, o), author="operator", by=acting_person(frame, ctx))
    return Done(drafts=(draft,), message=f"Jalon ajouté à l'objectif n° {o.id}.", guard=unchanged(p.id, LIVE))


class SettleArgs(BaseModel):
    objective: Annotated[str, Knob(label="Objectif", widget="hidden")] = Field(min_length=1, max_length=12)
    milestone: Annotated[str, Knob(label="Jalon", widget="hidden")] = Field(min_length=1, max_length=12)
    verdict: Annotated[str, Knob(label="Ce que tu en fais", choices=VERDICTS, advanced=False, order=1)
                       ] = reaching.VALIDATE
    reason: Annotated[str, Knob(label="Ta raison, ou ton mot", widget="textarea", advanced=False, order=2,
                                help="Demandée pour refuser : elle la lira à sa prochaine exécution. Gardée avec le "
                                     "jalon.")] = Field(default="", max_length=milestones.REASON_MAX)


@PROJECTS.action("jalon_trancher", title="Trancher un point d'arrêt", args=SettleArgs, emits=[MILESTONE_CHANGED],
                 subject="project", order=34, available=can_edit, inline=True,
                 description="Valider ou refuser un point d'arrêt qu'elle a dit prêt : validé, le jalon est atteint et "
                             "elle reprend ; refusé, il lui revient avec ta raison.")
def _settle(s: ProjectsState, frame: Frame, args: SettleArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    o = target_objective(p, args.objective)
    m = milestone_at(o, args.milestone)
    if m is None or m.status != c.OPEN or not m.ready_at:
        raise Refused("Ce jalon n'attend pas ta validation.")
    if args.verdict not in (reaching.VALIDATE, reaching.REFUSE):
        raise Refused("Verdict inconnu.", {"verdict": "valider ou refuser"})
    if args.verdict == reaching.REFUSE and not args.reason.strip():
        raise Refused("Un point d'arrêt ne se refuse pas sans dire pourquoi.", {"reason": "valeur requise"})
    draft = reaching.settling(p, o, m, args.verdict, author="operator", by=acting_person(frame, ctx), text=args.reason)
    said = "validé : elle reprend" if args.verdict == reaching.VALIDATE else "refusé : il lui revient"
    return Done(drafts=(draft,), message=f"Jalon n° {m.id} de l'objectif n° {o.id} {said}.",
                guard=unchanged(p.id, LIVE))


# ── Le modifier, le retirer ───────────────────────────────────────────────


class MilestoneEditArgs(BaseModel):
    objective: Annotated[str, Knob(label="Objectif", widget="hidden")] = Field(min_length=1, max_length=12)
    milestone: Annotated[str, Knob(label="Jalon", widget="hidden")] = Field(min_length=1, max_length=12)
    text: Annotated[str, Knob(label="Jalon", widget="textarea", advanced=False, order=1)
                    ] = Field(min_length=1, max_length=milestones.TEXT_MAX)
    check: Annotated[str, Knob(label="Vérifié par", advanced=False, order=2)] = c.CHECK_PROSE
    command: Annotated[str, Knob(label="Sa commande", advanced=False, order=3)] = Field(default="", max_length=2000)
    item_list: Annotated[str, Knob(label="Liste de l'élément", advanced=False, order=4)] = Field(default="",
                                                                                               max_length=40)
    item: Annotated[str, Knob(label="Élément", advanced=False, order=5)] = Field(default="", max_length=61)
    item_status: Annotated[str, Knob(label="Statut attendu", advanced=False, order=6)] = Field(default="",
                                                                                               max_length=24)
    reason: Annotated[str, Knob(label="Pourquoi", widget="textarea", advanced=False, order=7,
                                help="Facultatif : gardé avec le jalon, elle le lira.")
                      ] = Field(default="", max_length=milestones.REASON_MAX)


def _milestone(s: ProjectsState, frame: Frame, ctx: ActionContext, objective: str, milestone: str) -> tuple[Any, ...]:
    """Le jalon visé, s'il peut encore être défait par qui agit (``milestones.undoing``)."""
    p = target_project(s, ctx)
    o = target_objective(p, objective)
    m = milestone_at(o, milestone)
    if m is None:
        raise Refused(f"Aucun jalon n° {milestone[:12]} sur cet objectif.")
    person = acting_person(frame, ctx)
    if why := milestones.undoing(m, tracker.frames(frame, p, person)):
        raise Refused(HELD_WORDS.get(why, HELD_WORDS["other"]))
    return p, o, m, person


@PROJECTS.action("jalon_modifier", title="Modifier un jalon", args=MilestoneEditArgs, emits=[MILESTONE_CHANGED],
                 subject="project", order=35, available=can_edit, inline=True,
                 description="Le texte d'un jalon encore ouvert, et comment on le vérifie.")
def _milestone_edit(s: ProjectsState, frame: Frame, args: MilestoneEditArgs, ctx: ActionContext) -> Done:
    p, o, m, person = _milestone(s, frame, ctx, args.objective, args.milestone)
    try:
        argv = tuple(shlex.split(args.command))
    except ValueError as exc:
        raise Refused("Cette commande ne se lit pas (un guillemet n'est pas fermé).",
                      {"command": "commande illisible"}) from exc
    spec = milestones.Spec(args.text, args.check, argv, args.item_list, args.item, args.item_status)
    if why := milestones.problem(spec):
        field = {"no_command": "command", "no_item": "item", "bad_check": "check"}.get(why, "text")
        raise Refused(REFUSALS[why], {field: "valeur requise"})
    draft = milestones.changing(p, o.id, m, level=written_for(p, o), inherited=inherited_for(p, o),
                                author="operator", by=person, spec=spec, reason=args.reason)
    return Done(drafts=(draft,), message=f"Jalon n° {m.id} de l'objectif n° {o.id} modifié.",
                guard=unchanged(p.id, LIVE))


class MilestoneDropArgs(BaseModel):
    objective: Annotated[str, Knob(label="Objectif", widget="hidden")] = Field(min_length=1, max_length=12)
    milestone: Annotated[str, Knob(label="Jalon", widget="hidden")] = Field(min_length=1, max_length=12)
    reason: Annotated[str, Knob(label="Pourquoi", widget="textarea", advanced=False, order=1,
                                help="Facultatif : gardé avec le jalon retiré.")
                      ] = Field(default="", max_length=milestones.REASON_MAX)


@PROJECTS.action("jalon_retirer", title="Retirer un jalon", args=MilestoneDropArgs, emits=[MILESTONE_CHANGED],
                 subject="project", order=36, available=can_edit, inline=True, danger=True,
                 description="Un jalon encore ouvert n'a plus lieu d'être : « fait » ne l'attendra plus. Il reste "
                             "lisible, retiré.")
def _milestone_drop(s: ProjectsState, frame: Frame, args: MilestoneDropArgs, ctx: ActionContext) -> Done:
    p, o, m, person = _milestone(s, frame, ctx, args.objective, args.milestone)
    draft = milestones.changing(p, o.id, m, level=written_for(p, o), inherited=inherited_for(p, o),
                                author="operator", by=person, status=c.DROPPED, reason=args.reason)
    return Done(drafts=(draft,), message=f"Jalon n° {m.id} de l'objectif n° {o.id} retiré.", guard=unchanged(p.id, LIVE))

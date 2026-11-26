"""Gérer un projet depuis l'espace d'une personne (ADR 0290) : les actions que la console n'avait pas, et leurs mots.

L'écran Projets modifie ce qu'il montre. La plupart de ses gestes passent par une action que la console déclare déjà
(``actions.py``, ``inspect_milestones.py``, ``inspect_tracker.py``) ; celles d'ici comblent ce qui manquait :

- ``projects.projet_confier`` : un projet demandé depuis l'écran — il naît **à cadrer**, avec les mots de qui le
  demande (ADR 0145), comme ``create_project`` en conversation, et pour qui s'occupe d'elle seulement ;
- ``projects.jalon_modifier``, ``projects.jalon_retirer`` : un jalon encore ouvert ; un point d'arrêt et un jalon tenu
  (ADR 0278) seulement par qui tranche (``managing.undoing``) ;
- ``projects.ticket_modifier`` : le titre, le texte, la sorte et la priorité d'un ticket ;
- ``projects.decision_modifier`` : les textes d'une décision technique qui n'est pas remplacée ;
- ``projects.pull_modifier``, ``projects.pull_commenter`` : le titre et le texte d'une pull request, un commentaire —
  le geste d'une personne, qui pose un fait ; l'effet part ensuite chez l'hôte (``managing.py``).

Des textes de console et d'écran, lus par qui décide — pas des phrases qu'elle lit. La console n'a pas encore le
formulaire de ces actions : elles se font par l'API de la personne (``app/domains/projects/api/manage.py``).
"""

from __future__ import annotations

import shlex
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects import managing, milestones, tracker
from mika.faculties.projects.actions import MODE_CHOICES, OTHER_RULE, SCHEDULE_CHOICES, can_edit
from mika.faculties.projects.faculty import (
    ASAP,
    MILESTONE_CHANGED,
    OBJECTIVE_ADDED,
    PROJECTS,
    ProjectsState,
    check_schedule,
    decision_at,
    inherited_for,
    milestone_at,
    objectives_of,
    opened,
    written_for,
)
from mika.faculties.projects.inspect_common import (
    LIVE,
    operator_person,
    target_objective,
    target_project,
    unchanged,
)
from mika.faculties.projects.inspect_milestones import REFUSALS
from mika.faculties.projects.inspect_tracker import KIND_CHOICES, PRIORITY_CHOICES, target_entry
from mika.kernel.events import Content
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.operate import ActionContext, Done, Refused
from mika.vocab.privacy import Sensitivity

#: pourquoi un jalon ne se défait pas (``managing.undoing``), en mots
HELD_WORDS = {
    managing.SETTLED: "Ce jalon est atteint ou retiré : il ne bouge plus.",
    "breakpoint": "C'est un point d'arrêt : seul le propriétaire du projet, ou qui s'occupe d'elle, le défait.",
    "other": "Ce jalon a été posé par une personne : seul le propriétaire du projet, ou qui s'occupe d'elle, le "
             "défait.",
    "agreed": "Ce jalon vient d'un plan validé : seul le propriétaire du projet, ou qui s'occupe d'elle, le défait.",
    "refused": "Le propriétaire a refusé ce jalon : lui seul, ou qui s'occupe d'elle, le défait.",
}
NOT_KEEPER = "Seul qui s'occupe d'elle lui confie un projet d'ici."
NOT_WRITER = ("Seul le propriétaire du projet, ou qui s'occupe d'elle, écrit chez l'hôte sur une pull request : elle, "
              "jamais.")
NOT_WRITABLE = "Cet objectif n'a pas de pull request ouverte chez l'hôte."
#: pourquoi ce qu'une personne a écrit sur une pull request n'est pas parti (``PullWriteAnswered.why``)
WRITE_WORDS = {
    managing.STALE: "la pull request avait changé entre-temps",
    managing.NO_HOST: "aucun hôte ne sait l'écrire sur ce dépôt",
    managing.FORGOTTEN: "son texte ne se lit plus",
    managing.REFUSED: "l'hôte a refusé, ou n'a pas répondu",
    managing.CUT: "la demande a été interrompue — relis la pull request chez l'hôte",
}
ENTRUSTED = "Projet confié : elle relit ta demande, pose ses questions, puis te propose un plan."
EDIT_ASKED = "Modification demandée chez l'hôte, à ton nom : la pull request se relit dans un instant."
COMMENT_ASKED = "Commentaire demandé chez l'hôte : il part du compte du jeton, et dit qu'il est de toi."


def writer(frame: Frame, ctx: ActionContext) -> str:
    """La personne qui agit : celle de son compte."""
    return operator_person(frame, ctx) or ctx.by


# ── Confier un projet ─────────────────────────────────────────────────────


class EntrustArgs(BaseModel):
    title: Annotated[str, Knob(label="Son nom", advanced=False, order=1)] = Field(min_length=1, max_length=200)
    request: Annotated[str, Knob(label="Ce que tu veux", widget="textarea", advanced=False, order=2,
                                 help="Dis-le comme tu le dirais à quelqu'un : elle garde tes mots tels quels.")
                       ] = Field(default="", max_length=2000)
    mode: Annotated[str, Knob(label="Mode de travail", choices=MODE_CHOICES, advanced=False, order=3)] = c.PERSONA
    schedule: Annotated[str, Knob(label="Agenda", choices=SCHEDULE_CHOICES, advanced=False, order=4)
                        ] = Field(default=ASAP, max_length=120)
    schedule_rule: Annotated[str, Knob(label="Sa règle", advanced=False, order=5,
                                       only=(("schedule", (OTHER_RULE,)),))] = Field(default="", max_length=120)


@PROJECTS.action("projet_confier", title="Confier un projet", args=EntrustArgs,
                 emits=[c.PROJECT_CREATED, OBJECTIVE_ADDED], order=11,
                 description="Un projet demandé en quelques mots : il naît à cadrer — elle relit la demande, pose ses "
                             "questions et propose un plan avant de s'y mettre.")
def _entrust(s: ProjectsState, frame: Frame, args: EntrustArgs, ctx: ActionContext) -> Done:
    person = writer(frame, ctx)
    if not person or not frame.get(identity_c.IS_OWNER(person)):
        raise Refused(NOT_KEEPER)
    errors: dict[str, str] = {}
    title = args.title.strip()
    if not title:
        errors["title"] = "valeur requise"
    if args.mode not in c.MODES:
        errors["mode"] = "mode inconnu"
    other = args.schedule.strip() == OTHER_RULE
    where, rule = ("schedule_rule", args.schedule_rule.strip()) if other else ("schedule", args.schedule.strip())
    try:
        rule = check_schedule(rule or ASAP)
    except ValueError as exc:
        errors[where] = f"règle refusée : {exc}"
    if errors:
        raise Refused("Le projet n'a pas été confié : vérifie le formulaire.", errors)
    level, about = int(Sensitivity.PERSONAL), (person,)
    draft = opened(title=title, description="", authority=c.USER, mode=args.mode, owner=person, address=ctx.by or None,
                   about=about, level=level, source="space", schedule_rule=rule, request=args.request.strip() or title,
                   asked_by=person, framing=True)

    def objectives(seqs: tuple[int, ...]) -> list[Any]:
        """Une idée de départ, que son plan gardera, réécrira ou retirera (ADR 0145)."""
        return objectives_of(seqs[0], [title], [], author="owner", by=ctx.by, owner=person, about=about, level=level)

    return Done(drafts=(draft,), then=objectives, message=ENTRUSTED)


# ── Ses jalons ────────────────────────────────────────────────────────────


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
    """Le jalon visé, s'il peut encore être défait par qui agit (``managing.undoing``)."""
    p = target_project(s, ctx)
    o = target_objective(p, objective)
    m = milestone_at(o, milestone)
    if m is None:
        raise Refused(f"Aucun jalon n° {milestone[:12]} sur cet objectif.")
    person = writer(frame, ctx)
    if why := managing.undoing(m, managing.frames(frame, p, person)):
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


# ── Un ticket ─────────────────────────────────────────────────────────────


class TicketEditArgs(BaseModel):
    item: Annotated[str, Knob(label="Ticket", widget="hidden")] = Field(min_length=1, max_length=tracker.KEY_MAX + 1)
    title: Annotated[str, Knob(label="Titre", advanced=False, order=1)] = Field(min_length=1,
                                                                               max_length=tracker.TITLE_MAX)
    text: Annotated[str, Knob(label="Détail", widget="textarea", advanced=False, order=2)
                    ] = Field(default="", max_length=tracker.TEXT_MAX)
    kind: Annotated[str, Knob(label="Sorte", choices=KIND_CHOICES, advanced=False, order=3)] = c.TASK
    priority: Annotated[str, Knob(label="Priorité", choices=PRIORITY_CHOICES, advanced=False, order=4)] = c.NORMAL


@PROJECTS.action("ticket_modifier", title="Modifier un ticket", args=TicketEditArgs, emits=[tracker.ITEM_CHANGED],
                 subject="project", order=68, available=can_edit, inline=True,
                 description="Le titre, le détail, la sorte et la priorité d'un ticket. Son étape ne change pas.")
def _ticket_edit(s: ProjectsState, frame: Frame, args: TicketEditArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    e = target_entry(p, ctx, tracker.TICKET_LIST, args.item)
    item = e.item
    title, text = args.title.strip(), args.text.strip()
    if not title:
        raise Refused("Le titre est vide.", {"title": "valeur requise"})
    if args.kind not in c.TICKET_KINDS or args.priority not in c.PRIORITIES:
        raise Refused("Sorte ou priorité inconnue.")
    changes: dict[str, Any] = {}
    if title != e.title.strip():
        changes["title"] = title
    if text and text != e.body.strip():
        changes["text"] = text
    if args.kind != item.kind:
        changes["kind"] = args.kind
    if args.priority != item.priority:
        changes["priority"] = args.priority
    if not changes:
        raise Refused("Rien n'a changé.")
    draft = tracker.changing(p, item, author=c.BY_OPERATOR, by=writer(frame, ctx), **changes)
    return Done(drafts=(draft,), message=f"Ticket #{item.number} modifié.", guard=unchanged(p.id, LIVE))


# ── Une décision technique ────────────────────────────────────────────────


class DecisionEditArgs(BaseModel):
    decision: Annotated[str, Knob(label="Décision", widget="hidden")] = Field(min_length=1, max_length=12)
    title: Annotated[str, Knob(label="La question tranchée", advanced=False, order=1)
                     ] = Field(min_length=1, max_length=200)
    choice: Annotated[str, Knob(label="Ce qui est choisi", widget="textarea", advanced=False, order=2)
                      ] = Field(min_length=1, max_length=1500)
    reason: Annotated[str, Knob(label="Pourquoi", widget="textarea", advanced=False, order=3)
                      ] = Field(default="", max_length=1500)
    context: Annotated[str, Knob(label="Le contexte", widget="textarea", order=4)] = Field(default="",
                                                                                         max_length=2000)
    options: Annotated[str, Knob(label="Les options envisagées", widget="textarea", order=5)
                       ] = Field(default="", max_length=2000)


@PROJECTS.action("decision_modifier", title="Modifier une décision", args=DecisionEditArgs,
                 emits=[managing.DECISION_REVISED], subject="project", order=42, available=can_edit, inline=True,
                 description="Les textes d'une décision technique. Pour revenir sur ce qu'elle choisit, remplace-la "
                             "plutôt : l'ancienne reste lisible.")
def _decision_edit(s: ProjectsState, frame: Frame, args: DecisionEditArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    d = decision_at(p, args.decision)
    if d is None:
        raise Refused(f"Aucune décision n° {args.decision[:12]}.")
    if d.status == c.SUPERSEDED:
        raise Refused(f"La décision n° {d.id} a été remplacée (par D{d.replaced_by}) : c'est celle-là qu'on change.")
    store = (ctx.ports or {}).get("store")
    refs = {"title": d.title_ref, "choice": d.choice_ref, "context": d.context_ref, "options": d.options_ref,
            "reason": d.reason_ref}
    texts = store.content([r for r in refs.values() if r]) if store is not None else {}
    level = p.sensitivity
    changes: dict[str, Any] = {}
    cleared: list[str] = []
    for name, ref in refs.items():
        new, old = getattr(args, name).strip(), texts.get(ref, "").strip()
        if new == old:
            continue
        if new:
            changes[name] = Content.of(new, level=level)
        elif name in managing.OPTIONAL and ref:
            cleared.append(name)
    if not changes and not cleared:
        raise Refused("Rien n'a changé.")
    draft = managing.DECISION_REVISED.draft(project=p.id, decision=d.id, cleared=tuple(cleared),
                                            by=writer(frame, ctx), owner=p.owner, about=p.about,
                                            read_about=p.read_about, **changes)
    return Done(drafts=(draft,), message=f"Décision n° {d.id} modifiée.", guard=unchanged(p.id, LIVE))


# ── Écrire chez l'hôte sur une pull request ───────────────────────────────


def _pull(s: ProjectsState, frame: Frame, ctx: ActionContext, objective: str) -> tuple[Any, ...]:
    """La pull request ouverte d'un objectif, pour qui a le droit d'y écrire : le propriétaire du projet, ou qui
    s'occupe d'elle."""
    p = target_project(s, ctx)
    o = target_objective(p, objective)
    person = writer(frame, ctx)
    if not managing.frames(frame, p, person):
        raise Refused(NOT_WRITER)
    if not managing.writable(p, o):
        raise Refused(NOT_WRITABLE)
    return p, o, person


class PullEditArgs(BaseModel):
    objective: Annotated[str, Knob(label="Objectif", widget="hidden")] = Field(min_length=1, max_length=12)
    title: Annotated[str, Knob(label="Son titre", advanced=False, order=1)
                     ] = Field(default="", max_length=managing.TITLE_MAX)
    body: Annotated[str, Knob(label="Son texte", widget="textarea", advanced=False, order=2)
                    ] = Field(default="", max_length=managing.BODY_MAX)


@PROJECTS.action("pull_modifier", title="Modifier la pull request", args=PullEditArgs,
                 emits=[managing.PULL_WRITE_ASKED], subject="project", order=69, available=can_edit, inline=True,
                 description="Le titre et le texte d'une pull request, chez l'hôte. Ton geste : elle n'y écrit pas "
                             "ainsi. Un champ laissé vide ne change pas.")
def _pull_edit(s: ProjectsState, frame: Frame, args: PullEditArgs, ctx: ActionContext) -> Done:
    p, o, person = _pull(s, frame, ctx, args.objective)
    if not args.title.strip() and not args.body.strip():
        raise Refused("Dis ce qui change : son titre, son texte, ou les deux.", {"title": "valeur requise"})
    draft = managing.writing(p, o, person, title=args.title, body=args.body)
    return Done(drafts=(draft,), message=EDIT_ASKED, guard=unchanged(p.id, LIVE))


class PullCommentArgs(BaseModel):
    objective: Annotated[str, Knob(label="Objectif", widget="hidden")] = Field(min_length=1, max_length=12)
    text: Annotated[str, Knob(label="Ton commentaire", widget="textarea", advanced=False, order=1)
                    ] = Field(min_length=1, max_length=managing.COMMENT_MAX)


@PROJECTS.action("pull_commenter", title="Répondre dans la pull request", args=PullCommentArgs,
                 emits=[managing.PULL_WRITE_ASKED], subject="project", order=70, available=can_edit, inline=True,
                 description="Un commentaire sur une pull request, chez l'hôte : il part du compte du jeton, et son "
                             "texte dit qu'il est de toi.")
def _pull_comment(s: ProjectsState, frame: Frame, args: PullCommentArgs, ctx: ActionContext) -> Done:
    p, o, person = _pull(s, frame, ctx, args.objective)
    if not args.text.strip():
        raise Refused("Le commentaire est vide.", {"text": "valeur requise"})
    draft = managing.writing(p, o, person, comment=args.text)
    return Done(drafts=(draft,), message=COMMENT_ASKED, guard=unchanged(p.id, LIVE))

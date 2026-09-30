"""Ce qu'un opérateur peut faire de ses buts depuis la console.

Des opérations seulement : lui **confier** un projet et en **modifier** le
cadre (titre, cadre, pour qui, échéance, agenda, pas, accord, priorité),
**reprogrammer** un rappel, **suspendre** un but puis le **reprendre**, le
faire **avancer maintenant**, lui donner une **consigne**, tenir avec elle son
**plan de travail** (des tâches), **approuver ou refuser** ce qu'il veut faire
sortir de la machine, **déposer** un fichier dans son atelier, le **clore**,
le **rouvrir**. Sur ce qu'elle a entrepris d'elle-même, on pilote sans
réécrire : ni son titre, ni son envie. Jamais ce qu'elle en pense ni ce
qu'elle en ressent : un but annulé ou rouvert ne la rend ni fière ni
frustrée, une consigne s'ajoute au cadre sans réécrire son carnet.

Chaque action rend les brouillons de ses propres événements ; le moteur de la
console les journalise avec l'origine « extérieure », sous une garde qui
refuse d'agir sur un but qui a changé entre-temps.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from mika.contracts import goals as c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.faculties.goals.faculty import (
    GOAL_AMENDED,
    GOAL_DEPOSITED,
    GOAL_NUDGED,
    GOAL_PAUSED,
    GOAL_REFRAMED,
    GOAL_REOPENED,
    GOAL_RESUMED,
    GOALS,
    TASK_ADDED,
    TASK_CHANGED,
    TASK_REMOVED,
    TASKS_KEPT,
    Goal,
    GoalsState,
    Task,
    budget,
    goal_at,
    live,
    params,
    status,
    task_at,
    workable,
)
from mika.faculties.goals.tools import closing, project_opened
from mika.kernel import schedule
from mika.kernel.clock import DAY, instant, local
from mika.kernel.events import Content
from mika.kernel.forms import UPLOAD_MAX, Knob, Upload
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.operate import ActionContext, Decision, Done, Refused
from mika.ports.workshop import OutsideWorkshop
from mika.vocab.episodes import goal_of
from mika.vocab.privacy import Sensitivity

#: une échéance au-delà est sans doute une faute de frappe
DUE_HORIZON = 3 * 366 * DAY
#: une date sans heure : en fin de journée
DEFAULT_HOUR = 18
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:(?:\s+|t)(?:à\s*)?(\d{1,2})\s*[:h]\s*(\d{2})?)?$")
_FR = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?(?:\s+(?:à\s*)?(\d{1,2})\s*[:h]\s*(\d{2})?)?$")
CANCELLED_REASON = "annulé par un opérateur"


def parse_due(text: str, tz: ZoneInfo, now: int) -> int:
    """Une échéance tapée à la française (« 2026-10-02 18:00 », « 02/10/2026 à
    18h », « 02/10 18h30 », une date seule = 18 h), en heure locale ; lève
    ``ValueError`` avec la raison, en français."""
    raw = " ".join(text.strip().lower().split())  # « 18H », « 2026-10-02T18:00 » : en minuscules
    iso, fr = _ISO.match(raw), _FR.match(raw)
    if iso is not None:
        year, month, day, hour, minute = iso.groups()
    elif fr is not None:
        day, month, year, hour, minute = fr.groups()
    else:
        raise ValueError("date illisible : écris-la « 2026-10-02 18:00 » ou « 02/10/2026 18h »")
    if year is None:
        y = local(now, tz).year
    else:
        y = int(year) + (2000 if len(year) == 2 else 0)
    h, m = (int(hour), int(minute or 0)) if hour is not None else (DEFAULT_HOUR, 0)
    try:
        due = instant(datetime(y, int(month), int(day), h, m, tzinfo=tz))
        if year is None and due <= now:  # « 02/10 » sans année : le prochain
            due = instant(datetime(y + 1, int(month), int(day), h, m, tzinfo=tz))
    except ValueError:
        raise ValueError("cette date n'existe pas (jour, mois ou heure hors bornes)") from None
    if due <= now:
        raise ValueError("cette date est déjà passée")
    if due > now + DUE_HORIZON:
        raise ValueError("c'est trop loin : trois ans au plus")
    return due


def _known_person(frame: Frame, key: str, *also: str | None) -> str | None:
    """La clé de personne de ``key`` si l'identité la connaît (une poignée vue, une
    propriétaire déclarée) ou si c'est l'une de ``also`` (l'opérateur lui-même, la
    personne que le but a déjà : un opérateur qui n'a jamais parlé par le chat n'a pas
    de poignée, et n'en reste pas moins quelqu'un), sinon rien."""
    person = frame.get(identity_c.PERSON(key))
    if frame.get(identity_c.HANDLES(person)) or person in frame.get(identity_c.OWNERS):
        return person
    if person in {a for a in also if a} or key in {a for a in also if a}:
        return person
    return None


def _still(goal: int, wanted: tuple[str, ...]) -> Guard:
    """L'opération ne vaut que si le but est toujours dans l'état où l'opérateur l'a vu."""
    return Guard("but inchangé", predicate=lambda view, g=goal: view.get(c.STATUS(g)) in wanted)


# ── Confier un projet ─────────────────────────────────────────────────────


PRIORITY_CHOICES = ((c.LOW, "basse"), (c.NORMAL, "normale"), (c.HIGH, "haute"), (c.URGENT, "urgente"))
PRIORITY_HELP = ("Entre deux buts qui peuvent avancer, le plus prioritaire passe devant. Elle ne contourne ni "
                 "le plafond de pas par heure, ni le sommeil.")

#: des agendas courants (proposés ; une autre règle se tape)
SCHEDULES = (("manual", "dès qu'elle peut (manuel)"), ("interval:30m", "toutes les 30 min"),
             ("interval:2h", "toutes les 2 h"), ("interval:6h", "toutes les 6 h"),
             ("cron:0 9 * * *", "chaque jour à 9 h"), ("cron:0 9 * * MON-FRI", "les jours ouvrés à 9 h"),
             ("cron:0 18 * * SUN", "le dimanche à 18 h"))


class ConfideArgs(BaseModel):
    title: Annotated[str, Knob(label="Titre", help="Ce qu'elle doit mener à bout, en quelques mots : il nomme le "
                                                   "projet partout (liste, fiche, ce qu'elle en raconte).",
                               group="Le projet", advanced=False, order=10),
                     Field(max_length=120)]
    details: Annotated[str, Knob(label="Le cadre", widget="textarea", group="Le projet", advanced=False, order=20,
                                 help="Ce qu'il faut faire, comment, et ce qui est hors sujet. Elle le lit à chaque "
                                      "pas et ne le modifiera jamais ; tu pourras ajouter des consignes ensuite."),
                       Field(max_length=2000)] = ""
    owner: Annotated[str, Knob(label="Pour qui", widget="subject", subject="person", group="Le projet",
                               advanced=False, order=30,
                               help="La personne pour qui elle travaille (elle lui en parle, lui raconte le "
                                    "résultat). Vide : pour toi."),
                     Field(max_length=120)] = ""
    due: Annotated[str, Knob(label="Échéance", widget="datetime", group="Son rythme", advanced=False, order=40,
                             help="Facultative, en heure locale. Sans heure : 18 h. Plus elle approche, plus elle "
                                  "s'y met."),
                   Field(max_length=40)] = ""
    schedule: Annotated[str, Knob(label="Agenda", widget="suggest", choices=SCHEDULES, group="Son rythme",
                                  advanced=False, order=50,
                                  help="Quand elle y avance : « manual » dès qu'elle peut, « interval:2h » toutes "
                                       "les deux heures, « cron:0 9 * * MON-FRI » les jours ouvrés à 9 h."),
                        Field(max_length=120)] = "manual"
    max_steps: Annotated[int, Knob(label="Pas au plus", group="Son rythme", advanced=False, order=60,
                                   help="Combien de pas de travail au plus avant de s'arrêter. 0 : la valeur par "
                                        "défaut (Configuration › Comportement › Buts)."),
                         Field(ge=0, le=50)] = 0
    approval: Annotated[bool, Knob(label="Ce qui sort de la machine attend ton accord", group="Sa liberté",
                                   advanced=False, order=70,
                                   help="Un mail, une commande avec le réseau : rien ne part sans que tu l'approuves "
                                        "(Approbations). Dans son atelier, elle travaille librement.")] = True
    priority: Annotated[str, Knob(label="Priorité", choices=PRIORITY_CHOICES, group="Son rythme", advanced=False,
                                  order=65, help=PRIORITY_HELP)] = c.NORMAL


@GOALS.action("confier", title="Confier un projet", args=ConfideArgs, emits=[c.GOAL_OPENED], section="buts",
              order=10, description="Un travail qu'elle mènera par pas, dans son atelier, avec ce cadre.")
def _confide(s: GoalsState, frame: Frame, args: ConfideArgs, ctx: ActionContext) -> Done:
    errors: dict[str, str] = {}
    if not args.title.strip():
        errors["title"] = "valeur requise"
    due = None
    if args.due.strip():
        try:
            due = parse_due(args.due, frame.env.tz_of(frame.root), frame.now)
        except ValueError as exc:
            errors["due"] = str(exc)
    rule = args.schedule.strip() or "manual"
    try:
        schedule.parse(rule)
    except ValueError as exc:
        errors["schedule"] = f"règle refusée : {exc}"
    me = frame.get(identity_c.PERSON(ctx.by)) if ctx.by else None
    owner = me
    if args.owner.strip():
        owner = _known_person(frame, args.owner.strip(), me)
        if owner is None:
            errors["owner"] = f"personne inconnue : « {args.owner.strip()[:60]} »"
    if errors:
        raise Refused("Le projet n'a pas été confié : vérifie le formulaire.", errors)
    p = params(frame.env.params_of("goals", frame.root))
    level = int(Sensitivity.PERSONAL) if owner else int(Sensitivity.NONE)
    draft = project_opened(
        title=args.title, details=args.details, owner=owner, address=ctx.by if owner == me and ctx.by else None,
        rule=rule, approval=args.approval, max_steps=args.max_steps or p.project_steps, source="operator",
        level=level, due=due, priority=args.priority)
    return Done(drafts=(draft,), message="Projet confié : elle y avancera par pas, dans son atelier.",
                go_created="goal")


# ── Suspendre, reprendre ──────────────────────────────────────────────────


class NoArgs(BaseModel):
    pass


def _pausable(s: GoalsState, frame: Frame, key: str) -> bool:
    g = goal_at(s, key)
    return g is not None and workable(g, frame.now)


def _resumable(s: GoalsState, frame: Frame, key: str) -> bool:
    g = goal_at(s, key)
    return g is not None and status(g, frame.now) == c.PAUSED


def _target(s: GoalsState, ctx: ActionContext) -> Goal:
    g = goal_at(s, ctx.subject)
    if g is None:
        raise Refused(f"Aucun but « {ctx.subject} » en mémoire.")
    return g


@GOALS.action("pause", title="Mettre en pause", args=NoArgs, emits=[GOAL_PAUSED], subject="goal", order=10,
              available=_pausable,
              description="Plus aucun pas ni rappel, et son envie ne s'use pas, jusqu'à ce que tu le reprennes.")
def _pause(s: GoalsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    return Done(drafts=(GOAL_PAUSED.draft(goal=g.id, by=ctx.by, owner=g.owner, about=g.about),),
                message="But mis en pause.", guard=_still(g.id, (c.ACTIVE, c.WAITING)))


@GOALS.action("reprendre", title="Reprendre", args=NoArgs, emits=[GOAL_RESUMED], subject="goal", order=20,
              available=_resumable, description="Il repart d'où il en était.")
def _resume(s: GoalsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    return Done(drafts=(GOAL_RESUMED.draft(goal=g.id, by=ctx.by, owner=g.owner, about=g.about),),
                message="But repris.", guard=_still(g.id, (c.PAUSED,)))


# ── Une consigne ──────────────────────────────────────────────────────────


class InstructionArgs(BaseModel):
    instruction: Annotated[str, Knob(label="Consigne", widget="textarea",
                                     help="elle la lira à son prochain pas ; la plus récente prime"),
                           Field(min_length=1, max_length=2000)]


def _amendable(s: GoalsState, frame: Frame, key: str) -> bool:
    g = goal_at(s, key)
    return g is not None and live(g, frame.now) and g.kind != c.REMINDER


@GOALS.action("consigne", title="Donner une consigne", args=InstructionArgs, emits=[GOAL_AMENDED], subject="goal",
              order=30, available=_amendable,
              description="Une précision sur ce qu'elle doit faire, ajoutée au cadre du but.")
def _amend(s: GoalsState, frame: Frame, args: InstructionArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    text = args.instruction.strip()
    if not text:
        raise Refused("La consigne est vide.", {"instruction": "valeur requise"})
    draft = GOAL_AMENDED.draft(goal=g.id, instruction=Content.of(text, level=g.sensitivity), by=ctx.by,
                               owner=g.owner, about=g.about)
    return Done(drafts=(draft,), message="Consigne ajoutée : elle la lira à son prochain pas.",
                guard=_still(g.id, c.LIVE_STATUSES))


# ── Clore ─────────────────────────────────────────────────────────────────


def _closable(s: GoalsState, frame: Frame, key: str) -> bool:
    g = goal_at(s, key)
    return g is not None and live(g, frame.now)


@GOALS.action("clore", title="Clore", args=NoArgs, emits=[c.GOAL_CLOSED], subject="goal", order=90,
              available=_closable, danger=True,
              confirm="Clore ce but ? Elle n'y travaillera plus (il sera « annulé », sans qu'elle en soit affectée).",
              description="Le but est annulé : plus de pas, plus de rappel. Elle n'en tire ni fierté ni frustration.")
def _close(s: GoalsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    return Done(drafts=(closing(ctx, g, c.CANCELLED, reason=CANCELLED_REASON),), message="But clos (annulé).",
                guard=_still(g.id, c.LIVE_STATUSES))


# ── Relire un but (pré-remplir les formulaires) ───────────────────────────


def _texts(ports: Mapping[str, Any], refs: Iterable[str]) -> Mapping[str, str]:
    store = ports.get("store")
    wanted = [r for r in refs if r]
    return store.content(wanted) if store is not None and wanted else {}


def _due_text(frame: Frame, due: int | None) -> str:
    """Une échéance comme la relit un champ « date et heure » (heure locale)."""
    return local(due, frame.env.tz_of(frame.root)).strftime("%Y-%m-%dT%H:%M") if due is not None else ""


def _me(frame: Frame, ctx: ActionContext) -> str | None:
    return frame.get(identity_c.PERSON(ctx.by)) if ctx.by else None


# ── Modifier le cadre d'un projet confié ──────────────────────────────────


class ModifyArgs(BaseModel):
    title: Annotated[str, Knob(label="Titre", group="Le projet", advanced=False, order=10,
                               help="Ce qu'elle doit mener à bout, en quelques mots.")] = Field(max_length=120)
    details: Annotated[str, Knob(label="Le cadre", widget="textarea", group="Le projet", advanced=False, order=20,
                                 help="Ce qu'il faut faire, comment, et ce qui est hors sujet. Elle relit le cadre à "
                                      "chaque pas ; elle ne le change jamais elle-même.")] = Field(default="",
                                                                                                  max_length=2000)
    owner: Annotated[str, Knob(label="Pour qui", widget="subject", subject="person", group="Le projet",
                               advanced=False, order=30, help="La personne pour qui elle travaille. Vide : pour toi.")
                     ] = Field(default="", max_length=120)
    due: Annotated[str, Knob(label="Échéance", widget="datetime", group="Son rythme", advanced=False, order=40,
                             help="En heure locale ; vide : sans échéance.")] = Field(default="", max_length=40)
    schedule: Annotated[str, Knob(label="Agenda", widget="suggest", choices=SCHEDULES, group="Son rythme",
                                  advanced=False, order=50,
                                  help="« manual » dès qu'elle peut, « interval:2h », « cron:0 9 * * MON-FRI ».")
                        ] = Field(default="manual", max_length=120)
    max_steps: Annotated[int, Knob(label="Pas au plus", group="Son rythme", advanced=False, order=60,
                                   help="Plus que ceux qu'elle a déjà faits. 0 : la valeur par défaut.")
                         ] = Field(default=0, ge=0, le=200)
    priority: Annotated[str, Knob(label="Priorité", choices=PRIORITY_CHOICES, group="Son rythme", advanced=False,
                                  order=65, help=PRIORITY_HELP)] = c.NORMAL
    approval: Annotated[bool, Knob(label="Ce qui sort de la machine attend ton accord", group="Sa liberté",
                                   advanced=False, order=70,
                                   help="Un mail, une commande avec le réseau. Dans son atelier, elle travaille "
                                        "librement.")] = True


def _confided(s: GoalsState, frame: Frame, key: str) -> bool:
    g = goal_at(s, key)
    return g is not None and g.kind == c.PROJECT and g.authority == c.USER and live(g, frame.now)


def _modify_initial(s: GoalsState, frame: Frame, key: str, ports: Mapping[str, Any]) -> dict[str, Any]:
    g = goal_at(s, key)
    if g is None:
        return {}
    texts = _texts(ports, (g.title_ref, g.details_ref))
    return {"title": texts.get(g.title_ref, ""), "details": texts.get(g.details_ref, ""), "owner": g.owner or "",
            "due": _due_text(frame, g.due), "schedule": g.schedule or "manual", "max_steps": g.max_steps,
            "priority": g.priority, "approval": g.approval}


def _steps_left(g: Goal, max_steps: int, p: Any) -> str:
    """Une erreur si ce budget ne laisse aucun pas à faire (vide : il en laisse)."""
    effective = max_steps or (p.project_steps if g.kind == c.PROJECT else p.exploration_steps)
    if effective <= g.steps:
        return f"elle en a déjà fait {g.steps} : au moins {g.steps + 1} (0 : la valeur par défaut, {effective})"
    return ""


@GOALS.action("modifier", title="Modifier le projet", args=ModifyArgs, emits=[GOAL_REFRAMED], subject="goal",
              order=5, available=_confided, initial=_modify_initial,
              description="Son titre, son cadre, pour qui, son rythme et sa liberté. Elle lira le nouveau cadre à son "
                          "prochain pas ; ce qu'elle a déjà fait reste.")
def _modify(s: GoalsState, frame: Frame, args: ModifyArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    ports = ctx.ports or {}
    texts = _texts(ports, (g.title_ref, g.details_ref))
    p = params(frame.env.params_of("goals", frame.root))
    errors: dict[str, str] = {}
    changes: dict[str, Any] = {}
    title, details = args.title.strip(), args.details.strip()
    if not title:
        errors["title"] = "valeur requise"
    elif title != texts.get(g.title_ref, ""):
        changes["title"] = Content.of(title, level=g.sensitivity)
    if details != texts.get(g.details_ref, "").strip():
        if details:
            changes["details"] = Content.of(details, level=g.sensitivity)
        else:
            changes["clear_details"] = True
    me = _me(frame, ctx)
    owner = me
    if args.owner.strip():
        # la personne qu'il a déjà (le formulaire part d'elle) ne se revalide pas
        owner = _known_person(frame, args.owner.strip(), me, g.owner)
        if owner is None:
            errors["owner"] = f"personne inconnue : « {args.owner.strip()[:60]} »"
    if "owner" not in errors and owner != g.owner:
        changes.update(set_owner=True, address=ctx.by if owner == me and ctx.by else None)
    due_text = args.due.strip()
    if due_text != _due_text(frame, g.due):
        if not due_text:
            changes["clear_due"] = True
        else:
            try:
                changes["due"] = parse_due(due_text, frame.env.tz_of(frame.root), frame.now)
            except ValueError as exc:
                errors["due"] = str(exc)
    rule = args.schedule.strip() or "manual"
    if rule != (g.schedule or "manual"):
        try:
            schedule.parse(rule)
            changes["schedule"] = rule
        except ValueError as exc:
            errors["schedule"] = f"règle refusée : {exc}"
    if args.max_steps != g.max_steps:
        problem = _steps_left(g, args.max_steps, p)
        if problem:
            errors["max_steps"] = problem
        else:
            changes["max_steps"] = args.max_steps
    if args.priority != g.priority:
        changes["priority"] = args.priority
    if args.approval != g.approval:
        changes["approval"] = args.approval
    if errors:
        raise Refused("Le projet n'a pas été modifié : vérifie le formulaire.", errors)
    if not changes:
        raise Refused("Rien n'a changé.")
    new_owner = owner if changes.get("set_owner") else g.owner
    about = (new_owner,) if changes.get("set_owner") and new_owner else g.about
    draft = GOAL_REFRAMED.draft(goal=g.id, by=ctx.by, owner=new_owner, about=about, **changes)
    return Done(drafts=(draft,), message="Projet modifié : elle lira son nouveau cadre à son prochain pas.",
                guard=_still(g.id, c.LIVE_STATUSES))


# ── Reprogrammer un rappel ────────────────────────────────────────────────


class RescheduleArgs(BaseModel):
    what: Annotated[str, Knob(label="Ce qu'il faudra rappeler", advanced=False, order=10)] = Field(max_length=300)
    when: Annotated[str, Knob(label="Quand", widget="datetime", advanced=False, order=20,
                              help="En heure locale.")] = Field(max_length=40)
    urgent: Annotated[bool, Knob(label="Urgent (même la nuit)", advanced=False, order=30,
                                 help="Un rappel urgent la réveille ; l'ordinaire attend son réveil.")] = False


def _reschedulable(s: GoalsState, frame: Frame, key: str) -> bool:
    g = goal_at(s, key)
    return g is not None and g.kind == c.REMINDER and live(g, frame.now) and not g.delivered


def _reschedule_initial(s: GoalsState, frame: Frame, key: str, ports: Mapping[str, Any]) -> dict[str, Any]:
    g = goal_at(s, key)
    if g is None:
        return {}
    return {"what": _texts(ports, (g.title_ref,)).get(g.title_ref, ""), "when": _due_text(frame, g.due),
            "urgent": g.urgent}


@GOALS.action("reprogrammer", title="Reprogrammer le rappel", args=RescheduleArgs, emits=[GOAL_REFRAMED],
              subject="goal", order=5, available=_reschedulable, initial=_reschedule_initial,
              description="Son texte, son heure, s'il est urgent. Ses tentatives repartent de zéro.")
def _reschedule(s: GoalsState, frame: Frame, args: RescheduleArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    texts = _texts(ctx.ports or {}, (g.title_ref,))
    changes: dict[str, Any] = {}
    errors: dict[str, str] = {}
    what = args.what.strip()
    if not what:
        errors["what"] = "valeur requise"
    elif what != texts.get(g.title_ref, ""):
        changes["title"] = Content.of(what, level=g.sensitivity)
    if args.when.strip() != _due_text(frame, g.due):
        try:
            changes["due"] = parse_due(args.when, frame.env.tz_of(frame.root), frame.now)
        except ValueError as exc:
            errors["when"] = str(exc)
    if args.urgent != g.urgent:
        changes["urgent"] = args.urgent
    if errors:
        raise Refused("Le rappel n'a pas été reprogrammé : vérifie le formulaire.", errors)
    if not changes:
        raise Refused("Rien n'a changé.")
    draft = GOAL_REFRAMED.draft(goal=g.id, by=ctx.by, owner=g.owner, about=g.about, **changes)
    return Done(drafts=(draft,), message="Rappel reprogrammé.", guard=_still(g.id, c.LIVE_STATUSES))


# ── La priorité ───────────────────────────────────────────────────────────


class PriorityArgs(BaseModel):
    priority: Annotated[str, Knob(label="Priorité", choices=PRIORITY_CHOICES, advanced=False, help=PRIORITY_HELP)
                        ] = c.NORMAL


def _prioritizable(s: GoalsState, frame: Frame, key: str) -> bool:
    g = goal_at(s, key)
    return g is not None and live(g, frame.now) and g.kind != c.REMINDER


def _priority_initial(s: GoalsState, frame: Frame, key: str) -> dict[str, Any]:
    g = goal_at(s, key)
    return {"priority": g.priority} if g is not None else {}


@GOALS.action("priorite", title="Priorité", args=PriorityArgs, emits=[GOAL_REFRAMED], subject="goal", order=25,
              available=_prioritizable, initial=_priority_initial,
              description="Entre deux buts qui peuvent avancer, le plus prioritaire passe devant.")
def _prioritize(s: GoalsState, frame: Frame, args: PriorityArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    if args.priority == g.priority:
        raise Refused("C'est déjà sa priorité.", {"priority": "inchangée"})
    draft = GOAL_REFRAMED.draft(goal=g.id, priority=args.priority, by=ctx.by, owner=g.owner, about=g.about)
    return Done(drafts=(draft,), message="Priorité changée.", guard=_still(g.id, c.LIVE_STATUSES))


# ── Avancer maintenant ────────────────────────────────────────────────────


def _advanceable(s: GoalsState, frame: Frame, key: str) -> bool:
    g = goal_at(s, key)
    if g is None or g.kind == c.REMINDER or not workable(g, frame.now):
        return False
    p = params(frame.env.params_of("goals", frame.root))
    running = any(r.goal == g.id and r.purpose == "step" for r in s.running.values())
    return not running and g.steps < budget(g, p) and not g.nudged_at > g.last_step_at


@GOALS.action("avancer", title="Avancer maintenant", args=NoArgs, emits=[GOAL_NUDGED], subject="goal", order=8,
              available=_advanceable,
              description="Son prochain pas n'attend ni son agenda ni l'espacement (ni une attente en cours) ; il "
                          "reste sous le plafond de pas par heure, et jamais pendant son sommeil.")
def _advance(s: GoalsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    draft = GOAL_NUDGED.draft(goal=g.id, by=ctx.by, owner=g.owner, about=g.about)
    return Done(drafts=(draft,), message="Elle y avance dès que possible.", guard=_still(g.id, (c.ACTIVE, c.WAITING)))


# ── Rouvrir ───────────────────────────────────────────────────────────────


class ReopenArgs(BaseModel):
    extra: Annotated[int, Knob(label="Pas de plus", advanced=False, order=10,
                               help="Combien de pas elle a encore, au moins, à partir d'où elle en est.")
                     ] = Field(default=4, ge=1, le=50)
    instruction: Annotated[str, Knob(label="Consigne (facultative)", widget="textarea", advanced=False, order=20,
                                     help="Ce qu'elle doit faire autrement cette fois ; elle la lira au prochain pas.")
                           ] = Field(default="", max_length=2000)


def _reopenable(s: GoalsState, frame: Frame, key: str) -> bool:
    g = goal_at(s, key)
    return g is not None and g.kind != c.REMINDER and g.status in c.CLOSED_STATUSES and g.status != c.ACHIEVED


@GOALS.action("rouvrir", title="Rouvrir", args=ReopenArgs, emits=[GOAL_REOPENED, GOAL_AMENDED], subject="goal",
              order=12, available=_reopenable,
              description="Il reprend là où il s'était arrêté, avec quelques pas de plus. Elle n'en ressent rien : ni "
                          "fierté, ni frustration.")
def _reopen(s: GoalsState, frame: Frame, args: ReopenArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    drafts: list[Any] = [GOAL_REOPENED.draft(goal=g.id, extra=args.extra, by=ctx.by, owner=g.owner, about=g.about)]
    if args.instruction.strip():
        drafts.append(GOAL_AMENDED.draft(goal=g.id, instruction=Content.of(args.instruction.strip(),
                                                                              level=g.sensitivity),
                                         by=ctx.by, owner=g.owner, about=g.about))
    return Done(drafts=tuple(drafts), message="Rouvert : elle y retourne.", guard=_still(g.id, (g.status,)))


# ── Le plan de travail ────────────────────────────────────────────────────


class TaskAddArgs(BaseModel):
    text: Annotated[str, Knob(label="Tâche", widget="textarea", advanced=False,
                              help="Une étape à faire, en une phrase ; elle la lira à son prochain pas et la cochera "
                                   "quand elle sera faite.")] = Field(min_length=1, max_length=500)


class TaskStatusArgs(BaseModel):
    task: Annotated[str, Knob(label="Tâche", widget="hidden")] = Field(min_length=1, max_length=12)
    status: Annotated[str, Knob(label="Statut", widget="hidden")] = Field(min_length=1, max_length=12)


class TaskEditArgs(BaseModel):
    task: Annotated[str, Knob(label="Tâche", widget="hidden")] = Field(min_length=1, max_length=12)
    text: Annotated[str, Knob(label="Tâche", widget="textarea", advanced=False)] = Field(min_length=1,
                                                                                         max_length=500)
    note: Annotated[str, Knob(label="Résultat ou raison du blocage", widget="textarea", advanced=False,
                              help="Facultatif.")] = Field(default="", max_length=1000)


class TaskArgs(BaseModel):
    task: Annotated[str, Knob(label="Tâche", widget="hidden")] = Field(min_length=1, max_length=12)


def _plannable(s: GoalsState, frame: Frame, key: str) -> bool:
    g = goal_at(s, key)
    return g is not None and live(g, frame.now) and g.kind != c.REMINDER


def _task_of(g: Goal, raw: str) -> Task:
    t = task_at(g, raw)
    if t is None:
        raise Refused(f"Aucune tâche n° {raw[:12]} dans ce but (retirée entre-temps ?).")
    return t


def _task_common(g: Goal, ctx: ActionContext) -> dict[str, Any]:
    return {"goal": g.id, "author": "operator", "by": ctx.by, "owner": g.owner, "about": g.about}


@GOALS.action("tache_ajouter", title="Ajouter une tâche", args=TaskAddArgs, emits=[TASK_ADDED], subject="goal",
              order=40, available=_plannable,
              description="Une étape de son plan de travail : elle la voit à chaque pas, marquée « demandée ».")
def _task_add(s: GoalsState, frame: Frame, args: TaskAddArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    if len(g.tasks) >= TASKS_KEPT:
        raise Refused(f"Son plan a déjà {TASKS_KEPT} tâches : retires-en avant d'en ajouter.")
    draft = TASK_ADDED.draft(task=g.task_seq + 1, text=Content.of(args.text.strip(), level=g.sensitivity),
                             **_task_common(g, ctx))
    return Done(drafts=(draft,), message="Tâche ajoutée à son plan.", guard=_still(g.id, c.LIVE_STATUSES))


@GOALS.action("tache_statut", title="Changer le statut", args=TaskStatusArgs, emits=[TASK_CHANGED],
              subject="goal", order=41, available=_plannable)
def _task_status(s: GoalsState, frame: Frame, args: TaskStatusArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    t = _task_of(g, args.task)
    if args.status not in c.TASK_STATUSES:
        raise Refused(f"Statut inconnu : « {args.status[:12]} ».")
    if args.status == t.status:
        raise Refused("La tâche a déjà ce statut.")
    draft = TASK_CHANGED.draft(task=t.id, status=args.status, **_task_common(g, ctx))
    return Done(drafts=(draft,), message=f"Tâche n° {t.id} : {TASK_STATUS_FR[args.status]}.",
                guard=_still(g.id, c.LIVE_STATUSES))


@GOALS.action("tache_modifier", title="Modifier la tâche", args=TaskEditArgs, emits=[TASK_CHANGED],
              subject="goal", order=42, available=_plannable)
def _task_edit(s: GoalsState, frame: Frame, args: TaskEditArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    t = _task_of(g, args.task)
    texts = _texts(ctx.ports or {}, (t.text_ref, t.note_ref))
    changes: dict[str, Any] = {}
    if args.text.strip() != texts.get(t.text_ref, ""):
        changes["text"] = Content.of(args.text.strip(), level=g.sensitivity)
    if args.note.strip() and args.note.strip() != texts.get(t.note_ref, ""):
        changes["note"] = Content.of(args.note.strip(), level=g.sensitivity)
    if not changes:
        raise Refused("Rien n'a changé.")
    draft = TASK_CHANGED.draft(task=t.id, **changes, **_task_common(g, ctx))
    return Done(drafts=(draft,), message=f"Tâche n° {t.id} modifiée.", guard=_still(g.id, c.LIVE_STATUSES))


@GOALS.action("tache_retirer", title="Retirer la tâche", args=TaskArgs, emits=[TASK_REMOVED], subject="goal",
              order=43, available=_plannable, danger=True, confirm="Retirer cette tâche de son plan ?")
def _task_remove(s: GoalsState, frame: Frame, args: TaskArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    t = _task_of(g, args.task)
    draft = TASK_REMOVED.draft(task=t.id, **_task_common(g, ctx))
    return Done(drafts=(draft,), message=f"Tâche n° {t.id} retirée.", guard=_still(g.id, c.LIVE_STATUSES))


TASK_STATUS_FR = {c.TODO: "à faire", c.DOING: "en cours", c.TASK_DONE: "faite", c.TASK_BLOCKED: "bloquée"}


# ── Décider de ce qui sort de la machine ──────────────────────────────────


class ApproveArgs(BaseModel):
    proposal: Annotated[str, Knob(label="Demande", widget="hidden")] = Field(min_length=1, max_length=20)
    seen: Annotated[str, Knob(label="Lu", widget="hidden")] = Field(default="", max_length=100)


class RefuseArgs(BaseModel):
    proposal: Annotated[str, Knob(label="Demande", widget="hidden")] = Field(min_length=1, max_length=20)
    note: Annotated[str, Knob(label="Pourquoi", widget="textarea", advanced=False,
                              help="Facultatif : elle le lira à son prochain pas.")] = Field(default="",
                                                                                              max_length=500)


def pending_of(frame: Frame, goal: int) -> list[Any]:
    """Les demandes de ce but qui attendent un accord."""
    return [v for v in frame.get(rt.PENDING_EFFECTS) if v.owner == c.OWNER and goal_of(v.context) == goal]


def _decidable(s: GoalsState, frame: Frame, key: str) -> bool:
    g = goal_at(s, key)
    return g is not None and bool(pending_of(frame, g.id))


def _proposal_of(frame: Frame, g: Goal, raw: str) -> int:
    wanted = int(raw) if raw.strip().isdigit() else -1
    if wanted not in {v.proposal for v in pending_of(frame, g.id)}:
        raise Refused("Cette demande n'attend plus de décision (déjà décidée ?).")
    return wanted


@GOALS.action("approuver", title="Approuver", args=ApproveArgs, emits=[], subject="goal", order=30,
              available=_decidable, confirm="Approuver cette demande ? Elle part aussitôt.")
def _approve(s: GoalsState, frame: Frame, args: ApproveArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    proposal = _proposal_of(frame, g, args.proposal)
    return Done(decide=(Decision(proposal, True, seen=args.seen),), message="Approuvé : elle part dans un instant.")


@GOALS.action("refuser", title="Refuser", args=RefuseArgs, emits=[], subject="goal", order=31,
              available=_decidable, danger=True)
def _refuse(s: GoalsState, frame: Frame, args: RefuseArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    proposal = _proposal_of(frame, g, args.proposal)
    return Done(decide=(Decision(proposal, False, note=args.note.strip()),), message="Refusé : elle le saura.")


# ── Déposer un fichier dans l'atelier ─────────────────────────────────────


class DepositArgs(BaseModel):
    file: Annotated[Upload | None, Knob(label="Fichier", widget="file", advanced=False, order=10,
                                        help=f"{UPLOAD_MAX // (1024 * 1024)} Mo au plus. Il arrive dans son atelier, "
                                             "enregistré à part (« apport de l'opérateur »).")] = None
    folder: Annotated[str, Knob(label="Dans le dossier", advanced=False, order=20,
                                help="Facultatif (« donnees/ ») ; vide : à la racine de l'atelier.")
                      ] = Field(default="", max_length=200)
    note: Annotated[str, Knob(label="Ce qu'il faut en faire", widget="textarea", advanced=False, order=30,
                              help="Facultatif : elle le lira à son prochain pas.")] = Field(default="",
                                                                                              max_length=1000)


def _depositable(s: GoalsState, frame: Frame, key: str, ports: Mapping[str, Any]) -> bool:
    g = goal_at(s, key)
    return g is not None and live(g, frame.now) and "workshop" in g.bundles and ports.get("workshop") is not None


@GOALS.action("deposer", title="Déposer un fichier", args=DepositArgs, emits=[GOAL_DEPOSITED], subject="goal",
              order=50, available=_depositable,
              description="Une donnée, un exemple, un modèle : dans son atelier, pour qu'elle s'en serve.")
async def _deposit(s: GoalsState, frame: Frame, args: DepositArgs, ctx: ActionContext) -> Done:
    g = _target(s, ctx)
    if args.file is None or not args.file.data:
        raise Refused("Aucun fichier (ou un fichier vide).", {"file": "choisis un fichier"})
    port = (ctx.ports or {}).get("workshop")
    if port is None:
        raise Refused("L'atelier n'est pas disponible ici.")
    folder = args.folder.strip().strip("/")
    path = f"{folder}/{args.file.name}" if folder else args.file.name
    try:
        rel = await port.write_bytes(g.id, path, args.file.data)
    except OutsideWorkshop as exc:
        raise Refused(f"Refusé : {exc}", {"folder": str(exc)}) from None
    await port.commit(g.id, f"apport de l'opérateur : {rel}")
    note = Content.of(args.note.strip(), level=g.sensitivity) if args.note.strip() else None
    draft = GOAL_DEPOSITED.draft(goal=g.id, name=rel, size=len(args.file.data), note=note, by=ctx.by, owner=g.owner,
                                 about=g.about)
    return Done(drafts=(draft,), message=f"Déposé dans son atelier : {rel}.", guard=_still(g.id, c.LIVE_STATUSES))

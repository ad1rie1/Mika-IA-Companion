"""Ce qu'un opérateur peut faire de ses buts depuis la console.

Des opérations seulement : lui **confier** un projet, **suspendre** un but
puis le **reprendre**, lui donner une **consigne**, le **clore**. Jamais ce
qu'elle en pense ni ce qu'elle en ressent : un but annulé ne la rend ni fière
ni frustrée, une consigne s'ajoute au cadre sans réécrire son carnet.

Chaque action rend les brouillons de ses propres événements ; le moteur de la
console les journalise avec l'origine « extérieure », sous une garde qui
refuse d'agir sur un but qui a changé entre-temps.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from mika.contracts import goals as c
from mika.contracts import identity as identity_c
from mika.faculties.goals.faculty import (
    GOAL_AMENDED,
    GOAL_PAUSED,
    GOAL_RESUMED,
    GOALS,
    Goal,
    GoalsState,
    goal_at,
    live,
    params,
    status,
    workable,
)
from mika.faculties.goals.tools import closing, project_opened
from mika.kernel import schedule
from mika.kernel.clock import DAY, instant, local
from mika.kernel.events import Content
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.operate import ActionContext, Done, Refused
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


def _known_person(frame: Frame, key: str) -> str | None:
    """La clé de personne de ``key`` si l'identité la connaît (une poignée vue,
    ou une propriétaire déclarée), sinon rien."""
    person = frame.get(identity_c.PERSON(key))
    if frame.get(identity_c.HANDLES(person)) or person in frame.get(identity_c.OWNERS):
        return person
    return None


def _still(goal: int, wanted: tuple[str, ...]) -> Guard:
    """L'opération ne vaut que si le but est toujours dans l'état où l'opérateur l'a vu."""
    return Guard("but inchangé", predicate=lambda view, g=goal: view.get(c.STATUS(g)) in wanted)


# ── Confier un projet ─────────────────────────────────────────────────────


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
        owner = _known_person(frame, args.owner.strip())
        if owner is None:
            errors["owner"] = f"personne inconnue : « {args.owner.strip()[:60]} »"
    if errors:
        raise Refused("Le projet n'a pas été confié : vérifie le formulaire.", errors)
    p = params(frame.env.params_of("goals", frame.root))
    level = int(Sensitivity.PERSONAL) if owner else int(Sensitivity.NONE)
    draft = project_opened(
        title=args.title, details=args.details, owner=owner, address=ctx.by if owner == me and ctx.by else None,
        rule=rule, approval=args.approval, max_steps=args.max_steps or p.project_steps, source="operator",
        level=level, due=due)
    return Done(drafts=(draft,), message="Projet confié : elle y avancera par pas, dans son atelier.")


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

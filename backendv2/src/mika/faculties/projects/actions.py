"""Ce qu'un opérateur fait de ses projets depuis la console (ADR 0031).

Des opérations seulement, chacune journalisée sous une garde (« le projet n'a
pas changé entre-temps ») : **créer** un projet, le **modifier** (cadre, mode,
rythme, plage de travail, accord), choisir ses **outils**, régler son **dépôt
distant**, le **lancer maintenant** (ou sur un objectif), le **mettre en
pause**, le **reprendre**, l'**archiver**, le **restaurer**, lui donner une
**consigne**, tenir ses **objectifs** et ses **décisions techniques**,
**déposer** un fichier dans l'atelier, **pousser** ou **récupérer**, et
**décider** de ce qu'il veut faire sortir de la machine. Jamais ce qu'elle en
pense ou en ressent : un objectif coché par l'opérateur ne la rend pas fière.

Sur un projet qu'elle a ouvert d'elle-même, on pilote sans réécrire : ni son
titre, ni sa description.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects.faculty import (
    AMENDED,
    ARCHIVED,
    BASE_BUNDLES,
    DECIDED,
    DECISION_CHANGED,
    DECISIONS_KEPT,
    DEPOSITED,
    EXTRA_BUNDLES,
    NUDGED,
    OBJECTIVE_ADDED,
    OBJECTIVE_CHANGED,
    OBJECTIVES_KEPT,
    PAUSED,
    PROJECTS,
    REFRAMED,
    REMOTE_REQUESTED,
    RESTORED,
    RESUMED,
    Objective,
    Project,
    ProjectsState,
    busy,
    decision_at,
    in_force,
    living,
    nudged,
    objective_at,
    project_at,
)
from mika.faculties.projects.tools import objectives_of, opened
from mika.kernel import schedule
from mika.kernel.clock import HOUR
from mika.kernel.events import Content
from mika.kernel.forms import UPLOAD_MAX, Knob, Upload
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.operate import ActionContext, Decision, Done, Refused
from mika.ports.workshop import OutsideWorkshop
from mika.vocab.episodes import project_of
from mika.vocab.privacy import Sensitivity

MODE_CHOICES = ((c.PERSONA, "Mika : elle y travaille avec son humeur et ses avis"),
                (c.PLAIN, "Impersonnel : un travail factuel, sans persona ni émotion"))
MODE_HELP = ("En mode Mika, c'est elle qui travaille : sa voix, son humeur, ses avis ; ce qu'elle mène à bout la "
             "rend fière, ce qui bloque la frustre, et elle le raconte. En mode impersonnel, le travail est factuel, "
             "sans persona ni émotion, et ne suit pas son sommeil (seulement la plage de travail).")
PRIORITY_CHOICES = ((c.LOW, "basse"), (c.NORMAL, "normale"), (c.HIGH, "haute"), (c.URGENT, "urgente"))
PRIORITY_HELP = "Entre deux projets qui peuvent avancer, le plus prioritaire passe devant (sans passer les plafonds)."
DAYS_CHOICES = ((c.EVERY_DAY, "tous les jours"), (c.WEEKDAYS, "les jours ouvrés (lundi–vendredi)"),
                (c.WEEKEND, "le week-end"))
KIND_CHOICES = ((c.ONCE, "ponctuel — à faire une fois"), (c.CONSTANT, "constant — à entretenir, il revient"))
SCHEDULES = (("manual", "dès que possible"), ("interval:30m", "toutes les 30 min"),
             ("interval:2h", "toutes les 2 h"), ("interval:6h", "toutes les 6 h"),
             ("cron:0 9 * * *", "chaque jour à 9 h"), ("cron:0 9 * * MON-FRI", "les jours ouvrés à 9 h"),
             ("cron:0 18 * * SUN", "le dimanche à 18 h"))
#: les lots qu'on peut lui donner, en mots
BUNDLE_WORDS = {"memory": "sa mémoire (souvenirs, croyances)", "email": "le courrier (lire, proposer des envois)",
                "rss": "ses flux RSS", "forge": "la Forge (écrire des apps)", "forge_apps": "ses apps forgées",
                "camera": "la caméra"}
_HHMM = re.compile(r"^(\d{1,2})(?:\s*[:h]\s*(\d{0,2}))?$")


def _label(bundle: str) -> str:
    """Le libellé d'une case d'outil : la majuscule au début, le reste tel quel (« Ses flux RSS »)."""
    words = BUNDLE_WORDS[bundle]
    return words[:1].upper() + words[1:]


def _still(project: int, wanted: tuple[str, ...]) -> Guard:
    """L'opération ne vaut que si le projet est toujours dans l'état où l'opérateur l'a vu."""
    return Guard("projet inchangé", predicate=lambda view, p=project: view.get(c.STATUS(p)) in wanted)


LIVE = (c.ACTIVE, c.PAUSED)


def _target(s: ProjectsState, ctx: ActionContext) -> Project:
    p = project_at(s, ctx.subject)
    if p is None:
        raise Refused(f"Aucun projet « {ctx.subject} ».")
    return p


def _texts(ports: Mapping[str, Any], refs: Iterable[str]) -> Mapping[str, str]:
    store = ports.get("store")
    wanted = [r for r in refs if r]
    return store.content(wanted) if store is not None and wanted else {}


def _known_person(frame: Frame, key: str, *also: str | None) -> str | None:
    """La clé de personne de ``key`` si l'identité la connaît (une adresse vue, une propriétaire) ou si c'est
    l'une de ``also`` (l'opérateur lui-même, la personne que le projet a déjà), sinon rien."""
    person = frame.get(identity_c.PERSON(key))
    if frame.get(identity_c.HANDLES(person)) or person in frame.get(identity_c.OWNERS):
        return person
    if person in {a for a in also if a} or key in {a for a in also if a}:
        return person
    return None


def parse_hhmm(text: str, *, end: bool = False) -> int:
    """« 9:00 », « 18h30 », « 9 h », « 9 » → minutes depuis minuit ; « 24:00 » seulement pour une fin."""
    raw = text.strip().lower().replace(" ", "")
    if not raw:
        return 24 * 60 if end else 0
    m = _HHMM.match(raw)
    if m is None:
        raise ValueError("une heure « 9:00 » ou « 18h30 »")
    h, mins = int(m.group(1)), int(m.group(2) or 0)
    if h > 24 or mins > 59 or (h == 24 and (mins or not end)):
        raise ValueError("heure hors bornes")
    return h * 60 + mins


def check_remote(url: str) -> str:
    """Une adresse de dépôt distant https sans identifiants (le jeton est un réglage, jamais dans l'adresse)."""
    raw = url.strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if parts.scheme != "https" or not parts.hostname or any(ch.isspace() for ch in raw):
        raise ValueError("une adresse https, comme https://github.com/compte/depot.git")
    if parts.username or parts.password or "@" in parts.netloc:
        raise ValueError("pas d'identifiants dans l'adresse : le jeton se règle dans Configuration › Canaux › "
                         "Dépôts git")
    if parts.query or parts.fragment or "?" in raw or "#" in raw:
        raise ValueError("une adresse de dépôt, sans « ? » ni « # » (rien de secret ne va dans l'adresse)")
    return raw


def check_branch(branch: str) -> str:
    raw = branch.strip() or "main"
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$", raw) or ".." in raw or raw.endswith((".lock", "/")):
        raise ValueError("nom de branche refusé")
    return raw


def _bundles(args: Any) -> tuple[str, ...]:
    return (*BASE_BUNDLES, *(b for b in EXTRA_BUNDLES if getattr(args, f"tool_{b}", False)))


def _rhythm(args: Any, errors: dict[str, str]) -> tuple[str, int, int]:
    rule = args.schedule.strip() or "manual"
    try:
        schedule.parse(rule)
    except ValueError as exc:
        errors["schedule"] = f"règle refusée : {exc}"
    start = end = 0
    try:
        start = parse_hhmm(args.start)
    except ValueError as exc:
        errors["start"] = str(exc)
    try:
        end = parse_hhmm(args.end, end=True)
    except ValueError as exc:
        errors["end"] = str(exc)
    if "start" not in errors and "end" not in errors and start % (24 * 60) == end % (24 * 60) \
            and (start, end) != (0, 24 * 60):
        errors["end"] = "la fin doit différer du début (vide des deux côtés : toute la journée)"
    return rule, start, end


# ── Créer un projet ───────────────────────────────────────────────────────


TOOL_HELP = "Son atelier (fichiers, programmes, git) et ses propres outils sont toujours là."


class CreateArgs(BaseModel):
    title: Annotated[str, Knob(label="Titre", group="Le projet", advanced=False, order=10,
                               help="Ce qu'est ce projet, en quelques mots : il le nomme partout.")
                     ] = Field(max_length=200)
    description: Annotated[str, Knob(label="Le cadre", widget="textarea", group="Le projet", advanced=False,
                                     order=20, help="Ce qu'il faut faire, comment, ce qui est hors sujet. Elle le "
                                                    "relit à chaque exécution ; tu pourras ajouter des consignes.")
                           ] = Field(default="", max_length=4000)
    owner: Annotated[str, Knob(label="Pour qui", widget="subject", subject="person", group="Le projet",
                               advanced=False, order=30, help="La personne pour qui elle travaille. Vide : pour toi.")
                     ] = Field(default="", max_length=120)
    objectives: Annotated[tuple[str, ...], Knob(
        label="Objectifs ponctuels", group="Ses objectifs", advanced=False, order=40,
        help="Un par ligne : ce qui se fait une fois (« Créer un module RDP »). Une exécution vise un objectif à "
             "la fois.")] = ()
    constants: Annotated[tuple[str, ...], Knob(
        label="Objectifs constants", group="Ses objectifs", advanced=False, order=50,
        help="Un par ligne : ce qui s'entretient et revient (« Améliorer la sécurité »).")] = ()
    cadence_hours: Annotated[int, Knob(label="Cadence des constants (heures)", group="Ses objectifs",
                                       advanced=False, order=55, lo=0, hi=720,
                                       help="Un objectif constant revient après ce délai une fois son passage fait. "
                                            "0 : la valeur par défaut (Configuration › Comportement › Projets).")
                         ] = Field(default=0, ge=0, le=720)
    mode: Annotated[str, Knob(label="Mode de travail", choices=MODE_CHOICES, group="Son mode et ses outils",
                              advanced=False, order=60, help=MODE_HELP)] = c.PERSONA
    tool_memory: Annotated[bool, Knob(label=_label("memory"), group="Son mode et ses outils",
                                      advanced=False, order=61, help=TOOL_HELP)] = True
    tool_email: Annotated[bool, Knob(label=_label("email"), group="Son mode et ses outils",
                                     advanced=False, order=62)] = False
    tool_rss: Annotated[bool, Knob(label=_label("rss"), group="Son mode et ses outils",
                                   advanced=False, order=63)] = False
    tool_forge: Annotated[bool, Knob(label=_label("forge"), group="Son mode et ses outils",
                                     advanced=False, order=64)] = False
    tool_forge_apps: Annotated[bool, Knob(label=_label("forge_apps"),
                                          group="Son mode et ses outils", advanced=False, order=65)] = False
    tool_camera: Annotated[bool, Knob(label=_label("camera"), group="Son mode et ses outils",
                                      advanced=False, order=66)] = False
    schedule: Annotated[str, Knob(label="Agenda", widget="suggest", choices=SCHEDULES, group="Son rythme",
                                  advanced=False, order=70,
                                  help="« manual » dès que possible, « interval:2h », « cron:0 9 * * MON-FRI ».")
                        ] = Field(default="manual", max_length=120)
    days: Annotated[str, Knob(label="Jours de travail", choices=DAYS_CHOICES, group="Son rythme", advanced=False,
                              order=71)] = c.EVERY_DAY
    start: Annotated[str, Knob(label="De", group="Son rythme", advanced=False, order=72,
                               help="Début de la plage de travail, en heure locale (vide : minuit).")
                     ] = Field(default="", max_length=10)
    end: Annotated[str, Knob(label="À", group="Son rythme", advanced=False, order=73,
                             help="Fin de la plage (vide : minuit le soir). Une fin avant le début passe minuit.")
                   ] = Field(default="", max_length=10)
    runs_per_day: Annotated[int, Knob(label="Exécutions par jour au plus", group="Son rythme", advanced=False,
                                      order=74, lo=0, hi=500, help="0 : la valeur par défaut.")
                            ] = Field(default=0, ge=0, le=500)
    priority: Annotated[str, Knob(label="Priorité", choices=PRIORITY_CHOICES, group="Son rythme", advanced=False,
                                  order=75, help=PRIORITY_HELP)] = c.NORMAL
    approval: Annotated[bool, Knob(label="Ce qui sort de la machine attend ton accord", group="Sa liberté",
                                   advanced=False, order=80,
                                   help="Une commande avec le réseau, un envoi au dépôt distant : rien ne part sans "
                                        "ton accord. Dans son atelier, elle travaille librement.")] = True
    remote: Annotated[str, Knob(label="Dépôt distant", group="Son dépôt distant", advanced=False, order=90,
                                help="Facultatif : une adresse https (https://github.com/compte/depot.git). Le jeton "
                                     "se règle dans Configuration › Canaux › Dépôts git.")
                      ] = Field(default="", max_length=300)
    branch: Annotated[str, Knob(label="Branche", group="Son dépôt distant", advanced=False, order=91)
                      ] = Field(default="main", max_length=100)
    auto_push: Annotated[bool, Knob(label="Pousser après chaque exécution qui enregistre quelque chose",
                                    group="Son dépôt distant", advanced=False, order=92,
                                    help="Selon l'accord ci-dessus : tout de suite, ou après ton accord.")] = False


@PROJECTS.action("creer", title="Créer un projet", args=CreateArgs, emits=[c.PROJECT_CREATED, OBJECTIVE_ADDED],
                 section="projets", order=10,
                 description="Un espace de travail qu'elle mènera par exécutions : un dossier et son dépôt git, des "
                             "objectifs, un mode, des outils, un rythme.")
def _create(s: ProjectsState, frame: Frame, args: CreateArgs, ctx: ActionContext) -> Done:
    errors: dict[str, str] = {}
    if not args.title.strip():
        errors["title"] = "valeur requise"
    if not [t for t in (*args.objectives, *args.constants) if t.strip()]:
        errors["objectives"] = "au moins un objectif (ponctuel ou constant)"
    if len(args.objectives) + len(args.constants) > OBJECTIVES_KEPT:
        errors["objectives"] = f"au plus {OBJECTIVES_KEPT} objectifs"
    rule, start, end = _rhythm(args, errors)
    remote = branch = ""
    try:
        remote = check_remote(args.remote)
    except ValueError as exc:
        errors["remote"] = str(exc)
    try:
        branch = check_branch(args.branch)
    except ValueError as exc:
        errors["branch"] = str(exc)
    me = frame.get(identity_c.PERSON(ctx.by)) if ctx.by else None
    owner = me
    if args.owner.strip():
        owner = _known_person(frame, args.owner.strip(), me)
        if owner is None:
            errors["owner"] = f"personne inconnue : « {args.owner.strip()[:60]} »"
    if errors:
        raise Refused("Le projet n'a pas été créé : vérifie le formulaire.", errors)
    level = int(Sensitivity.PERSONAL) if owner else int(Sensitivity.NONE)
    about = (owner,) if owner else ()
    draft = opened(
        title=args.title, description=args.description, authority=c.USER, mode=args.mode, owner=owner,
        address=ctx.by if owner == me and ctx.by else None, about=about, level=level, source="operator",
        schedule_rule=rule, approval=args.approval, priority=args.priority, bundles=_bundles(args), days=args.days,
        start_min=start, end_min=end, runs_per_day=args.runs_per_day, remote=remote, branch=branch,
        auto_push=args.auto_push and bool(remote))

    def objectives(seqs: tuple[int, ...]) -> list[Any]:
        """Ses objectifs, aussitôt après : ils portent le numéro que la création vient de lui donner."""
        return objectives_of(seqs[0], list(args.objectives), list(args.constants), author="operator", by=ctx.by,
                             owner=owner, about=about, level=level, cadence_us=args.cadence_hours * HOUR)

    return Done(drafts=(draft,), then=objectives, go_created="project",
                message="Projet créé : elle y travaillera par exécutions, objectif par objectif.")


# ── Modifier ──────────────────────────────────────────────────────────────


class ModifyArgs(BaseModel):
    title: Annotated[str, Knob(label="Titre", group="Le projet", advanced=False, order=10)] = Field(max_length=200)
    description: Annotated[str, Knob(label="Le cadre", widget="textarea", group="Le projet", advanced=False,
                                     order=20, help="Elle relit le cadre à chaque exécution.")
                           ] = Field(default="", max_length=4000)
    owner: Annotated[str, Knob(label="Pour qui", widget="subject", subject="person", group="Le projet",
                               advanced=False, order=30, help="Vide : pour toi.")] = Field(default="", max_length=120)
    mode: Annotated[str, Knob(label="Mode de travail", choices=MODE_CHOICES, group="Son mode", advanced=False,
                              order=40, help=MODE_HELP)] = c.PERSONA
    schedule: Annotated[str, Knob(label="Agenda", widget="suggest", choices=SCHEDULES, group="Son rythme",
                                  advanced=False, order=50)] = Field(default="manual", max_length=120)
    days: Annotated[str, Knob(label="Jours de travail", choices=DAYS_CHOICES, group="Son rythme", advanced=False,
                              order=51)] = c.EVERY_DAY
    start: Annotated[str, Knob(label="De", group="Son rythme", advanced=False, order=52,
                               help="En heure locale (vide : minuit).")] = Field(default="", max_length=10)
    end: Annotated[str, Knob(label="À", group="Son rythme", advanced=False, order=53,
                             help="Vide : minuit le soir. Une fin avant le début passe minuit.")
                   ] = Field(default="", max_length=10)
    runs_per_day: Annotated[int, Knob(label="Exécutions par jour au plus", group="Son rythme", advanced=False,
                                      order=54, lo=0, hi=500, help="0 : la valeur par défaut.")
                            ] = Field(default=0, ge=0, le=500)
    priority: Annotated[str, Knob(label="Priorité", choices=PRIORITY_CHOICES, group="Son rythme", advanced=False,
                                  order=55, help=PRIORITY_HELP)] = c.NORMAL
    approval: Annotated[bool, Knob(label="Ce qui sort de la machine attend ton accord", group="Sa liberté",
                                   advanced=False, order=60)] = True


def _editable(s: ProjectsState, frame: Frame, key: str) -> bool:
    p = project_at(s, key)
    return p is not None and p.status in LIVE


def _modify_initial(s: ProjectsState, frame: Frame, key: str, ports: Mapping[str, Any]) -> dict[str, Any]:
    p = project_at(s, key)
    if p is None:
        return {}
    texts = _texts(ports, (p.title_ref, p.description_ref))
    return {"title": texts.get(p.title_ref, ""), "description": texts.get(p.description_ref, ""),
            "owner": p.owner or "", "mode": p.mode, "schedule": p.schedule or "manual", "days": p.days,
            "start": _clock(p.start_min) if p.start_min else "", "end": _clock(p.end_min) if p.end_min < 1440 else "",
            "runs_per_day": p.runs_per_day, "priority": p.priority, "approval": p.approval}


def _clock(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"


@PROJECTS.action("modifier", title="Modifier le projet", args=ModifyArgs, emits=[REFRAMED], subject="project",
                 order=60, available=_editable, initial=_modify_initial, inline=True,
                 description="Son cadre, pour qui, son mode, son rythme, sa plage de travail et sa liberté. La "
                             "prochaine exécution lira le nouveau cadre ; ce qui est fait reste.")
def _modify(s: ProjectsState, frame: Frame, args: ModifyArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    texts = _texts(ctx.ports or {}, (p.title_ref, p.description_ref))
    errors: dict[str, str] = {}
    changes: dict[str, Any] = {}
    title, description = args.title.strip(), args.description.strip()
    own = p.authority == c.SELF
    me = frame.get(identity_c.PERSON(ctx.by)) if ctx.by else None
    owner = p.owner if own else me
    if args.owner.strip():
        owner = _known_person(frame, args.owner.strip(), me, p.owner)
        if owner is None:
            errors["owner"] = f"personne inconnue : « {args.owner.strip()[:60]} »"
    # pour quelqu'un, il parle de quelqu'un : ce qui s'y écrit (dès ce formulaire) est au moins personnel
    level = max(p.sensitivity, int(Sensitivity.PERSONAL)) if owner and owner != p.owner else p.sensitivity
    if not title:
        if texts.get(p.title_ref) is not None:  # un titre oublié (l'oubli d'une personne) ne bloque pas le reste
            errors["title"] = "valeur requise"
    elif title != texts.get(p.title_ref, ""):
        if own:
            errors["title"] = "c'est son projet à elle : on le pilote, on ne le renomme pas"
        changes["title"] = Content.of(title, level=level)
    if description != texts.get(p.description_ref, "").strip():
        if own:
            errors["description"] = "c'est son projet à elle : on ne réécrit pas ce qu'elle veut en faire"
        elif description:
            changes["description"] = Content.of(description, level=level)
        else:
            changes["clear_description"] = True
    if "owner" not in errors and owner != p.owner:
        changes.update(set_owner=True, address=ctx.by if owner == me and ctx.by else None)
        if level > p.sensitivity:
            changes["sensitivity"] = level
    rule, start, end = _rhythm(args, errors)
    if args.mode != p.mode:
        changes["mode"] = args.mode
    if rule != (p.schedule or "manual"):
        changes["schedule"] = rule
    if args.days != p.days:
        changes["days"] = args.days
    if start != p.start_min:
        changes["start_min"] = start
    if end != p.end_min:
        changes["end_min"] = end
    if args.runs_per_day != p.runs_per_day:
        changes["runs_per_day"] = args.runs_per_day
    if args.priority != p.priority:
        changes["priority"] = args.priority
    if args.approval != p.approval:
        changes["approval"] = args.approval
    if errors:
        raise Refused("Le projet n'a pas été modifié : vérifie le formulaire.", errors)
    if not changes:
        raise Refused("Rien n'a changé.")
    new_owner = owner if changes.get("set_owner") else p.owner
    about = (new_owner,) if changes.get("set_owner") and new_owner else p.about
    return Done(drafts=(REFRAMED.draft(project=p.id, by=ctx.by, owner=new_owner, about=about, **changes),),
                message="Projet modifié : la prochaine exécution lira son nouveau cadre.", guard=_still(p.id, LIVE))


# ── Ses outils ────────────────────────────────────────────────────────────


class ToolsArgs(BaseModel):
    tool_memory: Annotated[bool, Knob(label=_label("memory"), advanced=False, order=1,
                                      help=TOOL_HELP)] = False
    tool_email: Annotated[bool, Knob(label=_label("email"), advanced=False, order=2)] = False
    tool_rss: Annotated[bool, Knob(label=_label("rss"), advanced=False, order=3)] = False
    tool_forge: Annotated[bool, Knob(label=_label("forge"), advanced=False, order=4)] = False
    tool_forge_apps: Annotated[bool, Knob(label=_label("forge_apps"), advanced=False,
                                          order=5)] = False
    tool_camera: Annotated[bool, Knob(label=_label("camera"), advanced=False, order=6)] = False


def _tools_initial(s: ProjectsState, frame: Frame, key: str) -> dict[str, Any]:
    p = project_at(s, key)
    return {f"tool_{b}": b in p.bundles for b in EXTRA_BUNDLES} if p is not None else {}


@PROJECTS.action("outils", title="Enregistrer ses outils", args=ToolsArgs, emits=[REFRAMED], subject="project",
                 order=61, available=_editable, initial=_tools_initial, inline=True,
                 description="Ce qu'elle a en main pendant une exécution, en plus de son atelier.")
def _tools(s: ProjectsState, frame: Frame, args: ToolsArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    bundles = _bundles(args)
    if set(bundles) == set(p.bundles):
        raise Refused("Rien n'a changé.")
    return Done(drafts=(REFRAMED.draft(project=p.id, bundles=bundles, by=ctx.by, owner=p.owner, about=p.about),),
                message="Outils enregistrés : la prochaine exécution les aura en main.", guard=_still(p.id, LIVE))


# ── Son dépôt distant ─────────────────────────────────────────────────────


class RemoteArgs(BaseModel):
    remote: Annotated[str, Knob(label="Adresse du dépôt distant", advanced=False, order=1,
                                help="https://github.com/compte/depot.git — vide : aucun. Le jeton se règle dans "
                                     "Configuration › Canaux › Dépôts git.")] = Field(default="", max_length=300)
    branch: Annotated[str, Knob(label="Branche", advanced=False, order=2)] = Field(default="main", max_length=100)
    auto_push: Annotated[bool, Knob(label="Pousser après chaque exécution qui enregistre quelque chose",
                                    advanced=False, order=3,
                                    help="Selon l'accord du projet : tout de suite, ou après ton accord.")] = False


def _remote_initial(s: ProjectsState, frame: Frame, key: str) -> dict[str, Any]:
    p = project_at(s, key)
    return {"remote": p.remote, "branch": p.branch, "auto_push": p.auto_push} if p is not None else {}


@PROJECTS.action("depot_distant", title="Enregistrer le dépôt distant", args=RemoteArgs, emits=[REFRAMED],
                 subject="project", order=62, available=_editable, initial=_remote_initial, inline=True,
                 description="Où pousser son travail (GitHub ou un autre hôte https), et quand.")
def _remote(s: ProjectsState, frame: Frame, args: RemoteArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    errors: dict[str, str] = {}
    remote = branch = ""
    try:
        remote = check_remote(args.remote)
    except ValueError as exc:
        errors["remote"] = str(exc)
    try:
        branch = check_branch(args.branch)
    except ValueError as exc:
        errors["branch"] = str(exc)
    if errors:
        raise Refused("Le dépôt distant n'a pas été enregistré.", errors)
    auto = args.auto_push and bool(remote)
    if (remote, branch, auto) == (p.remote, p.branch, p.auto_push):
        raise Refused("Rien n'a changé.")
    return Done(drafts=(REFRAMED.draft(project=p.id, remote=remote, branch=branch, auto_push=auto, by=ctx.by,
                                       owner=p.owner, about=p.about),),
                message="Dépôt distant enregistré." if remote else "Dépôt distant retiré.", guard=_still(p.id, LIVE))


class NoArgs(BaseModel):
    pass


def _remote_ready(s: ProjectsState, frame: Frame, key: str, ports: Mapping[str, Any]) -> bool:
    p = project_at(s, key)
    return p is not None and p.status != c.ARCHIVED and bool(p.remote) and ports.get("workshop") is not None


@PROJECTS.action("pousser", title="Pousser maintenant", args=NoArgs, emits=[REMOTE_REQUESTED], subject="project",
                 order=63, available=_remote_ready, inline=True,
                 description="Envoyer ce qui est enregistré dans l'atelier vers le dépôt distant, tout de suite.")
def _push(s: ProjectsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    return Done(drafts=(REMOTE_REQUESTED.draft(project=p.id, what="push", by=ctx.by, owner=p.owner, about=p.about),),
                message="Envoi demandé : il part dans un instant. Son résultat s'affiche ici.")


def _pullable(s: ProjectsState, frame: Frame, key: str, ports: Mapping[str, Any]) -> bool:
    p = project_at(s, key)
    return _remote_ready(s, frame, key, ports) and p is not None and not busy(s, p.id)


@PROJECTS.action("recuperer", title="Récupérer du dépôt distant", args=NoArgs, emits=[REMOTE_REQUESTED],
                 subject="project", order=64, available=_pullable, inline=True,
                 confirm="Récupérer l'histoire du dépôt distant ? (en ligne droite seulement : rien n'est écrasé)",
                 description="Avancer l'atelier jusqu'au dépôt distant (en ligne droite). Un atelier vierge prend "
                             "toute son histoire.")
def _pull(s: ProjectsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    return Done(drafts=(REMOTE_REQUESTED.draft(project=p.id, what="pull", by=ctx.by, owner=p.owner, about=p.about),),
                message="Récupération demandée : elle part dans un instant.")


# ── Le piloter ────────────────────────────────────────────────────────────


def _runnable(s: ProjectsState, frame: Frame, key: str) -> bool:
    p = project_at(s, key)
    return p is not None and p.status == c.ACTIVE and not busy(s, p.id) and \
        any(o.status == c.OPEN for o in p.objectives) and not nudged(p)


@PROJECTS.action("lancer", title="Lancer maintenant", args=NoArgs, emits=[NUDGED], subject="project", order=5,
                 available=_runnable,
                 description="Sa prochaine exécution n'attend ni l'agenda, ni l'espacement, ni la plage de travail ; "
                             "elle reste sous les plafonds (par heure, par jour) et, en mode Mika, jamais pendant son "
                             "sommeil.")
def _run_now(s: ProjectsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    return Done(drafts=(NUDGED.draft(project=p.id, by=ctx.by, owner=p.owner, about=p.about),),
                message="Elle s'y met dès que possible.", guard=_still(p.id, (c.ACTIVE,)))


class ObjectiveArgs(BaseModel):
    objective: Annotated[str, Knob(label="Objectif", widget="hidden")] = Field(min_length=1, max_length=12)


def _objective_of(p: Project, raw: str) -> Objective:
    o = objective_at(p, raw)
    if o is None:
        raise Refused(f"Aucun objectif n° {raw[:12]} dans ce projet.")
    return o


@PROJECTS.action("lancer_objectif", title="Lancer cet objectif", args=ObjectiveArgs, emits=[NUDGED],
                 subject="project", order=6, available=lambda s, frame, key: _runnable(s, frame, key),
                 description="La prochaine exécution vise cet objectif, dès que possible.")
def _run_objective(s: ProjectsState, frame: Frame, args: ObjectiveArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    o = _objective_of(p, args.objective)
    if o.status != c.OPEN:
        raise Refused("Cet objectif n'est pas ouvert : rouvre-le d'abord.")
    return Done(drafts=(NUDGED.draft(project=p.id, objective=o.id, by=ctx.by, owner=p.owner, about=p.about),),
                message=f"L'objectif n° {o.id} passe en premier.", guard=_still(p.id, (c.ACTIVE,)))


def _pausable(s: ProjectsState, frame: Frame, key: str) -> bool:
    p = project_at(s, key)
    return p is not None and p.status == c.ACTIVE


def _resumable(s: ProjectsState, frame: Frame, key: str) -> bool:
    p = project_at(s, key)
    return p is not None and p.status == c.PAUSED


@PROJECTS.action("pause", title="Mettre en pause", args=NoArgs, emits=[PAUSED], subject="project", order=10,
                 available=_pausable, description="Plus aucune exécution jusqu'à ce que tu le reprennes ; une "
                                                  "exécution en cours s'arrête.")
def _pause(s: ProjectsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    return Done(drafts=(PAUSED.draft(project=p.id, reason="mis en pause par un opérateur", by=ctx.by, owner=p.owner,
                                     about=p.about),), message="Projet en pause.", guard=_still(p.id, (c.ACTIVE,)))


@PROJECTS.action("reprendre", title="Reprendre", args=NoArgs, emits=[RESUMED], subject="project", order=11,
                 available=_resumable, description="Il repart d'où il en était (ses pannes oubliées).")
def _resume(s: ProjectsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    return Done(drafts=(RESUMED.draft(project=p.id, by=ctx.by, owner=p.owner, about=p.about),),
                message="Projet repris.", guard=_still(p.id, (c.PAUSED,)))


class InstructionArgs(BaseModel):
    instruction: Annotated[str, Knob(label="Consigne", widget="textarea", advanced=False,
                                     help="Elle la lira à sa prochaine exécution ; la plus récente prime.")
                           ] = Field(min_length=1, max_length=2000)


@PROJECTS.action("consigne", title="Donner une consigne", args=InstructionArgs, emits=[AMENDED], subject="project",
                 order=20, available=_editable,
                 description="Une précision sur ce qu'elle doit faire, ajoutée au cadre du projet.")
def _amend(s: ProjectsState, frame: Frame, args: InstructionArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    text = args.instruction.strip()
    if not text:
        raise Refused("La consigne est vide.", {"instruction": "valeur requise"})
    return Done(drafts=(AMENDED.draft(project=p.id, instruction=Content.of(text, level=p.sensitivity), by=ctx.by,
                                      owner=p.owner, about=p.about),),
                message="Consigne ajoutée : elle la lira à sa prochaine exécution.", guard=_still(p.id, LIVE))


def _archivable(s: ProjectsState, frame: Frame, key: str) -> bool:
    p = project_at(s, key)
    return p is not None and p.status in LIVE


def _restorable(s: ProjectsState, frame: Frame, key: str) -> bool:
    p = project_at(s, key)
    return p is not None and p.status == c.ARCHIVED


@PROJECTS.action("archiver", title="Archiver", args=NoArgs, emits=[ARCHIVED], subject="project", order=90,
                 available=_archivable, danger=True,
                 confirm="Archiver ce projet ? Il ne fera plus aucune exécution ; son dossier, son dépôt et son "
                         "histoire restent, et on peut le restaurer.",
                 description="Il ne travaille plus. Rien n'est effacé : on peut le restaurer.")
def _archive(s: ProjectsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    return Done(drafts=(ARCHIVED.draft(project=p.id, reason="archivé par un opérateur", by=ctx.by, owner=p.owner,
                                       about=p.about),), message="Projet archivé.", guard=_still(p.id, LIVE))


@PROJECTS.action("restaurer", title="Restaurer", args=NoArgs, emits=[RESTORED], subject="project", order=91,
                 available=_restorable, description="Il revient, en pause : reprends-le quand tu veux.")
def _restore(s: ProjectsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    return Done(drafts=(RESTORED.draft(project=p.id, by=ctx.by, owner=p.owner, about=p.about),),
                message="Projet restauré (en pause).", guard=_still(p.id, (c.ARCHIVED,)))


# ── Ses objectifs ─────────────────────────────────────────────────────────


class ObjectiveAddArgs(BaseModel):
    text: Annotated[str, Knob(label="Objectif", widget="textarea", advanced=False, order=1,
                              help="En une phrase : ce qu'il faut atteindre, ou entretenir.")
                    ] = Field(min_length=1, max_length=500)
    kind: Annotated[str, Knob(label="Sorte", choices=KIND_CHOICES, advanced=False, order=2)] = c.ONCE
    cadence_hours: Annotated[int, Knob(label="Cadence (heures, pour un constant)", advanced=False, order=3, lo=0,
                                       hi=720, help="0 : la valeur par défaut.")] = Field(default=0, ge=0, le=720)


@PROJECTS.action("objectif_ajouter", title="Ajouter un objectif", args=ObjectiveAddArgs, emits=[OBJECTIVE_ADDED],
                 subject="project", order=30, available=_editable, inline=True,
                 description="Une ligne de plus : elle la verra à la prochaine exécution.")
def _objective_add(s: ProjectsState, frame: Frame, args: ObjectiveAddArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    if living(p) >= OBJECTIVES_KEPT:
        raise Refused(f"Ce projet a déjà {OBJECTIVES_KEPT} objectifs ouverts ou bloqués : retires-en avant d'en "
                      "ajouter.")
    if args.kind not in c.OBJECTIVE_KINDS:
        raise Refused("Sorte inconnue.", {"kind": "ponctuel ou constant"})
    draft = OBJECTIVE_ADDED.draft(project=p.id, objective=p.objective_seq + 1,
                                  text=Content.of(args.text.strip(), level=p.sensitivity), kind=args.kind,
                                  cadence_us=args.cadence_hours * HOUR if args.kind == c.CONSTANT else 0,
                                  author="operator", by=ctx.by, owner=p.owner, about=p.about)
    return Done(drafts=(draft,), message="Objectif ajouté.", guard=_still(p.id, LIVE))


class ObjectiveStatusArgs(BaseModel):
    objective: Annotated[str, Knob(label="Objectif", widget="hidden")] = Field(min_length=1, max_length=12)
    status: Annotated[str, Knob(label="Statut", widget="hidden")] = Field(min_length=1, max_length=12)


OBJECTIVE_STATUS_FR = {c.OPEN: "rouvert", c.DONE: "fait", c.BLOCKED: "bloqué", c.DROPPED: "retiré"}


@PROJECTS.action("objectif_statut", title="Changer le statut", args=ObjectiveStatusArgs, emits=[OBJECTIVE_CHANGED],
                 subject="project", order=31, available=_editable)
def _objective_status(s: ProjectsState, frame: Frame, args: ObjectiveStatusArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    o = _objective_of(p, args.objective)
    if args.status not in c.OBJECTIVE_STATUSES:
        raise Refused(f"Statut inconnu : « {args.status[:12]} ».")
    if args.status == o.status:
        raise Refused("L'objectif a déjà ce statut.")
    if o.kind == c.CONSTANT and args.status == c.DONE:
        raise Refused("Un objectif constant ne se coche pas : il revient. Retire-le s'il n'a plus lieu d'être.")
    if args.status == c.OPEN and o.status in (c.DONE, c.DROPPED) and living(p) >= OBJECTIVES_KEPT:
        raise Refused(f"Ce projet a déjà {OBJECTIVES_KEPT} objectifs ouverts ou bloqués : retires-en avant d'en "
                      "rouvrir un.")
    draft = OBJECTIVE_CHANGED.draft(project=p.id, objective=o.id, status=args.status, by=ctx.by, owner=p.owner,
                                    about=p.about)
    return Done(drafts=(draft,), message=f"Objectif n° {o.id} : {OBJECTIVE_STATUS_FR[args.status]}.",
                guard=_still(p.id, LIVE))


class ObjectiveEditArgs(BaseModel):
    objective: Annotated[str, Knob(label="Objectif", widget="hidden")] = Field(min_length=1, max_length=12)
    text: Annotated[str, Knob(label="Objectif", widget="textarea", advanced=False)] = Field(min_length=1,
                                                                                            max_length=500)
    kind: Annotated[str, Knob(label="Sorte", choices=KIND_CHOICES, advanced=False)] = c.ONCE
    cadence_hours: Annotated[int, Knob(label="Cadence (heures, pour un constant)", advanced=False, lo=0, hi=720,
                                       help="0 : la valeur par défaut.")] = Field(default=0, ge=0, le=720)


@PROJECTS.action("objectif_modifier", title="Modifier l'objectif", args=ObjectiveEditArgs,
                 emits=[OBJECTIVE_CHANGED], subject="project", order=32, available=_editable)
def _objective_edit(s: ProjectsState, frame: Frame, args: ObjectiveEditArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    o = _objective_of(p, args.objective)
    text = _texts(ctx.ports or {}, (o.text_ref,)).get(o.text_ref, "")
    changes: dict[str, Any] = {}
    if args.text.strip() != text:
        changes["text"] = Content.of(args.text.strip(), level=p.sensitivity)
    if args.kind in c.OBJECTIVE_KINDS and args.kind != o.kind:
        changes["kind"] = args.kind
    cadence = args.cadence_hours * HOUR if (changes.get("kind") or o.kind) == c.CONSTANT else 0
    if cadence != o.cadence_us:
        changes["cadence_us"] = cadence
    if not changes:
        raise Refused("Rien n'a changé.")
    return Done(drafts=(OBJECTIVE_CHANGED.draft(project=p.id, objective=o.id, by=ctx.by, owner=p.owner, about=p.about,
                                                **changes),),
                message=f"Objectif n° {o.id} modifié.", guard=_still(p.id, LIVE))


# ── Ses décisions techniques ──────────────────────────────────────────────


class DecideArgs(BaseModel):
    title: Annotated[str, Knob(label="La question tranchée", advanced=False, order=1,
                               help="En quelques mots : « stockage des réglages », « langage du module »…")
                     ] = Field(min_length=1, max_length=200)
    choice: Annotated[str, Knob(label="Ce qui est choisi", widget="textarea", advanced=False, order=2)
                      ] = Field(min_length=1, max_length=1500)
    reason: Annotated[str, Knob(label="Pourquoi", widget="textarea", advanced=False, order=3)
                      ] = Field(default="", max_length=1500)
    context: Annotated[str, Knob(label="Le contexte", widget="textarea", order=4,
                                 help="Ce qui rendait la décision nécessaire.")] = Field(default="", max_length=2000)
    options: Annotated[str, Knob(label="Les options envisagées", widget="textarea", order=5)
                       ] = Field(default="", max_length=2000)
    replaces: Annotated[int, Knob(label="Remplace la décision n°", order=6, lo=0, hi=100_000,
                                  help="Facultatif : une décision en vigueur que celle-ci remplace (0 : aucune).")
                        ] = Field(default=0, ge=0)


@PROJECTS.action("decision_ajouter", title="Consigner une décision", args=DecideArgs, emits=[DECIDED],
                 subject="project", order=40, available=_editable, inline=True,
                 description="Une décision technique qu'elle relira à chaque exécution (et ne rouvrira pas sans la "
                             "remplacer).")
def _decide(s: ProjectsState, frame: Frame, args: DecideArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    if args.replaces:
        old = decision_at(p, args.replaces)
        if old is None or old.status != c.IN_FORCE:
            raise Refused("Il n'y a pas de décision en vigueur à ce numéro.",
                          {"replaces": "le numéro d'une décision en vigueur, ou 0"})
    elif in_force(p) >= DECISIONS_KEPT:
        raise Refused(f"Ce projet a déjà {DECISIONS_KEPT} décisions en vigueur : retires-en une, ou remplace-la.")
    level = p.sensitivity

    def opt(text: str) -> Content | None:
        return Content.of(text.strip(), level=level) if text.strip() else None

    number = p.decision_seq + 1
    draft = DECIDED.draft(project=p.id, decision=number, title=Content.of(args.title.strip(), level=level),
                          choice=Content.of(args.choice.strip(), level=level), context=opt(args.context),
                          options=opt(args.options), reason=opt(args.reason), replaces=args.replaces,
                          author="operator", by=ctx.by, owner=p.owner, about=p.about)
    return Done(drafts=(draft,), message="Décision consignée.", guard=_still(p.id, LIVE))


class DecisionStatusArgs(BaseModel):
    decision: Annotated[str, Knob(label="Décision", widget="hidden")] = Field(min_length=1, max_length=12)
    status: Annotated[str, Knob(label="Statut", widget="hidden")] = Field(min_length=1, max_length=12)


DECISION_STATUS_FR = {c.IN_FORCE: "remise en vigueur", c.WITHDRAWN: "retirée", c.SUPERSEDED: "remplacée"}


@PROJECTS.action("decision_statut", title="Changer le statut", args=DecisionStatusArgs, emits=[DECISION_CHANGED],
                 subject="project", order=41, available=_editable)
def _decision_status(s: ProjectsState, frame: Frame, args: DecisionStatusArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    d = decision_at(p, args.decision)
    if d is None:
        raise Refused(f"Aucune décision n° {args.decision[:12]}.")
    if d.status == c.SUPERSEDED:
        raise Refused(f"La décision n° {d.id} a été remplacée (par D{d.replaced_by}) : c'est celle-là qu'on change.")
    if args.status not in (c.IN_FORCE, c.WITHDRAWN) or args.status == d.status:
        raise Refused("Ce statut ne s'applique pas ici.")
    if args.status == c.IN_FORCE and in_force(p) >= DECISIONS_KEPT:
        raise Refused(f"Ce projet a déjà {DECISIONS_KEPT} décisions en vigueur.")
    return Done(drafts=(DECISION_CHANGED.draft(project=p.id, decision=d.id, status=args.status, by=ctx.by,
                                               owner=p.owner, about=p.about),),
                message=f"Décision n° {d.id} {DECISION_STATUS_FR[args.status]}.", guard=_still(p.id, LIVE))


# ── Déposer un fichier ────────────────────────────────────────────────────


class DepositArgs(BaseModel):
    file: Annotated[Upload | None, Knob(label="Fichier", widget="file", advanced=False, order=10,
                                        help=f"{UPLOAD_MAX // (1024 * 1024)} Mo au plus. Il arrive dans l'atelier, "
                                             "enregistré à part (« apport de l'opérateur »).")] = None
    folder: Annotated[str, Knob(label="Dans le dossier", advanced=False, order=20,
                                help="Facultatif (« donnees/ ») ; vide : à la racine.")] = Field(default="",
                                                                                               max_length=200)
    note: Annotated[str, Knob(label="Ce qu'il faut en faire", widget="textarea", advanced=False, order=30,
                              help="Facultatif : elle le lira à sa prochaine exécution.")] = Field(default="",
                                                                                                 max_length=1000)
    replace: Annotated[bool, Knob(label="Remplacer un fichier du même nom", advanced=False, order=40,
                                  help="Sans cette case, un fichier qui existe déjà n'est pas écrasé.")] = False


def _depositable(s: ProjectsState, frame: Frame, key: str, ports: Mapping[str, Any]) -> bool:
    p = project_at(s, key)
    return p is not None and p.status in LIVE and ports.get("workshop") is not None


@PROJECTS.action("deposer", title="Déposer un fichier", args=DepositArgs, emits=[DEPOSITED], subject="project",
                 order=50, available=_depositable, inline=True,
                 description="Une donnée, un exemple, un modèle : dans l'atelier, pour qu'elle s'en serve.")
async def _deposit(s: ProjectsState, frame: Frame, args: DepositArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    if args.file is None or not args.file.data:
        raise Refused("Aucun fichier (ou un fichier vide).", {"file": "choisis un fichier"})
    port = (ctx.ports or {}).get("workshop")
    if port is None:
        raise Refused("L'atelier n'est pas disponible ici.")
    if p.status not in LIVE:
        raise Refused("Ce projet est archivé : restaure-le d'abord.")
    folder = args.folder.strip().strip("/")
    path = f"{folder}/{args.file.name}" if folder else args.file.name
    try:
        if not args.replace and port.exists(p.id) and await port.tree(p.id, path):
            raise Refused(f"« {path} » existe déjà dans l'atelier : coche « Remplacer » pour l'écraser.",
                          {"replace": "le fichier existe déjà"})
        rel = await port.write_bytes(p.id, path, args.file.data)
    except OutsideWorkshop as exc:
        raise Refused(f"Refusé : {exc}", {"folder": str(exc)}) from None
    # ce fichier seulement : le travail en cours d'une exécution reste à elle (elle l'enregistrera)
    await port.commit(p.id, f"apport de l'opérateur : {rel}", paths=(rel,))
    note = Content.of(args.note.strip(), level=p.sensitivity) if args.note.strip() else None
    return Done(drafts=(DEPOSITED.draft(project=p.id, name=rel, size=len(args.file.data), note=note, by=ctx.by,
                                        owner=p.owner, about=p.about),),
                message=f"Déposé dans l'atelier : {rel}.", guard=_still(p.id, LIVE))


# ── Décider de ce qui sort de la machine ──────────────────────────────────


class ApproveArgs(BaseModel):
    proposal: Annotated[str, Knob(label="Demande", widget="hidden")] = Field(min_length=1, max_length=20)
    seen: Annotated[str, Knob(label="Lu", widget="hidden")] = Field(default="", max_length=100)


class RefuseArgs(BaseModel):
    proposal: Annotated[str, Knob(label="Demande", widget="hidden")] = Field(min_length=1, max_length=20)
    note: Annotated[str, Knob(label="Pourquoi", widget="textarea", advanced=False,
                              help="Facultatif : elle le lira à sa prochaine exécution.")] = Field(default="",
                                                                                                 max_length=500)


def pending_of(frame: Frame, project: int) -> list[Any]:
    """Les demandes de ce projet qui attendent un accord."""
    return [v for v in frame.get(rt.PENDING_EFFECTS) if v.owner == c.OWNER and project_of(v.context) == project]


def _decidable(s: ProjectsState, frame: Frame, key: str) -> bool:
    p = project_at(s, key)
    return p is not None and bool(pending_of(frame, p.id))


def _approvable(s: ProjectsState, frame: Frame, key: str) -> bool:
    """Approuver : seulement un projet vivant (un projet archivé ne fait plus rien sortir ; refuser, si)."""
    p = project_at(s, key)
    return _decidable(s, frame, key) and p is not None and p.status != c.ARCHIVED


def _proposal_of(frame: Frame, p: Project, raw: str) -> int:
    wanted = int(raw) if raw.strip().isdigit() else -1
    if wanted not in {v.proposal for v in pending_of(frame, p.id)}:
        raise Refused("Cette demande n'attend plus de décision (déjà décidée ?).")
    return wanted


@PROJECTS.action("approuver", title="Approuver", args=ApproveArgs, emits=[], subject="project", order=70,
                 available=_approvable, confirm="Approuver cette demande ? Elle part aussitôt.")
def _approve(s: ProjectsState, frame: Frame, args: ApproveArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    proposal = _proposal_of(frame, p, args.proposal)
    return Done(decide=(Decision(proposal, True, seen=args.seen),), message="Approuvé : elle part dans un instant.")


@PROJECTS.action("refuser", title="Refuser", args=RefuseArgs, emits=[], subject="project", order=71,
                 available=_decidable, danger=True)
def _refuse(s: ProjectsState, frame: Frame, args: RefuseArgs, ctx: ActionContext) -> Done:
    p = _target(s, ctx)
    proposal = _proposal_of(frame, p, args.proposal)
    return Done(decide=(Decision(proposal, False, note=args.note.strip()),), message="Refusé : elle le saura.")


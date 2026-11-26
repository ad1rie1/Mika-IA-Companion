"""Ce qu'un opérateur fait de ses projets depuis la console (ADR 0031).

Des opérations seulement, chacune journalisée sous une garde (« le projet n'a
pas changé entre-temps ») : **créer** un projet, le **modifier** (cadre, mode,
rythme, plage de travail, accord), choisir ses **outils**, régler son **dépôt
distant**, poser **ce qu'il lit** (ADR 0257), le **lancer maintenant** (ou sur un objectif), le **mettre en
pause**, le **reprendre**, l'**archiver**, le **restaurer**, lui donner une
**consigne**, tenir ses **objectifs** et ses **décisions techniques**,
**déposer** un fichier dans l'atelier, **pousser** ou **récupérer**. Ce qu'il
veut faire sortir de la machine ne se décide pas ici : la file « À valider »
le décide, avec son aperçu (ADR 0177). Jamais ce qu'elle en pense ou en
ressent : un objectif coché par l'opérateur ne la rend pas fière.

Sur un projet qu'elle a ouvert d'elle-même, on pilote sans réécrire : ni son
titre, ni sa description.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import mcp as mcp_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects import asks, links, managing, triggers
from mika.faculties.projects.faculty import (
    AMENDED,
    APPROVE,
    ARCHIVED,
    ASAP,
    BASE_BUNDLES,
    DECIDED,
    DECISION_CHANGED,
    DECISIONS_KEPT,
    DEPOSITED,
    EXTRA_BUNDLES,
    LINKS_MAX,
    LINKS_SET,
    NUDGED,
    OBJECTIVE_ADDED,
    OBJECTIVE_CHANGED,
    OBJECTIVES_KEPT,
    PAUSED,
    PLAN_ANSWERED,
    PROJECTS,
    REFRAMED,
    REMOTE_REQUESTED,
    RESTORED,
    RESUMED,
    REVISE,
    Project,
    ProjectsState,
    busy,
    by_pulls,
    check_schedule,
    decision_at,
    default_flow,
    in_force,
    living,
    nudged,
    objectives_of,
    opened,
    outgoing,
    params,
    project_at,
    subjects_of,
    writes_pulls,
    written,
)
from mika.faculties.projects.inspect_common import (
    LIVE,
    operator_person,
    target_objective,
    target_project,
    unchanged,
)
from mika.faculties.projects.inspect_reviews import REREAD_CHOICES, REREAD_HELP, REREAD_LABEL, REREAD_UNKNOWN
from mika.faculties.projects.milestones import routine_text
from mika.faculties.projects.rhythm import pick
from mika.kernel import schedule
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.events import Content
from mika.kernel.forms import UPLOAD_MAX, FormField, Knob, Upload, describe
from mika.kernel.frame import Frame
from mika.kernel.operate import ActionContext, Done, Refused
from mika.ports.workshop import BASE_BRANCH, OutsideWorkshop, WorkshopFull, check_branch, check_remote
from mika.vocab.circadian import DAYS_FR
from mika.vocab.episodes import project_of
from mika.vocab.phrasebook import family
from mika.vocab.privacy import Sensitivity

MODE_CHOICES = ((c.PERSONA, "Elle-même : elle y travaille avec son humeur et ses avis"),
                (c.PLAIN, "Impersonnel : un travail factuel, sans persona ni émotion"))
#: ce que veut dire chaque mode — l'humeur dans son prompt, ce qu'elle en ressent, son sommeil : la fiche dessinée
#: d'un projet ne redit pas ces faits à côté du formulaire (la vue les garde, faculties/projects/inspect.py)
MODE_HELP = ("En mode « elle-même », c'est elle qui travaille : sa voix, ses avis, son humeur et sa fatigue dans son "
             "prompt ; ce qu'elle mène à bout la rend fière, ce qui bloque la frustre, et elle le raconte ; elle ne "
             "travaille pas pendant son sommeil. En mode impersonnel, le travail est factuel, sans persona, émotion ni "
             "récit, et se fait même pendant son sommeil (dans la plage de travail).")
PRIORITY_CHOICES = ((c.LOW, "basse"), (c.NORMAL, "normale"), (c.HIGH, "haute"), (c.URGENT, "urgente"))
PRIORITY_HELP = "Entre deux projets qui peuvent avancer, le plus prioritaire passe devant (sans passer les plafonds)."
DAYS_CHOICES = ((c.EVERY_DAY, "tous les jours"), (c.WEEKDAYS, "les jours ouvrés (lundi–vendredi)"),
                (c.WEEKEND, "le week-end"))
KIND_CHOICES = ((c.ONCE, "ponctuel — à faire une fois"), (c.CONSTANT, "constant — à entretenir, il revient"))
SCHEDULES = (("manual", "dès que possible"), ("demand", "sur demande (seulement quand on le lance)"),
             ("interval:30m", "toutes les 30 min"),
             ("interval:2h", "toutes les 2 h"), ("interval:6h", "toutes les 6 h"),
             ("cron:0 9 * * *", "chaque jour à 9 h"), ("cron:0 9 * * MON-FRI", "les jours ouvrés à 9 h"),
             ("cron:0 18 * * SUN", "le dimanche à 18 h"))
#: le choix de l'agenda qui ouvre le champ libre ``schedule_rule`` : un intervalle ou des horaires hors de la liste
OTHER_RULE = "autre"
#: l'agenda se choisit par ses mots (la valeur envoyée reste la règle), ou s'écrit à la main
SCHEDULE_CHOICES = (*SCHEDULES, (OTHER_RULE, "une autre règle…"))
SCHEDULE_HELP = ("Quand elle y travaille d'elle-même, dans sa plage de travail. « Une autre règle… » : un intervalle "
                 "ou des horaires à toi.")
RULE_HELP = ("Un intervalle : « interval:45m » (toutes les 45 min ; s, m, h ou d, cinq minutes au moins). Des "
             "horaires, en cron et à l'heure locale (minute, heure, jour du mois, mois, jour de la semaine) : "
             "« cron:30 8 * * MON-FRI » (les jours ouvrés à 8 h 30).")
_DAY_SETS = {frozenset(range(7)): "chaque jour", frozenset(range(5)): "les jours ouvrés",
             frozenset({5, 6}): "le week-end"}


def _at(hour: int, minute: int) -> str:
    return f"à {hour} h" + (f" {minute:02d}" if minute else "")


def schedule_words(rule: str) -> str:
    """L'agenda d'un projet en mots (« dès que possible », « les jours ouvrés à 9 h »), tel que la console (la liste
    des projets, sa fiche) et le panneau de frontendv2 le disent : jamais ``manual`` ni ``cron:0 9 * * MON-FRI``.
    Une valeur de ``SCHEDULES`` garde son libellé ; un intervalle ou un cron hors de la liste se traduit ; un cron
    qu'on ne sait pas dire en une phrase devient « selon son agenda »."""
    raw = (rule or "manual").strip()
    known = next((label for value, label in SCHEDULES if value == raw), None)
    if known:
        return known
    parsed = schedule.read(raw)
    if parsed.kind == "interval":
        minutes = parsed.every_us // MINUTE
        if minutes % (24 * 60) == 0:
            n = minutes // (24 * 60)
            return "tous les jours" if n == 1 else f"tous les {n} jours"
        if minutes % 60 == 0:
            return f"toutes les {minutes // 60} h"
        return f"toutes les {minutes} min"
    if parsed.kind == "cron" and len(parsed.hours) == 1 and len(parsed.minutes) == 1 and not parsed.dom_restricted \
            and len(parsed.months) == 12:
        (hour,), (minute,) = tuple(parsed.hours), tuple(parsed.minutes)
        days = _DAY_SETS.get(parsed.weekdays)
        if days is None:
            days = ", ".join(f"le {DAYS_FR[d]}" for d in sorted(parsed.weekdays))
        return f"{days} {_at(hour, minute)}"
    return "selon son agenda" if parsed.kind == "cron" else "dès que possible"


#: les lots qu'on peut lui donner, en mots
BUNDLE_WORDS = {"memory": "sa mémoire (souvenirs, croyances)", "mcp.web": "le web (chercher, lire des pages)",
                "email": "le courrier (lire, proposer des envois)",
                "rss": "ses flux RSS", "forge": "la Forge (écrire des apps)", "forge_apps": "ses apps forgées",
                "camera": "la caméra"}
_HHMM = re.compile(r"^(\d{1,2})(?:\s*[:h]\s*(\d{0,2}))?$")


def _capital(words: str) -> str:
    return words[:1].upper() + words[1:]


def _label(bundle: str) -> str:
    """Le libellé d'une case d'outil : la majuscule au début, le reste tel quel (« Ses flux RSS »)."""
    return _capital(BUNDLE_WORDS[bundle])


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


def knob_of(bundle: str) -> str:
    """Le nom de la case d'un lot (« mcp.web » → ``tool_web``)."""
    return "tool_" + bundle.removeprefix("mcp.")


#: la case d'un service branché (ADR 0254) : « mcp.meteo » → ``service_meteo`` — à part des cases des lots du code,
#: pour qu'un serveur nommé comme l'un d'eux ne prenne pas sa case
SERVICE_KNOB = "service_"


def service_knob(bundle: str) -> str:
    return SERVICE_KNOB + mcp_c.service_of(bundle)


def service_words(bundle: str) -> str:
    """Un service branché, en mots (« le service « meteo » »)."""
    return f"le service « {mcp_c.service_of(bundle)} »"


def services_here(frame: Frame) -> dict[str, str]:
    """Les services branchés qu'on peut donner à un projet : leur lot, et ce qu'il permet (ADR 0254). Le web n'en
    est pas un : il a sa case."""
    known: Mapping[str, str] = getattr(frame.env, "bundles", {}) or {}
    return {b: known[b] for b in sorted(known) if mcp_c.is_service(b)}


# ── Ce que le cadre réserve à qui s'occupe d'elle (ADR 0292) ───────────────

#: les champs du cadre d'un projet qui ouvrent autre chose que le projet lui-même, par action : pour qui il est et
#: l'accord de ce qui sort ; son dépôt distant en entier (son adresse, sa branche, l'envoi automatique, son flux) ; la
#: publication de ses tickets en issues. Les cases de ses outils se jugent lot par lot (``managing.beyond``)
RESERVED_FIELDS: Mapping[str, tuple[str, ...]] = {
    "projects.modifier": ("owner", "approval"),
    "projects.depot_distant": ("remote", "branch", "auto_push", "flow"),
    "projects.tickets_regler": ("issues",),
}
TOOLS_ACTION = "projects.outils"
KEEPER_ONLY = ("Ce réglage ouvre autre chose que ce projet (son courrier, sa caméra, ses services, ce qui sort sans "
               "accord, un dépôt distant) : il est réservé à qui s'occupe d'elle.")
KEEPER_FIELD = "réservé à qui s'occupe d'elle"


def reserved_field(action: str, name: str) -> bool:
    """Ce champ du cadre d'un projet est-il réservé à qui s'occupe d'elle ? La règle que les actions appliquent, et
    que l'API de la personne lit pour dire d'avance, champ par champ, ce qu'elle peut changer."""
    if action == TOOLS_ACTION:
        return name.startswith(SERVICE_KNOB) or name in {knob_of(b) for b in EXTRA_BUNDLES if managing.beyond(b)}
    return name in RESERVED_FIELDS.get(action, ())


def keeper_acts(frame: Frame, ctx: ActionContext) -> bool:
    """La personne qui agit s'occupe-t-elle d'elle ?"""
    return managing.keeps(frame, operator_person(frame, ctx))


def refuse_reserved(frame: Frame, ctx: ActionContext, action: str, changed: Iterable[str]) -> None:
    """Refuse le geste si l'un des champs qu'il change est réservé à qui s'occupe d'elle et que la personne qui
    agit ne l'est pas — depuis la console comme depuis son espace : la garde est ici, pas dans une route."""
    held = [name for name in changed if reserved_field(action, name)]
    if held and not keeper_acts(frame, ctx):
        raise Refused(KEEPER_ONLY, {name: KEEPER_FIELD for name in held})


def _ticked(args: Any, knob: str) -> bool:
    """Une case cochée, que les arguments viennent d'un modèle ou d'un formulaire à champs dynamiques."""
    return bool(args.get(knob, False) if isinstance(args, Mapping) else getattr(args, knob, False))


def _bundles(args: Any, services: Iterable[str] = ()) -> tuple[str, ...]:
    """Ses lots : ceux de tout projet, les cases cochées, puis les services cochés parmi ``services``."""
    return (*BASE_BUNDLES, *(b for b in EXTRA_BUNDLES if _ticked(args, knob_of(b))),
            *(b for b in services if _ticked(args, service_knob(b))))


def _rhythm(args: Any, errors: dict[str, str]) -> tuple[str, int, int]:
    """Son agenda (la valeur choisie, ou la règle écrite sous « une autre règle… », l'erreur sur le champ qui la
    porte) et sa plage de travail, en minutes. Une valeur de ``schedule`` hors de ``SCHEDULE_CHOICES`` n'arrive pas
    par un formulaire (``kernel.forms`` refuse un choix inconnu) : arrivée autrement, elle se lit comme une règle."""
    other = args.schedule.strip() == OTHER_RULE
    where, rule = ("schedule_rule", args.schedule_rule.strip()) if other else ("schedule", args.schedule.strip())
    if other and not rule:
        errors[where] = "écris la règle, ou choisis un agenda proposé"
    else:
        try:
            rule = check_schedule(rule or ASAP)
        except ValueError as exc:
            errors[where] = f"règle refusée : {exc}"
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
                                            "0 : la valeur par défaut (Réglages › Paramètres avancés › Projets).")
                         ] = Field(default=0, ge=0, le=720)
    mode: Annotated[str, Knob(label="Mode de travail", choices=MODE_CHOICES, group="Son mode et ses outils",
                              advanced=False, order=60, help=MODE_HELP)] = c.PERSONA
    tool_memory: Annotated[bool, Knob(label=_label("memory"), group="Son mode et ses outils",
                                      advanced=False, order=61, help=TOOL_HELP)] = True
    tool_web: Annotated[bool, Knob(label=_label("mcp.web"), group="Son mode et ses outils",
                                   advanced=False, order=62)] = True
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
    schedule: Annotated[str, Knob(label="Agenda", choices=SCHEDULE_CHOICES, group="Son rythme", advanced=False,
                                  order=70, help=SCHEDULE_HELP)] = Field(default=ASAP, max_length=120)
    schedule_rule: Annotated[str, Knob(label="Sa règle", group="Son rythme", advanced=False, order=70,
                                       only=(("schedule", (OTHER_RULE,)),), help=RULE_HELP)
                             ] = Field(default="", max_length=120)
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
    # la relecture indépendante (ADR 0276) : ses mots sont dans ``inspect_reviews.py``
    reread: Annotated[str, Knob(label=REREAD_LABEL, choices=REREAD_CHOICES, group="Sa liberté", advanced=False,
                                order=81, help=REREAD_HELP)] = c.REREAD_OUT
    remote: Annotated[str, Knob(label="Dépôt distant", group="Son dépôt distant", advanced=False, order=90,
                                help="Facultatif : une adresse https (https://github.com/compte/depot.git). Le jeton "
                                     "se règle dans Connexions › Dépôts Git.")
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
        auto_push=args.auto_push and bool(remote),
        # son flux se décide ici, à sa naissance : par pull request dès que l'hôte sait en ouvrir une (ADR 0274)
        flow=default_flow(ctx.ports, remote), reread=args.reread)

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
                               advanced=False, order=30,
                               help="Vide : pour toi. Un projet qui n'est pour personne le reste tant qu'on ne nomme "
                                    "personne.")] = Field(default="", max_length=120)
    mode: Annotated[str, Knob(label="Mode de travail", choices=MODE_CHOICES, group="Son mode", advanced=False,
                              order=40, help=MODE_HELP)] = c.PERSONA
    schedule: Annotated[str, Knob(label="Agenda", choices=SCHEDULE_CHOICES, group="Son rythme", advanced=False,
                                  order=50, help=SCHEDULE_HELP)] = Field(default=ASAP, max_length=120)
    schedule_rule: Annotated[str, Knob(label="Sa règle", group="Son rythme", advanced=False, order=50,
                                       only=(("schedule", (OTHER_RULE,)),), help=RULE_HELP)
                             ] = Field(default="", max_length=120)
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
    # absente d'un formulaire (un client d'avant l'ADR 0276, un envoi qui ne la porte pas), elle garde sa valeur :
    # jamais un refus, jamais le défaut posé à la place de ce que le projet avait
    reread: Annotated[str | None, Knob(label=REREAD_LABEL, choices=REREAD_CHOICES, group="Sa liberté",
                                       advanced=False, order=61, help=REREAD_HELP)] = None


def can_edit(s: ProjectsState, frame: Frame, key: str) -> bool:
    p = project_at(s, key)
    return p is not None and p.status in LIVE


def _modify_initial(s: ProjectsState, frame: Frame, key: str, ports: Mapping[str, Any]) -> dict[str, Any]:
    p = project_at(s, key)
    if p is None:
        return {}
    texts = _texts(ports, (p.title_ref, p.description_ref))
    return {"title": texts.get(p.title_ref, ""), "description": texts.get(p.description_ref, ""),
            "owner": p.owner or "", "mode": p.mode, **_schedule_initial(p.schedule), "days": p.days,
            "start": _clock(p.start_min) if p.start_min else "", "end": _clock(p.end_min) if p.end_min < 1440 else "",
            "runs_per_day": p.runs_per_day, "priority": p.priority, "approval": p.approval, "reread": p.reread}


def _schedule_initial(rule: str) -> dict[str, str]:
    """Son agenda tel que le formulaire le montre : la valeur proposée quand c'en est une, sinon « une autre
    règle… » et la règle dans le champ libre. Un sélecteur dont la valeur n'est pas parmi ses choix se poserait sur
    le premier, et l'enregistrement d'un autre champ remettrait l'agenda à « dès que possible »."""
    raw = (rule or ASAP).strip()
    if raw in dict(SCHEDULES):
        return {"schedule": raw, "schedule_rule": ""}
    return {"schedule": OTHER_RULE, "schedule_rule": raw}


def _clock(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"


@PROJECTS.action("modifier", title="Modifier le projet", args=ModifyArgs, emits=[REFRAMED], subject="project",
                 order=60, available=can_edit, initial=_modify_initial, inline=True,
                 description="Son cadre, pour qui, son mode, son rythme, sa plage de travail et sa liberté. La "
                             "prochaine exécution lira le nouveau cadre ; ce qui est fait reste.")
def _modify(s: ProjectsState, frame: Frame, args: ModifyArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    texts = _texts(ctx.ports or {}, (p.title_ref, p.description_ref))
    errors: dict[str, str] = {}
    changes: dict[str, Any] = {}
    title, description = args.title.strip(), args.description.strip()
    own = p.authority == c.SELF
    me = frame.get(identity_c.PERSON(ctx.by)) if ctx.by else None
    # un champ vidé dit « pour toi » ; un projet qui n'est pour personne le reste tant qu'on ne nomme personne — sinon
    # enregistrer n'importe quel autre réglage poserait qui agit comme son propriétaire (ADR 0292)
    owner = p.owner if own or not p.owner else me
    if args.owner.strip():
        owner = _known_person(frame, args.owner.strip(), me, p.owner)
        if owner is None:
            errors["owner"] = f"personne inconnue : « {args.owner.strip()[:60]} »"
    # pour qui il est, et l'accord de ce qui sort : à qui s'occupe d'elle seulement
    refuse_reserved(frame, ctx, "projects.modifier", [name for name, moved in (
        ("owner", "owner" not in errors and owner != p.owner), ("approval", args.approval != p.approval)) if moved])
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
    reread = p.reread if args.reread is None else args.reread
    if reread not in c.REREADS:
        errors["reread"] = REREAD_UNKNOWN
    elif reread != p.reread:
        changes["reread"] = reread
    if errors:
        raise Refused("Le projet n'a pas été modifié : vérifie le formulaire.", errors)
    if not changes:
        raise Refused("Rien n'a changé.")
    new_owner = owner if changes.get("set_owner") else p.owner
    about = (new_owner,) if changes.get("set_owner") and new_owner else p.about
    return Done(drafts=(REFRAMED.draft(project=p.id, by=ctx.by, owner=new_owner, about=about, read_about=p.read_about,
                                       **changes),),
                message="Projet modifié : la prochaine exécution lira son nouveau cadre.", guard=unchanged(p.id, LIVE))


# ── Ses outils ────────────────────────────────────────────────────────────


class ToolsArgs(BaseModel):
    # « son atelier et ses outils de projet sont toujours là » : la section « Ses outils » le dit, au-dessus
    tool_memory: Annotated[bool, Knob(label=_label("memory"), advanced=False, order=1)] = False
    tool_web: Annotated[bool, Knob(label=_label("mcp.web"), advanced=False, order=2)] = False
    tool_email: Annotated[bool, Knob(label=_label("email"), advanced=False, order=2)] = False
    tool_rss: Annotated[bool, Knob(label=_label("rss"), advanced=False, order=3)] = False
    tool_forge: Annotated[bool, Knob(label=_label("forge"), advanced=False, order=4)] = False
    tool_forge_apps: Annotated[bool, Knob(label=_label("forge_apps"), advanced=False,
                                          order=5)] = False
    tool_camera: Annotated[bool, Knob(label=_label("camera"), advanced=False, order=6)] = False


def _services_of(p: Project | None, frame: Frame) -> dict[str, str]:
    """Les services qu'on peut cocher sur ce projet : ceux qui sont branchés, et ceux qu'il a déjà — un service
    débranché depuis se décoche encore."""
    offered = services_here(frame)
    gone = {b: "" for b in (p.bundles if p is not None else ()) if mcp_c.is_service(b) and b not in offered}
    return {**offered, **gone}


def _tools_initial(s: ProjectsState, frame: Frame, key: str) -> dict[str, Any]:
    p = project_at(s, key)
    if p is None:
        return {}
    return {**{knob_of(b): b in p.bundles for b in EXTRA_BUNDLES},
            **{service_knob(b): b in p.bundles for b in _services_of(p, frame)}}


def _tools_fields(s: ProjectsState, frame: Frame, key: str, fixed: Mapping[str, str]) -> tuple[FormField, ...]:
    """Les cases de « Ses outils » : celles des lots du code, puis une par service branché (ADR 0254) — la liste
    dépend de ce que l'opérateur a branché, d'où des champs dits au moment de l'afficher."""
    base = describe(ToolsArgs)
    services = _services_of(project_at(s, key), frame)
    last = max((f.order for f in base), default=0)
    extra = tuple(
        replace(base[0], path=service_knob(b), label=_capital(service_words(b)) + ("" if what else " (débranché)"),
                help=what[:200], default=False, order=last + 1 + n)
        for n, (b, what) in enumerate(services.items()))
    return (*base, *extra)


@PROJECTS.action("outils", title="Enregistrer ses outils", args=ToolsArgs, emits=[REFRAMED], subject="project",
                 order=61, available=can_edit, initial=_tools_initial, fields=_tools_fields, inline=True,
                 description="Ce qu'elle a en main pendant une exécution, en plus de son atelier.")
def _tools(s: ProjectsState, frame: Frame, args: Any, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    services = _services_of(p, frame)
    bundles = _bundles(args, services)
    if set(bundles) == set(p.bundles):
        raise Refused("Rien n'a changé.")
    # le courrier, la caméra, ses flux, la Forge, ses apps, un service : à qui s'occupe d'elle seulement
    refuse_reserved(frame, ctx, TOOLS_ACTION, [service_knob(b) if mcp_c.is_service(b) else knob_of(b)
                                     for b in (*EXTRA_BUNDLES, *services) if (b in bundles) != (b in p.bundles)])
    return Done(drafts=(REFRAMED.draft(project=p.id, bundles=bundles, by=ctx.by, owner=p.owner, about=p.about,
                                       read_about=p.read_about),),
                message="Outils enregistrés : la prochaine exécution les aura en main.", guard=unchanged(p.id, LIVE))


# ── Ce qu'il lit (ADR 0257) ───────────────────────────────────────────────


#: pourquoi un projet ne peut pas en lire un autre, en mots (``links.refusal``)
LINK_REFUSALS = {links.UNKNOWN: "il n'existe pas", links.ITSELF: "c'est ce projet lui-même",
                 links.ARCHIVED: "il est archivé",
                 links.LOOP: "il lit déjà ce projet, de près ou de loin : les liens ne font jamais de boucle",
                 links.UNSHARED: "son propriétaire ne le laisse pas voir à celui de ce projet (ses lignes d'accès)",
                 links.FULL: f"un projet en lit {LINKS_MAX} au plus"}
#: la case d'un projet à lire : « lit_7 »
LINK_KNOB = "lit_"
#: la case du mode direct d'un lien posé (ADR 0271) : « direct_7 » — ses demandes entrent dans les tickets du projet
#: lu sans attendre l'accord de son propriétaire
DIRECT_KNOB = "direct_"
#: pourquoi le mode direct ne vaut pas sur un lien, en mots (``asks.indirect``)
DIRECT_REFUSALS = {asks.MATRIX: "ses lignes d'accès ne donnent pas la modification au propriétaire de ce projet",
                   asks.LEVEL: "ce qu'il écrit est d'un niveau moins confidentiel que ce qu'écrit ce projet"}


class LinkArgs(BaseModel):
    """Le gabarit d'une case de « Ce qu'il lit » : ses cases dépendent des projets qu'il peut lire, elles sont dites
    au moment de l'afficher (``_links_fields``)."""

    lit: Annotated[bool, Knob(label="Un projet", advanced=False, order=1)] = False


def link_knob(project: int) -> str:
    return f"{LINK_KNOB}{project}"


def direct_knob(project: int) -> str:
    return f"{DIRECT_KNOB}{project}"


#: le mot de son propriétaire sur un lien (ADR 0293), sa borne
LINK_WHY_MAX = 300


def _link_word(args: Any, kept: tuple[int, ...]) -> tuple[int, str]:
    """Le mot dit sur un lien, et le projet qu'il concerne (``why``, ``why_for`` : des champs cachés, que la console
    ne rend pas) ; ``(0, "")`` : rien n'est dit. Il ne se dit que d'un projet que ce projet lit, ou se met à lire."""
    given = args if isinstance(args, Mapping) else {}
    why = " ".join(str(given.get("why") or "").split())
    if not why:
        return 0, ""
    target = str(given.get("why_for") or "")
    if not target.isdecimal() or int(target) not in kept:
        raise Refused("Ce mot se dit d'un projet que ce projet lit.", {"why_for": "projet non lu"})
    if len(why) > LINK_WHY_MAX:
        raise Refused(f"Ce mot est trop long ({LINK_WHY_MAX} caractères au plus).", {"why": "trop long"})
    return int(target), why


#: un geste de console qui pose tout l'état lu, quand cet état a bougé depuis (ADR 0297)
LINKS_MOVED = ("Ce qu'il lit a changé depuis ta lecture (dans un autre onglet, ou par quelqu'un d'autre) : rien n'est "
               "enregistré. Relis la page, puis refais ton geste.")


def links_seen(p: Any) -> str:
    """L'état de « Ce qu'il lit » tel qu'une page l'a lu : les projets qu'il lit, le mode direct de chacun. Un geste qui
    le pose (``seen``, un champ caché) prend tout l'état lu : il est refusé si cet état a bougé depuis — il déferait
    ce qu'un autre onglet a posé. Sans lui (l'API, qui envoie ce qui change), rien n'est comparé."""
    return ",".join(str(t) for t in sorted(p.reads)) + "|" + ",".join(str(t) for t in sorted(p.direct))


def numbered(ids: Iterable[int]) -> str:
    """Des projets à la suite, par leur numéro (« n° 3, n° 5 »)."""
    return ", ".join(f"n° {i}" for i in ids)


def refused_words(refused: Iterable[tuple[int, str]]) -> str:
    """Les projets qu'un lien ne peut pas viser, chacun avec sa raison (« n° 7 (il est archivé) »)."""
    return " ; ".join(f"n° {i} ({LINK_REFUSALS.get(why, why)})" for i, why in refused)


def link_options(s: ProjectsState, frame: Frame, p: Project) -> list[tuple[Project, str]]:
    """Les projets qu'on peut cocher sous « Ce qu'il lit », et ce qu'il faut en dire : ceux qu'il lit déjà (un lien
    suspendu se décoche encore), puis ceux qu'il peut se mettre à lire (ce que son plan demande le dit)."""
    world = links.world_of(frame)
    read = [(r.project, "suspendu" if r.suspended else "") for r in links.readings(s, p, world)
            if r.project is not None]
    return [*read, *((t, "demandé par son plan" if t.id in p.plan_reads else "")
                     for t in links.candidates(s, p, world))]


def _links_initial(s: ProjectsState, frame: Frame, key: str) -> dict[str, Any]:
    p = project_at(s, key)
    if p is None:
        return {}
    return {**{link_knob(t): True for t in p.reads}, **{direct_knob(t): True for t in p.direct}}


def _links_fields(s: ProjectsState, frame: Frame, key: str, fixed: Mapping[str, str],
                  ports: Mapping[str, Any]) -> tuple[FormField, ...]:
    """Les cases de « Ce qu'il lit » : une par projet qu'il lit ou peut lire, nommé par son numéro et son titre. Sous
    chaque lien déjà posé, la case de son mode direct (ADR 0271) : elle dit quand il ne vaudrait pas maintenant."""
    p = project_at(s, key)
    if p is None:
        return ()
    options = link_options(s, frame, p)
    texts = _texts(ports, (t.title_ref for t, _ in options))
    base = describe(LinkArgs)[0]
    world = links.world_of(frame)
    fields: list[FormField] = []
    for t, note in options:
        fields.append(replace(base, path=link_knob(t.id), default=False, order=len(fields) + 1,
                              label=f"n° {t.id} — {texts.get(t.title_ref) or '(titre oublié)'}"
                                    + (f" ({note})" if note else "")))
        if t.id in p.reads:
            why = asks.indirect(p, t, links.grant(p, t, world))
            fields.append(replace(
                base, path=direct_knob(t.id), default=False, order=len(fields) + 1,
                label=f"↳ ses demandes au n° {t.id} entrent directement dans ses tickets"
                      + (f" (sans effet pour l'instant : {DIRECT_REFUSALS[why]})" if why else ""),
                help="Sans cette case, une demande de ce projet y naît « proposée » : son propriétaire l'accepte ou "
                     "l'écarte."))
    return tuple(fields)


@PROJECTS.action("liens", title="Enregistrer ce qu'il lit", args=LinkArgs, emits=[LINKS_SET], subject="project",
                 order=65, available=can_edit, initial=_links_initial, fields=_links_fields, inline=True,
                 description="Les projets qu'il lit, sans jamais y écrire. Ce qu'il en reçoit se lit dans leurs lignes "
                             "d'accès, à chaque exécution. Il peut leur adresser une demande — un ticket chez eux — "
                             "quand leurs lignes donnent de les piloter : sur l'accord de leur propriétaire, ou "
                             "directement si le lien le règle ici.")
def _links(s: ProjectsState, frame: Frame, args: Any, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    world = links.world_of(frame)
    if not links.may_link(p, operator_person(frame, ctx), world):
        owner = links.owner_of(p)
        raise Refused(f"Seul son propriétaire ({identity_c.person_name(frame, owner) or owner}) pose ce que lit ce "
                      "projet." if owner else "Seul quelqu'un qui s'occupe d'elle pose ce que lit un projet à elle.")
    seen = str((args if isinstance(args, Mapping) else {}).get("seen") or "")
    if seen and seen != links_seen(p):
        raise Refused(LINKS_MOVED)
    wanted = [t.id for t, _ in link_options(s, frame, p) if _ticked(args, link_knob(t.id))]
    kept, refused = links.chosen(s, p, wanted, world)
    if refused:
        raise Refused(f"Ce projet ne peut pas lire : {refused_words(refused)}.")
    # le mode direct (ADR 0271) se règle sur un lien déjà posé, et seulement s'il vaudrait maintenant
    direct = tuple(t for t in kept if t in p.reads and _ticked(args, direct_knob(t)))
    why_for, why = _link_word(args, kept)
    if kept == p.reads and direct == p.direct and not why:
        raise Refused("Rien n'a changé.")
    blocked = [(t, why) for t in direct if t not in p.direct and (target := s.projects.get(t)) is not None
               and (why := asks.indirect(p, target, links.grant(p, target, world)))]
    if blocked:
        raise Refused("Ses demandes ne peuvent pas entrer directement chez : "
                      + " ; ".join(f"n° {t} ({DIRECT_REFUSALS[why]})" for t, why in blocked) + ".")
    said = f"Il lit maintenant : {numbered(kept)}. Sa prochaine exécution les aura sous les yeux." if kept else \
        "Il ne lit plus aucun projet. Ce qu'il en a déjà écrit garde leur niveau et leurs sujets."
    if direct:
        said += f" Ses demandes entrent directement chez : {numbered(direct)}."
    word: dict[str, Any] = {}
    if why:
        # un texte gardé (ADR 0293) : au niveau de ce qu'écrivent les deux projets, avec les sujets du sien et —
        # pour l'oubli — ceux du projet lu, que le lien lui laissera
        read = s.projects[why_for]
        word = {"why": Content.of(why, level=max(written(p), written(read))), "why_for": why_for, "owner": p.owner,
                "about": p.about, "read_about": tuple(dict.fromkeys((*p.read_about, *subjects_of(read))))}
    return Done(drafts=(LINKS_SET.draft(project=p.id, reads=kept, direct=direct, by=ctx.by, **word),), message=said,
                guard=unchanged(p.id, LIVE))


# ── Son dépôt distant ─────────────────────────────────────────────────────


#: le flux qu'on règle avec le dépôt distant (ADR 0274) : laissé à l'hôte, par pull request, ou direct
FLOW_AUTO = "auto"
FLOW_CHOICES = ((FLOW_AUTO, "selon l'hôte (par pull request s'il sait en ouvrir une)"),
                (c.FLOW_PR, "par pull request"), (c.FLOW_DIRECT, "direct"))


class RemoteArgs(BaseModel):
    remote: Annotated[str, Knob(label="Adresse du dépôt distant", advanced=False, order=1,
                                help="https://github.com/compte/depot.git — vide : aucun. Le jeton se règle dans "
                                     "Connexions › Dépôts Git.")] = Field(default="", max_length=300)
    branch: Annotated[str, Knob(label="Branche", advanced=False, order=2)] = Field(default="main", max_length=100)
    auto_push: Annotated[bool, Knob(label="Pousser après chaque exécution qui enregistre quelque chose",
                                    advanced=False, order=3,
                                    help="Selon l'accord du projet : tout de suite, ou après ton accord. Par pull "
                                         "request, c'est sa branche de travail qui part.")] = False
    flow: Annotated[str, Knob(label="Son flux", choices=FLOW_CHOICES, advanced=False, order=4,
                              help="Par pull request : chaque objectif a sa branche, elle propose une pull request "
                                   "quand il est fait, et elle ne fusionne jamais — la branche ci-dessus ne reçoit "
                                   "que ce que tu acceptes. Direct : son travail va sur cette branche.")
                    ] = Field(default=FLOW_AUTO, max_length=10)


def _remote_initial(s: ProjectsState, frame: Frame, key: str) -> dict[str, Any]:
    p = project_at(s, key)
    return {"remote": p.remote, "branch": p.branch, "auto_push": p.auto_push,
            "flow": p.flow if p.remote else FLOW_AUTO} if p is not None else {}


@PROJECTS.action("depot_distant", title="Enregistrer le dépôt distant", args=RemoteArgs, emits=[REFRAMED],
                 subject="project", order=62, available=can_edit, initial=_remote_initial, inline=True,
                 description="Où pousser son travail (GitHub ou un autre hôte https), et quand.")
def _remote(s: ProjectsState, frame: Frame, args: RemoteArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
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
    # son flux (ADR 0274) : celui qu'on choisit, sinon celui que l'hôte permet — décidé ici, écrit dans l'événement
    flow = (args.flow if args.flow in c.FLOWS else default_flow(ctx.ports, remote)) if remote else c.FLOW_DIRECT
    if flow == c.FLOW_PR and not writes_pulls(ctx.ports, remote):
        raise Refused("Le dépôt distant n'a pas été enregistré.",
                      {"flow": "l'hôte de ce dépôt ne sait pas ouvrir de pull request d'ici (GitHub seulement)"})
    if (remote, branch, auto, flow) == (p.remote, p.branch, p.auto_push, p.flow):
        raise Refused("Rien n'a changé.")
    # le dépôt distant est atteint par le jeton git de l'instance : le brancher, le changer, y envoyer d'office
    # reste à qui s'occupe d'elle
    refuse_reserved(frame, ctx, "projects.depot_distant", [name for name, moved in (
        ("remote", remote != p.remote), ("branch", branch != p.branch), ("auto_push", auto != p.auto_push),
        ("flow", flow != p.flow)) if moved])
    said = "Dépôt distant retiré." if not remote else "Dépôt distant enregistré." + (
        " Elle passera par des pull requests : une branche par travail, et la fusion reste à toi."
        if flow == c.FLOW_PR else "")
    return Done(drafts=(REFRAMED.draft(project=p.id, remote=remote, branch=branch, auto_push=auto, flow=flow,
                                       by=ctx.by, owner=p.owner, about=p.about, read_about=p.read_about),),
                message=said, guard=unchanged(p.id, LIVE))


class NoArgs(BaseModel):
    pass


def can_use_remote(s: ProjectsState, frame: Frame, key: str, ports: Mapping[str, Any]) -> bool:
    p = project_at(s, key)
    return p is not None and p.status != c.ARCHIVED and bool(p.remote) and ports.get("workshop") is not None


def _pushable(s: ProjectsState, frame: Frame, key: str, ports: Mapping[str, Any]) -> bool:
    """Pousser : seulement un atelier qui existe (l'action vérifie qu'il a plus que son commit d'amorce)."""
    p = project_at(s, key)
    port = ports.get("workshop")
    return can_use_remote(s, frame, key, ports) and p is not None and port is not None and port.exists(p.id)


@PROJECTS.action("pousser", title="Pousser maintenant", args=NoArgs, emits=[REMOTE_REQUESTED], subject="project",
                 order=63, available=_pushable, inline=True, danger=True,
                 confirm="Envoyer maintenant le dernier enregistrement de l'atelier vers le dépôt distant ? Il sort "
                         "de la machine, sans autre accord.",
                 description="Envoyer ce qui est enregistré dans l'atelier vers le dépôt distant, tout de suite.")
async def _push(s: ProjectsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    if p.status == c.ARCHIVED or not p.remote:
        raise Refused("Ce projet n'a plus de dépôt distant, ou il est archivé : rien ne part.")
    port = (ctx.ports or {}).get("workshop")
    if port is None or not port.exists(p.id) or await port.count(p.id) <= 1:
        raise Refused("L'atelier n'a encore rien enregistré à envoyer (seulement son amorce).")
    return Done(drafts=(REMOTE_REQUESTED.draft(project=p.id, what="push", by=ctx.by, owner=p.owner, about=p.about),),
                message="Envoi demandé : il part dans un instant. Son résultat s'affiche ici.", guard=unchanged(p.id, LIVE))


def _pullable(s: ProjectsState, frame: Frame, key: str, ports: Mapping[str, Any]) -> bool:
    p = project_at(s, key)
    return can_use_remote(s, frame, key, ports) and p is not None and not busy(s, p.id)


@PROJECTS.action("recuperer", title="Récupérer du dépôt distant", args=NoArgs, emits=[REMOTE_REQUESTED],
                 subject="project", order=64, available=_pullable, inline=True,
                 confirm="Récupérer l'histoire du dépôt distant ? (en ligne droite seulement : rien n'est écrasé)",
                 description="Avancer l'atelier jusqu'au dépôt distant (en ligne droite). Un atelier vierge prend "
                             "toute son histoire.")
def _pull(s: ProjectsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    if p.status == c.ARCHIVED or not p.remote:
        raise Refused("Ce projet n'a plus de dépôt distant, ou il est archivé : rien ne se récupère.")
    return Done(drafts=(REMOTE_REQUESTED.draft(project=p.id, what="pull", by=ctx.by, owner=p.owner, about=p.about),),
                message="Récupération demandée : elle part dans un instant.", guard=unchanged(p.id, LIVE))


# ── Le piloter ────────────────────────────────────────────────────────────


def can_run(s: ProjectsState, frame: Frame, key: str) -> bool:
    """« Lancer maintenant » : seulement si une exécution peut vraiment partir (un objectif qu'elle viserait, rien
    en route hors de la machine)."""
    p = project_at(s, key)
    if p is None or p.status != c.ACTIVE or busy(s, p.id) or nudged(p) or outgoing(p, frame.now):
        return False
    pm = params(frame.env.params_of("projects", frame.root))
    return pick(p, frame.now, pm) is not None or any(o.status == c.OPEN and o.kind == c.CONSTANT
                                                     for o in p.objectives)


@PROJECTS.action("lancer", title="Lancer maintenant", args=NoArgs, emits=[NUDGED], subject="project", order=5,
                 available=can_run,
                 description="Sa prochaine exécution n'attend ni l'agenda, ni l'espacement, ni la plage de travail ; "
                             "elle reste sous les plafonds (par heure, par jour) et, en mode « elle-même », jamais pendant son "
                             "sommeil.")
def _run_now(s: ProjectsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    return Done(drafts=(NUDGED.draft(project=p.id, by=ctx.by, owner=p.owner, about=p.about),),
                message="Elle s'y met dès que possible.", guard=unchanged(p.id, (c.ACTIVE,)))


class ObjectiveArgs(BaseModel):
    objective: Annotated[str, Knob(label="Objectif", widget="hidden")] = Field(min_length=1, max_length=12)


@PROJECTS.action("lancer_objectif", title="Lancer cet objectif", args=ObjectiveArgs, emits=[NUDGED],
                 subject="project", order=6, available=lambda s, frame, key: can_run(s, frame, key),
                 description="La prochaine exécution vise cet objectif, dès que possible.")
def _run_objective(s: ProjectsState, frame: Frame, args: ObjectiveArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    o = target_objective(p, args.objective)
    if o.status != c.OPEN:
        raise Refused("Cet objectif n'est pas ouvert : rouvre-le d'abord.")
    return Done(drafts=(NUDGED.draft(project=p.id, objective=o.id, by=ctx.by, owner=p.owner, about=p.about),),
                message=f"L'objectif n° {o.id} passe en premier.", guard=unchanged(p.id, (c.ACTIVE,)))


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
    p = target_project(s, ctx)
    return Done(drafts=(PAUSED.draft(project=p.id, reason="mis en pause par un opérateur", by=ctx.by, owner=p.owner,
                                     about=p.about),), message="Projet en pause.", guard=unchanged(p.id, (c.ACTIVE,)))


# la principale de la fiche (ADR 0176, la maquette) : « Lancer maintenant » (actif) ou « Reprendre » (en pause) — l'une
# exclut l'autre —, puis « Donner une consigne » ; la pause et le reste sous « ⋯ »
@PROJECTS.action("reprendre", title="Reprendre", args=NoArgs, emits=[RESUMED], subject="project", order=4,
                 available=_resumable, description="Il repart d'où il en était (ses pannes oubliées).")
def _resume(s: ProjectsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    return Done(drafts=(RESUMED.draft(project=p.id, by=ctx.by, owner=p.owner, about=p.about),),
                message="Projet repris.", guard=unchanged(p.id, (c.PAUSED,)))


# la réponse à son plan (ADR 0145) : le valider, ou lui demander de le reprendre
def _plan_waits(s: ProjectsState, frame: Frame, key: str) -> bool:
    p = project_at(s, key)
    return p is not None and p.status == c.ACTIVE and p.plan_state == c.PROPOSED


def _plan_revisable(s: ProjectsState, frame: Frame, key: str) -> bool:
    p = project_at(s, key)
    return p is not None and p.status == c.ACTIVE and p.plan_state != c.TO_FRAME


@PROJECTS.action("plan_valider", title="Valider le plan", args=NoArgs, emits=[PLAN_ANSWERED, LINKS_SET],
                 subject="project", order=3, available=_plan_waits, inline=True,
                 description="Son plan attend une réponse : validé, le projet le suit et elle s'y met. Validé par le "
                             "propriétaire du projet, ce que le plan demandait à lire se pose avec lui.")
def _plan_approve(s: ProjectsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    # ce que son plan demandait à lire se pose si qui valide est le propriétaire du projet (ADR 0257)
    linking = links.approved(s, p, operator_person(frame, ctx), links.world_of(frame))
    drafts = [PLAN_ANSWERED.draft(project=p.id, verdict=APPROVE, by=ctx.by, owner=p.owner, about=p.about,
                                  read_about=p.read_about)]
    said = "Plan validé : elle s'y met dès que possible."
    if linking.added:
        drafts.append(LINKS_SET.draft(project=p.id, reads=linking.reads, by=ctx.by, owner=p.owner, about=p.about, read_about=p.read_about))
        said += f" Ce projet lit maintenant : {numbered(linking.added)}."
    if linking.denied:
        said += (f" Ce que son plan demandait à lire ({numbered(linking.pending)}) n'est pas lié : seul le "
                 "propriétaire du projet pose ce lien.")
    if linking.refused:
        said += f" Ne peuvent pas être lus : {refused_words(linking.refused)}."
    return Done(drafts=tuple(drafts), message=said, tone="warn" if linking.denied or linking.refused else "ok",
                guard=unchanged(p.id, (c.ACTIVE,)))


class ReviseArgs(BaseModel):
    words: Annotated[str, Knob(label="Ce qu'il faut changer", widget="textarea", advanced=False,
                               help="Tes mots, tels quels : la séance qui reprend son plan les aura sous les yeux.")
                     ] = Field(min_length=1, max_length=2000)


@PROJECTS.action("plan_reviser", title="Demander une révision du plan", args=ReviseArgs, emits=[PLAN_ANSWERED],
                 subject="project", order=4, available=_plan_revisable, inline=True,
                 description="Elle reprend son plan (une séance de cadrage), avec ce que tu lui dis.")
def _plan_revise(s: ProjectsState, frame: Frame, args: ReviseArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    text = args.words.strip()
    if not text:
        raise Refused("Dis ce qu'il faut changer.", {"words": "valeur requise"})
    return Done(drafts=(PLAN_ANSWERED.draft(project=p.id, verdict=REVISE, words=Content.of(text, level=p.sensitivity),
                                            by=ctx.by, owner=p.owner, about=p.about, read_about=p.read_about),),
                message="Révision demandée : elle reprendra son plan avec tes mots.", guard=unchanged(p.id, (c.ACTIVE,)))


class InstructionArgs(BaseModel):
    instruction: Annotated[str, Knob(label="Consigne", widget="textarea", advanced=False,
                                     help="Elle la lira à sa prochaine exécution ; la plus récente prime.")
                           ] = Field(min_length=1, max_length=2000)


@PROJECTS.action("consigne", title="Donner une consigne", args=InstructionArgs, emits=[AMENDED], subject="project",
                 order=7, available=can_edit,
                 description="Une précision sur ce qu'elle doit faire, ajoutée au cadre du projet.")
def _amend(s: ProjectsState, frame: Frame, args: InstructionArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    text = args.instruction.strip()
    if not text:
        raise Refused("La consigne est vide.", {"instruction": "valeur requise"})
    return Done(drafts=(AMENDED.draft(project=p.id, instruction=Content.of(text, level=p.sensitivity), by=ctx.by,
                                      owner=p.owner, about=p.about, read_about=p.read_about),),
                message="Consigne ajoutée : elle la lira à sa prochaine exécution.", guard=unchanged(p.id, LIVE))


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
    p = target_project(s, ctx)
    return Done(drafts=(ARCHIVED.draft(project=p.id, reason="archivé par un opérateur", by=ctx.by, owner=p.owner,
                                       about=p.about),), message="Projet archivé.", guard=unchanged(p.id, LIVE))


@PROJECTS.action("restaurer", title="Restaurer", args=NoArgs, emits=[RESTORED], subject="project", order=91,
                 available=_restorable, description="Il revient, en pause : reprends-le quand tu veux.")
def _restore(s: ProjectsState, frame: Frame, args: NoArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    return Done(drafts=(RESTORED.draft(project=p.id, by=ctx.by, owner=p.owner, about=p.about),),
                message="Projet restauré (en pause).", guard=unchanged(p.id, (c.ARCHIVED,)))


# ── Ses objectifs ─────────────────────────────────────────────────────────


#: ce qui déclenche un objectif constant (ADR 0265), tel que les deux formulaires d'un objectif le demandent
TRIGGERS_HELP = ("Pour un constant, ce qui le fait passer en plus de sa cadence, un par ligne (quatre au plus) : "
                 "project:<n>:commit (la base du projet n° n, que ce projet lit, a avancé : un commit en flux direct, "
                 "une fusion acceptée en flux par pull request), "
                 "project:<n>:done (un de ses objectifs a abouti), app:<nom> (une app de ce projet a signalé quelque "
                 "chose), wake:<nom> (le réveil par API de ce nom vise cet objectif), item:<liste> (un autre qu'elle a "
                 "ajouté, changé ou noté un élément de cette liste du projet : item:tickets). Vide : sa cadence "
                 "seule.")
ONLY_ON_EVENT_HELP = "Coché : il n'a aucune cadence, il ne passe que quand un de ses déclencheurs arrive."
AT_ONCE_HELP = ("Pour un constant. Coché : son premier passage vient tout de suite (un audit hebdomadaire commence "
                "par un audit). Sinon il vient une cadence après sa naissance : un bilan de la semaine ne tombe pas "
                "le premier jour.")
ROUTINE_HELP = ("Ce que chaque passage d'un constant doit faire, une ligne par chose (cinq au plus) : elle le relit à "
                "chaque passage. Un ponctuel a des jalons à la place.")
#: son critère de fait (ADR 0145), tel que les deux formulaires d'un objectif le demandent (ADR 0290), et sa borne
DONE_WHEN_HELP = ("Facultatif : ce qui te ferait dire « c'est fait ». Elle dit comment il est rempli quand elle "
                  "conclut. Vide : inchangé.")
DONE_WHEN_MAX = 1500


def _triggers(p: Project, kind: str, on: Iterable[str], only_on_event: bool) -> tuple[str, ...]:
    """Les déclencheurs d'un objectif saisis dans la console, vérifiés et normalisés (ADR 0265) — un constant
    seulement, un projet que le sien lit ; sinon le formulaire dit pourquoi, sur son champ."""
    try:
        return triggers.accepted(p.id, p.reads, kind == c.CONSTANT, on, only_on_event)
    except triggers.BadTrigger as exc:
        why = family("projects.triggers.refused")[exc.why]
        said = f"« {exc.text} » : {why}" if exc.text else why
        raise Refused("Ce qui le déclenche n'est pas accepté.", {"on": said}) from exc


class ObjectiveAddArgs(BaseModel):
    text: Annotated[str, Knob(label="Objectif", widget="textarea", advanced=False, order=1,
                              help="En une phrase : ce qu'il faut atteindre, ou entretenir.")
                    ] = Field(min_length=1, max_length=500)
    kind: Annotated[str, Knob(label="Sorte", choices=KIND_CHOICES, advanced=False, order=2)] = c.ONCE
    cadence_hours: Annotated[int, Knob(label="Cadence (heures, pour un constant)", advanced=False, order=3, lo=0,
                                       hi=720, help="0 : la valeur par défaut.")] = Field(default=0, ge=0, le=720)
    on: Annotated[tuple[str, ...], Knob(label="Déclenché par", advanced=False, order=4, help=TRIGGERS_HELP)] = ()
    only_on_event: Annotated[bool, Knob(label="Sur événement seulement", advanced=False, order=5,
                                        help=ONLY_ON_EVENT_HELP)] = False
    routine: Annotated[str, Knob(label="À chaque passage (pour un constant)", widget="textarea", advanced=False,
                                 order=6, help=ROUTINE_HELP)] = Field(default="", max_length=1200)
    at_once: Annotated[bool, Knob(label="Premier passage tout de suite", advanced=False, order=7,
                                  help=AT_ONCE_HELP)] = False
    done_when: Annotated[str, Knob(label="Fini quand", widget="textarea", advanced=False, order=8,
                                   help=DONE_WHEN_HELP)] = Field(default="", max_length=DONE_WHEN_MAX)


@PROJECTS.action("objectif_ajouter", title="Ajouter un objectif", args=ObjectiveAddArgs, emits=[OBJECTIVE_ADDED],
                 subject="project", order=30, available=can_edit, inline=True,
                 description="Une ligne de plus : elle la verra à la prochaine exécution.")
def _objective_add(s: ProjectsState, frame: Frame, args: ObjectiveAddArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    if living(p) >= OBJECTIVES_KEPT:
        raise Refused(f"Ce projet a déjà {OBJECTIVES_KEPT} objectifs ouverts ou bloqués : retires-en avant d'en "
                      "ajouter.")
    if args.kind not in c.OBJECTIVE_KINDS:
        raise Refused("Sorte inconnue.", {"kind": "ponctuel ou constant"})
    on = _triggers(p, args.kind, args.on, args.only_on_event)
    each = routine_text(args.routine.split("\n")) if args.kind == c.CONSTANT else ""
    draft = OBJECTIVE_ADDED.draft(project=p.id, objective=p.objective_seq + 1,
                                  text=Content.of(args.text.strip(), level=p.sensitivity), kind=args.kind,
                                  cadence_us=args.cadence_hours * HOUR if args.kind == c.CONSTANT else 0,
                                  author="operator", by=ctx.by, owner=p.owner, about=p.about,
                                  read_about=p.read_about, on=on, only_on_event=args.only_on_event,
                                  at_once=args.at_once and args.kind == c.CONSTANT,
                                  routine=Content.of(each, level=p.sensitivity) if each else None,
                                  done_when=Content.of(args.done_when.strip(), level=p.sensitivity)
                                  if args.done_when.strip() else None)
    return Done(drafts=(draft,), message="Objectif ajouté.", guard=unchanged(p.id, LIVE))


class ObjectiveStatusArgs(BaseModel):
    objective: Annotated[str, Knob(label="Objectif", widget="hidden")] = Field(min_length=1, max_length=12)
    status: Annotated[str, Knob(label="Statut", widget="hidden")] = Field(min_length=1, max_length=12)


OBJECTIVE_STATUS_FR = {c.OPEN: "rouvert", c.DONE: "fait", c.BLOCKED: "bloqué", c.DROPPED: "retiré"}


@PROJECTS.action("objectif_statut", title="Changer le statut", args=ObjectiveStatusArgs, emits=[OBJECTIVE_CHANGED],
                 subject="project", order=31, available=can_edit)
def _objective_status(s: ProjectsState, frame: Frame, args: ObjectiveStatusArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    o = target_objective(p, args.objective)
    if args.status not in c.OBJECTIVE_STATUSES:
        raise Refused(f"Statut inconnu : « {args.status[:12]} ».")
    if args.status == o.status:
        raise Refused("L'objectif a déjà ce statut.")
    if o.kind == c.CONSTANT and args.status == c.DONE:
        raise Refused("Un objectif constant ne se coche pas : il revient. Retire-le s'il n'a plus lieu d'être.")
    if args.status in (c.OPEN, c.BLOCKED) and o.status in (c.DONE, c.DROPPED) and living(p) >= OBJECTIVES_KEPT:
        raise Refused(f"Ce projet a déjà {OBJECTIVES_KEPT} objectifs ouverts ou bloqués : retires-en avant d'en "
                      "rouvrir un.")
    draft = OBJECTIVE_CHANGED.draft(project=p.id, objective=o.id, status=args.status, by=ctx.by, owner=p.owner,
                                    about=p.about, read_about=p.read_about)
    return Done(drafts=(draft,), message=f"Objectif n° {o.id} : {OBJECTIVE_STATUS_FR[args.status]}.",
                guard=unchanged(p.id, LIVE))


class ObjectiveEditArgs(BaseModel):
    objective: Annotated[str, Knob(label="Objectif", widget="hidden")] = Field(min_length=1, max_length=12)
    text: Annotated[str, Knob(label="Objectif", widget="textarea", advanced=False)] = Field(min_length=1,
                                                                                            max_length=500)
    kind: Annotated[str, Knob(label="Sorte", choices=KIND_CHOICES, advanced=False)] = c.ONCE
    cadence_hours: Annotated[int, Knob(label="Cadence (heures, pour un constant)", advanced=False, lo=0, hi=720,
                                       help="0 : la valeur par défaut.")] = Field(default=0, ge=0, le=720)
    on: Annotated[tuple[str, ...], Knob(label="Déclenché par", advanced=False, help=TRIGGERS_HELP)] = ()
    only_on_event: Annotated[bool, Knob(label="Sur événement seulement", advanced=False,
                                        help=ONLY_ON_EVENT_HELP)] = False
    routine: Annotated[str, Knob(label="À chaque passage (pour un constant)", widget="textarea", advanced=False,
                                 help=ROUTINE_HELP)] = Field(default="", max_length=1200)
    at_once: Annotated[bool, Knob(label="Premier passage tout de suite", advanced=False,
                                  help=AT_ONCE_HELP)] = False
    # absent ou vide, son critère garde sa valeur : l'événement ne sait pas le retirer
    done_when: Annotated[str | None, Knob(label="Fini quand", widget="textarea", advanced=False,
                                          help=DONE_WHEN_HELP)] = Field(default=None, max_length=DONE_WHEN_MAX)


@PROJECTS.action("objectif_modifier", title="Modifier l'objectif", args=ObjectiveEditArgs,
                 emits=[OBJECTIVE_CHANGED], subject="project", order=32, available=can_edit)
def _objective_edit(s: ProjectsState, frame: Frame, args: ObjectiveEditArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    o = target_objective(p, args.objective)
    texts = _texts(ctx.ports or {}, (o.text_ref, o.routine_ref, o.done_when_ref))
    text = texts.get(o.text_ref, "")
    changes: dict[str, Any] = {}
    if args.text.strip() != text:
        changes["text"] = Content.of(args.text.strip(), level=p.sensitivity)
    criterion = (args.done_when or "").strip()
    if criterion and criterion != texts.get(o.done_when_ref, "").strip():
        changes["done_when"] = Content.of(criterion, level=p.sensitivity)
    if args.kind in c.OBJECTIVE_KINDS and args.kind != o.kind:
        if args.kind == c.CONSTANT and o.status == c.DONE:
            raise Refused("Un objectif fait ne devient pas constant : rouvre-le d'abord, ou ajoutes-en un.")
        changes["kind"] = args.kind
    kind = changes.get("kind") or o.kind
    cadence = args.cadence_hours * HOUR if kind == c.CONSTANT else 0
    if cadence != o.cadence_us:
        changes["cadence_us"] = cadence
    # ce qui le déclenche (ADR 0265) : seul un constant en a — devenu ponctuel, le formulaire demande de les retirer
    on = _triggers(p, kind, args.on, args.only_on_event)
    if on != o.on:
        changes["on"] = on
    if args.only_on_event != o.only_on_event:
        changes["only_on_event"] = args.only_on_event
    # son premier passage tout de suite (ADR 0280) : un constant seulement
    if (args.at_once and kind == c.CONSTANT) != o.at_once:
        changes["at_once"] = args.at_once and kind == c.CONSTANT
    # sa liste de passage (ADR 0273) : un constant seulement ; vidée, elle est retirée
    each = routine_text(args.routine.split("\n")) if kind == c.CONSTANT else ""
    if each != (texts.get(o.routine_ref, "") if o.routine_ref else ""):
        changes.update({"routine": Content.of(each, level=p.sensitivity)} if each else {"routine_cleared": True})
    if not changes:
        raise Refused("Rien n'a changé.")
    return Done(drafts=(OBJECTIVE_CHANGED.draft(project=p.id, objective=o.id, by=ctx.by, owner=p.owner, about=p.about,
                                                read_about=p.read_about, **changes),),
                message=f"Objectif n° {o.id} modifié.", guard=unchanged(p.id, LIVE))


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
                 subject="project", order=40, available=can_edit, inline=True,
                 description="Une décision technique qu'elle relira à chaque exécution (et ne rouvrira pas sans la "
                             "remplacer).")
def _decide(s: ProjectsState, frame: Frame, args: DecideArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
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
                          author="operator", by=ctx.by, owner=p.owner, about=p.about, read_about=p.read_about)
    return Done(drafts=(draft,), message="Décision consignée.", guard=unchanged(p.id, LIVE))


class DecisionStatusArgs(BaseModel):
    decision: Annotated[str, Knob(label="Décision", widget="hidden")] = Field(min_length=1, max_length=12)
    status: Annotated[str, Knob(label="Statut", widget="hidden")] = Field(min_length=1, max_length=12)


DECISION_STATUS_FR = {c.IN_FORCE: "remise en vigueur", c.WITHDRAWN: "retirée", c.SUPERSEDED: "remplacée"}


@PROJECTS.action("decision_statut", title="Changer le statut", args=DecisionStatusArgs, emits=[DECISION_CHANGED],
                 subject="project", order=41, available=can_edit)
def _decision_status(s: ProjectsState, frame: Frame, args: DecisionStatusArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
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
                message=f"Décision n° {d.id} {DECISION_STATUS_FR[args.status]}.", guard=unchanged(p.id, LIVE))


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


def can_deposit(s: ProjectsState, frame: Frame, key: str, ports: Mapping[str, Any]) -> bool:
    p = project_at(s, key)
    return p is not None and p.status in LIVE and ports.get("workshop") is not None


@PROJECTS.action("deposer", title="Déposer un fichier", args=DepositArgs, emits=[DEPOSITED], subject="project",
                 order=50, available=can_deposit, inline=True,
                 description="Une donnée, un exemple, un modèle : dans l'atelier, pour qu'elle s'en serve.")
async def _deposit(s: ProjectsState, frame: Frame, args: DepositArgs, ctx: ActionContext) -> Done:
    p = target_project(s, ctx)
    if args.file is None or not args.file.data:
        raise Refused("Aucun fichier (ou un fichier vide).", {"file": "choisis un fichier"})
    port = (ctx.ports or {}).get("workshop")
    if port is None:
        raise Refused("L'atelier n'est pas disponible ici.")
    # l'état d'abord (rien ne s'écrit dans l'atelier d'un projet que l'opérateur ne voit plus tel qu'il était)
    if p.status not in LIVE or frame.get(c.STATUS(p.id)) not in LIVE:
        raise Refused("Ce projet est archivé : restaure-le d'abord.")
    folder = args.folder.strip().strip("/")
    path = f"{folder}/{args.file.name}" if folder else args.file.name
    try:
        existing = await port.tree(p.id, path) if port.exists(p.id) else []
        if existing and not existing[0].startswith(f"{path.strip('/')} ("):
            raise Refused(f"« {path} » est un dossier dans l'atelier : choisis un autre nom.", {"folder": "un dossier"})
        if existing and not args.replace:
            raise Refused(f"« {path} » existe déjà dans l'atelier : coche « Remplacer » pour l'écraser.",
                          {"replace": "le fichier existe déjà"})
        rel = await port.write_bytes(p.id, path, args.file.data)
    except OutsideWorkshop as exc:  # dit sous « Dans le dossier » ; le bandeau ne le recopie pas
        raise Refused("Le fichier n'a pas été déposé.", {"folder": str(exc)}) from None
    except WorkshopFull as exc:  # rien à voir avec le dossier choisi : dit en bandeau seulement
        raise Refused(f"Le fichier n'a pas été déposé : {exc}") from None
    except OSError as exc:  # un dossier pris pour un fichier, un disque plein : dit en français, jamais brut
        raise Refused(f"Le fichier n'a pas pu être écrit dans l'atelier ({exc.strerror or exc}).") from None
    # ce fichier seulement : le travail en cours d'une exécution reste à elle (elle l'enregistrera)
    # sur la base d'un projet qui passe par des pull requests, rien ne s'enregistre (ADR 0274) : la base ne reçoit
    # que ce qui est accepté chez l'hôte — le fichier suivra sur la branche de sa prochaine exécution
    on_base = by_pulls(p) and await port.branch(p.id) in ("", BASE_BRANCH)
    sha = "" if on_base else await port.commit(p.id, f"apport de l'opérateur : {rel}", paths=(rel,))
    note = Content.of(args.note.strip(), level=p.sensitivity) if args.note.strip() else None
    said = f"Déposé dans l'atelier : {rel} (enregistré : {sha[:12]})." if sha else \
        f"Déposé dans l'atelier : {rel} — il s'enregistrera sur la branche de sa prochaine exécution." if on_base \
        else f"Déposé dans l'atelier : {rel} — mais pas enregistré dans son dépôt (identique, ou git indisponible)."
    return Done(drafts=(DEPOSITED.draft(project=p.id, name=rel, size=len(args.file.data), note=note, by=ctx.by,
                                        owner=p.owner, about=p.about, read_about=p.read_about),),
                message=said, tone="ok" if sha else "warn", guard=unchanged(p.id, LIVE))


# ── Ce qui attend un accord ───────────────────────────────────────────────


def pending_of(frame: Frame, project: int) -> list[Any]:
    """Les demandes de ce projet qui attendent un accord. Elles se décident dans la file « À valider », avec leur
    aperçu (``runtime/decisions.py``, ADR 0177) : la fiche n'y mène que par un lien."""
    return [v for v in frame.get(rt.PENDING_EFFECTS) if v.owner == c.OWNER and project_of(v.context) == project]

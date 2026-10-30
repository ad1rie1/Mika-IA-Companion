"""La faculté ``projects`` : sa tranche, ses réducteurs, ses faits, ce que
ses événements font ressentir (ADR 0031).

- **Une exécution se réserve au départ** (``episode.started``) ; une exécution
  qui échoue sans que le modèle ait répondu (panne, délai, supplantation)
  **rend son crédit** ; trois pannes de suite mettent le projet en pause.
- **Une exécution sans verdict** compte pour son objectif : trois de suite, et
  il bloque (``tend.py``).
- **« Fait » sans preuve** n'est pas fait pour un objectif ponctuel : la preuve
  est un commit non vide pendant l'objectif (ou un brouillon de mail, une app
  forgée) — lancer ``ls`` ou noter ne prouve rien ; pour un constant, « fait »
  clôt le passage, et le suivant revient après la cadence.
- **Ce qui sort de l'atelier ne le dispute pas à une exécution** : une commande
  réseau sans accord attend la fin de l'exécution en cours, et aucune
  exécution ne part pendant qu'une commande réseau, un envoi ou une
  récupération sont en route (``outgoing``).
- **Le mode** décide de ce qu'elle en ressent : en mode ``persona``, un
  ponctuel abouti rend fière, un ponctuel bloqué frustre ; en mode ``plain``,
  rien.
- **Une demande d'aide dite attend sa personne** : dès que celle à qui elle l'a
  dite écrit, l'objectif n'attend plus (``projects.answered``, ``tend.py``) ;
  personne d'autre ne lève l'attente.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from mika.contracts import agency as agency_c
from mika.contracts import identity as identity_c
from mika.contracts import mcp as mcp_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import wakeup as wakeup_c
from mika.kernel import schedule
from mika.kernel.clock import DAY, HOUR, MINUTE, instant, local
from mika.kernel.events import Content, Payload
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict
from mika.vocab import causes
from mika.vocab.access import PERSON
from mika.vocab.affect import Appraisal, Emotion
from mika.vocab.episodes import PROJECT_KINDS, Kind, project_of
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity

NOTES_KEPT = 8
INSTRUCTIONS_KEPT = 8
EFFECTS_KEPT = 8
DEPOSITS_KEPT = 8
#: les objectifs vivants (ouverts ou bloqués) d'un projet, au plus ; son histoire (les faits et les retirés en
#: plus) en garde davantage, les plus anciens clos tombant d'abord
OBJECTIVES_KEPT = 60
OBJECTIVES_HISTORY = 200
#: les décisions en vigueur, au plus ; une décision remplacée ou retirée reste lisible tant qu'il y a la place
DECISIONS_KEPT = 200
#: les lots d'outils que tout projet a : son atelier et ses propres outils
BASE_BUNDLES = ("projects", "workshop")
#: chercher et lire sur le web (ADR 0105) : un projet à elle l'a toujours en main, comme ses autres outils ; un projet
#: confié l'a quand son cadre le dit (coché d'office à sa création)
WEB = mcp_c.WEB_BUNDLE
#: les lots qu'on peut lui ajouter (dans cet ordre dans la console)
EXTRA_BUNDLES = ("memory", WEB, "email", "rss", "forge", "forge_apps", "camera")
#: les lots d'un projet qui n'en dit rien
DEFAULT_BUNDLES = (*BASE_BUNDLES, "memory", WEB)
#: les lots qu'elle se donne elle-même, sur un projet à elle : de quoi se fabriquer un outil (la Forge, ses apps) et
#: lire ce qu'il observe (ses flux) ; le courrier et la caméra touchent la vie des autres — un opérateur seulement
#: (ADR 0104)
SELF_BUNDLES = ("memory", "rss", "forge", "forge_apps")
PRIORITY_RANK = {c.LOW: -1, c.NORMAL: 0, c.HIGH: 1, c.URGENT: 2}
#: l'agenda « dès que possible » (gardé sous son ancien nom, ``manual`` : les journaux le portent) et le vrai
#: « sur demande » : il ne part que quand on le lance
ASAP, ON_DEMAND = "manual", "demand"
#: une commande qui sort de la machine et dont on n'a pas de nouvelles depuis ce délai ne retient plus le projet
OUTGOING_STALE = 30 * MINUTE
#: ce qu'une exécution garde de ce que le réseau lui a rendu (une donnée, citée dans le prompt)
NETWORK_OUT_KEPT = 2000


def check_schedule(text: str) -> str:
    """Une règle d'agenda acceptable, normalisée (« asap » → ``manual``, « sur demande » → ``demand``), ou
    ``ValueError``."""
    raw = (text or "").strip()
    if raw.lower() in ("", "manual", "asap", "dès que possible"):
        return ASAP
    if raw.lower() in ("demand", "on_demand", "sur demande"):
        return ON_DEMAND
    schedule.parse(raw)
    return raw


class ProjectsParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_spacing_us: Annotated[int, Knob(
        label="Espacement des exécutions", group="Les exécutions", lo=MINUTE, hi=DAY,
        help="Entre deux exécutions d'un même projet, au moins ce délai (plus si son agenda le dit). « Lancer "
             "maintenant » passe outre.")] = 10 * MINUTE
    runs_per_hour: Annotated[int, Knob(
        label="Exécutions par heure au plus", group="Les exécutions", lo=0, hi=60,
        help="Tous projets confondus : chaque exécution est une boucle d'outils du modèle (0 : plus aucun "
             "travail sur les projets).")] = 4
    runs_per_day: Annotated[int, Knob(
        label="Exécutions par jour et par projet", group="Les exécutions", lo=1, hi=500,
        help="Le plafond quotidien d'un projet qui n'en précise pas (sur les dernières 24 h).")] = 24
    run_evidence: Annotated[float, Knob(
        label="Preuve d'une exécution", group="Les exécutions", lo=0.0, hi=12.0, step=0.5,
        help="Constante quand une exécution est due ; au-dessus du seuil des exécutions (8), elle part vite.")] = 10.0
    priority_step: Annotated[float, Knob(
        label="Poids d'un cran de priorité", group="Les exécutions", lo=0.0, hi=4.0, step=0.25,
        help="Ce qu'un cran de priorité ajoute à la preuve (basse : −1, haute : +1, urgente : +2), plafonnée à "
             "12 : entre deux projets dus, le plus prioritaire passe devant.")] = 1.0
    once_runs_max: Annotated[int, Knob(
        label="Exécutions par objectif ponctuel", group="Les objectifs", lo=1, hi=200,
        help="Un objectif ponctuel qui n'est toujours pas fait après autant d'exécutions bloque (« à bout "
             "d'exécutions ») ; rouvert, il en retrouve autant.")] = 12
    constant_cadence_us: Annotated[int, Knob(
        label="Cadence d'un objectif constant", group="Les objectifs", lo=HOUR, hi=30 * DAY,
        help="Un objectif constant qui n'en précise pas revient après ce délai, une fois son passage fait.")] = DAY
    silent_before_blocked: Annotated[int, Knob(
        label="Exécutions sans verdict avant blocage", group="Les objectifs", lo=1, hi=10,
        help="Après autant d'exécutions de suite où le modèle a travaillé sans rien conclure, l'objectif "
             "bloque.")] = 3
    failures_before_pause: Annotated[int, Knob(
        label="Pannes avant la pause", group="Les exécutions", lo=1, hi=20,
        help="Une exécution qui échoue (le modèle ne répond pas, ou son délai passe) rend son crédit ; après autant "
             "de pannes d'affilée, le projet se met en pause (« en panne ») jusqu'à ce qu'on le reprenne.")] = 3
    wait_min_us: Annotated[int, Knob(
        label="Attente minimale", group="Les exécutions", lo=MINUTE, hi=DAY,
        help="Quand une exécution conclut « attendre », le délai demandé est ramené au moins à cette durée.")] = \
        10 * MINUTE
    wait_max_us: Annotated[int, Knob(
        label="Attente maximale", group="Les exécutions", lo=HOUR, hi=30 * DAY,
        help="…et au plus à celle-ci.")] = DAY
    live_self_max: Annotated[int, Knob(
        label="Projets à elle en même temps", group="Ses projets à elle", lo=0, hi=10,
        help="Au plus autant de projets qu'elle a ouverts d'elle-même et qui vivent encore (0 : elle n'en ouvre "
             "plus).")] = 2
    share_notable_from: Annotated[float, Knob(
        label="Notable à partir de", group="Raconter", lo=0.0, hi=1.0, step=0.05,
        help="En mode « elle-même », un objectif mené à bout qu'elle juge au moins aussi notable se raconte à qui lui a "
             "confié le projet.")] = 0.4
    share_within_us: Annotated[int, Knob(
        label="Raconter dans les", group="Raconter", lo=HOUR, hi=7 * DAY,
        help="Passé ce délai après l'aboutissement, elle ne le raconte plus.")] = 12 * HOUR
    share_evidence: Annotated[float, Knob(
        label="Envie de raconter", group="Raconter", lo=0.0, hi=10.0, step=0.5,
        help="La preuve (log-odds) de l'initiative de le raconter, face au seuil d'initiative (9).")] = 10.0
    share_attempts: Annotated[int, Knob(
        label="Tentatives de raconter", group="Raconter", lo=1, hi=10,
        help="Après autant de tentatives qui n'ont pas abouti, elle n'essaie plus.")] = 2
    share_settle_us: Annotated[int, Knob(
        label="Attendre que le travail se pose", group="Raconter", lo=MINUTE, hi=12 * HOUR,
        help="Elle fait le point d'un projet quand le travail s'est posé : aucune exécution en cours, et aucune due "
             "avant ce délai — ou le dernier objectif fini attend déjà depuis lui. Le récit dit alors, en une fois, "
             "tout ce qu'elle a mené à bout depuis le précédent.")] = 45 * MINUTE
    self_done_after_us: Annotated[int, Knob(
        label="Clore ses projets finis après", group="Ses projets à elle", lo=HOUR, hi=60 * DAY,
        help="Un projet à elle qui n'a plus aucun objectif ouvert depuis ce délai, elle le clôt d'elle-même (un "
             "soulagement s'il en a fait quelque chose) : il ne reste pas « en cours » pour toujours. Un opérateur "
             "peut le restaurer.")] = 3 * DAY
    run_programs_us: Annotated[int, Knob(
        label="Temps des programmes par exécution", group="Les exécutions", lo=MINUTE, hi=30 * MINUTE,
        help="Les programmes qu'elle lance pendant une exécution (ws_run) ont au plus ce temps à eux tous. À garder "
             "en deçà du délai d'une exécution (15 min) : un programme lent finit en « délai dépassé » qu'elle lit, "
             "jamais en exécution coupée qu'on prendrait pour une panne du modèle.")] = 7 * MINUTE
    need_evidence: Annotated[float, Knob(
        label="Envie de demander de l'aide", group="Raconter", lo=0.0, hi=10.0, step=0.5,
        help="La preuve (log-odds) de l'initiative de dire à qui lui a confié le projet qu'un objectif bloque ou "
             "attend quelque chose de lui, face au seuil d'initiative (9).")] = 9.5


@dataclass(frozen=True, slots=True)
class Objective:
    """Une ligne de ce que le projet cherche : ponctuelle (elle se coche) ou constante (elle revient)."""

    id: int
    text_ref: str
    kind: str = c.ONCE
    status: str = c.OPEN
    #: un constant : au moins ce délai entre deux passages (0 : la valeur par défaut)
    cadence_us: int = 0
    #: ``operator`` | ``owner`` | ``self``
    author: str = "operator"
    at: int = 0
    runs: int = 0
    #: la panne d'app qu'il répare (« cours@3 ») — un seul objectif par version cassée (ADR 0104)
    app: str = ""
    #: exécutions de suite sans verdict
    silent: int = 0
    unproven: int = 0
    #: les outils qui ont produit quelque chose pour cet objectif (la preuve d'un « fait »)
    evidence: int = 0
    last_run_at: int = 0
    #: un constant : la fin de son dernier passage, et combien
    passed_at: int = 0
    passes: int = 0
    #: le dernier compte rendu, ou pourquoi il bloque
    note_ref: str = ""
    waiting_until: int = 0
    closed_at: int = 0
    notable: float = 0.0
    result_ref: str = ""
    shared: bool = False
    share_attempts: int = 0
    #: « j'ai besoin de toi pour… » : ce qu'il lui faudrait (sa dernière exécution l'a dit), et si elle l'a dit
    #: (ou tenté de le dire) à qui l'a confié
    need_ref: str = ""
    asked: bool = False
    ask_attempts: int = 0
    #: …quand elle l'a dit, et à qui (la personne) : seule sa réponse, après ce moment, lève l'attente ; et quand
    #: cette réponse est arrivée (l'exécution suivante l'a sous les yeux, citée)
    asked_at: int = 0
    asked_to: str = ""
    answered_at: int = 0
    #: quand une consigne est arrivée pendant ce besoin : la consigne de qui suit le projet **est** sa réponse
    steered_at: int = 0
    #: son plan (ADR 0145) : quand il est fait (son critère), l'objectif dont il dépend (0 : aucun), sa place dans
    #: l'ordre du plan (0 : hors plan — l'ordre d'avant)
    done_when_ref: str = ""
    after: int = 0
    rank: int = 0
    #: un constant : le compte rendu de son dernier passage abouti, ce qu'elle en a jugé notable, et quand elle l'a
    #: raconté pour la dernière fois (un bilan de la semaine se dit, ADR 0145)
    pass_ref: str = ""
    pass_notable: float = 0.0
    told_at: int = 0


@dataclass(frozen=True, slots=True)
class Decision:
    """Une décision technique : ce qu'on a choisi, pourquoi, et ce qu'elle remplace."""

    id: int
    title_ref: str
    choice_ref: str
    context_ref: str = ""
    options_ref: str = ""
    reason_ref: str = ""
    status: str = c.IN_FORCE
    author: str = "self"
    at: int = 0
    replaces: int = 0
    replaced_by: int = 0
    objective: int = 0


@dataclass(frozen=True, slots=True)
class Project:
    id: int
    title_ref: str
    authority: str
    created_at: int
    description_ref: str = ""
    mode: str = c.PERSONA
    owner: str | None = None
    address: str | None = None
    about: tuple[str, ...] = ()
    sensitivity: int = 1
    source: str = ""
    bundles: tuple[str, ...] = DEFAULT_BUNDLES
    schedule: str = ""
    days: str = c.EVERY_DAY
    start_min: int = 0
    end_min: int = 24 * 60
    runs_per_day: int = 0
    approval: bool = True
    priority: str = c.NORMAL
    remote: str = ""
    branch: str = "main"
    auto_push: bool = False
    status: str = c.ACTIVE
    paused_at: int = 0
    pause_reason: str = ""
    archived_at: int = 0
    objectives: tuple[Objective, ...] = ()
    objective_seq: int = 0
    decisions: tuple[Decision, ...] = ()
    decision_seq: int = 0
    notes: tuple[str, ...] = ()
    instructions: tuple[str, ...] = ()
    deposits: tuple[tuple[str, int, str], ...] = ()
    effects: tuple[str, ...] = ()
    #: les refus accompagnés d'une note de qui a refusé : (proposition, réf. de la note — l'oubli l'atteint)
    refusals: tuple[tuple[int, str], ...] = ()
    runs: int = 0
    #: les exécutions des dernières 24 h (le plafond du jour)
    runs_at: tuple[int, ...] = ()
    #: le départ de la dernière exécution qui a eu lieu (une exécution dont le crédit est rendu n'en est pas une)
    last_run_at: int = 0
    #: le départ de la dernière tentative, aboutie ou non : l'espacement se compte depuis elle
    tried_at: int = 0
    failures: int = 0
    #: la cause de la dernière tentative en panne (le détail de sa fin d'épisode, « NomDeClasse: message ») : la
    #: pause qui suit dit la vraie (ADR 0142)
    last_failure: str = ""
    #: mis en pause pour pannes à cet instant (0 : non, ou repris) : un projet à elle, elle le dit à qui s'occupe
    #: d'elle (« il ne tourne plus, tu peux le relancer ? »), une fois, quelques tentatives au plus (ADR 0143)
    stalled_at: int = 0
    stall_asked: bool = False
    stall_attempts: int = 0
    summary_ref: str = ""
    last_commit: str = ""
    #: « lancer maintenant » demandé à cet instant, sur cet objectif (0 : celui qui vient)
    nudged_at: int = 0
    nudged_objective: int = 0
    #: le dernier envoi au dépôt distant (ou la dernière récupération) : instant, réussi, ce qu'il en est
    remote_at: int = 0
    remote_ok: bool = False
    remote_line: str = ""
    #: une demande de l'opérateur (pousser, récupérer) pas encore proposée : (événement, sorte)
    requests: tuple[tuple[int, str], ...] = ()
    #: ses commandes réseau sans accord, qui attendent la fin de l'exécution : (événement, argv, réf. de « pourquoi »)
    network: tuple[tuple[int, tuple[str, ...], str], ...] = ()
    #: ce qui est en route hors de la machine (proposition, depuis) : aucune exécution ne part pendant ce temps
    outgoing: tuple[tuple[int, int], ...] = ()
    #: ce que le réseau a rendu à sa dernière commande (une donnée : citée dans le prompt, jamais une consigne)
    network_out: str = ""
    network_out_at: int = 0
    #: qui peut quoi sur lui et ses apps (ADR 0133) : ses lignes d'accès et sa ligne par défaut ; ``None`` : jamais
    #: réglées, celles d'avant l'ADR valent (``access_of``)
    access: tuple[c.ProjectAccess, ...] | None = None
    default_access: c.ProjectAccess = c.CLOSED
    #: les mots de qui l'a demandé (une référence, l'oubli l'atteint) et qui ; l'état de son plan (ADR 0145)
    request_ref: str = ""
    asked_by: str | None = None
    plan_state: str = c.UNPLANNED
    #: son plan en cours : son texte, ses questions, quand et combien de fois il a été écrit ; une révision demandée
    #: à cet instant relance le cadrage
    plan_ref: str = ""
    questions_ref: str = ""
    plan_at: int = 0
    plan_version: int = 0
    revise_at: int = 0
    #: le dire à qui l'a demandé (« voilà comment je vois ça ») : à dire, dit à qui et quand, ses essais, sa relance
    plan_tell: bool = False
    plan_asked: bool = False
    plan_asked_at: int = 0
    plan_asked_to: str = ""
    plan_attempts: int = 0
    plan_reminded: bool = False
    #: la réponse à ses questions (une référence : ses mots tels quels, vide s'il l'a validé sans rien dire — ses
    #: recommandations valent) ; ses séances de cadrage d'affilée qui n'ont pas écrit de plan (ADR 0161)
    plan_answer_ref: str = ""
    frame_silent: int = 0
    #: ses derniers comptes rendus, du plus ancien au plus récent : (instant, objectif, verdict, réf. du texte) — la
    #: mémoire de travail d'une exécution (ADR 0145)
    reports: tuple[tuple[int, int, str, str], ...] = ()
    #: les mots de la personne derrière une consigne de vive voix : (réf. de la consigne, réf. de ses mots)
    said: tuple[tuple[str, str], ...] = ()


#: les comptes rendus qu'une exécution relit (sa mémoire de travail, ADR 0145)
REPORTS_KEPT = 5


@dataclass(frozen=True, slots=True)
class Run:
    project: int
    objective: int
    #: "run" | "frame" (une séance de cadrage, ADR 0145) | "share" | "need" | "plan" (dire son plan) | "stalled"
    #: (dire qu'il s'est arrêté : ADR 0143)
    purpose: str
    reported: bool = False
    #: son départ, et la dernière exécution d'avant (du projet, de l'objectif) : ce qu'un crédit rendu restaure
    started: int = 0
    previous: int = 0
    previous_objective: int = 0
    #: un récit, une demande d'aide : l'adresse à qui elle parle
    address: str = ""


@dataclass(frozen=True, slots=True)
class ProjectsState:
    projects: FrozenDict[int, Project] = field(default_factory=FrozenDict)
    running: FrozenDict[str, Run] = field(default_factory=FrozenDict)
    #: les exécutions de la dernière heure, tous projets confondus (plafond horaire)
    runs_at: tuple[int, ...] = ()
    #: proposition d'effet → (projet, capacité)
    proposals: FrozenDict[int, tuple[int, str]] = field(default_factory=FrozenDict)
    #: ce qu'une proposition qui attend un accord ferait (ses arguments) : la fiche en montre l'aperçu exact
    awaiting: FrozenDict[int, str] = field(default_factory=FrozenDict)
    #: les demandes de pilotage sur ton accord (ADR 0133), par demande, et la proposition qui les porte
    steers: FrozenDict[str, SteerAsk] = field(default_factory=FrozenDict)
    steer_proposals: FrozenDict[int, str] = field(default_factory=FrozenDict)


@dataclass(frozen=True, slots=True)
class SteerAsk:
    """Une demande de pilotage qui attend ton accord (ADR 0133) : ce qu'elle ferait, pour qui, son texte (un contenu
    effaçable) ; ``applied`` une fois acceptée."""

    project: int
    what: str
    by: str
    at: int
    text_ref: str = ""
    kind: str = c.ONCE
    cadence_us: int = 0
    objective: int = 0
    applied: bool = False


#: les demandes de pilotage qu'on garde, au plus (les plus anciennes, déjà tranchées, s'effacent d'abord)
STEERS_KEPT = 50


#: v3 : un récit, un appel à l'aide devancés, interrompus ou dont elle s'est ravisée ne comptent plus comme essais.
#: v4 : un récit fait le point — il couvre tout ce qu'elle a mené à bout avant son départ, pas un seul objectif.
#: v5 : une demande d'aide dite attend la réponse de sa personne (``asked_at``, ``asked_to``, ``answered_at``).
#: v6 : une consigne reçue pendant un besoin y répond (``steered_at``) — elle ne l'attend plus, ne le redemande pas.
#: v7 : un besoin qui reste après sa réponse (ou sa consigne) est une nouvelle demande — elle le redit, une fois ;
#:     un objectif qui bloque après cette réponse se dit aussi (« ça bloque »).
#: v8 : ses accès (ADR 0133) et les demandes de pilotage sur ton accord (``access``, ``steers``).
#: v9 : la cause de la dernière panne (``last_failure``), que dit la pause (ADR 0142) ; une pause pour pannes, qu'elle
#:     dit à qui s'occupe d'elle (``stalled_at``, ``stall_asked``, ``stall_attempts`` : ADR 0143).
#: v10 : le cadrage (ADR 0145) — la demande, son plan et son état, les critères et l'ordre des objectifs, ses
#:     derniers comptes rendus, les passages des constants qu'elle raconte.
#: v11 : la réponse à ses questions gardée avec elles, ses séances de cadrage sans plan, un objectif bloqué que sa
#:     réponse rouvre, le premier passage d'un constant à sa cadence (ADR 0161).
PROJECTS = Faculty("projects", state=ProjectsState, init=lambda p: ProjectsState(), params=ProjectsParams,
                   state_version=11, retired_params=("wrap_up_after",))
PROJECTS.declare(*c.ALL)


# ── Ses événements privés ─────────────────────────────────────────────────


class ObjectiveAdded(Payload):
    project: int
    objective: int
    text: Content
    kind: str = c.ONCE
    cadence_us: int = 0
    #: ``operator`` | ``owner`` | ``self``
    author: str = "operator"
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    #: un objectif « Réparer » né de la panne d'une de ses apps : l'app et sa version cassée (« cours@3 », ADR 0104)
    app: str = ""
    #: son plan (ADR 0145) : son critère de fait, l'objectif dont il dépend, sa place dans l'ordre (0 : hors plan)
    done_when: Content | None = None
    after: int = 0
    rank: int = 0


class ObjectiveChanged(Payload):
    project: int
    objective: int
    status: str | None = None
    text: Content | None = None
    kind: str | None = None
    cadence_us: int | None = None
    note: Content | None = None
    #: son plan revu (ADR 0145)
    done_when: Content | None = None
    after: int | None = None
    rank: int | None = None
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class Decided(Payload):
    """Une décision technique (la sienne pendant une exécution, ou celle d'un opérateur)."""

    project: int
    decision: int
    title: Content
    choice: Content
    context: Content | None = None
    options: Content | None = None
    reason: Content | None = None
    #: la décision qu'elle remplace (0 : aucune)
    replaces: int = 0
    objective: int = 0
    author: str = "self"
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class DecisionChanged(Payload):
    project: int
    decision: int
    status: str
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class Reframed(Payload):
    """Le cadre d'un projet change : seuls les champs donnés."""

    project: int
    title: Content | None = None
    description: Content | None = None
    clear_description: bool = False
    mode: str | None = None
    set_owner: bool = False
    address: str | None = None
    bundles: tuple[str, ...] | None = None
    schedule: str | None = None
    days: str | None = None
    start_min: int | None = None
    end_min: int | None = None
    runs_per_day: int | None = None
    approval: bool | None = None
    priority: str | None = None
    remote: str | None = None
    branch: str | None = None
    auto_push: bool | None = None
    #: la sensibilité ne fait que monter (fixer « pour qui » la relève : ce qui s'y écrit parle de quelqu'un)
    sensitivity: int | None = None
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class StateChanged(Payload):
    """Pause, reprise, archivage, restauration. ``reason`` : pourquoi (une pause pour pannes le dit)."""

    project: int
    reason: str = ""
    by: str = ""
    #: elle clôt elle-même un projet à elle : ``done`` (il a fait son temps : un soulagement) ou ``dropped``
    #: (elle y renonce : une mélancolie) ; vide : un opérateur, ou une panne
    ending: str = ""
    #: une pause pour pannes (``projects.tend``) : un projet à elle, elle le dira (ADR 0143)
    broke: bool = False
    owner: str | None = None
    about: tuple[str, ...] = ()


class Nudged(Payload):
    """« Lancer maintenant » : la prochaine exécution n'attend ni l'agenda, ni l'espacement, ni la plage."""

    project: int
    objective: int = 0
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class Noted(Payload):
    """Une note de son carnet (privée)."""

    project: int
    text: Content
    owner: str | None = None
    about: tuple[str, ...] = ()


class SteerAsked(Payload):
    """Une demande de pilotage faite de vive voix, qui attend ton accord (ADR 0133) : la proposition qui la porte
    (``projects.steer``) la nomme par ``request``."""

    project: int
    request: str
    #: ``add`` | ``instruct`` | ``now`` | ``pause`` | ``resume``
    what: str
    text: Content | None = None
    kind: str = c.ONCE
    cadence_us: int = 0
    objective: int = 0
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class AccessSet(Payload):
    """Ses lignes d'accès, réglées d'un coup par un opérateur (ADR 0133) : tout le tableau, dans son ordre, et la ligne
    par défaut."""

    project: int
    rows: tuple[c.ProjectAccess, ...] = ()
    default: c.ProjectAccess = c.CLOSED
    by: str = ""


class Amended(Payload):
    """Une consigne d'un opérateur, ou de vive voix de qui s'occupe d'elle (``project_steer``) : elle la lit à
    l'exécution suivante (la plus récente prime)."""

    project: int
    instruction: Content
    #: de vive voix : les mots de la personne, tels quels, à côté de ce qu'elle en a retenu (ADR 0145)
    words: Content | None = None
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class PlanProposed(Payload):
    """Son plan, écrit par une séance de cadrage ou revu pendant une exécution (ADR 0145) : son texte (le but, ce que
    la personne verra, l'approche, le hors-sujet), ses questions (avec ce qu'elle recommande) ; ``approved`` : il vaut
    d'office (sans question, sans personne qui l'ait demandé, ou revu en cours de route) ; ``tell`` : le dire à qui
    l'a demandé. Les objectifs du plan s'écrivent à côté (``objective_added`` / ``objective_changed``)."""

    project: int
    plan: Content
    questions: Content | None = None
    approved: bool = False
    tell: bool = False
    owner: str | None = None
    about: tuple[str, ...] = ()


class PlanAnswered(Payload):
    """La réponse de qui a demandé le projet (ou d'un opérateur) à son plan : ``approve`` (il le lance) ou ``revise``
    (elle le reprend, ses mots sous les yeux)."""

    project: int
    verdict: str
    words: Content | None = None
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class Deposited(Payload):
    project: int
    name: str
    size: int = 0
    note: Content | None = None
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class NetworkQueued(Payload):
    """Une commande réseau qu'elle propose sur un projet sans accord : elle partira à la fin de l'exécution, pas
    pendant (elle ne dispute pas l'atelier à son propre travail)."""

    project: int
    argv: tuple[str, ...]
    why: Content
    owner: str | None = None
    about: tuple[str, ...] = ()


class Answered(Payload):
    """La personne à qui elle a dit son besoin (« j'ai besoin de toi pour… ») a écrit depuis : l'objectif n'attend
    plus, l'exécution suivante a sa réponse sous les yeux."""

    project: int
    objective: int
    person: str
    owner: str | None = None
    about: tuple[str, ...] = ()


class RemoteRequested(Payload):
    """L'opérateur demande de pousser (``push``) ou de récupérer (``pull``) maintenant."""

    project: int
    #: ``push`` | ``pull``
    what: str = "push"
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


OBJECTIVE_ADDED = PROJECTS.event("objective_added", ObjectiveAdded, content=("text", "done_when"),
                                 subjects=("owner", "about", "by"))
OBJECTIVE_CHANGED = PROJECTS.event("objective_changed", ObjectiveChanged, content=("text", "note", "done_when"),
                                   subjects=("owner", "about", "by"))
DECIDED = PROJECTS.event("decided", Decided, content=("title", "choice", "context", "options", "reason"),
                         subjects=("owner", "about", "by"))
DECISION_CHANGED = PROJECTS.event("decision_changed", DecisionChanged, subjects=("owner", "about"))
REFRAMED = PROJECTS.event("reframed", Reframed, content=("title", "description"), subjects=("owner", "about", "by"))
PAUSED = PROJECTS.event("paused", StateChanged, subjects=("owner", "about"))
RESUMED = PROJECTS.event("resumed", StateChanged, subjects=("owner", "about"))
ARCHIVED = PROJECTS.event("archived", StateChanged, subjects=("owner", "about"))
RESTORED = PROJECTS.event("restored", StateChanged, subjects=("owner", "about"))
NUDGED = PROJECTS.event("nudged", Nudged, subjects=("owner", "about"))
NOTED = PROJECTS.event("noted", Noted, content=("text",), subjects=("owner", "about"))
AMENDED = PROJECTS.event("amended", Amended, content=("instruction", "words"), subjects=("owner", "about", "by"))
PLAN_PROPOSED = PROJECTS.event("plan_proposed", PlanProposed, content=("plan", "questions"),
                               subjects=("owner", "about"))
PLAN_ANSWERED = PROJECTS.event("plan_answered", PlanAnswered, content=("words",), subjects=("owner", "about", "by"))
DEPOSITED = PROJECTS.event("deposited", Deposited, content=("note",), subjects=("owner", "about", "by"))
REMOTE_REQUESTED = PROJECTS.event("remote_requested", RemoteRequested, subjects=("owner", "about"))
NETWORK_QUEUED = PROJECTS.event("network_queued", NetworkQueued, content=("why",), subjects=("owner", "about"))
ANSWERED = PROJECTS.event("answered", Answered, subjects=("owner", "about", "person"))
ACCESS_SET = PROJECTS.event("access_set", AccessSet, subjects=("by",))
STEER_ASKED = PROJECTS.event("steer_asked", SteerAsked, content=("text",), subjects=("owner", "about", "by"))
#: ce qu'un opérateur (ou elle) fait d'un projet — la chronologie du carnet
OPERATIONS = (REFRAMED, PAUSED, RESUMED, ARCHIVED, RESTORED, NUDGED, OBJECTIVE_ADDED, OBJECTIVE_CHANGED,
              DECISION_CHANGED, DEPOSITED, REMOTE_REQUESTED, PLAN_PROPOSED, PLAN_ANSWERED)


# ── Lectures ──────────────────────────────────────────────────────────────


def params(p: ProjectsParams | None) -> ProjectsParams:
    return p if p is not None else ProjectsParams()


def project_at(s: ProjectsState, key: str | int | None) -> Project | None:
    """Le projet d'une clé de fiche (``7``, ``"7"`` ou ``"#7"``), ou rien."""
    raw = str(key if key is not None else "").strip().lstrip("#")
    return s.projects.get(int(raw)) if raw.isdigit() else None


def objective_at(p: Project, key: int | str | None) -> Objective | None:
    raw = str(key if key is not None else "").strip().lstrip("#")
    return next((o for o in p.objectives if str(o.id) == raw), None) if raw.isdigit() else None


def decision_at(p: Project, key: int | str | None) -> Decision | None:
    raw = str(key if key is not None else "").strip().lstrip("#").lstrip("Dd")
    return next((d for d in p.decisions if str(d.id) == raw), None) if raw.isdigit() else None


def live(p: Project) -> bool:
    """Vivant : actif ou en pause (pas archivé)."""
    return p.status in (c.ACTIVE, c.PAUSED)


def run_bundles(p: Project) -> tuple[str, ...]:
    """Ce qu'une exécution a en main : les lots du projet — et, sur un projet à elle, toujours le web, comme ses
    autres outils (un projet ouvert avant l'ADR 0105 ne l'avait pas) ; un projet confié garde son cadre."""
    return tuple(dict.fromkeys((*p.bundles, WEB))) if p.authority == c.SELF else p.bundles


def written(p: Project) -> int:
    """Le niveau de ce qu'elle écrit pendant une exécution (compte rendu, carnet, décisions, résultat, les fichiers
    de l'atelier) : elle y voit toute sa mémoire, ce qui en sort est au moins personnel."""
    return max(p.sensitivity, int(Sensitivity.PERSONAL))


def living(p: Project) -> int:
    """Ses objectifs vivants (ouverts ou bloqués) : ce que compte la limite d'objectifs."""
    return sum(1 for o in p.objectives if o.status in (c.OPEN, c.BLOCKED))


def in_force(p: Project) -> int:
    return sum(1 for d in p.decisions if d.status == c.IN_FORCE)


def nudged(p: Project) -> bool:
    """« Lancer maintenant » attend encore son exécution."""
    return p.nudged_at > p.last_run_at


def rank(p: Project) -> int:
    return PRIORITY_RANK.get(p.priority, 0)


def daily_cap(p: Project, pm: ProjectsParams) -> int:
    return p.runs_per_day or pm.runs_per_day


def cadence(o: Objective, pm: ProjectsParams) -> int:
    return o.cadence_us or pm.constant_cadence_us


def runs_today(p: Project, now: int) -> int:
    return sum(1 for t in p.runs_at if now - t < DAY)


def busy(s: ProjectsState, project: int) -> bool:
    return any(r.project == project and r.purpose == "run" for r in s.running.values())


def workable(o: Objective, now: int) -> bool:
    """Un objectif sur lequel une exécution peut porter (ouvert, pas en attente)."""
    return o.status == c.OPEN and o.waiting_until <= now


def due_at(p: Project, o: Objective, pm: ProjectsParams) -> int:
    """Quand un objectif peut être repris : un ponctuel tout de suite ; un constant une cadence après son dernier
    passage — et son premier, une cadence après qu'il a pu commencer (l'étape dont il dépend faite, sinon sa
    naissance) : un bilan de la semaine ne tombe pas le jour où l'app vient d'être écrite (ADR 0161)."""
    if o.kind != c.CONSTANT:
        return o.waiting_until
    if o.passed_at:
        return max(o.passed_at + cadence(o, pm), o.waiting_until)
    dep = objective_at(p, o.after) if o.after else None
    began = max(o.at, dep.closed_at if dep is not None else 0)
    return max(began + cadence(o, pm), o.waiting_until)


def framing(p: Project) -> bool:
    """Il n'a pas encore de plan qui vaille (ADR 0145) : à cadrer, ou un plan proposé qui attend sa réponse."""
    return p.plan_state in (c.TO_FRAME, c.PROPOSED)


def ready(p: Project, o: Objective) -> bool:
    """Ce dont il dépend dans son plan est fait (ou retiré, ou oublié) : il peut être travaillé (ADR 0145)."""
    dep = objective_at(p, o.after) if o.after else None
    return dep is None or dep.status in (c.DONE, c.DROPPED)


#: un objectif de son plan passe par son rang ; un objectif à elle hors plan, après eux
_UNRANKED = 10_000


def _order(o: Objective) -> tuple[int, int, int]:
    """L'ordre des ponctuels : ce qu'on a ajouté hors de son plan d'abord (l'opérateur, la personne), puis les
    étapes de son plan à leur rang — une idée de départ qu'il garde a le sien (ADR 0161) —, puis ce qu'elle a ajouté
    d'elle-même."""
    if o.rank:
        return 1, o.rank, o.id
    return (2 if o.author == "self" else 0), _UNRANKED, o.id


def pick(p: Project, now: int, pm: ProjectsParams) -> Objective | None:
    """L'objectif de la prochaine exécution : celui qu'on a demandé, sinon le constant le plus en retard,
    sinon le premier ponctuel ouvert (``_order``). Un objectif attend celui dont il dépend ; sans plan qui vaille,
    aucun (ADR 0145). Rien de dû : rien."""
    if framing(p):
        return None
    if nudged(p) and p.nudged_objective:
        wanted = objective_at(p, p.nudged_objective)
        if wanted is not None and wanted.status == c.OPEN:
            return wanted
    opened = [o for o in p.objectives if o.status == c.OPEN and ready(p, o)]
    constants = sorted((due_at(p, o, pm), o.id, o) for o in opened
                       if o.kind == c.CONSTANT and o.waiting_until <= now)
    due = [o for at, _, o in constants if at <= now]
    if due:
        return due[0]
    once = [o for o in opened if o.kind == c.ONCE and o.waiting_until <= now]
    once.sort(key=_order)
    if once:
        return once[0]
    # « lancer maintenant » sans rien de dû : le constant le plus proche de sa cadence, en avance
    return constants[0][2] if constants and nudged(p) else None


def next_due(p: Project, pm: ProjectsParams) -> int | None:
    """Le prochain instant où un objectif de ce projet sera dû (sans tenir compte de la plage) — aucun tant qu'il n'a
    pas de plan qui vaille."""
    if framing(p):
        return None
    times = [due_at(p, o, pm) for o in p.objectives if o.status == c.OPEN and ready(p, o)]
    return min(times) if times else None


# ── La plage de travail ───────────────────────────────────────────────────


def _day_ok(days: str, weekday: int) -> bool:
    if days == c.WEEKDAYS:
        return weekday < 5
    if days == c.WEEKEND:
        return weekday >= 5
    return True


def always(p: Project) -> bool:
    return p.days == c.EVERY_DAY and p.start_min <= 0 and p.end_min >= 24 * 60


def in_window(p: Project, t: int, tz: ZoneInfo) -> bool:
    """``t`` tombe-t-il dans sa plage de travail (jours, heures locales ; une plage dont la fin précède le
    début passe minuit et appartient au jour où elle commence) ?"""
    if always(p):
        return True
    dt = local(t, tz)
    minute = dt.hour * 60 + dt.minute
    start, end = p.start_min, p.end_min
    if start < end:
        return _day_ok(p.days, dt.weekday()) and start <= minute < end
    if minute >= start:
        return _day_ok(p.days, dt.weekday())
    return minute < end and _day_ok(p.days, (dt.weekday() - 1) % 7)


def window_opens(p: Project, after: int, tz: ZoneInfo) -> int | None:
    """Le premier instant à partir de ``after`` qui tombe dans sa plage (``None`` : jamais, sur huit jours)."""
    if in_window(p, after, tz):
        return after
    base = local(after, tz)
    for d in range(0, 9):
        day = (base + timedelta(days=d)).date()
        start = datetime(day.year, day.month, day.day, tzinfo=tz) + timedelta(minutes=p.start_min)
        at = instant(start)
        if at >= after and in_window(p, at, tz):
            return at
    return None


def window_words(p: Project) -> str:
    """La plage en mots (« les jours ouvrés, de 9 h à 18 h »)."""
    if always(p):
        return "à toute heure"
    days = {c.EVERY_DAY: "tous les jours", c.WEEKDAYS: "les jours ouvrés", c.WEEKEND: "le week-end"}.get(p.days, p.days)
    return f"{days}, de {hhmm(p.start_min)} à {hhmm(p.end_min)}"


def hhmm(minutes: int) -> str:
    h, m = divmod(max(0, min(24 * 60, minutes)), 60)
    return f"{h} h" if not m else f"{h} h {m:02d}"


# ── Réducteurs ────────────────────────────────────────────────────────────


def _set(s: ProjectsState, p: Project) -> ProjectsState:
    return replace(s, projects=s.projects.set(p.id, p))


def _objective(p: Project, o: Objective) -> Project:
    return replace(p, objectives=tuple(o if x.id == o.id else x for x in p.objectives))


@PROJECTS.reducer(c.PROJECT_CREATED)
def _created(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    bundles = tuple(dict.fromkeys((*BASE_BUNDLES, *d.bundles))) if d.bundles else DEFAULT_BUNDLES
    p = Project(
        id=e.seq, title_ref=d.title.ref or "", authority=d.authority, created_at=e.at,
        description_ref=d.description.ref or "" if d.description is not None else "",
        mode=d.mode if d.mode in c.MODES else c.PERSONA, owner=d.owner, address=d.address, about=tuple(d.about),
        sensitivity=d.sensitivity, source=d.source, bundles=bundles, schedule=d.schedule,
        days=d.days if d.days in c.DAYS else c.EVERY_DAY, start_min=max(0, min(24 * 60, d.start_min)),
        end_min=max(0, min(24 * 60, d.end_min)), runs_per_day=max(0, d.runs_per_day), approval=d.approval,
        priority=d.priority if d.priority in c.PRIORITIES else c.NORMAL, remote=d.remote, branch=d.branch or "main",
        auto_push=d.auto_push, request_ref=d.request.ref or "" if d.request is not None else "", asked_by=d.asked_by,
        plan_state=c.TO_FRAME if d.framing else c.UNPLANNED,
    )
    return _set(s, p)


@PROJECTS.reducer(OBJECTIVE_ADDED)
def _objective_added(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None or not d.text.ref or living(p) >= OBJECTIVES_KEPT:
        return s
    # deux ajouts du même numéro (l'opérateur et une exécution en même temps) : le second prend le suivant ;
    # un numéro déjà donné ne revient jamais (même tombé de l'histoire)
    oid = d.objective if d.objective > p.objective_seq and objective_at(p, d.objective) is None else \
        max([p.objective_seq, *(o.id for o in p.objectives)]) + 1
    o = Objective(id=oid, text_ref=d.text.ref, kind=d.kind if d.kind in c.OBJECTIVE_KINDS else c.ONCE,
                  cadence_us=max(0, d.cadence_us), author=d.author, at=e.at, app=d.app,
                  done_when_ref=d.done_when.ref or "" if d.done_when is not None else "",
                  after=d.after if d.after != oid else 0, rank=max(0, d.rank))
    objectives = (*p.objectives, o)
    while len(objectives) > OBJECTIVES_HISTORY:  # l'histoire déborde : le plus ancien clos tombe
        oldest = next((x for x in objectives if x.status in (c.DONE, c.DROPPED)), None)
        if oldest is None:
            break
        objectives = tuple(x for x in objectives if x is not oldest)
    return _set(s, replace(p, objectives=objectives, objective_seq=max(p.objective_seq, oid)))


@PROJECTS.reducer(OBJECTIVE_CHANGED)
def _objective_changed(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or o is None:
        return s
    changes: dict[str, Any] = {}
    if d.text is not None and d.text.ref:
        changes["text_ref"] = d.text.ref
    if d.kind in c.OBJECTIVE_KINDS and d.kind != o.kind:
        # une autre sorte : la preuve et le résultat de l'ancienne ne valent pas pour la nouvelle
        changes.update(kind=d.kind, evidence=0, unproven=0, notable=0.0, result_ref="")
    if d.cadence_us is not None:
        changes["cadence_us"] = max(0, d.cadence_us)
    if d.note is not None and d.note.ref:
        changes["note_ref"] = d.note.ref
    if d.done_when is not None and d.done_when.ref:
        changes["done_when_ref"] = d.done_when.ref
    if d.after is not None:
        changes["after"] = d.after if d.after != o.id else 0
    if d.rank is not None:
        changes["rank"] = max(0, d.rank)
    if d.status in c.OBJECTIVE_STATUSES and d.status != o.status:
        changes["status"] = d.status
        if d.status == c.OPEN:  # rouvert : il repart de rien (ni dette, ni preuve, ni résultat d'avant)
            changes.update(silent=0, unproven=0, waiting_until=0, closed_at=0, runs=0, evidence=0, notable=0.0,
                           result_ref="", shared=False, share_attempts=0, need_ref="", asked=False, ask_attempts=0,
                           asked_at=0, asked_to="", answered_at=0)
        else:
            changes["closed_at"] = e.at
            if d.status == c.DONE:  # coché par quelqu'un d'autre : ce n'est pas elle qui l'a mené à bout
                changes.update(shared=True, notable=0.0)
    return _set(s, _objective(p, replace(o, **changes))) if changes else s


@PROJECTS.reducer(DECIDED)
def _decided(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None or not d.title.ref or not d.choice.ref:
        return s
    did = d.decision if d.decision > p.decision_seq and decision_at(p, d.decision) is None else \
        max([p.decision_seq, *(x.id for x in p.decisions)]) + 1  # le numéro déjà pris : le suivant
    replaced = decision_at(p, d.replaces) if d.replaces else None
    decision = Decision(
        id=did, title_ref=d.title.ref, choice_ref=d.choice.ref,
        context_ref=d.context.ref or "" if d.context is not None else "",
        options_ref=d.options.ref or "" if d.options is not None else "",
        reason_ref=d.reason.ref or "" if d.reason is not None else "", author=d.author, at=e.at,
        replaces=d.replaces if replaced is not None and replaced.status == c.IN_FORCE else 0, objective=d.objective)
    decisions = tuple(replace(x, status=c.SUPERSEDED, replaced_by=did) if x.id == decision.replaces else x
                      for x in p.decisions)
    if sum(1 for x in decisions if x.status == c.IN_FORCE) >= DECISIONS_KEPT:
        return s  # trop de décisions en vigueur : qu'on en retire avant d'en prendre d'autres
    decisions = (*decisions, decision)
    while len(decisions) > DECISIONS_KEPT:  # la place manque : la plus ancienne qui n'est plus en vigueur tombe
        oldest = next(x for x in decisions if x.status != c.IN_FORCE)
        decisions = tuple(x for x in decisions if x is not oldest)
    return _set(s, replace(p, decisions=decisions, decision_seq=max(p.decision_seq, did)))


@PROJECTS.reducer(DECISION_CHANGED)
def _decision_changed(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    x = decision_at(p, d.decision) if p is not None else None
    if p is None or x is None or d.status not in c.DECISION_STATUSES:
        return s
    new = replace(x, status=d.status, replaced_by=x.replaced_by if d.status == c.SUPERSEDED else 0)
    return _set(s, replace(p, decisions=tuple(new if y.id == x.id else y for y in p.decisions)))


@PROJECTS.reducer(REFRAMED)
def _reframed(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None or p.status == c.ARCHIVED:
        return s
    changes: dict[str, Any] = {}
    if d.title is not None and d.title.ref:
        changes["title_ref"] = d.title.ref
    if d.clear_description:
        changes["description_ref"] = ""
    elif d.description is not None and d.description.ref:
        changes["description_ref"] = d.description.ref
    if d.mode in c.MODES:
        changes["mode"] = d.mode
    if d.set_owner:
        changes.update(owner=d.owner, about=tuple(d.about), address=d.address)
    if d.bundles is not None:
        changes["bundles"] = tuple(dict.fromkeys((*BASE_BUNDLES, *d.bundles)))
    for name in ("schedule", "remote", "branch", "auto_push", "approval"):
        value = getattr(d, name)
        if value is not None:
            changes[name] = value
    if d.days in c.DAYS:
        changes["days"] = d.days
    if d.start_min is not None:
        changes["start_min"] = max(0, min(24 * 60, d.start_min))
    if d.end_min is not None:
        changes["end_min"] = max(0, min(24 * 60, d.end_min))
    if d.runs_per_day is not None:
        changes["runs_per_day"] = max(0, d.runs_per_day)
    if d.priority in c.PRIORITIES:
        changes["priority"] = d.priority
    if d.sensitivity is not None and d.sensitivity > p.sensitivity:
        changes["sensitivity"] = d.sensitivity
    return _set(s, replace(p, **changes)) if changes else s


@PROJECTS.reducer(PAUSED)
def _paused(s: ProjectsState, e, cx) -> ProjectsState:
    p = s.projects.get(e.data.project)
    if p is None or p.status != c.ACTIVE:
        return s
    return _set(s, replace(p, status=c.PAUSED, paused_at=e.at, pause_reason=e.data.reason[:300],
                           stalled_at=e.at if e.data.broke else 0, stall_asked=False, stall_attempts=0))


@PROJECTS.reducer(RESUMED)
def _resumed(s: ProjectsState, e, cx) -> ProjectsState:
    p = s.projects.get(e.data.project)
    if p is None or p.status != c.PAUSED:
        return s
    return _set(s, replace(p, status=c.ACTIVE, paused_at=0, pause_reason="", failures=0, stalled_at=0,
                           frame_silent=0))


@PROJECTS.reducer(ARCHIVED)
def _archived(s: ProjectsState, e, cx) -> ProjectsState:
    p = s.projects.get(e.data.project)
    if p is None or p.status == c.ARCHIVED:
        return s
    # archivé, il ne pousse ni ne récupère plus rien : ses demandes en file tombent
    return _set(s, replace(p, status=c.ARCHIVED, archived_at=e.at, pause_reason=e.data.reason[:300], requests=(),
                           network=()))


@PROJECTS.reducer(RESTORED)
def _restored(s: ProjectsState, e, cx) -> ProjectsState:
    p = s.projects.get(e.data.project)
    if p is None or p.status != c.ARCHIVED:
        return s
    # restauré, il repart en pause : on le relance quand on veut ; rien de ce qui attendait avant ne repart seul
    return _set(s, replace(p, status=c.PAUSED, archived_at=0, paused_at=e.at, pause_reason="restauré", failures=0,
                           requests=(), network=(), outgoing=()))


@PROJECTS.reducer(NUDGED)
def _nudged(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None or p.status == c.ARCHIVED:
        return s
    o = objective_at(p, d.objective) if d.objective else None
    if o is not None and o.waiting_until:  # « maintenant » l'emporte sur l'attente
        p = _objective(p, replace(o, waiting_until=0))
    return _set(s, replace(p, nudged_at=e.at, nudged_objective=d.objective if o is not None else 0))


@PROJECTS.reducer(ACCESS_SET)
def _access_set(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None:
        return s
    return _set(s, replace(p, access=tuple(d.rows), default_access=d.default))


@PROJECTS.reducer(STEER_ASKED)
def _steer_asked(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    if d.project not in s.projects:
        return s
    asked = SteerAsk(project=d.project, what=d.what, by=d.by, at=e.at, text_ref=(d.text.ref or "") if d.text is not None else "",
                     kind=d.kind, cadence_us=d.cadence_us, objective=d.objective)
    steers = s.steers.set(d.request, asked)
    while len(steers) > STEERS_KEPT:  # les tranchées d'abord, puis les plus anciennes
        steers = steers.delete(min(steers.items(), key=lambda kv: (not kv[1].applied, kv[1].at))[0])
    return replace(s, steers=steers)


@PROJECTS.reducer(NOTED)
def _noted(s: ProjectsState, e, cx) -> ProjectsState:
    p = s.projects.get(e.data.project)
    if p is None or not e.data.text.ref:
        return s
    return _set(s, replace(p, notes=(*p.notes, e.data.text.ref)[-NOTES_KEPT:]))


@PROJECTS.reducer(AMENDED)
def _amended(s: ProjectsState, e, cx) -> ProjectsState:
    """Une consigne : elle la lira à l'exécution suivante. Arrivée pendant un besoin (« tu es d'accord pour… ? »),
    elle **est** la réponse de qui suit le projet : le besoin n'attend plus, ni ne se redemande — même s'il n'avait
    jamais été dit en propre (glissé dans un récit, sonde du 2026-10-13 : « oui, resserre le filtre » passé en
    consigne, et l'exécution suivante attendait encore sa réponse)."""
    p = s.projects.get(e.data.project)
    if p is None or not e.data.instruction.ref:
        return s
    p = replace(p, instructions=(*p.instructions, e.data.instruction.ref)[-INSTRUCTIONS_KEPT:])
    if e.data.words is not None and e.data.words.ref:
        kept = set(p.instructions)
        p = replace(p, said=tuple(x for x in (*p.said, (e.data.instruction.ref, e.data.words.ref)) if x[0] in kept))
    p = replace(p, objectives=tuple(
        replace(o, steered_at=e.at, asked=True, waiting_until=0) if o.status == c.OPEN and o.need_ref
        else reopened(o, e.at, steered=True) if stuck_asking(o, e.at) else o
        for o in p.objectives))
    return _set(s, p)


#: une réponse rouvre un blocage qu'elle a dit dans ce délai : au-delà, la personne a parlé d'autre chose depuis
#: longtemps — un vieux blocage ne se rouvre pas d'un coup (ADR 0161)
ANSWER_REOPENS_WITHIN = 7 * DAY


def stuck_asking(o: Objective, at: int) -> bool:
    """Un ponctuel bloqué dont elle a dit le blocage à quelqu'un, il y a moins d'une semaine à ``at`` : sa réponse,
    ou une consigne, le rouvre (ADR 0161) — sinon ce qui en dépend dans son plan attendrait pour toujours."""
    return o.kind == c.ONCE and o.status == c.BLOCKED and o.asked and 0 <= at - o.asked_at <= ANSWER_REOPENS_WITHIN


def reopened(o: Objective, at: int, *, steered: bool = False) -> Objective:
    """Rouvert par la réponse à son blocage : il repart (ses exécutions, son silence, sa clôture remis à zéro), le
    besoin et la réponse sous les yeux de l'exécution qui vient."""
    return replace(o, status=c.OPEN, closed_at=0, runs=0, silent=0, waiting_until=0, result_ref="", notable=0.0,
                   steered_at=at if steered else o.steered_at, answered_at=o.answered_at if steered else at)


#: la réponse à un plan (ADR 0145)
APPROVE, REVISE = "approve", "revise"


@PROJECTS.reducer(PLAN_PROPOSED)
def _plan_proposed(s: ProjectsState, e, cx) -> ProjectsState:
    """Son plan : validé d'office (sans question, sans personne qui l'ait demandé, ou revu en cours de route), il
    lance le projet ; sinon il attend la réponse de qui l'a demandé. Une séance de cadrage y conclut."""
    d = e.data
    p = s.projects.get(d.project)
    if p is None or not d.plan.ref or p.status == c.ARCHIVED:
        return s
    run = s.running.get(e.correlation)
    if run is not None and run.project == p.id and run.purpose == "frame":
        s = replace(s, running=s.running.set(e.correlation, replace(run, reported=True)))
    state = c.PLANNED if d.approved else c.PROPOSED
    asked = d.questions.ref or "" if d.questions is not None else ""
    # revu en cours de route sans question neuve, il garde celles qui l'ont fondé et leur réponse (ADR 0161)
    kept = not asked and p.plan_state == c.PLANNED
    return _set(s, replace(p, plan_ref=d.plan.ref, questions_ref=p.questions_ref if kept else asked,
                           plan_answer_ref=p.plan_answer_ref if kept else "", plan_at=e.at,
                           plan_version=p.plan_version + 1, plan_state=state, plan_tell=d.tell, plan_asked=False,
                           plan_asked_at=0, plan_asked_to="", plan_attempts=0, plan_reminded=False, frame_silent=0))


@PROJECTS.reducer(PLAN_ANSWERED)
def _plan_answered(s: ProjectsState, e, cx) -> ProjectsState:
    """Sa réponse : validé, le projet suit son plan, ses mots gardés avec ses questions — la réponse à ce qu'elle
    demandait (ADR 0161) ; à revoir, une séance de cadrage le reprend, ses mots (une consigne) sous les yeux."""
    d = e.data
    p = s.projects.get(d.project)
    if p is None or p.status == c.ARCHIVED or (p.plan_state == c.UNPLANNED and d.verdict != REVISE):
        return s  # un projet d'avant n'a pas de plan à valider ; le revoir lui en donne un
    words = d.words.ref if d.words is not None and d.words.ref else ""
    if d.verdict == APPROVE and p.plan_state == c.PROPOSED:
        return _set(s, replace(p, plan_state=c.PLANNED, plan_tell=False, plan_answer_ref=words))
    if words:
        p = replace(p, instructions=(*p.instructions, words)[-INSTRUCTIONS_KEPT:])
    if d.verdict == REVISE:
        return _set(s, replace(p, plan_state=c.TO_FRAME, revise_at=e.at, plan_tell=False, frame_silent=0))
    return _set(s, p)


@PROJECTS.reducer(DEPOSITED)
def _deposited(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None:
        return s
    entry = (d.name, d.size, d.note.ref or "" if d.note is not None else "")
    return _set(s, replace(p, deposits=(*p.deposits, entry)[-DEPOSITS_KEPT:]))


@PROJECTS.reducer(REMOTE_REQUESTED)
def _remote_requested(s: ProjectsState, e, cx) -> ProjectsState:
    p = s.projects.get(e.data.project)
    # un projet archivé ne pousse ni ne récupère : la demande tombe (elle ne repartira pas à la restauration)
    if p is None or e.data.what not in ("push", "pull") or p.status == c.ARCHIVED:
        return s
    return _set(s, replace(p, requests=(*p.requests, (e.seq, e.data.what))[-4:]))


@PROJECTS.reducer(NETWORK_QUEUED)
def _network_queued(s: ProjectsState, e, cx) -> ProjectsState:
    p = s.projects.get(e.data.project)
    if p is None or p.status == c.ARCHIVED or not e.data.argv:
        return s
    entry = (e.seq, tuple(str(a) for a in e.data.argv), e.data.why.ref or "")
    return _set(s, replace(p, network=(*p.network, entry)[-4:]))


def subject_of(project: int, objective: int) -> str:
    """Le sujet d'une exécution : le projet et l'objectif qu'elle vise."""
    return f"objective:{project}:{objective}"


def stall_subject(project: int) -> str:
    """Le sujet d'une initiative qui dit qu'un projet s'est arrêté (ADR 0143) : le projet, sans objectif."""
    return f"stalled:{project}"


def stall_of(subject: str | None) -> int | None:
    """Le projet d'un sujet ``stall_subject``, sinon ``None``."""
    if not subject or not subject.startswith("stalled:"):
        return None
    tail = subject[len("stalled:"):]
    return int(tail) if tail.isdigit() else None


def frame_subject(project: int) -> str:
    """Le sujet d'une séance de cadrage (ADR 0145) : le projet, sans objectif."""
    return f"frame:{project}"


def plan_subject(project: int) -> str:
    """Le sujet d'une initiative qui dit son plan à qui a demandé le projet (ADR 0145)."""
    return f"plan:{project}"


def _numbered(subject: str | None, prefix: str) -> int | None:
    if not subject or not subject.startswith(prefix):
        return None
    tail = subject[len(prefix):]
    return int(tail) if tail.isdigit() else None


def frame_of(subject: str | None) -> int | None:
    """Le projet d'un sujet ``frame_subject``, sinon ``None``."""
    return _numbered(subject, "frame:")


def plan_of(subject: str | None) -> int | None:
    """Le projet d'un sujet ``plan_subject``, sinon ``None``."""
    return _numbered(subject, "plan:")


def objective_of(subject: str | None) -> tuple[int, int] | None:
    """``(projet, objectif)`` d'un sujet d'exécution (ou d'un récit), sinon ``None``."""
    if not subject or not subject.startswith("objective:"):
        return None
    head, _, tail = subject[len("objective:"):].partition(":")
    return (int(head), int(tail)) if head.isdigit() and tail.isdigit() else None


@PROJECTS.reducer(rt.EPISODE_STARTED)
def _started(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    if d.kind in PROJECT_KINDS:
        pid = project_of(d.target)
        p = s.projects.get(pid) if pid is not None else None
        if p is None:
            return s
        got = objective_of(d.subject)
        oid = got[1] if got is not None and got[0] == p.id else 0
        o = objective_at(p, oid)
        purpose = "frame" if frame_of(d.subject) == p.id else "run"
        run = Run(p.id, oid, purpose, started=e.at, previous=p.last_run_at,
                  previous_objective=o.last_run_at if o is not None else 0)
        s = replace(s, running=s.running.set(e.correlation, run),
                    runs_at=tuple(t for t in s.runs_at if e.at - t < HOUR) + (e.at,))
        p = replace(p, runs=p.runs + 1, runs_at=tuple(t for t in p.runs_at if e.at - t < DAY) + (e.at,))
        if wakeup_c.call_of(d.subject) is None:
            # une exécution venue d'un réveil par API (ADR 0068) compte dans les plafonds, mais ne touche ni à
            # l'agenda ni à l'espacement : elle n'avale pas un « Lancer maintenant » en attente
            p = replace(p, last_run_at=e.at, tried_at=e.at)
        if o is not None:
            p = _objective(p, replace(o, runs=o.runs + 1, last_run_at=e.at))
        return _set(s, p)
    got = objective_of(d.subject)
    reasons = d.reason.split(",")
    stalled = stall_of(d.subject)
    if d.kind == Kind.INITIATIVE and stalled in s.projects and c.NEED in reasons:
        run = Run(stalled, 0, "stalled", started=e.at, address=d.target or "")
        return replace(s, running=s.running.set(e.correlation, run))
    planned = plan_of(d.subject)
    if d.kind == Kind.INITIATIVE and planned in s.projects and c.PLAN in reasons:
        run = Run(planned, 0, "plan", started=e.at, address=d.target or "")
        return replace(s, running=s.running.set(e.correlation, run))
    if d.kind != Kind.INITIATIVE or got is None or got[0] not in s.projects:
        return s
    o = objective_at(s.projects[got[0]], got[1])
    # récit ou demande : lu sur l'objectif du sujet (la ligne porte aussi les raisons des autres candidats)
    purpose = ("need" if asking(o) else "share") if o is not None and (c.SHARE in reasons or c.NEED in reasons) \
        else ""
    run = Run(got[0], got[1], purpose, started=e.at, address=d.target or "")
    return replace(s, running=s.running.set(e.correlation, run)) if purpose else s


def _story(p: Project, run: Run) -> frozenset[int]:
    """Ce qu'un récit couvre : l'objectif qu'il vise et tout ce qu'elle a mené à bout avant son départ sans l'avoir
    encore raconté — un récit fait le point, il ne s'en dit pas un par objectif (ce qui n'était pas assez notable
    pour y figurer passe avec lui)."""
    return frozenset({run.objective} | {o.id for o in p.objectives if (o.kind == c.ONCE and o.status == c.DONE
                                                                       and not o.shared and o.closed_at <= run.started)
                                        or (pass_untold(o) and o.passed_at <= run.started)})


def pass_untold(o: Objective) -> bool:
    """Un constant dont le dernier passage a produit et n'a pas encore été raconté (ADR 0145)."""
    return o.kind == c.CONSTANT and o.status == c.OPEN and bool(o.pass_ref) and o.passed_at > o.told_at


def achieved_at(o: Objective) -> int:
    """Quand ce qu'un récit dirait de cet objectif a eu lieu : sa clôture, ou le passage d'un constant."""
    return o.passed_at if o.kind == c.CONSTANT else o.closed_at


@PROJECTS.reducer(rt.UTTERANCE, reads=[identity_c.PERSON])
def _uttered(s: ProjectsState, e, cx) -> ProjectsState:
    run = s.running.get(e.correlation)
    if run is None or run.purpose not in ("share", "need", "stalled", "plan") or run.project not in s.projects:
        return s
    p = s.projects[run.project]
    if run.purpose == "stalled":  # c'est dit : elle ne le redira pas, il attend qu'on le relance
        return _set(s, replace(p, stall_asked=True))
    if run.purpose == "plan":
        # son plan est dit : s'il attend une réponse, c'est celle de cette personne-là ; dit une seconde fois, c'était
        # la relance
        s = replace(s, running=s.running.set(e.correlation, replace(run, reported=True)))
        if p.plan_asked:
            return _set(s, replace(p, plan_reminded=True))
        person = (cx.facts.get(identity_c.PERSON(run.address)) or run.address) if run.address else ""
        return _set(s, replace(p, plan_asked=True, plan_asked_at=e.at, plan_asked_to=person))
    o = objective_at(p, run.objective)
    if o is None:
        return s
    if run.purpose == "need":
        # « j'ai besoin de toi pour… » est dit : elle attend la réponse de cette personne-là, à partir de maintenant
        person = (cx.facts.get(identity_c.PERSON(run.address)) or run.address) if run.address else ""
        return _set(s, _objective(p, replace(o, asked=True, asked_at=e.at, asked_to=person)))
    story = _story(p, run)
    return _set(s, replace(p, objectives=tuple(
        (replace(x, told_at=e.at) if x.kind == c.CONSTANT else replace(x, shared=True)) if x.id in story else x
        for x in p.objectives)))


@PROJECTS.reducer(ANSWERED)
def _answered(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or o is None:
        return s
    if stuck_asking(o, e.at):  # la réponse à son blocage le rouvre (ADR 0161)
        return _set(s, _objective(p, reopened(o, e.at)))
    if o.status != c.OPEN:
        return s
    # sa réponse est là : l'objectif n'attend plus (l'exécution suivante part dans l'espacement normal)
    return _set(s, _objective(p, replace(o, waiting_until=0, answered_at=e.at)))


def asking(o: Objective) -> bool:
    """Une initiative sur cet objectif est une demande (il bloque, ou attend quelque chose d'elle), sinon un récit
    (il est mené à bout) — lu sur l'objectif, jamais sur les raisons de la ligne : une initiative porte un seul sujet,
    et les raisons des autres candidats de la ligne y figurent aussi."""
    return o.status == c.BLOCKED or (o.status == c.OPEN and bool(o.need_ref))


def answered(o: Objective) -> bool:
    """La personne à qui elle a dit son besoin a répondu depuis."""
    return o.answered_at > o.asked_at > 0


def _settled(o: Objective, before: int) -> bool:
    """Le besoin qu'elle a dit a eu sa réponse avant ``before`` : la personne a répondu, ou une consigne est venue.
    Ce qui reste à demander ensuite (le même besoin, pas réglé, ou un autre) est une nouvelle demande."""
    return (answered(o) and o.answered_at <= before) or o.asked_at < o.steered_at <= before


#: Ce qui ne dit rien de l'exécution : elle n'a pas eu lieu, son crédit est rendu.
REFUND = frozenset({"failed", "timeout", "superseded", "preempted", "cancelled", "interrupted"})
#: …et parmi elles, une panne du modèle : elle a pu coûter des appels (le plafond horaire ne la rend pas), et
#: trois d'affilée mettent le projet en pause
BROKEN = frozenset({"failed", "timeout"})
#: ce qu'on garde de la cause d'une panne (caractères)
FAILURE_KEPT = 300


@PROJECTS.reducer(rt.EPISODE_ENDED, reads=[agency_c.RENOUNCED])
def _ended(s: ProjectsState, e, cx) -> ProjectsState:
    run = s.running.get(e.correlation)
    if run is None:
        return s
    s = replace(s, running=s.running.delete(e.correlation))
    p = s.projects.get(run.project)
    if p is None:
        return s
    o = objective_at(p, run.objective)
    if run.purpose == "stalled":
        renounced = cx.facts.get(agency_c.RENOUNCED(e.data.target)) if e.data.target else 0
        if p.stall_asked or not agency_c.tried(e.data.outcome, run.started, renounced):
            return _set(s, p)
        return _set(s, replace(p, stall_attempts=p.stall_attempts + 1))
    if run.purpose == "plan":
        renounced = cx.facts.get(agency_c.RENOUNCED(e.data.target)) if e.data.target else 0
        if run.reported or not agency_c.tried(e.data.outcome, run.started, renounced):
            return _set(s, p)  # dit (la parole l'a noté), ou pas vraiment tenté
        if p.plan_asked:  # la relance a été tentée sans être dite : elle n'insiste pas
            return _set(s, replace(p, plan_reminded=True))
        return _set(s, replace(p, plan_attempts=p.plan_attempts + 1))
    if run.purpose in ("share", "need"):
        renounced = cx.facts.get(agency_c.RENOUNCED(e.data.target)) if e.data.target else 0
        if o is None or not agency_c.tried(e.data.outcome, run.started, renounced):
            return _set(s, p)
        still_untold = pass_untold(o) if o.kind == c.CONSTANT else not o.shared
        if run.purpose == "share" and still_untold:  # un essai pour tout ce que le récit couvrait
            story = _story(p, run)
            p = replace(p, objectives=tuple(replace(x, share_attempts=x.share_attempts + 1) if x.id in story else x
                                            for x in p.objectives))
        elif run.purpose == "need" and not o.asked:
            p = _objective(p, replace(o, ask_attempts=o.ask_attempts + 1))
        return _set(s, p)
    if run.reported:
        return s
    if run.purpose == "frame" and e.data.outcome not in REFUND:
        # une séance de cadrage qui n'a pas écrit de plan : comptée — d'affilée, elles arrêtent le projet, qui ne
        # recommence pas en boucle sans rien dire (ADR 0161)
        return _set(s, replace(p, failures=0, frame_silent=p.frame_silent + 1))
    if e.data.outcome in REFUND:
        # elle n'a pas eu lieu : ni l'agenda, ni « lancer maintenant », ni le plafond du jour ne la comptent ;
        # l'espacement, si (il court depuis la tentative : pas de relance en boucle)
        broke = e.data.outcome in BROKEN
        p = replace(p, runs=max(0, p.runs - 1), failures=p.failures + (1 if broke else 0),
                    runs_at=tuple(t for t in p.runs_at if t != run.started), last_run_at=run.previous)
        if broke:
            # sans détail, la sorte de fin parle pour elle (« délai dépassé », « erreur ») : la pause dit une cause
            cause = e.data.detail or ("TimeoutError()" if e.data.outcome == "timeout" else "RuntimeError()")
            p = replace(p, last_failure=cause[:FAILURE_KEPT])
        if not broke:
            s = replace(s, runs_at=tuple(t for t in s.runs_at if t != run.started))
        if o is not None:
            p = _objective(p, replace(o, runs=max(0, o.runs - 1), last_run_at=run.previous_objective))
        return _set(s, p)
    if o is not None:  # le modèle a travaillé, mais n'a rien conclu
        p = _objective(p, replace(o, silent=o.silent + 1))
    return _set(s, replace(p, failures=0))


@PROJECTS.reducer(c.RUN_REPORTED)
def _reported(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None:
        return s
    run = s.running.get(e.correlation)
    if run is not None and run.project == p.id:
        s = replace(s, running=s.running.set(e.correlation, replace(run, reported=True)))
    # la cadence d'un constant court depuis le départ du passage, pas depuis sa fin (elle ne dérive pas)
    began = run.started if run is not None and run.project == p.id and run.started else e.at
    pm = params(cx.params)
    p = replace(p, failures=0, summary_ref=d.summary.ref or p.summary_ref, last_commit=d.commit or p.last_commit)
    if d.summary.ref:
        p = replace(p, reports=(*p.reports, (e.at, d.objective, d.verdict, d.summary.ref))[-REPORTS_KEPT:])
    o = objective_at(p, d.objective)
    if o is not None:
        # la preuve : un ancien journal comptait chaque outil réussi ; désormais une exécution qui a produit
        # (un commit, un brouillon, une app) compte une fois
        gained = len(d.tools) if d.proof is None else int(bool(d.proof))
        o = replace(o, silent=0, evidence=o.evidence + gained, note_ref=d.summary.ref or o.note_ref,
                    waiting_until=0)
        needed = d.need.ref if d.need is not None and d.need.ref else ""
        # un nouveau besoin, ou un besoin qui reste après la réponse que l'exécution avait sous les yeux : elle le dira
        if needed and (not o.need_ref or (o.asked and _settled(o, began))):
            o = replace(o, need_ref=needed, asked=False, ask_attempts=0, steered_at=0)
        elif needed:  # le même besoin, redit à chaque exécution (sa référence change) : déjà dit, on ne relance pas
            o = replace(o, need_ref=needed)
        elif not needed and d.verdict in (c.CONTINUE, c.DONE):  # elle avance seule à nouveau
            o = replace(o, need_ref="", steered_at=0)
        if d.verdict == c.WAIT:
            o = replace(o, waiting_until=e.at + max(pm.wait_min_us, min(pm.wait_max_us, d.wait_s * 1_000_000)))
        elif d.verdict in (c.DONE, c.BLOCKED) and o.kind == c.CONSTANT:  # un passage fini (ou buté) : il reviendra
            o = replace(o, passed_at=began, passes=o.passes + 1)
            if d.verdict == c.DONE and d.proven and d.summary.ref:  # un passage qui a produit : il peut se raconter
                o = replace(o, pass_ref=d.summary.ref, pass_notable=d.notable, share_attempts=0)
        elif d.verdict == c.DONE and not d.proven:
            o = replace(o, unproven=o.unproven + 1)
        p = _objective(p, o)
    return _set(s, p)


@PROJECTS.reducer(c.OBJECTIVE_CLOSED)
def _objective_closed(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or o is None or o.status != c.OPEN:
        return s
    o = replace(o, status=d.status if d.status in (c.DONE, c.BLOCKED) else c.BLOCKED, closed_at=e.at,
                notable=d.notable, result_ref=d.result.ref or "" if d.result is not None else "")
    if o.status == c.BLOCKED and o.asked and _settled(o, e.at):  # il bloque après sa réponse : elle le dira
        o = replace(o, asked=False, ask_attempts=0)
    return _set(s, _objective(p, o))


def _effect_line(p: Project, line: str) -> Project:
    """Où en est une demande (« #N … ») : sa ligne la plus récente remplace la précédente (proposée, puis faite)."""
    key = line.split(" ", 1)[0]
    kept = tuple(x for x in p.effects if x.split(" ", 1)[0] != key) if key.startswith("#") else p.effects
    return replace(p, effects=(*kept, line)[-EFFECTS_KEPT:])


@PROJECTS.reducer(rt.EFFECT_PROPOSED)
def _proposed(s: ProjectsState, e, cx) -> ProjectsState:
    pid = project_of(e.data.context)
    if e.data.owner != c.OWNER or pid is None or pid not in s.projects:
        return s
    p = s.projects[pid]
    line = f"#{e.seq} {effect_words(e.data.capability, phrase('projects.effect.networked'))}" + \
        (phrase("projects.effect.pending") if e.data.approval else "")
    # une demande (de l'opérateur, ou sa commande réseau mise en file), maintenant proposée, n'est plus à proposer
    asked = _request_of(e.data.args_json)
    p = replace(_effect_line(p, line), requests=tuple(r for r in p.requests if r[0] != asked),
                network=tuple(r for r in p.network if r[0] != asked))
    if not e.data.approval:  # elle part aussitôt : l'atelier est occupé jusqu'à ce qu'elle revienne
        p = replace(p, outgoing=(*p.outgoing, (e.seq, e.at))[-8:])
    awaiting = s.awaiting.set(e.seq, e.data.args_json) if e.data.approval else s.awaiting
    s = replace(_set(s, p), proposals=s.proposals.set(e.seq, (pid, e.data.capability)), awaiting=awaiting)
    if e.data.capability == STEER:
        asked = _asked_of(e.data.args_json)
        if asked in s.steers:
            s = replace(s, steer_proposals=_kept(s.steer_proposals.set(e.seq, asked)))
    return s


PUSH, PULL, NETWORKED = f"{c.OWNER}.push", f"{c.OWNER}.pull", f"{c.OWNER}.networked"
#: piloter un projet sur ton accord (ADR 0133) : rien ne sort de la machine, le geste s'écrit une fois accepté
STEER = f"{c.OWNER}.steer"


def _asked_of(args_json: str) -> str:
    """La demande de pilotage qu'une proposition porte (vide : aucune)."""
    try:
        data = json.loads(args_json)
    except ValueError:
        return ""
    value = data.get("asked") if isinstance(data, dict) else None
    return value if isinstance(value, str) else ""


def _kept(items: FrozenDict[int, str]) -> FrozenDict[int, str]:
    while len(items) > STEERS_KEPT:
        items = items.delete(min(items))
    return items


def effect_words(capability: str, default: str) -> str:
    """Ce qu'est une demande, en mots (« pousser vers le dépôt distant ») — ``default`` pour une autre capacité."""
    if capability == PUSH:
        return phrase("projects.effect.push")
    if capability == PULL:
        return phrase("projects.effect.pull")
    if capability == NETWORKED:
        return phrase("projects.effect.networked")
    if capability == STEER:
        return phrase("projects.effect.steer")
    return default


def _request_of(args_json: str) -> int:
    """La demande de l'opérateur qu'une proposition exécute (0 : aucune)."""
    try:
        data = json.loads(args_json)
    except ValueError:
        return 0
    value = data.get("request") if isinstance(data, dict) else None
    return value if isinstance(value, int) else 0


@PROJECTS.reducer(rt.EFFECT_RESOLVED)
def _resolved(s: ProjectsState, e, cx) -> ProjectsState:
    got = s.proposals.get(e.data.proposal)
    if e.data.proposal in s.awaiting:
        s = replace(s, awaiting=s.awaiting.delete(e.data.proposal))
    if got is None or got[0] not in s.projects:
        return s
    p = s.projects[got[0]]
    if got[1] == STEER and not e.data.approved:  # refusée : elle ne s'appliquera jamais
        asked = s.steer_proposals.get(e.data.proposal, "")
        s = replace(s, steers=s.steers.delete(asked) if asked in s.steers else s.steers,
                    steer_proposals=s.steer_proposals.delete(e.data.proposal))
    if e.data.approved and got[1] != STEER:  # elle part : l'atelier est occupé jusqu'à ce qu'elle revienne
        return _set(s, replace(p, outgoing=(*p.outgoing, (e.data.proposal, e.at))[-8:]))
    if e.data.approved:
        return s
    # la note de qui refuse est gardée à part (l'oubli l'atteint) : seule celle d'un journal ancien est en clair
    note = f" : « {e.data.legacy_note[:200]} »" if e.data.legacy_note else ""
    if e.data.note is not None and e.data.note.ref:
        p = replace(p, refusals=(*p.refusals, (e.data.proposal, e.data.note.ref))[-EFFECTS_KEPT:])
    return _set(s, _effect_line(p, f"#{e.data.proposal} {phrase('projects.effect.refused')}{note}"))


@PROJECTS.reducer(rt.EFFECT_EXECUTED)
def _executed(s: ProjectsState, e, cx) -> ProjectsState:
    got = s.proposals.get(e.data.proposal)
    if got is None or got[0] not in s.projects:
        return s
    p = s.projects[got[0]]
    result = e.data.result
    p = replace(p, outgoing=tuple(x for x in p.outgoing if x[0] != e.data.proposal))
    # l'état seulement (fait, échoué, son code) : ce que le réseau a rendu est une donnée, citée à part
    state = phrase("projects.effect.done") if e.data.ok else phrase("projects.effect.failed")
    p = _effect_line(p, f"#{e.data.proposal} {effect_words(got[1], phrase('projects.effect.other'))}"
                        + phrase("projects.effect.result", state=state, code=_code_of(result)))
    if got[1] == NETWORKED:
        p = replace(p, network_out=result[:NETWORK_OUT_KEPT], network_out_at=e.at)
    if got[1] in (PUSH, PULL):
        p = replace(p, remote_at=e.at, remote_ok=e.data.ok,
                    remote_line=f"{effect_words(got[1], '')} : {result[:400]}")
    asked = s.steer_proposals.get(e.data.proposal, "") if got[1] == STEER else ""
    if asked in s.steers:  # acceptée : son geste s'écrit (l'effet ``tools._steer_accepted``)
        s = replace(s, steers=s.steers.set(asked, replace(s.steers[asked], applied=True)))
    return _set(s, p)


#: ce que l'atelier dit d'une commande finie (``RunResult.summary``) : « … — code 0 (12 ms) »
_CODE = re.compile(r"— code (-?\d+) \(\d+ ms\)")


def _code_of(result: str) -> str:
    """Le code de sortie d'une commande, lu dans son résumé — avant ce qu'elle a écrit (``sortie :``,
    ``erreurs :``), qu'une sortie ne puisse pas le contrefaire ; une commande peut tenir sur plusieurs lignes."""
    head = re.split(r"\n(?:sortie|erreurs) :\n", result, maxsplit=1)[0]
    codes = _CODE.findall(head)
    if codes:
        return phrase("projects.effect.code", code=codes[-1])
    if "délai dépassé" in head:
        return phrase("projects.effect.timeout")
    if head.startswith(("Refusé", "refusé")):
        return phrase("projects.effect.refused_code")
    return ""


def outgoing(p: Project, now: int) -> bool:
    """Quelque chose est-il en route hors de la machine pour ce projet (une commande, un envoi) ?"""
    return any(now - at < OUTGOING_STALE for _, at in p.outgoing)


# ── Faits ─────────────────────────────────────────────────────────────────


def view(p: Project) -> c.ProjectView:
    once = [o for o in p.objectives if o.kind == c.ONCE and o.status != c.DROPPED]
    return c.ProjectView(
        id=p.id, title_ref=p.title_ref, authority=p.authority, mode=p.mode, status=p.status, owner=p.owner,
        about=p.about, sensitivity=p.sensitivity, created_at=p.created_at, priority=p.priority,
        schedule=p.schedule, open_once=sum(1 for o in once if o.status == c.OPEN),
        done_once=sum(1 for o in once if o.status == c.DONE),
        blocked_once=sum(1 for o in once if o.status == c.BLOCKED),
        constants=sum(1 for o in p.objectives if o.kind == c.CONSTANT and o.status == c.OPEN),
        blocked=sum(1 for o in p.objectives if o.status == c.BLOCKED), runs=p.runs, last_run_at=p.last_run_at,
        last_summary_ref=p.summary_ref, written=written(p), instructions=p.instructions[-3:],
        access=access_of(p)[0], default_access=access_of(p)[1], plan_state=p.plan_state)


def access_of(p: Project) -> tuple[tuple[c.ProjectAccess, ...], c.ProjectAccess]:
    """Ses lignes d'accès et sa ligne par défaut (ADR 0133, 0134) ; jamais réglées : toi et elle seule, tout ; la
    personne qui l'a confié le voit, le pilote sur ton accord et en reçoit les fichiers ; les autres l'entendent selon
    sa confidentialité, en lecture seule (``UNSET``)."""
    if p.access is None:
        if p.authority == c.USER and p.owner:
            return (*c.UNSET, c.ProjectAccess(who=(PERSON + p.owner,), see=True, steer=c.STEER_ASK, files=True)), \
                c.UNSET_DEFAULT
        return c.UNSET, c.UNSET_DEFAULT
    return p.access, p.default_access


@PROJECTS.fact(c.LIVE)
def _live(s: ProjectsState, cx) -> tuple[c.ProjectView, ...]:
    return tuple(view(p) for p in sorted(s.projects.values(), key=lambda p: p.id) if live(p))


@PROJECTS.fact(c.STATUS)
def _status(s: ProjectsState, cx, project: int) -> str:
    p = s.projects.get(project)
    return p.status if p is not None else ""


@PROJECTS.fact(c.OUTGOING)
def _outgoing(s: ProjectsState, cx, project: int) -> bool:
    p = s.projects.get(project)
    return p is not None and outgoing(p, cx.now)


@PROJECTS.fact(c.OBJECTIVE_STATUS)
def _objective_status(s: ProjectsState, cx, key: tuple) -> str:
    p = s.projects.get(key[0]) if len(key) == 2 else None
    o = objective_at(p, key[1]) if p is not None else None
    return o.status if o is not None else ""


# ── Ce que ses événements font ressentir ──────────────────────────────────


@PROJECTS.appraisal(ARCHIVED)
def _ended_felt(e, cx) -> Appraisal | None:
    """Elle clôt elle-même un projet à elle : soulagée s'il a fait son temps, un peu mélancolique si elle y
    renonce. Un opérateur qui archive ne lui fait rien ressentir."""
    if e.data.ending == "done":
        return Appraisal(Emotion.RELIEVED, 0.2, reason=causes.PROJECT_CLOSED)
    if e.data.ending == "dropped":
        return Appraisal(Emotion.MELANCHOLIC, 0.2, reason=causes.PROJECT_ABANDONED)
    return None


@PROJECTS.appraisal(c.OBJECTIVE_CLOSED)
def _closed_felt(e, cx) -> Appraisal | None:
    """En mode Mika, mener un objectif à bout rend fière, bloquer frustre. En mode impersonnel : rien."""
    d = e.data
    if d.mode != c.PERSONA:
        return None
    if d.status == c.DONE:
        return Appraisal(Emotion.PROUD, 0.35, reason=causes.OBJECTIVE_ACHIEVED)
    if d.status == c.BLOCKED:
        return Appraisal(Emotion.FRUSTRATED, 0.3, reason=causes.OBJECTIVE_STUCK)
    return None

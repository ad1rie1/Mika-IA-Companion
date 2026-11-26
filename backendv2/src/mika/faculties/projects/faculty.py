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
- **Un objectif constant devient aussi dû par un événement** (ADR 0265) : il dit
  ce qui le déclenche (``Objective.on``, ``triggers.py``). Les réducteurs notent
  ce qui vient d'arriver et qu'un objectif attend (``heard``) sans juger aucun
  droit ; le processus ``projects.stirs`` (``tend.py``) le juge devant ce qu'elle
  vit et l'écrit (``projects.stirred``) ; l'objectif garde ses causes
  (``stirred``) jusqu'au départ de l'exécution qui le vise.
- **Son registre** (ADR 0268) : ses tickets et ses listes de suivi. Leurs formes sont ici (``Board``, ``Listing``,
  ``Item``) ; leurs événements, leurs règles, leurs réducteurs et leur projection sont dans ``tracker.py``.
- **Ses pull requests** (ADR 0274) : un projet au flux ``pr`` travaille une branche par objectif
  (``Objective.branch``, que dit le compte rendu de l'exécution) et finit en pull request (``Objective.pull``,
  ``pull_state``). Leurs faits sont ici (``projects.pull_seen`` : ce que l'hôte en dit, daté) ; ce qui les propose,
  les ouvre et les relit, dans ``pulls.py``. Rien ici ne fusionne.
- **Ses jalons** (ADR 0273) : un objectif ponctuel dit où il en est (``Objective.milestones``, ``Milestone``). Leurs
  événements et leurs réducteurs sont ici ; ce qui s'écrit et ce qu'on en lit, dans ``milestones.py`` ; ses outils,
  dans ``reaching.py``. Un jalon atteint ne se défait pas ; un objectif qui en a bloque quand il n'en atteint plus
  (``Objective.stale``, ``tend.py``) ; un constant n'en a pas — il a sa liste de passage (``routine_ref``). En
  exécution, elle ne défait ni un point d'arrêt, ni un jalon qu'un autre a posé ou qu'un plan validé par une
  personne a fixé (``milestone_guard``, ADR 0278) : la règle est ici, pure, lue par le réducteur et par l'outil.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Annotated, Any, NamedTuple

from pydantic import BaseModel, ConfigDict

from mika.contracts import agency as agency_c
from mika.contracts import forge as forge_c
from mika.contracts import identity as identity_c
from mika.contracts import mcp as mcp_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import wakeup as wakeup_c
from mika.faculties.projects import triggers
from mika.kernel import schedule
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content, Draft, Payload
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict
from mika.ports.workshop import (
    CHECKS_FAILED,
    CHECKS_NONE,
    CHECKS_PASSED,
    CHECKS_STATES,
    EXITED,
    PULL_CLOSED,
    PULL_MERGED,
    PULL_OPEN,
    PULL_STATES,
    REFUSED,
    TIMED_OUT,
    run_status,
)
from mika.vocab import causes
from mika.vocab.access import PERSON
from mika.vocab.affect import Appraisal, Emotion
from mika.vocab.episodes import PROJECT_KINDS, Kind, project_of
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity

NOTES_KEPT = 8
#: ce qu'un objectif garde de lui-même (ADR 0253) : ses derniers comptes rendus et ses dernières notes
OBJECTIVE_REPORTS_KEPT = 3
OBJECTIVE_NOTES_KEPT = 3
INSTRUCTIONS_KEPT = 8
EFFECTS_KEPT = 8
DEPOSITS_KEPT = 8
#: les objectifs vivants (ouverts ou bloqués) d'un projet, au plus ; son histoire (les faits et les retirés en
#: plus) en garde davantage, les plus anciens clos tombant d'abord
OBJECTIVES_KEPT = 60
OBJECTIVES_HISTORY = 200
#: les décisions en vigueur, au plus ; une décision remplacée ou retirée reste lisible tant qu'il y a la place
DECISIONS_KEPT = 200
#: les projets qu'un projet lit, au plus (ADR 0257)
LINKS_MAX = 4
#: les causes qu'un objectif garde en attente, au plus (ADR 0265) : les plus récentes
STIRS_KEPT = 8
#: un déclenchement n'attend jamais plus longtemps que ça après sa première cause, même si d'autres continuent d'arriver
STIR_MAX_WAIT = HOUR
#: ce qui vient d'arriver et n'est pas encore jugé, au plus (le processus le juge aussitôt : la file reste courte)
HEARD_KEPT = 32
#: ce qu'on garde du détail d'une cause (l'empreinte d'un commit, un numéro)
STIR_DETAIL = 40
#: ses demandes aux projets qu'il lit (ADR 0271) : celles qu'il garde, au plus ; ses demandes ouvertes par lien, au
#: plus ; celles qu'une exécution ouvre, au plus
ASKS_KEPT = 20
ASKS_OPEN_MAX = 5
ASKS_PER_RUN = 3
#: la liste de passage d'un constant (ADR 0273) : ses lignes, au plus, et ce qu'on garde de chacune
ROUTINE_LINES, ROUTINE_LINE_MAX = 5, 200
#: les jalons qu'un objectif garde en tout, retirés compris (les vivants : ``c.MILESTONES_MAX``) : au-delà, le plus
#: ancien retiré tombe — l'état reste borné
MILESTONES_KEPT = 12
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
#: ses capacités se déclarent sous ces noms complets (``atelier.py``, ``tools.py``), que le journal porte : ils ne
#: changent pas. Pousser vers le dépôt distant, en récupérer l'histoire, lancer une commande avec le réseau
PUSH_CAPABILITY, PULL_CAPABILITY = f"{c.OWNER}.push", f"{c.OWNER}.pull"
NETWORKED_CAPABILITY = f"{c.OWNER}.networked"
#: ouvrir la pull request d'une branche de travail (ADR 0274) : elle pousse la branche, puis l'ouvre chez l'hôte
PULL_REQUEST_CAPABILITY = f"{c.OWNER}.pull_request"
#: ses tentatives d'ouverture en échec, au plus, avant d'attendre un geste (un nouveau « fait », la console)
PULL_TRIES_MAX = 3
#: piloter un projet sur ton accord (ADR 0133) : rien ne sort de la machine, le geste s'écrit une fois accepté
STEER_CAPABILITY = f"{c.OWNER}.steer"
#: le reflet des tickets en issues chez l'hôte (ADR 0275) : publier un ticket, fermer ou rouvrir son issue, publier
#: une note de son fil — trois capacités, chacune avec son aperçu
ISSUE_CAPABILITY = f"{c.OWNER}.issue"
ISSUE_STATE_CAPABILITY = f"{c.OWNER}.issue_state"
ISSUE_NOTE_CAPABILITY = f"{c.OWNER}.issue_note"
ISSUE_CAPABILITIES = (ISSUE_CAPABILITY, ISSUE_STATE_CAPABILITY, ISSUE_NOTE_CAPABILITY)
#: ce qui part chez l'hôte pour un ticket (``IssueMove.what``) ; ce qu'un projet en garde, au plus ; les essais en
#: échec d'un même départ avant d'attendre un geste
MOVE_PUBLISH, MOVE_CLOSE, MOVE_REOPEN, MOVE_NOTE = "publish", "close", "reopen", "note"
MOVES = (MOVE_PUBLISH, MOVE_CLOSE, MOVE_REOPEN, MOVE_NOTE)
MOVES_KEPT = 40
MOVE_TRIES_MAX = 3


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
             "d'exécutions ») ; rouvert, il en retrouve autant. Un objectif qui a des jalons suit aussi "
             "l'autre règle : les exécutions sans jalon atteint.")] = 12
    milestone_runs_max: Annotated[int, Knob(
        label="Exécutions sans jalon atteint", group="Les objectifs", lo=1, hi=50,
        help="Un objectif ponctuel qui a des jalons bloque après autant d'exécutions de suite sans nouveau jalon "
             "atteint (« il n'avance plus »), sans attendre le plafond d'exécutions en tout, qui reste son "
             "filet ; dire un point d'arrêt prêt compte comme une avancée.")] = 4
    constant_cadence_us: Annotated[int, Knob(
        label="Cadence d'un objectif constant", group="Les objectifs", lo=HOUR, hi=30 * DAY,
        help="Un objectif constant qui n'en précise pas revient après ce délai, une fois son passage fait.")] = DAY
    stir_settle_us: Annotated[int, Knob(
        label="Attendre que le travail se pose avant un passage déclenché", group="Les objectifs", lo=MINUTE, hi=HOUR,
        help="Un objectif constant que quelque chose déclenche (un commit d'un projet lu, un signal d'app) passe "
             "quand rien de neuf n'est arrivé depuis ce délai — une heure au plus après la première cause : cinq "
             "commits de suite ne font qu'un passage.")] = 15 * MINUTE
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
class Stir:
    """Une cause en attente (ADR 0265) : ce qui a déclenché un objectif, et quand. ``key`` : le déclencheur, tel que
    l'objectif le déclare (``triggers.py``) ; ``detail`` : de quoi parler — l'empreinte du commit, le numéro de
    l'objectif abouti, la sorte du signal d'une app. Aucun texte : ce qu'on en dit se relit au moment de le dire."""

    at: int
    key: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Heard:
    """Ce qui vient d'arriver et qu'un déclencheur attend, pas encore jugé (ADR 0265) : l'événement entendu
    (``seq``), quand, le déclencheur qu'il éveille, son détail, et le projet où c'est arrivé (0 : il ne se sait pas
    ici — le signal d'une app, dont le processus lit le projet). Le réducteur le note sans rien savoir des droits ;
    le processus ``projects.stirs`` le juge et l'écrit (``projects.stirred``), ce qui l'ôte d'ici."""

    seq: int
    at: int
    key: str
    detail: str = ""
    project: int = 0


@dataclass(frozen=True, slots=True)
class Milestone:
    """Un jalon d'un objectif ponctuel (ADR 0273) : où elle en est, et ce qui rend « fait » vérifiable. ``check`` :
    comment il se vérifie (``c.CHECKS``) — une commande que l'outil lance (``command_ref`` : ses arguments, un
    contenu effaçable), un point d'arrêt que le propriétaire tranche, un élément du registre dans un statut donné
    (``item_list``, ``item_key``, ``item_status``), ou ce qu'elle en dit. Sans sous-jalons."""

    id: int
    text_ref: str
    check: str = c.CHECK_PROSE
    command_ref: str = ""
    item_list: str = ""
    item_key: str = ""
    item_status: str = ""
    #: ouvert, atteint, retiré (``c.OPEN``, ``c.REACHED``, ``c.DROPPED``) ; qui l'a posé (``operator`` | ``owner`` | ``self``), quand
    status: str = c.OPEN
    author: str = "self"
    at: int = 0
    #: le plan qui l'a posé a été validé par une personne (ADR 0278) — le plan du projet, ou le plan d'un ticket :
    #: ce jalon est à cette personne. En exécution elle ne le retire pas, n'en réécrit pas le texte et n'en
    #: affaiblit pas la vérification (``milestone_guard``)
    agreed: bool = False
    #: un point d'arrêt : elle l'a dit prêt à cet instant (0 : non) — il attend le propriétaire, et l'objectif avec
    #: lui ; refusé à cet instant (sa raison : ``reason_ref``), il est de nouveau à elle
    ready_at: int = 0
    refused_at: int = 0
    #: atteint : quand, par qui (``self``, une personne — sa clé —, ``operator``), comment elle dit l'avoir rempli,
    #: sa preuve (un fait arrivé, borné : le résumé de la sortie de sa commande, le statut de son élément) et le
    #: commit de l'atelier à ce moment-là — celui qui clôt l'exécution où elle l'a dit, dès qu'elle a rendu compte
    reached_at: int = 0
    reached_by: str = ""
    how_ref: str = ""
    proof_ref: str = ""
    commit: str = ""
    #: la raison de sa dernière révision, de son retrait ou de son refus ; combien de fois il a été révisé
    reason_ref: str = ""
    revised: int = 0


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
    #: ses exécutions qui ont eu lieu, depuis sa naissance (ADR 0280) : ``runs`` repart de zéro quand il se rouvre
    #: — l'hôte le renvoie, on lui répond, on le rouvre —, ce compte-ci jamais. « C'est ta première exécution sur
    #: cet objectif » ne se dit que s'il n'a vraiment jamais été travaillé
    worked: int = 0
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
    #: sa mémoire de travail à lui (ADR 0253) : ses derniers comptes rendus, du plus ancien au plus récent — (instant,
    #: verdict, réf. du texte) —, et ses dernières notes de carnet (des références). L'exécution qui le vise les
    #: retrouve même quand d'autres objectifs ont travaillé entre-temps
    reports: tuple[tuple[int, str, str], ...] = ()
    notes: tuple[str, ...] = ()
    #: un constant : ce qui le rend dû en plus de sa cadence (ADR 0265) — des déclencheurs normalisés
    #: (``triggers.py``), ``TRIGGERS_MAX`` au plus ; et s'il n'a aucune cadence (il ne passe que sur événement)
    on: tuple[str, ...] = ()
    only_on_event: bool = False
    #: un constant : son premier passage vient tout de suite — dès qu'il peut commencer —, pas une cadence après
    #: (ADR 0280 ; sans lui, la règle de l'ADR 0161 : un bilan de la semaine ne tombe pas le jour où l'app naît)
    at_once: bool = False
    #: ses causes pas encore traitées, de la plus ancienne à la plus récente, ``STIRS_KEPT`` au plus ; l'instant de
    #: la première depuis son dernier départ (le plafond d'une heure se compte depuis elle, même quand elle est
    #: tombée de la liste) ; combien sont tombées. Le départ de l'exécution qui le vise les lui prend
    #: (``Run.stirred``) ; une exécution qui n'a pas eu lieu les lui rend
    stirred: tuple[Stir, ...] = ()
    stirred_at: int = 0
    stirred_more: int = 0
    #: le ticket dont il est né (son numéro ; 0 : aucun) : le plan validé d'un ticket devient un objectif ponctuel,
    #: et le ticket se ferme quand il aboutit (ADR 0270) ; sa consigne — le commentaire de qui a validé son plan
    ticket: int = 0
    brief_ref: str = ""
    #: un ponctuel : ses jalons (ADR 0273), dans l'ordre où ils ont été posés, ``c.MILESTONES_MAX`` vivants au plus
    #: (un jalon retiré reste lisible) ; le dernier numéro donné ; ses exécutions de suite sans nouveau jalon atteint
    #: — autant que le réglage, et il bloque (``tend.py``)
    milestones: tuple[Milestone, ...] = ()
    milestone_seq: int = 0
    stale: int = 0
    #: un constant : ce que chaque passage doit faire (une référence : ``ROUTINE_LINES`` lignes au plus), montré à
    #: chaque passage — un constant n'a pas de jalons
    routine_ref: str = ""
    #: sa branche de travail (ADR 0274 ; vide : aucune exécution n'a encore rendu compte sur une branche) — celle que
    #: dit le compte rendu de sa dernière exécution ; et si elle porte un commit que sa pull request n'a pas encore
    branch: str = ""
    unsent: bool = False
    #: sa pull request chez l'hôte : son numéro (0 : pas encore lue, ou aucune), son état (``PULL_STATES`` du port ;
    #: vide : aucune), si sa relecture demande des changements, quand l'hôte l'a dit pour la dernière fois, et ce
    #: qu'il en dit (une référence : le texte d'un inconnu, cité, que l'oubli atteint)
    pull: int = 0
    pull_state: str = ""
    pull_changes: bool = False
    pull_review_at: int = 0
    pull_at: int = 0
    pull_said_ref: str = ""
    #: l'hôte la dit impossible à fusionner (ADR 0280) : sa branche est en conflit avec la base. Elle n'est pas
    #: prête, et l'objectif se rouvre une fois ; seul l'hôte, en la redisant fusionnable, lève ce fait
    pull_conflicts: bool = False
    #: sa proposition de pull request en attente (le numéro de la proposition ; 0 : aucune), ses essais d'ouverture
    #: en échec depuis le dernier « fait », et combien de ses pull requests ont été fusionnées (un constant change
    #: de branche après chacune)
    pull_proposal: int = 0
    pull_tries: int = 0
    pulls_merged: int = 0
    #: la fusion de sa pull request, demandée par une personne (ADR 0288) : quand elle l'a demandée (0 : rien
    #: n'attend la réponse de l'hôte) et qui ; quand l'hôte a répondu ; et pourquoi il ne l'a pas fusionnée
    #: (``MERGE_WHYS`` du port, ``MERGE_STALE``, ``MERGE_CUT`` ; vide : il l'a fusionnée, ou rien n'a été demandé).
    #: Ce n'est pas ce qui clôt l'objectif : la fusion s'apprend à la relecture de l'hôte (``pull_seen``)
    merge_asked_at: int = 0
    merge_by: str = ""
    merge_answered_at: int = 0
    merge_refused: str = ""
    #: les vérifications du commit de sa pull request (ADR 0275 ; ``CHECKS_STATES`` du port ; vide : pas encore
    #: lues, ou illisibles — rien ne s'en déduit), le commit qu'elles jugent, quand l'hôte l'a dit, et ce qu'il dit
    #: d'un échec (une référence : les vérifications en échec et la fin du journal, le texte d'un inconnu, cité)
    checks: str = ""
    checks_sha: str = ""
    checks_at: int = 0
    checks_said_ref: str = ""
    #: le dernier commit dont l'échec des vérifications a été vu (ADR 0278) : un échec ne rouvre l'objectif qu'une
    #: fois par commit — « échec, en cours, échec » pour le même commit ne le rouvre pas deux fois
    checks_failed_sha: str = ""
    #: la relecture indépendante (ADR 0276). Le dernier commit que ses exécutions ont laissé ; et, sur un projet au
    #: flux direct, d'où part ce qu'une relecture en lit — le commit d'avant son premier travail, puis celui de sa
    #: dernière relecture favorable (vide : le début du dépôt)
    commit: str = ""
    since: str = ""
    #: le commit dont une relecture est demandée (vide : aucune), et celles parties pour lui sans conclure
    review_due: str = ""
    review_tries: int = 0
    #: son dernier verdict : le commit relu, favorable ou non, quand, par quel fournisseur de modèle, et ses constats
    #: (une référence : le dire d'une autre exécution, cité, que l'oubli atteint ; vide : « bon »)
    reviewed: str = ""
    review_ok: bool = False
    review_at: int = 0
    review_by: str = ""
    review_ref: str = ""
    #: les constats de ses relectures refusées d'affilée (des références, ``REVIEW_REFUSALS_MAX`` au plus) : ce
    #: nombre atteint, la suivante n'a pas lieu et l'objectif va au propriétaire — sa réponse, ou sa consigne, les
    #: remet à zéro
    review_refused: tuple[str, ...] = ()


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


#: son registre (ADR 0268) : les listes d'un projet, au plus (``tickets`` comprise)
LISTS_MAX = 12
#: les éléments touchés en dernier que l'état garde, par projet, en plus de ses tickets ouverts
ITEMS_RECENT = 40
#: les tickets ouverts d'un projet, au plus : au-delà, en ouvrir un est refusé (l'état les garde tous)
TICKETS_OPEN_MAX = 200
#: les derniers changements qu'un élément garde
ITEM_CHANGES_KEPT = 5
#: la borne d'un petit ticket (ADR 0270), par défaut et au plus : les fichiers et les lignes que les exécutions de son
#: objectif ont changés ; les fichiers protégés d'un projet (des motifs de chemin), au plus, et leur longueur
SMALL_FILES, SMALL_LINES = 3, 40
SMALL_FILES_MAX, SMALL_LINES_MAX = 50, 2000
PROTECTED_MAX, PROTECTED_CHARS = 20, 120


@dataclass(frozen=True, slots=True)
class Change:
    """Un changement d'un élément (ADR 0268) : quand, qui (``self``, ``operator``, ``project:<n>``, ou la clé d'une
    personne), quoi — un code court (``status:todo>done``, ``accepted``, ``closed:done``, ``priority:high``),
    jamais un texte."""

    at: int
    by: str
    what: str


@dataclass(frozen=True, slots=True)
class Listing:
    """Une liste de suivi d'un projet (ADR 0268) : son nom (celui qu'écrit un déclencheur ``item:<nom>``), son titre
    (une référence), ses statuts ouverts puis clos, et qui agit par défaut sur ses éléments."""

    name: str
    title_ref: str = ""
    open: tuple[str, ...] = c.ITEM_OPEN
    closed: tuple[str, ...] = c.ITEM_CLOSED
    actor: str = c.ACTOR_SELF
    person: str = ""
    at: int = 0


@dataclass(frozen=True, slots=True)
class Item:
    """Un élément d'une liste (ADR 0268), tel que l'état et la projection le tiennent — la même forme des deux côtés
    (``tracker.added``, ``tracker.changed``). ``status`` : son statut, posé à la main ; pour un ticket, son étape,
    déduite de ses faits (``tracker.stage``). ``known`` : faux pour un élément que l'état ne gardait plus et qu'un
    changement y ramène — seuls sa clé, son statut et ses faits y sont sûrs, le reste se lit dans la projection."""

    list_name: str
    key: str
    #: un ticket : son numéro, compté par projet (0 : pas un ticket, ou inconnu ici)
    number: int = 0
    #: l'événement qui l'a ajouté ; son titre, son texte, sa référence extérieure (des références, effaçables)
    seq: int = 0
    title_ref: str = ""
    text_ref: str = ""
    link_ref: str = ""
    status: str = c.TODO
    #: qui agit : elle, le propriétaire, une personne (``person`` : sa clé)
    actor: str = c.ACTOR_SELF
    person: str = ""
    #: l'objectif qui le tient (0 : aucun)
    objective: int = 0
    #: un ticket : sa sorte, sa priorité
    kind: str = ""
    priority: str = c.NORMAL
    #: qui l'a ouvert (``self``, ``person``, ``operator``, ``project:<n>``) et sa personne
    author: str = c.BY_SELF
    by: str = ""
    #: un ticket, ses faits : proposé (il attend que le propriétaire l'accepte) ; accepté, quand et par qui ; fermé
    #: (``""`` : ouvert ; ``done`` : traité ; ``dropped`` : écarté), quand et par qui
    proposed: bool = False
    accepted_at: int = 0
    accepted_by: str = ""
    closed: str = ""
    closed_at: int = 0
    closed_by: str = ""
    #: un ticket, les faits de son parcours (ADR 0270 ; ``tickets.py`` en déduit son étape) : elle l'a pris ; sa
    #: question attend une réponse ; elle propose de l'écarter (le propriétaire confirme) ; son plan (la note qui le
    #: porte) et si elle le juge petit ; son plan validé, quand et par qui (``self`` : un petit ticket, sans attendre) ;
    #: son objectif bloque ; ce que les exécutions de son objectif ont changé (des fichiers, des lignes — la borne
    #: d'un petit ticket). Rouvrir un ticket les remet tous à zéro
    taken_at: int = 0
    asked_at: int = 0
    dismissal_at: int = 0
    plan_seq: int = 0
    small: bool = False
    validated_at: int = 0
    validated_by: str = ""
    stuck: bool = False
    diff_files: int = 0
    diff_lines: int = 0
    #: pris comme petit, il a dépassé sa borne (ADR 0272) : elle ne le valide plus elle-même, seul le propriétaire
    outgrown: bool = False
    #: ce qu'il dit de la pull request de son objectif (ADR 0274 ; ``c.PULLS``) et son numéro chez l'hôte : sur un
    #: projet qui passe par des pull requests, il n'est traité qu'à la fusion
    pull: str = c.PULL_NONE
    pull_number: int = 0
    #: un ticket, son reflet chez l'hôte (ADR 0275) : le numéro de son issue (0 : il n'en a pas ; posé une fois, il
    #: ne change plus — un ticket ne se publie qu'une fois), ce que l'hôte en a dit en dernier (``ISSUE_STATES`` du
    #: port) et quand il dit l'avoir fermée (0 : ouverte) ; et quand le ticket a été rouvert ici pour la dernière
    #: fois — avec ``closed_at``, l'heure de son dernier changement, face à celle de l'hôte
    issue: int = 0
    issue_state: str = ""
    issue_at: int = 0
    reopened_at: int = 0
    #: le niveau de ses textes (ADR 0272) : le plus haut de son titre, de son texte et de sa référence — celui du
    #: demandeur quand un autre projet l'a ouvert. Il décide de qui l'entend, et ce qui s'écrit ensuite sur lui (une
    #: note, un plan, l'objectif qui en naît) est au moins de ce niveau
    level: int = 0
    at: int = 0
    #: la dernière fois qu'on y a touché (un ajout, un changement, une note), et qui (comme ``author``)
    updated_at: int = 0
    touched_by: str = ""
    #: les notes de son fil, comptées
    notes: int = 0
    #: ses derniers changements, du plus ancien au plus récent, ``ITEM_CHANGES_KEPT`` au plus
    changes: tuple[Change, ...] = ()
    known: bool = True


@dataclass(frozen=True, slots=True)
class Board:
    """Le registre d'un projet (ADR 0268), borné : ses listes, ses comptes par liste et par statut, le compteur de
    ses tickets, et les éléments qu'il garde sous la main — tous ses tickets ouverts, puis les derniers touchés
    (``ITEMS_RECENT``), du plus ancien au plus récent. Tout le reste se lit dans la projection."""

    lists: tuple[Listing, ...] = ()
    #: (liste, statut, combien) — trié ; un compte à zéro n'y est pas
    counts: tuple[tuple[str, str, int], ...] = ()
    ticket_seq: int = 0
    items: tuple[Item, ...] = ()


@dataclass(frozen=True, slots=True)
class Tie:
    """Ce qu'un lien de lecture garde en plus du projet lu (ADR 0293) : depuis quand il est posé, et le mot que son
    propriétaire a écrit en le posant — pourquoi ce projet lit l'autre (une référence, que l'oubli atteint ; vide :
    aucun)."""

    target: int
    since: int = 0
    why_ref: str = ""


@dataclass(frozen=True, slots=True)
class Ask:
    """Une demande faite à un projet qu'il lit (ADR 0271) : le ticket ouvert chez lui. ``status`` : l'étape de ce
    ticket, que le réducteur du registre recopie ici à chaque fait (``asks.followed``). Aucun texte : son titre et la
    note de sa fermeture se relisent dans la projection, tant que le lien donne encore le détail du projet visé."""

    #: le projet visé, et le ticket chez lui : sa clé, son numéro
    target: int
    key: str
    number: int = 0
    #: l'objectif de ce projet dont l'exécution l'a ouverte (0 : aucun) : sa fermeture le réveille
    objective: int = 0
    at: int = 0
    status: str = c.STAGE_PROPOSED
    #: fermée : quand, et l'événement qui porte la note de sa fermeture (0 : fermée sans un mot)
    closed_at: int = 0
    note_seq: int = 0
    #: l'exécution qui l'a ouverte (son épisode) : trois demandes au plus par exécution
    run: str = ""


@dataclass(frozen=True, slots=True)
class IssueMove:
    """Ce qui part, ou doit partir, chez l'hôte pour un ticket (ADR 0275) : sa publication, la fermeture ou la
    réouverture de son issue, une note de son fil. Aucun texte : des numéros. Un départ se propose une fois
    (``proposal``), s'exécute (``sent_at``) ou échoue (``tries``, ``MOVE_TRIES_MAX`` au plus — un refus les épuise) ;
    le fait que pose ensuite la lecture de l'hôte l'efface, sauf une note : elle reste dite publiée."""

    ticket: int
    what: str
    #: une note : l'événement qui la porte
    note: int = 0
    #: qui le demande, comme l'auteur d'une note (``self``, ``operator``, ``person`` et sa clé) ; ``""`` : personne
    #: — le reflet lui-même (la synchronisation, une fermeture qui suit)
    author: str = ""
    by: str = ""
    #: la demande qui l'a fait naître (l'événement ``issue_asked`` ; 0 : aucune), sa proposition en attente
    asked: int = 0
    proposal: int = 0
    tries: int = 0
    sent_at: int = 0
    at: int = 0


#: sa documentation (ADR 0289), un espace à part de son dépôt : ses pages, les versions gardées par page (dans la
#: projection), ses images, au plus
DOC_PAGES_MAX = 200
DOC_VERSIONS_KEPT = 50
DOC_IMAGES_MAX = 200


@dataclass(frozen=True, slots=True)
class DocPage:
    """Une page de la documentation d'un projet (ADR 0289), telle que l'état la tient : son chemin, le numéro de sa
    dernière version, quand elle a été écrite. Son titre, son texte et ses versions se lisent dans la projection
    (``docs.py``)."""

    path: str
    version: int = 1
    at: int = 0


@dataclass(frozen=True, slots=True)
class DocImage:
    """Une image de la documentation d'un projet (ADR 0289) : son nom, l'identifiant de ses octets (gardés hors du
    journal, port ``project_docs``), sa taille, sa sorte, quand et par qui elle est arrivée."""

    name: str
    file: str
    size: int = 0
    mime: str = ""
    at: int = 0
    author: str = c.BY_SELF
    by: str = ""
    via: str = ""


@dataclass(frozen=True, slots=True)
class Docs:
    """La documentation d'un projet (ADR 0289), bornée : ses pages (``DOC_PAGES_MAX``), par chemin, et ses images
    (``DOC_IMAGES_MAX``), par nom."""

    pages: tuple[DocPage, ...] = ()
    images: tuple[DocImage, ...] = ()


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
    #: son flux (ADR 0274) : ``direct``, ou ``pr`` — une branche par travail, une pull request, jamais de fusion
    flow: str = c.FLOW_DIRECT
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
    #: le commit au bout de sa branche de base, tel qu'on l'a su pour la dernière fois (ADR 0280 ; vide : jamais
    #: su) — ce qu'un projet lecteur en voit : en flux direct, le dernier commit d'une exécution ou ce qu'une
    #: récupération a ramené ; en flux ``pr``, seulement ce qu'une récupération a ramené. Et si une récupération
    #: vient d'aboutir sans qu'on ait encore relu la base (``projects.base_seen`` le lève)
    base_commit: str = ""
    base_unread: bool = False
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
    #: les projets qu'il lit, sans jamais y écrire (ADR 0257) : leurs numéros, dans l'ordre où son propriétaire les a
    #: posés, ``LINKS_MAX`` au plus, jamais en boucle. Ce qu'un lien donne ne se garde pas ici : il se relit à chaque
    #: exécution dans les lignes d'accès du projet lu (``links.py``)
    reads: tuple[int, ...] = ()
    #: ce que son plan demande à lire (des numéros) : le lien se pose quand son propriétaire valide le plan
    plan_reads: tuple[int, ...] = ()
    #: ce que ses lectures lui laissent pour de bon : le niveau au moins de ce qu'il écrit (``written``), et les
    #: personnes des projets lus (leur propriétaire, de qui ils parlent, de lecteur en lecteur) — retirer un lien ne
    #: redescend ni l'un ni les autres. Ces personnes ne rejoignent jamais ``about`` (ADR 0262) : ``about`` dit de qui
    #: parle ce projet, et décide de qui l'entend ; ``read_about`` ne sert qu'à l'oubli — les sujets de plus de ce
    #: qu'il écrit ensuite (``subjects_of``)
    read_level: int = 0
    read_about: tuple[str, ...] = ()
    #: ce que chaque lien posé garde (ADR 0293) : depuis quand, et le mot de son propriétaire — un par projet lu, dans
    #: l'ordre de ``reads`` ; un lien retiré perd le sien
    ties: tuple[Tie, ...] = ()
    #: ses demandes aux projets qu'il lit (ADR 0271). ``direct`` : les liens où une demande entre directement dans les
    #: tickets du projet visé, sans attendre l'accord de son propriétaire — réglé lien par lien par le propriétaire de
    #: ce projet, et qui ne vaut que tant que la matrice et le niveau du projet visé le permettent (``asks.mode``).
    #: ``asks`` : ses demandes, de la plus ancienne à la plus récente, ``ASKS_KEPT`` au plus (les fermées les plus
    #: anciennes tombent d'abord)
    direct: tuple[int, ...] = ()
    asks: tuple[Ask, ...] = ()
    #: son registre (ADR 0268) : ses tickets et ses listes de suivi, bornés — le détail est dans la projection
    board: Board = Board()
    #: la validation du plan d'un ticket (ADR 0270) : toujours, ou seulement pour ce qui n'est pas petit ; la borne
    #: d'un petit ticket (0 : celle par défaut, ``SMALL_FILES`` et ``SMALL_LINES``) et ses fichiers protégés (des
    #: motifs de chemin : y toucher n'est jamais petit)
    ticket_review: str = c.REVIEW_ALWAYS
    small_files: int = 0
    small_lines: int = 0
    protected: tuple[str, ...] = ()
    #: le premier de ses objectifs qui a attendu ``item:tickets`` (son numéro ; 0 : aucun, jamais) : « Traiter les
    #: tickets » ne naît de lui-même qu'une fois — ni après qu'on l'a retiré, ni après qu'on lui a ôté son déclencheur
    #: (ADR 0272)
    triage: int = 0
    #: le reflet de ses tickets en issues chez l'hôte de son dépôt distant (ADR 0275) : jamais, sur accord, ou
    #: toujours (``c.ISSUES``) ; ce qui part ou doit partir (``MOVES_KEPT`` au plus) ; et l'heure, chez l'hôte, du
    #: dernier commentaire entré dans un fil, avec les numéros là-bas de ceux entrés à cette seconde-là
    #: (``REMARK_IDS_KEPT`` au plus, ADR 0278) — un commentaire n'y entre qu'une fois, et deux commentaires de la
    #: même seconde entrent tous les deux
    issues: str = c.ISSUES_ASK
    issue_moves: tuple[IssueMove, ...] = ()
    remarks_at: int = 0
    remarks_ids: tuple[int, ...] = ()
    #: les tickets venus de l'hôte, bornés aussi dans le temps (ADR 0278) : le début de la journée en cours — le
    #: premier entré depuis au moins un jour — et combien sont entrés depuis
    hosted_since: int = 0
    hosted_count: int = 0
    #: quand une exécution indépendante relit son travail conclu (ADR 0276) : jamais, avant de sortir, ou à chaque
    #: « fait » (``c.REREADS``)
    reread: str = c.REREAD_OUT
    #: sa documentation (ADR 0289) : ses pages et ses images, un espace à part de son dépôt
    docs: Docs = Docs()


#: les comptes rendus du projet qu'une exécution relit (sa mémoire de travail, ADR 0145) ; chaque objectif garde en
#: plus les siens (``OBJECTIVE_REPORTS_KEPT``, ADR 0253)
REPORTS_KEPT = 5


@dataclass(frozen=True, slots=True)
class Run:
    project: int
    objective: int
    #: "run" | "frame" (une séance de cadrage, ADR 0145) | "review" (une relecture indépendante, ADR 0276) | "share"
    #: | "need" | "plan" (dire son plan) | "stalled" (dire qu'il s'est arrêté : ADR 0143)
    purpose: str
    reported: bool = False
    #: son départ, et la dernière exécution d'avant (du projet, de l'objectif) : ce qu'un crédit rendu restaure
    started: int = 0
    previous: int = 0
    previous_objective: int = 0
    #: un récit, une demande d'aide : l'adresse à qui elle parle
    address: str = ""
    #: ce qui a déclenché l'objectif qu'elle vise (ADR 0265) : ses causes en attente à son départ, qu'elle a sous les
    #: yeux — rendues à l'objectif si elle n'a pas eu lieu
    stirred: tuple[Stir, ...] = ()
    stirred_at: int = 0
    stirred_more: int = 0
    #: une relecture indépendante (ADR 0276) : le commit qu'elle relit, épinglé à son départ
    reviewing: str = ""


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
    #: ce qui vient d'arriver et qu'un déclencheur attend, pas encore jugé (ADR 0265), du plus ancien au plus récent
    heard: tuple[Heard, ...] = ()


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
#: v12 : la mémoire de travail de chaque objectif — ses comptes rendus et ses notes à lui (ADR 0253).
#: v13 : les liens de lecture entre projets — ce qu'il lit, ce que son plan demande à lire, le niveau et les sujets
#:     que ses lectures lui laissent (``reads``, ``plan_reads``, ``read_level``, ``read_about`` : ADR 0257).
#: v14 : les sujets venus de ses lectures ne rejoignent plus ``about`` — ils restent dans ``read_about``, que seul
#:     l'oubli lit (ADR 0262) ; un état d'avant, où ils y étaient fondus, se reconstruit du journal.
#: v15 : les déclencheurs d'un objectif (ADR 0265) — ce qui le rend dû en plus de sa cadence (``on``,
#:     ``only_on_event``), ses causes en attente (``stirred``, ``stirred_at``, ``stirred_more``), celles qu'une
#:     exécution a sous les yeux (``Run.stirred``), et ce qui vient d'arriver sans être encore jugé (``heard``).
#: v16 : son registre (ADR 0268) — ses listes, ses comptes par liste et par statut, le compteur de ses tickets, ses
#:     tickets ouverts et ses derniers éléments touchés (``Project.board``) ; le reste est dans la projection.
#: v17 : le parcours d'un ticket (ADR 0270) — ses faits de plus (``Item``), l'objectif né d'un ticket
#:     (``Objective.ticket``, ``brief_ref``), la validation et la borne réglées par projet.
#: v18 : les demandes d'un projet à un autre (ADR 0271) — celles qu'il suit (``Project.asks``), les liens où elles
#:     entrent directement (``direct``).
#: v19 : la relecture du registre (ADR 0272) — le niveau d'un élément et le fait qu'il a dépassé sa borne
#:     (``Item.level``, ``outgrown``), les sujets d'une demande versés dans ``read_about`` du projet visé, l'objectif
#:     qui a attendu ses tickets (``Project.triage``), le numéro d'un ticket redit par ses changements.
#: v20 : les jalons (ADR 0273) — ceux d'un objectif ponctuel et son compte d'exécutions sans jalon atteint
#:     (``Objective.milestones``, ``milestone_seq``, ``stale``), la liste de passage d'un constant (``routine_ref``).
#: v23 : la relecture indépendante (ADR 0276) — le réglage du projet (``Project.reread``), le commit qu'un objectif
#:     laisse et d'où part son diff (``Objective.commit``, ``since``), la relecture demandée, son verdict et ses
#:     refus d'affilée (``review_due``, ``review_tries``, ``reviewed``, ``review_ok``, ``review_refused``…).
#: v24 : la forme ne change pas, ce que les réducteurs en font si (ADR 0277) — une fusion clôt un ponctuel rouvert,
#:     une fusion redite lève « à envoyer » : un état gardé d'avant se reconstruit du journal.
#: v25 : la seconde relecture des jalons, des pull requests et des issues (ADR 0278) — un jalon d'un plan validé
#:     (``Milestone.agreed``) et ce qu'elle ne défait plus en exécution, le compte des exécutions sans jalon atteint
#:     qui ne repart plus à une nouvelle pose, un échec de la CI compté une fois par commit
#:     (``Objective.checks_failed_sha``), le repère des commentaires de l'hôte et la borne par jour de ses tickets
#:     (``Project.remarks_ids``, ``hosted_since``, ``hosted_count``).
#: v26 : ce que le banc de la chaîne a montré (ADR 0280) — la base d'un projet telle qu'on l'a sue, et si elle est à
#:     relire (``Project.base_commit``, ``base_unread``) : un lecteur s'éveille quand elle avance, plus au commit d'une
#:     branche de travail ; une pull request que l'hôte dit impossible à fusionner (``Objective.pull_conflicts``) ; un
#:     constant dont le premier passage vient tout de suite (``Objective.at_once``) ; un objectif déjà travaillé
#:     avant d'être rouvert (``Objective.worked``).
#: v28 : sa documentation (ADR 0289) — ses pages et ses images (``Project.docs``).
#: v29 : ce qu'un lien garde (ADR 0293) — depuis quand il est posé et le mot de son propriétaire (``Project.ties``).
PROJECTS = Faculty("projects", state=ProjectsState, init=lambda p: ProjectsState(), params=ProjectsParams,
                   state_version=29, retired_params=("wrap_up_after",))
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
    #: les personnes des projets qu'il lit, ou a lus (ADR 0262) : pour l'oubli seulement, jamais « de qui ça parle »
    #: — comme sur chaque événement d'un projet qui garde un texte (``INHERITED``, ``subjects_of``)
    read_about: tuple[str, ...] = ()
    #: un constant : ce qui le déclenche en plus de sa cadence (``triggers.py``), et s'il n'a aucune cadence (ADR
    #: 0265)
    on: tuple[str, ...] = ()
    only_on_event: bool = False
    #: né du plan validé d'un ticket (ADR 0270) : le numéro du ticket, et sa consigne (le commentaire de la
    #: validation)
    ticket: int = 0
    brief: Content | None = None
    #: un constant : ce que chaque passage doit faire, une ligne par chose (ADR 0273)
    routine: Content | None = None
    #: un constant : son premier passage vient tout de suite, pas une cadence après (ADR 0280)
    at_once: bool = False


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
    read_about: tuple[str, ...] = ()
    #: ce qui le déclenche, et s'il n'a aucune cadence (ADR 0265) ; ``None`` : inchangés
    on: tuple[str, ...] | None = None
    only_on_event: bool | None = None
    #: sa consigne revue (ADR 0270 : le plan d'un ticket validé une seconde fois)
    brief: Content | None = None
    #: sa liste de passage revue, ou retirée (ADR 0273)
    routine: Content | None = None
    routine_cleared: bool = False
    #: son premier passage vient tout de suite, ou non (ADR 0280) ; ``None`` : inchangé
    at_once: bool | None = None


class MilestoneAdded(Payload):
    """Un jalon posé sur un objectif ponctuel (ADR 0273) : par son plan, par l'exécution qui l'affine, par le plan
    validé d'un ticket, ou par le propriétaire dans la console."""

    project: int
    objective: int
    milestone: int
    text: Content
    #: comment il se vérifie (``c.CHECKS``) ; une commande : ses arguments (un contenu : une liste JSON) ; un élément
    #: du registre : sa liste, sa clé (ou le numéro d'un ticket), le statut attendu
    check: str = c.CHECK_PROSE
    command: Content | None = None
    item_list: str = ""
    item_key: str = ""
    item_status: str = ""
    #: ``operator`` | ``owner`` | ``self``
    author: str = "self"
    by: str = ""
    #: posé par un plan qu'une personne vient de valider (le plan d'un ticket, ADR 0278) : il est à cette personne
    agreed: bool = False
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class MilestoneChanged(Payload):
    """Ce qui arrive à un jalon (ADR 0273) : révisé (son texte, sa vérification — ``None`` : inchangés), dit prêt
    (un point d'arrêt : il attend le propriétaire), refusé par lui, atteint, retiré. ``how`` : comment elle dit l'avoir
    rempli ; ``proof`` : sa preuve, un fait arrivé et borné (le résumé de ce que sa commande a rendu, le statut de
    son élément à ce moment-là) — jamais un état recalculé ; ``reason`` : la raison d'une révision, d'un retrait,
    d'un refus, ou le mot de qui le valide ; ``commit`` : le commit de l'atelier à ce moment-là."""

    project: int
    objective: int
    milestone: int
    text: Content | None = None
    check: str | None = None
    command: Content | None = None
    item_list: str | None = None
    item_key: str | None = None
    item_status: str | None = None
    #: ``c.REACHED`` ou ``c.DROPPED`` (``None`` : inchangé) — un jalon atteint ne se défait pas
    status: str | None = None
    ready: bool = False
    refused: bool = False
    how: Content | None = None
    proof: Content | None = None
    reason: Content | None = None
    commit: str = ""
    #: qui l'écrit : ``self`` (elle, pendant une exécution), ``owner`` (une personne en conversation : ``by``),
    #: ``operator`` (la console)
    author: str = "self"
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


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
    read_about: tuple[str, ...] = ()


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
    #: son flux (ADR 0274) : décidé par qui règle son dépôt distant (l'hôte sait-il ouvrir une pull request ?)
    flow: str | None = None
    #: la sensibilité ne fait que monter (fixer « pour qui » la relève : ce qui s'y écrit parle de quelqu'un)
    sensitivity: int | None = None
    #: la validation du plan d'un ticket, la borne d'un petit ticket et ses fichiers protégés (ADR 0270)
    ticket_review: str | None = None
    small_files: int | None = None
    small_lines: int | None = None
    protected: tuple[str, ...] | None = None
    #: le reflet de ses tickets en issues chez l'hôte (ADR 0275 ; ``c.ISSUES``)
    issues: str | None = None
    #: quand une exécution indépendante relit son travail conclu (ADR 0276 ; ``c.REREADS``)
    reread: str | None = None
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


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
    #: l'objectif que visait l'exécution qui l'a écrite (0 : aucun) — il la garde parmi les siennes (ADR 0253)
    objective: int = 0
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


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
    read_about: tuple[str, ...] = ()


class AccessSet(Payload):
    """Ses lignes d'accès, réglées d'un coup par un opérateur (ADR 0133) : tout le tableau, dans son ordre, et la ligne
    par défaut."""

    project: int
    rows: tuple[c.ProjectAccess, ...] = ()
    default: c.ProjectAccess = c.CLOSED
    by: str = ""


class LinksSet(Payload):
    """Ce qu'un projet lit, réglé d'un coup par son propriétaire (ADR 0257) : toute la liste, dans son ordre — les
    numéros des projets lus. Ce que chaque lien donne n'est pas ici : il se relit dans les lignes d'accès du projet
    lu."""

    project: int
    reads: tuple[int, ...] = ()
    by: str = ""
    #: parmi eux, ceux à qui ses demandes arrivent directement, sans l'accord de leur propriétaire (ADR 0271) ;
    #: ``None`` : inchangé (un lien posé par un plan, par ``create_project``)
    direct: tuple[int, ...] | None = None
    #: le mot de son propriétaire sur un de ces liens (ADR 0293) — pourquoi ce projet lit le projet ``why_for`` : un
    #: texte gardé, avec ses sujets (ceux du projet, et ceux du projet lu dans ``read_about``). ``None`` : rien n'est
    #: dit, le mot d'avant reste
    why: Content | None = None
    why_for: int = 0
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class Stirred(Payload):
    """Une nouvelle entendue, jugée (ADR 0265) : ce qui est arrivé ailleurs — un commit ou un objectif abouti d'un
    projet lu, le signal d'une app — éveille des objectifs, ou aucun (un lien qui ne donne plus rien, une app d'un
    autre projet). Un fait arrivé, écrit par le processus qui a lu les droits au moment où c'est arrivé : ce qu'est
    la nouvelle (son déclencheur, son instant, son détail) reste dans l'état, où le réducteur l'a notée."""

    #: l'événement entendu (son numéro dans le journal) : jugé, il quitte la file
    news: int
    #: le déclencheur jugé (ADR 0271) : un même événement peut en porter deux — un ticket fermé éveille ``item:tickets``
    #: chez lui et la demande de qui l'a ouvert. Vide (un journal d'avant) : le seul que porte cet événement
    key: str = ""
    #: les objectifs qu'il éveille : (projet, objectif)
    targets: tuple[tuple[int, int], ...] = ()


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
    read_about: tuple[str, ...] = ()


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
    #: les projets que ce plan demande à lire (ADR 0257) : posés quand son propriétaire le valide
    reads: tuple[int, ...] = ()
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class PlanAnswered(Payload):
    """La réponse de qui a demandé le projet (ou d'un opérateur) à son plan : ``approve`` (il le lance) ou ``revise``
    (elle le reprend, ses mots sous les yeux)."""

    project: int
    verdict: str
    words: Content | None = None
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class Deposited(Payload):
    project: int
    name: str
    size: int = 0
    note: Content | None = None
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class NetworkQueued(Payload):
    """Une commande réseau qu'elle propose sur un projet sans accord : elle partira à la fin de l'exécution, pas
    pendant (elle ne dispute pas l'atelier à son propre travail)."""

    project: int
    argv: tuple[str, ...]
    why: Content
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class Answered(Payload):
    """La personne à qui elle a dit son besoin (« j'ai besoin de toi pour… ») a écrit depuis : l'objectif n'attend
    plus, l'exécution suivante a sa réponse sous les yeux."""

    project: int
    objective: int
    person: str
    owner: str | None = None
    about: tuple[str, ...] = ()


class PullSeen(Payload):
    """Ce que l'hôte dit de la pull request d'un objectif, lu à un instant (ADR 0274) : un fait arrivé, daté — pas
    un état qu'on recalcule. ``said`` : ce qu'il en dit (une relecture, un commentaire), le texte d'un inconnu —
    précédé du nom de son compte là-bas, dans le même contenu : l'oubli efface l'un avec l'autre."""

    project: int
    objective: int
    #: son numéro chez l'hôte, la branche qu'elle porte, son état (``PULL_STATES``) et si sa relecture demande des
    #: changements
    number: int = 0
    branch: str = ""
    state: str = ""
    changes: bool = False
    #: quand la relecture qui demande des changements a été rendue chez l'hôte (µs ; 0 : il ne le dit pas)
    review_at: int = 0
    said: Content | None = None
    #: quand l'hôte dit l'avoir mise à jour (µs ; 0 : il ne le dit pas)
    updated: int = 0
    #: l'hôte la dit impossible à fusionner — sa branche est en conflit avec la base —, ou fusionnable (ADR 0280) ;
    #: ``None`` : il ne le dit pas (ou pas encore) — ce qu'on en savait reste
    conflicts: bool | None = None
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class MergeAsked(Payload):
    """Une personne demande la fusion de la pull request d'un objectif (ADR 0288) : le propriétaire du projet, ou
    qui s'occupe d'elle — jamais elle. Ce qu'elle a vu : son numéro, sa branche, et le commit à son bout ; la
    fusion n'a lieu que s'il n'a pas bougé. Aucun texte."""

    project: int
    objective: int
    number: int
    branch: str = ""
    sha: str = ""
    #: qui le demande (sa personne)
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class MergeAnswered(Payload):
    """Ce que l'hôte a répondu à une fusion demandée (ADR 0288) : fusionnée — et le commit qu'il a posé sur la
    base —, ou pourquoi non (``why`` : un code, ``MERGE_WHYS`` du port, ``MERGE_STALE`` ou ``MERGE_CUT``). Un fait
    arrivé ; il ne clôt rien : la fusion s'apprend à la relecture de l'hôte."""

    project: int
    objective: int
    number: int = 0
    merged: bool = False
    commit: str = ""
    why: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class BaseSeen(Payload):
    """Le commit au bout de la branche de base d'un atelier, lu après une récupération aboutie (ADR 0280) : un fait
    arrivé — ce que l'atelier avait à cet instant —, pas un état qu'on recalcule. ``commit`` vide : la base ne se
    lisait pas."""

    project: int
    commit: str = ""


class ChecksSeen(Payload):
    """Ce que l'hôte dit des vérifications du commit d'une pull request, lu à un instant (ADR 0275) : un fait
    arrivé, daté. ``said`` : d'un échec, les vérifications qui ont échoué et la fin du journal — le texte d'un
    inconnu, borné, que l'oubli atteint."""

    project: int
    objective: int
    sha: str = ""
    #: ``CHECKS_STATES`` du port
    state: str = ""
    said: Content | None = None
    #: quand l'hôte dit la dernière achevée (µs ; 0 : il ne le dit pas)
    updated: int = 0
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class ReviewAsked(Payload):
    """Une relecture indépendante est demandée pour le commit que porte le travail conclu d'un objectif (ADR 0276) :
    ce commit-là, et aucun autre."""

    project: int
    objective: int
    sha: str
    owner: str | None = None
    about: tuple[str, ...] = ()


class Reviewed(Payload):
    """Le verdict d'une relecture indépendante (ADR 0276), posé sur un objectif pour un commit : « bon », ou ses
    constats — cinq au plus, chacun avec où et quoi : le dire d'une autre exécution, un contenu effaçable au niveau
    de ce qui s'écrit sur cet objectif, avec ses sujets. ``by`` : le fournisseur de modèle qui a relu."""

    project: int
    objective: int
    sha: str
    good: bool = False
    findings: Content | None = None
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class IssueAsked(Payload):
    """Quelqu'un demande de publier un ticket en issue, ou une note de son fil (ADR 0275) : elle, pendant une
    exécution, ou une personne depuis la console. Aucun texte : des numéros — ce qui partira se compose à l'aperçu."""

    project: int
    ticket: int
    #: ``MOVE_PUBLISH`` ou ``MOVE_NOTE`` (et alors ``note`` : l'événement qui porte la note)
    what: str = MOVE_PUBLISH
    note: int = 0
    #: qui le demande (``self``, ``operator``, ``person``) et sa personne
    author: str = c.BY_SELF
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class RemoteRequested(Payload):
    """L'opérateur demande de pousser (``push``) ou de récupérer (``pull``) maintenant."""

    project: int
    #: ``push`` | ``pull``
    what: str = "push"
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


#: les sujets de chaque événement d'un projet qui garde un texte : pour qui il est, de qui il parle, qui l'a écrit — et,
#: à part, les personnes des projets qu'il lit (``read_about``, ADR 0262), que seul l'oubli lit
INHERITED = "read_about"
OBJECTIVE_ADDED = PROJECTS.event("objective_added", ObjectiveAdded,
                                 content=("text", "done_when", "brief", "routine"),
                                 subjects=("owner", "about", "by", INHERITED))
OBJECTIVE_CHANGED = PROJECTS.event("objective_changed", ObjectiveChanged,
                                   content=("text", "note", "done_when", "brief", "routine"),
                                   subjects=("owner", "about", "by", INHERITED))
MILESTONE_ADDED = PROJECTS.event("milestone_added", MilestoneAdded, content=("text", "command"),
                                 subjects=("owner", "about", "by", INHERITED))
MILESTONE_CHANGED = PROJECTS.event("milestone_changed", MilestoneChanged,
                                   content=("text", "command", "how", "proof", "reason"),
                                   subjects=("owner", "about", "by", INHERITED))
DECIDED = PROJECTS.event("decided", Decided, content=("title", "choice", "context", "options", "reason"),
                         subjects=("owner", "about", "by", INHERITED))
DECISION_CHANGED = PROJECTS.event("decision_changed", DecisionChanged, subjects=("owner", "about"))
REFRAMED = PROJECTS.event("reframed", Reframed, content=("title", "description"),
                          subjects=("owner", "about", "by", INHERITED))
PAUSED = PROJECTS.event("paused", StateChanged, subjects=("owner", "about"))
RESUMED = PROJECTS.event("resumed", StateChanged, subjects=("owner", "about"))
ARCHIVED = PROJECTS.event("archived", StateChanged, subjects=("owner", "about"))
RESTORED = PROJECTS.event("restored", StateChanged, subjects=("owner", "about"))
NUDGED = PROJECTS.event("nudged", Nudged, subjects=("owner", "about"))
NOTED = PROJECTS.event("noted", Noted, content=("text",), subjects=("owner", "about", INHERITED))
AMENDED = PROJECTS.event("amended", Amended, content=("instruction", "words"),
                         subjects=("owner", "about", "by", INHERITED))
PLAN_PROPOSED = PROJECTS.event("plan_proposed", PlanProposed, content=("plan", "questions"),
                               subjects=("owner", "about", INHERITED))
PLAN_ANSWERED = PROJECTS.event("plan_answered", PlanAnswered, content=("words",),
                               subjects=("owner", "about", "by", INHERITED))
DEPOSITED = PROJECTS.event("deposited", Deposited, content=("note",), subjects=("owner", "about", "by", INHERITED))
REMOTE_REQUESTED = PROJECTS.event("remote_requested", RemoteRequested, subjects=("owner", "about"))
PULL_SEEN = PROJECTS.event("pull_seen", PullSeen, content=("said",), subjects=("owner", "about", INHERITED))
CHECKS_SEEN = PROJECTS.event("checks_seen", ChecksSeen, content=("said",), subjects=("owner", "about", INHERITED))
BASE_SEEN = PROJECTS.event("base_seen", BaseSeen)
MERGE_ASKED = PROJECTS.event("merge_asked", MergeAsked, subjects=("owner", "about", "by"))
MERGE_ANSWERED = PROJECTS.event("merge_answered", MergeAnswered, subjects=("owner", "about"))
ISSUE_ASKED = PROJECTS.event("issue_asked", IssueAsked, subjects=("owner", "about", "by", INHERITED))
REVIEW_ASKED = PROJECTS.event("review_asked", ReviewAsked, subjects=("owner", "about"))
REVIEWED = PROJECTS.event("reviewed", Reviewed, content=("findings",), subjects=("owner", "about", INHERITED))
NETWORK_QUEUED = PROJECTS.event("network_queued", NetworkQueued, content=("why",),
                                subjects=("owner", "about", INHERITED))
ANSWERED = PROJECTS.event("answered", Answered, subjects=("owner", "about", "person"))
ACCESS_SET = PROJECTS.event("access_set", AccessSet, subjects=("by",))
LINKS_SET = PROJECTS.event("links_set", LinksSet, content=("why",), subjects=("owner", "about", "by", INHERITED))
STIRRED = PROJECTS.event("stirred", Stirred)
STEER_ASKED = PROJECTS.event("steer_asked", SteerAsked, content=("text",),
                             subjects=("owner", "about", "by", INHERITED))
#: ce qu'un opérateur (ou elle) fait d'un projet — la chronologie du carnet
OPERATIONS = (REFRAMED, PAUSED, RESUMED, ARCHIVED, RESTORED, NUDGED, OBJECTIVE_ADDED, OBJECTIVE_CHANGED,
              DECISION_CHANGED, DEPOSITED, REMOTE_REQUESTED, PLAN_PROPOSED, PLAN_ANSWERED, MILESTONE_ADDED,
              MILESTONE_CHANGED)


def opened(*, title: str, description: str, authority: str, mode: str, owner: str | None, address: str | None,
           about: tuple[str, ...], level: int, source: str, schedule_rule: str = "", approval: bool = True,
           priority: str = c.NORMAL, bundles: tuple[str, ...] = DEFAULT_BUNDLES, days: str = c.EVERY_DAY,
           start_min: int = 0, end_min: int = 24 * 60, runs_per_day: int = 0, remote: str = "",
           branch: str = "main", auto_push: bool = False, request: str = "", asked_by: str | None = None,
           flow: str = c.FLOW_DIRECT, reread: str = c.REREAD_OUT,
           framing: bool = False) -> Draft[Any]:
    """L'ouverture d'un projet (par une propriétaire, un opérateur, ou elle) ; né en conversation, il garde les mots
    de qui l'a demandé et naît à cadrer (ADR 0145)."""
    return c.PROJECT_CREATED.draft(
        title=Content.of(title.strip(), level=level),
        description=Content.of(description.strip(), level=level) if description.strip() else None,
        authority=authority, mode=mode, owner=owner, address=address, about=about, bundles=bundles,
        schedule=schedule_rule.strip(), days=days, start_min=start_min, end_min=end_min, runs_per_day=runs_per_day,
        approval=approval, priority=priority, remote=remote.strip(), branch=branch.strip() or "main",
        auto_push=auto_push, flow=flow if flow in c.FLOWS and remote.strip() else c.FLOW_DIRECT,
        reread=reread if reread in c.REREADS else c.REREAD_OUT, source=source, sensitivity=level,
        request=Content.of(request, level=level) if request.strip() else None, asked_by=asked_by, framing=framing)


class Constant(NamedTuple):
    """Un constant tel qu'on le donne à la création d'un projet : son texte, sa cadence en µs (0 : celle par
    défaut), ce qui le déclenche — des déclencheurs déjà vérifiés (``triggers.checked``) —, s'il n'a aucune
    cadence (ADR 0265), et si son premier passage vient tout de suite (ADR 0280)."""

    text: str
    cadence_us: int = 0
    on: tuple[str, ...] = ()
    only_on_event: bool = False
    at_once: bool = False


def objectives_of(project: int, lines: list[str], constants: list[str | tuple[Any, ...]], *, author: str,
                  by: str = "", owner: str | None, about: tuple[str, ...], level: int,
                  cadence_us: int = 0) -> list[Draft[Any]]:
    """Les objectifs d'un projet qui vient d'être créé : les ponctuels, puis les constants — un texte, ou un texte
    avec sa cadence en µs (0 : celle par défaut) et ce qui le déclenche (``Constant``) ; chacun à sa cadence, sinon à
    ``cadence_us`` (0 : celle des réglages)."""
    out: list[Draft[Any]] = []
    rows = [(c.ONCE, Constant(t)) for t in lines] + [
        (c.CONSTANT, Constant(x) if isinstance(x, str) else Constant(*x)) for x in constants]
    for i, (kind, k) in enumerate(((kind, k) for kind, k in rows if k.text.strip()), start=1):
        every = (k.cadence_us or cadence_us) if kind == c.CONSTANT else 0
        out.append(OBJECTIVE_ADDED.draft(project=project, objective=i, text=Content.of(k.text.strip()[:500], level=level),
                                         kind=kind, cadence_us=every, author=author, by=by, owner=owner, about=about,
                                         on=tuple(k.on), only_on_event=k.only_on_event,
                                         at_once=k.at_once and kind == c.CONSTANT))
    return out


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


def milestone_at(o: Objective, key: int | str | None) -> Milestone | None:
    raw = str(key if key is not None else "").strip().lstrip("#")
    return next((m for m in o.milestones if str(m.id) == raw), None) if raw.isdigit() else None


def milestones_of(o: Objective | None) -> tuple[Milestone, ...]:
    """Les jalons qui comptent pour cet objectif (ADR 0273) : ceux d'un ponctuel, sans les retirés. Un constant
    n'en a pas — devenu constant, ceux qu'il avait ne valent plus."""
    if o is None or o.kind != c.ONCE:
        return ()
    return tuple(m for m in o.milestones if m.status != c.DROPPED)


def open_milestones(o: Objective | None) -> tuple[Milestone, ...]:
    """Ses jalons encore ouverts — ni atteints, ni retirés : tant qu'il en reste, « fait » ne s'écrit pas."""
    return tuple(m for m in milestones_of(o) if m.status == c.OPEN)


def awaiting(o: Objective | None) -> Milestone | None:
    """Le point d'arrêt qu'elle a dit prêt et que le propriétaire n'a pas encore tranché : l'objectif attend, la
    main est à lui."""
    return next((m for m in open_milestones(o) if m.ready_at), None)


def waiting_in(p: Project) -> list[tuple[Objective, Milestone]]:
    """Les points d'arrêt de ce projet qui attendent le propriétaire : (objectif, jalon)."""
    return [(o, m) for o in p.objectives if o.status == c.OPEN and (m := awaiting(o)) is not None]


def next_milestone(o: Objective | None) -> Milestone | None:
    """Le jalon qui vient : le premier encore ouvert qui n'attend pas le propriétaire."""
    return next((m for m in open_milestones(o) if not m.ready_at), None)


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
    de l'atelier) : elle y voit toute sa mémoire, ce qui en sort est au moins personnel — et au moins du niveau de ce
    qu'écrivent les projets qu'il lit, ou a lus (``read_level``, ADR 0257)."""
    return max(p.sensitivity, int(Sensitivity.PERSONAL), p.read_level)


def subjects_of(p: Project, *more: str | None) -> tuple[str, ...]:
    """Toutes les personnes que l'oubli doit atteindre dans un texte de ce projet : pour qui il est, de qui il
    parle, celles des projets qu'il lit ou a lus (``read_about``), et ``more`` (qui le demande). C'est ce que porte
    le résumé d'une proposition d'effet (``EffectProposed.about`` : l'oubli seulement) et ce que ses lecteurs
    héritent de lui. **Jamais une audience** : qui entend un projet se lit dans ``about`` seul (ADR 0262)."""
    return tuple(dict.fromkeys(x for x in (*more, p.owner, *p.about, *p.read_about) if x))


def ticket_held(p: Project, o: Objective | None) -> Item | None:
    """Le ticket dont cet objectif est né (ADR 0270), s'il est encore sous la main de l'état — un ticket ouvert y
    est toujours."""
    if o is None or not o.ticket:
        return None
    return next((x for x in p.board.items if x.list_name == c.TICKETS and x.number == o.ticket), None)


def written_on(p: Project, item: Item | None) -> int:
    """Le niveau de ce qui s'écrit sur un élément de son registre (ADR 0272) : celui de ce qu'écrit le projet, et au
    moins celui de l'élément — une demande venue d'un projet qui lit plus confidentiel garde son niveau dans tout ce
    que le projet visé en écrit ensuite."""
    return max(written(p), item.level if item is not None else 0)


def inherited_on(p: Project, item: Item | None) -> tuple[str, ...]:
    """Les personnes que l'oubli doit atteindre dans ce qui s'écrit sur un élément, en plus de celles du projet
    (ADR 0272) : celles de ses lectures (``read_about`` — les personnes d'une demande y sont versées à sa naissance),
    qui l'a ouvert et qui y agit. Pour l'oubli seulement : jamais une audience (ADR 0262)."""
    more = (item.by, item.person) if item is not None else ()
    return tuple(dict.fromkeys(x for x in (*p.read_about, *more) if x))


def detail_level(p: Project) -> int:
    """Le niveau du détail d'un projet dit en conversation (son dernier compte rendu, ce qui vient) : ce qu'il
    écrit, et au moins le niveau des tickets que portent ses objectifs (ADR 0272) — le compte rendu d'un objectif né
    d'une demande plus confidentielle ne se dit pas à qui n'entend que le projet."""
    return max([written(p), *(x.level for x in p.board.items if x.objective)])


def written_for(p: Project, o: Objective | None) -> int:
    """Le niveau de ce que l'exécution d'un objectif écrit (son compte rendu, son carnet, sa clôture) : pour un
    objectif né d'un ticket, au moins celui de ce ticket (ADR 0272)."""
    return written_on(p, ticket_held(p, o))


def inherited_for(p: Project, o: Objective | None) -> tuple[str, ...]:
    """Les sujets hérités de ce que l'exécution d'un objectif écrit : pour un objectif né d'un ticket, ceux de ce
    ticket avec (ADR 0272)."""
    return inherited_on(p, ticket_held(p, o))


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


#: les branches de travail d'un projet qui passe par des pull requests (ADR 0274) : une par objectif, et celle d'une
#: exécution qui n'en vise aucun
WORK_PREFIX = "work/"
LOOSE_BRANCH = f"{WORK_PREFIX}misc"


def writes_pulls(ports: Mapping[str, Any] | None, url: str) -> bool:
    """L'hôte de ce dépôt distant sait-il ouvrir une pull request (``RepoHost.writes``) ? Un hôte qui ne sait rien
    écrire n'a pas la méthode : non."""
    writes = getattr((ports or {}).get("repo_host"), "writes", None)
    return bool(url) and callable(writes) and bool(writes(url))


def default_flow(ports: Mapping[str, Any] | None, remote: str) -> str:
    """Le flux d'un projet dont on règle le dépôt distant (ADR 0274) : par pull request dès que son hôte sait en
    ouvrir une, direct sinon et sans distant. Décidé par qui écrit l'événement, jamais recalculé ensuite."""
    return c.FLOW_PR if writes_pulls(ports, remote) else c.FLOW_DIRECT


def by_pulls(p: Project) -> bool:
    """Ce projet passe-t-il par des pull requests (ADR 0274) ? Son flux le dit, et il lui faut un dépôt distant."""
    return p.flow == c.FLOW_PR and bool(p.remote)


def branch_of(o: Objective | None) -> str:
    """La branche de travail de ce que vise une exécution (ADR 0274) : celle de son objectif — un constant en change
    après chaque pull request fusionnée, son passage suivant repart de la base —, sinon celle des exécutions sans
    objectif. Jamais la base."""
    if o is None:
        return LOOSE_BRANCH
    return f"{WORK_PREFIX}objective-{o.id}" + (f"-{o.pulls_merged + 1}" if o.kind == c.CONSTANT else "")


def busy(s: ProjectsState, project: int) -> bool:
    return any(r.project == project and r.purpose == "run" for r in s.running.values())


def reaches(projects: Mapping[int, Project], start: int, goal: int) -> bool:
    """En suivant les liens de lecture depuis ``start``, arrive-t-on à ``goal`` ?"""
    seen: set[int] = set()
    todo = [start]
    while todo:
        pid = todo.pop()
        if pid == goal:
            return True
        p = projects.get(pid)
        if pid in seen or p is None:
            continue
        seen.add(pid)
        todo.extend(p.reads)
    return False


def linked(projects: Mapping[int, Project], reader: int, asked: Iterable[int]) -> tuple[int, ...]:
    """Ce qu'un projet lira de ce qu'on demande, dans son ordre (ADR 0257) : des projets qui existent, jamais
    lui-même, chacun une fois, ``LINKS_MAX`` au plus — et aucun qui le lit déjà, de près ou de loin : les liens ne
    forment jamais de boucle. C'est la règle du réducteur, qui reste total : ce qui ne tient pas est ignoré."""
    kept: list[int] = []
    for target in asked:
        if len(kept) >= LINKS_MAX:
            break
        if target == reader or target in kept or target not in projects or reaches(projects, target, reader):
            continue
        kept.append(target)
    return tuple(kept)


def readers_of(s: ProjectsState, project: int) -> tuple[Project, ...]:
    """Les projets qui lisent celui-ci, par numéro."""
    return tuple(p for p in sorted(s.projects.values(), key=lambda p: p.id) if project in p.reads)


def tie_of(p: Project, target: int) -> Tie:
    """Ce que le lien de ``p`` vers ``target`` garde (ADR 0293) : depuis quand, le mot de son propriétaire — rien
    (un lien sans date ni mot) s'il ne le lit pas."""
    return next((t for t in p.ties if t.target == target), Tie(target))


def declared(project: int, kind: str, on: Iterable[str]) -> tuple[str, ...]:
    """Ce qu'un objectif garde des déclencheurs qu'on lui donne (ADR 0265) : la règle du réducteur, qui reste total.
    Seul un constant en a ; ce qui ne se lit pas, ce qui dépasse ``TRIGGERS_MAX`` et le projet lui-même (son propre
    commit le relancerait sans fin) sont ignorés. Qu'un projet nommé soit lu ne se juge pas ici : un plan nomme un
    projet qu'il demande à lire avant que le lien soit posé, et rien ne déclenche hors d'un lien (``_stirred``)."""
    if kind != c.CONSTANT:
        return ()
    return tuple(k for k in triggers.kept(on) if triggers.refusal(k, project, ()) != triggers.ITSELF)


def stirring(p: Project, o: Objective, key: str) -> bool:
    """Ce déclencheur éveille-t-il cet objectif, là, maintenant ? Un constant ouvert d'un projet vivant, qui le
    déclare — et, entre projets, le long d'un lien de lecture posé. Ce que le lien **donne** ne se sait pas ici :
    c'est le processus qui écrit ``projects.stirred`` qui l'a relu (``tend.py``)."""
    return live(p) and o.kind == c.CONSTANT and o.status == c.OPEN and key in o.on \
        and not triggers.refusal(key, p.id, p.reads)


def listening(s: ProjectsState, key: str) -> bool:
    """Un objectif attend-il ce déclencheur, quelque part ?"""
    return any(stirring(p, o, key) for p in s.projects.values() for o in p.objectives)


def stir(o: Objective, cause: Stir) -> Objective:
    """L'objectif, une cause de plus en attente : ``STIRS_KEPT`` au plus (les plus récentes), l'instant de la
    première gardé à part."""
    causes = (*o.stirred, cause)
    over = max(0, len(causes) - STIRS_KEPT)
    return replace(o, stirred=causes[over:], stirred_at=o.stirred_at or cause.at, stirred_more=o.stirred_more + over)


def _unstirred(o: Objective) -> Objective:
    """L'objectif, sans plus aucune cause en attente."""
    return replace(o, stirred=(), stirred_at=0, stirred_more=0) if o.stirred or o.stirred_at or o.stirred_more else o


def wake_aim(p: Project, endpoint: str) -> Objective | None:
    """L'objectif que vise un réveil par API dans ce projet (ADR 0265) : le premier constant ouvert qui le déclare
    (``wake:<nom>``) ; aucun tant que le projet n'a pas de plan qui vaille."""
    if p.plan_state in (c.TO_FRAME, c.PROPOSED):
        return None
    wanted = triggers.wake_key(endpoint)
    return next((o for o in p.objectives if o.kind == c.CONSTANT and o.status == c.OPEN and wanted in o.on), None)


# ── Réducteurs ────────────────────────────────────────────────────────────


def with_project(s: ProjectsState, p: Project) -> ProjectsState:
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
        auto_push=d.auto_push, flow=d.flow if d.flow in c.FLOWS and d.remote else c.FLOW_DIRECT,
        reread=d.reread if d.reread in c.REREADS else c.REREAD_OUT,
        request_ref=d.request.ref or "" if d.request is not None else "", asked_by=d.asked_by,
        plan_state=c.TO_FRAME if d.framing else c.UNPLANNED,
    )
    return with_project(s, p)


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
    kind = d.kind if d.kind in c.OBJECTIVE_KINDS else c.ONCE
    on = declared(p.id, kind, d.on)
    o = Objective(id=oid, text_ref=d.text.ref, kind=kind,
                  cadence_us=max(0, d.cadence_us), author=d.author, at=e.at, app=d.app,
                  done_when_ref=d.done_when.ref or "" if d.done_when is not None else "",
                  after=d.after if d.after != oid else 0, rank=max(0, d.rank),
                  # sans rien qui le déclenche, « sur événement seulement » ne passerait jamais : ignoré
                  on=on, only_on_event=d.only_on_event and bool(on), at_once=d.at_once and kind == c.CONSTANT,
                  ticket=max(0, d.ticket),
                  brief_ref=d.brief.ref or "" if d.brief is not None else "",
                  routine_ref=d.routine.ref or "" if d.routine is not None and kind == c.CONSTANT else "")
    # un constant qui attend les tickets naît souvent après le ticket qui l'a fait naître : ce ticket, qui attend
    # qu'elle le traite — qui que ce soit qui l'ait ouvert (ADR 0280) —, est sa première cause (ADR 0272) : il
    # passera au rythme du projet, sans « lancer maintenant ». Une cause dans son propre projet : aucun droit à
    # relire (ADR 0265)
    key = triggers.item_key(c.TICKETS)
    unread = next((x for x in p.board.items if awaits_her(x)), None) if key in on else None
    if unread is not None:
        o = stir(o, Stir(e.at, key, f"#{unread.number}"))
    objectives = (*p.objectives, o)
    while len(objectives) > OBJECTIVES_HISTORY:  # l'histoire déborde : le plus ancien clos tombe
        oldest = next((x for x in objectives if x.status in (c.DONE, c.DROPPED)), None)
        if oldest is None:
            break
        objectives = tuple(x for x in objectives if x is not oldest)
    return with_project(s, replace(p, objectives=objectives, objective_seq=max(p.objective_seq, oid),
                           triage=_triage(p, oid, on)))


def awaits_her(item: Item) -> bool:
    """Ce ticket ouvert attend-il qu'elle le traite (ADR 0280) ? Non lu — un autre l'a ouvert —, ou en analyse —
    elle l'a pris, ou elle l'a ouvert elle-même : la main est à elle, et il n'a pas encore de plan. Un ticket
    proposé attend l'accord du propriétaire : rien avant."""
    return item.list_name == c.TICKETS and not item.closed and item.status in (c.STAGE_UNREAD, c.STAGE_ANALYSIS)


def _triage(p: Project, objective: int, on: tuple[str, ...]) -> int:
    """L'objectif qui a le premier attendu les tickets du projet (ADR 0272) : gardé pour toujours, même retiré."""
    return p.triage or (objective if triggers.item_key(c.TICKETS) in on else 0)


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
    # son premier passage tout de suite (ADR 0280) : un constant seulement
    at_once = (o.at_once if d.at_once is None else d.at_once) and changes.get("kind", o.kind) == c.CONSTANT
    if at_once != o.at_once:
        changes["at_once"] = at_once
    if d.note is not None and d.note.ref:
        changes["note_ref"] = d.note.ref
    if d.done_when is not None and d.done_when.ref:
        changes["done_when_ref"] = d.done_when.ref
    if d.brief is not None and d.brief.ref:
        changes["brief_ref"] = d.brief.ref
    if d.routine_cleared:
        changes["routine_ref"] = ""
    elif d.routine is not None and d.routine.ref:
        changes["routine_ref"] = d.routine.ref
    if d.after is not None:
        changes["after"] = d.after if d.after != o.id else 0
    if d.rank is not None:
        changes["rank"] = max(0, d.rank)
    if d.status in c.OBJECTIVE_STATUSES and d.status != o.status:
        changes["status"] = d.status
        if d.status == c.OPEN:  # rouvert : il repart de rien (ni dette, ni preuve, ni résultat d'avant)
            changes.update(silent=0, unproven=0, waiting_until=0, closed_at=0, runs=0, evidence=0, notable=0.0,
                           result_ref="", shared=False, share_attempts=0, need_ref="", asked=False, ask_attempts=0,
                           asked_at=0, asked_to="", answered_at=0, stale=0)
        else:
            changes["closed_at"] = e.at
            if d.status == c.DONE:  # coché par quelqu'un d'autre : ce n'est pas elle qui l'a mené à bout
                changes.update(shared=True, notable=0.0)
    changes.update(_retriggered(p, o, d, changes))
    if not changes:
        return s
    new = replace(o, **changes)
    return with_project(s, replace(_objective(p, new), triage=_triage(p, new.id, new.on)))


def _retriggered(p: Project, o: Objective, d: ObjectiveChanged, changes: Mapping[str, Any]) -> dict[str, Any]:
    """Ce qu'un changement fait des déclencheurs d'un objectif et de ses causes en attente (ADR 0265) : seul un
    constant en a ; « sur événement seulement » ne vaut qu'avec un déclencheur ; une cause dont le déclencheur n'est
    plus déclaré tombe, et toutes quand l'objectif n'est plus ouvert."""
    kind = changes.get("kind", o.kind)
    on = declared(p.id, kind, o.on if d.on is None else d.on)
    only = (o.only_on_event if d.only_on_event is None else d.only_on_event) and bool(on)
    out: dict[str, Any] = {}
    if on != o.on:
        out["on"] = on
    if only != o.only_on_event:
        out["only_on_event"] = only
    opened = changes.get("status", o.status) == c.OPEN
    causes = tuple(x for x in o.stirred if x.key in on) if opened else ()
    if causes != o.stirred:
        out.update(stirred=causes)
        if not causes:
            out.update(stirred_at=0, stirred_more=0)
    return out


@PROJECTS.reducer(MILESTONE_ADDED)
def _milestone_added(s: ProjectsState, e, cx) -> ProjectsState:
    """Un jalon de plus sur un objectif ponctuel encore vivant (ADR 0273), ``c.MILESTONES_MAX`` vivants au plus :
    au-delà, ignoré. Ses tout premiers jalons — il n'en a jamais eu — font repartir de zéro le compte des exécutions
    sans jalon atteint ; aucune autre pose (ADR 0278) : retirer ses jalons ouverts puis en poser d'autres ne remet
    pas ce compte à zéro."""
    d = e.data
    p = s.projects.get(d.project)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or o is None or o.kind != c.ONCE or o.status not in (c.OPEN, c.BLOCKED) or not d.text.ref:
        return s
    alive = milestones_of(o)
    if len(alive) >= c.MILESTONES_MAX:
        return s
    # deux ajouts du même numéro : le second prend le suivant ; un numéro déjà donné ne revient jamais
    number = d.milestone if d.milestone > o.milestone_seq else o.milestone_seq + 1
    check = d.check if d.check in c.CHECKS else c.CHECK_PROSE
    on_item = check == c.CHECK_ITEM
    m = Milestone(id=number, text_ref=d.text.ref, check=check,
                  command_ref=d.command.ref or "" if d.command is not None and check == c.CHECK_COMMAND else "",
                  item_list=d.item_list if on_item else "", item_key=d.item_key if on_item else "",
                  item_status=d.item_status if on_item else "", author=d.author, at=e.at, agreed=d.agreed)
    kept = (*o.milestones, m)
    while len(kept) > MILESTONES_KEPT:  # les retirés restent lisibles tant qu'il y a la place : le plus ancien tombe
        oldest = next(x for x in kept if x.status == c.DROPPED)
        kept = tuple(x for x in kept if x is not oldest)
    first = o.milestone_seq == 0  # jamais aucun jalon : la toute première pose
    return with_project(s, _objective(p, replace(o, milestones=kept, milestone_seq=number, stale=0 if first else o.stale)))


#: pourquoi, en exécution, un jalon n'est pas à elle seule (ADR 0278 ; les clés de
#: ``projects.tools.milestones.held``) : le propriétaire l'a refusé, c'est un point d'arrêt, un autre qu'elle l'a
#: posé, le plan qui l'a posé a été validé par une personne
HELD_REFUSED, HELD_BREAKPOINT, HELD_OTHER, HELD_AGREED = "refused", "breakpoint", "other", "agreed"


def milestone_held(m: Milestone) -> str:
    """Ce qui tient ce jalon hors de sa seule main en exécution (ADR 0278), ou ``""`` : il est à elle."""
    if m.refused_at:
        return HELD_REFUSED
    if m.check == c.CHECK_OWNER:
        return HELD_BREAKPOINT
    if m.author != "self":
        return HELD_OTHER
    return HELD_AGREED if m.agreed else ""


def milestone_guard(m: Milestone, d: MilestoneChanged) -> str:
    """Pourquoi ce geste ne vaut pas quand c'est elle qui l'écrit, en exécution (ADR 0278) — un code ``HELD_…`` —,
    ou ``""``. Pure : la règle que le réducteur applique (``milestone_stepped``) et que l'outil lit pour refuser
    en disant pourquoi.

    - Elle ne **retire** pas un jalon tenu (``milestone_held``) : posé par un autre, fixé par un plan qu'une
      personne a validé, point d'arrêt, ou refusé par le propriétaire.
    - Elle n'en **change pas la vérification** (sa sorte, sa commande, son élément) — sauf pour en donner une à un
      jalon à elle, fixé par un plan validé, qui n'avait que sa parole : affiner n'est pas affaiblir.
    - Elle n'en **réécrit le texte** que s'il est d'elle, et que personne ne l'a validé.

    Dire un jalon atteint, ou un point d'arrêt prêt, n'est pas le défaire : ce n'est pas jugé ici. Ce que font le
    propriétaire et l'opérateur non plus."""
    if d.author != "self" or d.status == c.REACHED or d.ready or d.refused:
        return ""
    why = milestone_held(m)
    if d.status == c.DROPPED:
        return why
    rechecks = any(x is not None for x in (d.check, d.command, d.item_list, d.item_key, d.item_status))
    firms = why == HELD_AGREED and m.check == c.CHECK_PROSE and d.check in c.CHECKS and d.check != c.CHECK_PROSE
    if rechecks and why and not firms:
        return why
    if d.text is not None and (m.author != "self" or m.agreed):
        return HELD_AGREED if m.author == "self" else HELD_OTHER
    return ""


def milestone_stepped(m: Milestone, d: MilestoneChanged, at: int) -> tuple[Milestone, bool] | None:
    """Ce qu'un changement fait d'un jalon encore ouvert, et s'il fait avancer l'objectif (ADR 0273) ; ``None`` :
    rien. Pure : la seule règle, que lisent le réducteur et ce qui veut savoir d'avance si un geste vaudra.

    - **retiré**, avec sa raison ; **atteint** — un point d'arrêt ne l'est que par un autre qu'elle, et seulement
      quand elle l'a dit prêt ;
    - **refusé** par le propriétaire : il est de nouveau à elle, la raison gardée ;
    - **dit prêt** (un point d'arrêt seulement) : il attend le propriétaire — une avancée ;
    - sinon **révisé** : son texte, sa vérification, sa raison gardée.

    Tant qu'il attend le propriétaire, elle n'y touche plus ; et en exécution elle ne défait pas un jalon qui
    n'est pas à elle seule (``milestone_guard``, ADR 0278)."""
    hers = d.author == "self"
    reason = d.reason.ref or "" if d.reason is not None else ""
    how = d.how.ref or "" if d.how is not None else ""
    if milestone_guard(m, d):
        return None
    if d.status == c.DROPPED:
        if m.ready_at and hers:
            return None
        return replace(m, status=c.DROPPED, ready_at=0, reason_ref=reason or m.reason_ref), False
    if d.status == c.REACHED:
        if m.check == c.CHECK_OWNER and (hers or not m.ready_at):
            return None
        return replace(m, status=c.REACHED, reached_at=at, reached_by=d.by or d.author, ready_at=0,
                       how_ref=how or m.how_ref, proof_ref=d.proof.ref or "" if d.proof is not None else "",
                       commit=d.commit or m.commit, reason_ref=reason or m.reason_ref), True
    if d.refused:
        if hers or not m.ready_at:
            return None
        return replace(m, ready_at=0, refused_at=at, reason_ref=reason or m.reason_ref), False
    if d.ready:
        if m.check != c.CHECK_OWNER or m.ready_at:
            return None
        return replace(m, ready_at=at, refused_at=0, how_ref=how or m.how_ref, commit=d.commit or m.commit), True
    if m.ready_at and hers:
        return None
    check = d.check if d.check in c.CHECKS else m.check
    on_item = check == c.CHECK_ITEM
    new = replace(
        m, text_ref=d.text.ref if d.text is not None and d.text.ref else m.text_ref, check=check,
        command_ref=(d.command.ref if d.command is not None and d.command.ref else m.command_ref)
        if check == c.CHECK_COMMAND else "",
        item_list=(m.item_list if d.item_list is None else d.item_list) if on_item else "",
        item_key=(m.item_key if d.item_key is None else d.item_key) if on_item else "",
        item_status=(m.item_status if d.item_status is None else d.item_status) if on_item else "")
    if new == m:
        return None
    return replace(new, ready_at=0, revised=m.revised + 1, reason_ref=reason or m.reason_ref), False


@PROJECTS.reducer(MILESTONE_CHANGED)
def _milestone_changed(s: ProjectsState, e, cx) -> ProjectsState:
    """Un jalon atteint ou retiré ne bouge plus : il ne se défait ni ne se révise. Un jalon atteint, ou un point
    d'arrêt dit prêt, remet à zéro le compte des exécutions sans jalon atteint."""
    d = e.data
    p = s.projects.get(d.project)
    o = objective_at(p, d.objective) if p is not None else None
    m = milestone_at(o, d.milestone) if o is not None else None
    if p is None or o is None or m is None or m.status != c.OPEN:
        return s
    got = milestone_stepped(m, d, e.at)
    if got is None:
        return s
    new, progressed = got
    return with_project(s, _objective(p, replace(o, milestones=tuple(new if x.id == m.id else x for x in o.milestones),
                                         stale=0 if progressed else o.stale)))


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
    return with_project(s, replace(p, decisions=decisions, decision_seq=max(p.decision_seq, did)))


@PROJECTS.reducer(DECISION_CHANGED)
def _decision_changed(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    x = decision_at(p, d.decision) if p is not None else None
    if p is None or x is None or d.status not in c.DECISION_STATUSES:
        return s
    new = replace(x, status=d.status, replaced_by=x.replaced_by if d.status == c.SUPERSEDED else 0)
    return with_project(s, replace(p, decisions=tuple(new if y.id == x.id else y for y in p.decisions)))


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
    if d.set_owner:  # « pour qui » change : ses sujets aussi ; ceux venus de ses lectures restent à part (ADR 0262)
        changes.update(owner=d.owner, about=tuple(d.about), address=d.address)
    if d.bundles is not None:
        changes["bundles"] = tuple(dict.fromkeys((*BASE_BUNDLES, *d.bundles)))
    for name in ("schedule", "remote", "branch", "auto_push", "approval"):
        value = getattr(d, name)
        if value is not None:
            changes[name] = value
    if d.flow in c.FLOWS:
        changes["flow"] = d.flow
    if not changes.get("remote", p.remote):  # sans dépôt distant, pas de pull request : le flux est direct
        changes["flow"] = c.FLOW_DIRECT
    if changes.get("flow") == p.flow:
        del changes["flow"]
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
    if d.ticket_review in c.REVIEWS:
        changes["ticket_review"] = d.ticket_review
    if d.small_files is not None:
        changes["small_files"] = max(0, min(SMALL_FILES_MAX, d.small_files))
    if d.small_lines is not None:
        changes["small_lines"] = max(0, min(SMALL_LINES_MAX, d.small_lines))
    if d.protected is not None:
        changes["protected"] = tuple(dict.fromkeys(
            x.strip()[:PROTECTED_CHARS] for x in d.protected if x.strip()))[:PROTECTED_MAX]
    if d.issues in c.ISSUES:
        changes["issues"] = d.issues
    if d.reread in c.REREADS:
        changes["reread"] = d.reread
    if not changes:
        return s
    s = with_project(s, replace(p, **changes))
    # son niveau ou ses sujets ont changé : ce qu'il laisse à ses lecteurs aussi
    return spread_confidentiality(s, p.id) if changes.keys() & {"owner", "about", "sensitivity"} else s


@PROJECTS.reducer(PAUSED)
def _paused(s: ProjectsState, e, cx) -> ProjectsState:
    p = s.projects.get(e.data.project)
    if p is None or p.status != c.ACTIVE:
        return s
    return with_project(s, replace(p, status=c.PAUSED, paused_at=e.at, pause_reason=e.data.reason[:300],
                           stalled_at=e.at if e.data.broke else 0, stall_asked=False, stall_attempts=0))


@PROJECTS.reducer(RESUMED)
def _resumed(s: ProjectsState, e, cx) -> ProjectsState:
    p = s.projects.get(e.data.project)
    if p is None or p.status != c.PAUSED:
        return s
    return with_project(s, replace(p, status=c.ACTIVE, paused_at=0, pause_reason="", failures=0, stalled_at=0,
                           frame_silent=0))


@PROJECTS.reducer(ARCHIVED)
def _archived(s: ProjectsState, e, cx) -> ProjectsState:
    p = s.projects.get(e.data.project)
    if p is None or p.status == c.ARCHIVED:
        return s
    # archivé, il ne pousse ni ne récupère plus rien : ses demandes en file tombent
    return with_project(s, replace(p, status=c.ARCHIVED, archived_at=e.at, pause_reason=e.data.reason[:300], requests=(),
                           network=()))


@PROJECTS.reducer(RESTORED)
def _restored(s: ProjectsState, e, cx) -> ProjectsState:
    p = s.projects.get(e.data.project)
    if p is None or p.status != c.ARCHIVED:
        return s
    # restauré, il repart en pause : on le relance quand on veut ; rien de ce qui attendait avant ne repart seul
    return with_project(s, replace(p, status=c.PAUSED, archived_at=0, paused_at=e.at, pause_reason="restauré", failures=0,
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
    return with_project(s, replace(p, nudged_at=e.at, nudged_objective=d.objective if o is not None else 0))


@PROJECTS.reducer(ACCESS_SET)
def _access_set(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None:
        return s
    return with_project(s, replace(p, access=tuple(d.rows), default_access=d.default))


def _carried(p: Project) -> tuple[int, tuple[str, ...]]:
    """Ce qu'un projet laisse à qui le lit (ADR 0257) : le niveau de ce qu'il écrit, et les personnes que l'oubli
    doit y atteindre — son propriétaire, ses sujets, et celles de ses propres lectures."""
    return written(p), subjects_of(p)


def _reading(reader: Project, level: int, subjects: tuple[str, ...]) -> Project:
    """Le lecteur, une fois qu'il lit un projet de ce niveau, qui parle de ces personnes : ce qu'il écrit ensuite
    prend au moins ce niveau, et l'oubli de l'une d'elles l'atteindra (``read_about``). De qui il parle, lui
    (``about``), ne change pas : lire un projet ne fait de personne un témoin du lecteur (ADR 0262)."""
    kept = tuple(dict.fromkeys((*reader.read_about, *subjects)))
    level = max(reader.read_level, level)
    if (kept, level) == (reader.read_about, reader.read_level):
        return reader
    return replace(reader, read_about=kept, read_level=level)


def spread_confidentiality(s: ProjectsState, source: int) -> ProjectsState:
    """La confidentialité suit le lien, de lecteur en lecteur : ce que ``source`` laisse à qui le lit passe à ses
    lecteurs, puis aux leurs. Rien ne redescend, donc la marche s'arrête : chaque pas relève un niveau borné ou
    ajoute, aux sujets hérités d'un lecteur, une personne déjà connue d'un projet."""
    todo = [source]
    while todo:
        p = s.projects.get(todo.pop())
        if p is None:
            continue
        level, subjects = _carried(p)
        for reader in readers_of(s, p.id):
            raised = _reading(reader, level, subjects)
            if raised is not reader:
                s = with_project(s, raised)
                todo.append(reader.id)
    return s


@PROJECTS.reducer(LINKS_SET)
def _links_set(s: ProjectsState, e, cx) -> ProjectsState:
    """Ce qu'il lit : la liste demandée, moins ce qui ne tient pas (``linked`` : un projet inconnu, lui-même, un
    doublon, au-delà de ``LINKS_MAX``, un lien qui fermerait une boucle). Un lien retiré ne reprend ni le niveau ni
    les sujets qu'il a laissés : ce qu'elle en a lu est déjà dans ses notes."""
    d = e.data
    p = s.projects.get(d.project)
    if p is None:
        return s
    p = replace(p, reads=linked(s.projects, p.id, d.reads))
    # le mode direct ne tient qu'à un lien posé (ADR 0271) : un lien retiré le perd
    wanted = p.direct if d.direct is None else d.direct
    p = replace(p, direct=tuple(target for target in dict.fromkeys(wanted) if target in p.reads))
    # ce que chaque lien garde (ADR 0293) : un lien qui reste garde sa date et son mot, un lien nouveau date de
    # maintenant, un lien retiré perd les siens ; le mot dit ici remplace celui du lien qu'il nomme
    before = {t.target: t for t in p.ties}
    ties = [before.get(target) or Tie(target, since=e.at) for target in p.reads]
    if d.why is not None and d.why.ref:
        ties = [replace(t, why_ref=d.why.ref) if t.target == d.why_for else t for t in ties]
    p = replace(p, ties=tuple(ties))
    for target in p.reads:
        p = _reading(p, *_carried(s.projects[target]))
    return spread_confidentiality(with_project(s, p), p.id)


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
    ref = e.data.text.ref
    p = replace(p, notes=(*p.notes, ref)[-NOTES_KEPT:])
    o = objective_at(p, e.data.objective) if e.data.objective else None
    if o is not None:  # l'objectif qu'elle visait la garde aussi : il la retrouvera à son prochain passage
        p = _objective(p, replace(o, notes=(*o.notes, ref)[-OBJECTIVE_NOTES_KEPT:]))
    return with_project(s, p)


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
    return with_project(s, p)


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
    # la main lui était revenue après des relectures refusées (ADR 0276) : il a répondu, elles repartent de zéro
    return replace(o, status=c.OPEN, closed_at=0, runs=0, silent=0, stale=0, waiting_until=0, result_ref="",
                   notable=0.0, steered_at=at if steered else o.steered_at,
                   answered_at=o.answered_at if steered else at, review_refused=(), review_tries=0)


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
    reads = tuple(dict.fromkeys(t for t in d.reads if t != p.id))[:LINKS_MAX]  # ce qu'il demande à lire (ADR 0257)
    return with_project(s, replace(p, plan_ref=d.plan.ref, questions_ref=p.questions_ref if kept else asked,
                           plan_answer_ref=p.plan_answer_ref if kept else "", plan_at=e.at, plan_reads=reads,
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
        # une personne valide ce plan : les jalons qu'il a posés sont à elle (ADR 0278) — en exécution, ils ne se
        # retirent plus, ne se réécrivent plus et ne s'affaiblissent plus
        agreed = tuple(replace(o, milestones=tuple(
            replace(m, agreed=True) if m.status == c.OPEN and m.author == "self" else m for m in o.milestones))
            if o.kind == c.ONCE and o.status in (c.OPEN, c.BLOCKED) and o.milestones else o for o in p.objectives)
        return with_project(s, replace(p, objectives=agreed, plan_state=c.PLANNED, plan_tell=False, plan_answer_ref=words))
    if words:
        p = replace(p, instructions=(*p.instructions, words)[-INSTRUCTIONS_KEPT:])
    if d.verdict == REVISE:
        return with_project(s, replace(p, plan_state=c.TO_FRAME, revise_at=e.at, plan_tell=False, frame_silent=0))
    return with_project(s, p)


@PROJECTS.reducer(DEPOSITED)
def _deposited(s: ProjectsState, e, cx) -> ProjectsState:
    d = e.data
    p = s.projects.get(d.project)
    if p is None:
        return s
    entry = (d.name, d.size, d.note.ref or "" if d.note is not None else "")
    return with_project(s, replace(p, deposits=(*p.deposits, entry)[-DEPOSITS_KEPT:]))


@PROJECTS.reducer(REMOTE_REQUESTED)
def _remote_requested(s: ProjectsState, e, cx) -> ProjectsState:
    p = s.projects.get(e.data.project)
    # un projet archivé ne pousse ni ne récupère : la demande tombe (elle ne repartira pas à la restauration)
    if p is None or e.data.what not in ("push", "pull") or p.status == c.ARCHIVED:
        return s
    return with_project(s, replace(p, requests=(*p.requests, (e.seq, e.data.what))[-4:]))


@PROJECTS.reducer(PULL_SEEN)
def _pull_seen(s: ProjectsState, e, cx) -> ProjectsState:
    """Ce que l'hôte dit de la pull request d'un objectif (ADR 0274). Fusionnée : l'objectif est clos pour de bon
    — un ponctuel rouvert entre-temps aussi (``_accepted``, ADR 0277) —, sa branche a fait son temps, et la base se
    récupère (une demande, que ``projects.remote`` propose). Fermée sans fusion, ou des changements demandés : un
    ponctuel abouti se rouvre, avec le mot de l'hôte sous les yeux de l'exécution qui vient. Impossible à fusionner
    (ADR 0280 : sa branche est en conflit avec la base) : elle n'est pas prête, et l'objectif se rouvre de même —
    une fois, quand l'hôte le dit pour la première fois ; il ne se rouvrira de nouveau qu'après que l'hôte l'a
    redite fusionnable. Total : un objectif inconnu, un état inconnu ne changent rien."""
    d = e.data
    p = s.projects.get(d.project)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or o is None or d.state not in PULL_STATES:
        return s
    if o.pull_state == PULL_MERGED and d.branch == o.branch:
        # déjà fusionnée, la même branche : rien ne se compte deux fois. Mais une fusion redite — sa branche,
        # reprise depuis, est entrée dans la base hors de sa vue — lève « à envoyer » : sans cela la passe la
        # redirait chaque minute, sans fin (ADR 0277)
        if d.state != PULL_MERGED or not (o.unsent or o.pull_tries):
            return s
        return with_project(s, _objective(p, _accepted(replace(o, unsent=False, pull_tries=0), e.at)))
    said = d.said.ref or "" if d.said is not None else ""
    changes = d.changes and d.state == PULL_OPEN
    # un refus ne compte qu'une fois : une fermeture qu'on n'avait pas vue, une relecture plus récente que la dernière
    # (après un nouvel envoi, l'hôte redit la même relecture tant que personne n'a relu : elle ne rouvre rien)
    # ce que l'hôte dit de sa fusion ne vaut que pour une pull request ouverte ; s'il n'en dit rien, ce qu'on en
    # savait reste — il le recalcule après chaque envoi, et « je ne sais pas encore » ne lève pas un conflit
    conflicts = d.state == PULL_OPEN and (o.pull_conflicts if d.conflicts is None else d.conflicts)
    back = (d.state == PULL_CLOSED and o.pull_state != PULL_CLOSED) or (changes and (
        d.review_at > o.pull_review_at if d.review_at else not o.pull_changes)) or (
        conflicts and not o.pull_conflicts)
    o = replace(o, pull=d.number or o.pull, pull_state=d.state, pull_changes=changes,
                pull_review_at=max(o.pull_review_at, d.review_at), pull_at=e.at,
                pull_said_ref=said or o.pull_said_ref)
    fresh = conflicts and not o.pull_conflicts  # ``o`` : tel qu'il était avant ce que l'hôte vient de dire
    o = replace(o, pull_conflicts=conflicts)
    if d.state == PULL_MERGED:
        # fusionnée : plus aucune demande de fusion n'attend, et un refus d'avant ne se dit plus (ADR 0288)
        o = _accepted(replace(o, unsent=False, pull_tries=0, pulls_merged=o.pulls_merged + 1, merge_asked_at=0,
                              merge_refused=""), e.at)
    elif back:
        o = _sent_back(o)
    if (d.state == PULL_MERGED or fresh) and p.remote and p.status != c.ARCHIVED:
        # la base se récupère avant l'exécution suivante : une demande, proposée sans accord (``tend.waiting``) —
        # après une fusion, et quand l'hôte dit la pull request en conflit (ADR 0280) : sa base a avancé, et
        # l'outil qui la ramène dans la branche de travail ne ramène que ce que l'atelier en a
        p = replace(p, requests=(*p.requests, (e.seq, BASE_REQUEST))[-4:])
    return with_project(s, _objective(p, o))


def _accepted(o: Objective, at: int) -> Objective:
    """Sa pull request est fusionnée : ce qui est accepté chez l'hôte est clos pour de bon (ADR 0274, 0277). Un
    ponctuel que l'hôte ou une relecture avait rouvert — ou qui bloquait — est clos : sans cela son ticket restait
    « en attente de PR », « fait » se refusait faute de nouveau commit, et ses exécutions tournaient jusqu'au
    blocage. Plus aucune relecture ne l'attend : celle qui était demandée tombe. Tout autre objectif ne bouge
    pas."""
    o = replace(o, review_due="", review_tries=0)
    if o.kind != c.ONCE or o.status not in (c.OPEN, c.BLOCKED):
        return o
    return replace(o, status=c.DONE, closed_at=at, waiting_until=0, need_ref="", asked=False, ask_attempts=0)


def _sent_back(o: Objective) -> Objective:
    """Un ponctuel abouti que l'hôte renvoie (sa pull request refusée, ses vérifications en échec) se rouvre : il
    repart sans dette ni preuve — conclure de nouveau demandera un nouveau travail. Tout autre objectif ne bouge
    pas."""
    if o.kind != c.ONCE or o.status != c.DONE:
        return o
    return replace(o, status=c.OPEN, closed_at=0, runs=0, silent=0, stale=0, unproven=0, evidence=0,
                   waiting_until=0, result_ref="", notable=0.0, shared=False)


#: pourquoi une fusion demandée n'a pas eu lieu, en plus de ce que dit l'hôte (``MERGE_WHYS`` du port) : la pull
#: request n'était plus celle que la personne avait vue quand la demande est partie ; la demande a été interrompue
#: sans qu'on sache si elle a eu lieu
MERGE_STALE, MERGE_CUT = "stale", "cut"


@PROJECTS.reducer(MERGE_ASKED)
def _merge_asked(s: ProjectsState, e, cx) -> ProjectsState:
    """Une personne a demandé la fusion (ADR 0288) : la demande attend la réponse de l'hôte, et le refus d'avant ne
    se dit plus. Total : un objectif inconnu ne change rien."""
    d = e.data
    p = s.projects.get(d.project)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or o is None:
        return s
    return with_project(s, _objective(p, replace(o, merge_asked_at=e.at, merge_by=d.by, merge_refused="")))


@PROJECTS.reducer(MERGE_ANSWERED)
def _merge_answered(s: ProjectsState, e, cx) -> ProjectsState:
    """L'hôte a répondu à la fusion demandée (ADR 0288) : plus rien n'attend ; refusée, l'objectif garde pourquoi.
    Fusionnée, rien ne se clôt ici — le processus qui relit l'hôte le verra, comme toute fusion. Total."""
    d = e.data
    p = s.projects.get(d.project)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or o is None:
        return s
    return with_project(s, _objective(p, replace(o, merge_asked_at=0, merge_answered_at=e.at,
                                         merge_refused="" if d.merged else (d.why or MERGE_CUT))))


def checks_pass(o: Objective) -> bool:
    """Les vérifications du commit de sa pull request la laissent-elles prête (ADR 0275) ? Oui tant qu'aucune ne
    tourne ni n'a échoué : un dépôt sans CI, ou des vérifications qui ne se lisent pas, ne bloquent rien."""
    return o.checks in ("", CHECKS_NONE, CHECKS_PASSED)


@PROJECTS.reducer(CHECKS_SEEN)
def _checks_seen(s: ProjectsState, e, cx) -> ProjectsState:
    """Ce que l'hôte dit des vérifications du commit d'une pull request (ADR 0275). En échec : un ponctuel abouti se
    rouvre — une fois par commit en échec, pas à chaque lecture, ni quand « en cours » s'est intercalé entre deux
    échecs du même commit (``checks_failed_sha``, ADR 0278) —, la fin du journal sous les yeux de l'exécution qui
    vient. Total : un objectif inconnu, un état inconnu ne changent rien."""
    d = e.data
    p = s.projects.get(d.project)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or o is None or d.state not in CHECKS_STATES:
        return s
    failed = d.state == CHECKS_FAILED
    failed_anew = failed and d.sha != o.checks_failed_sha
    said = d.said.ref or "" if d.said is not None else ""
    o = replace(o, checks=d.state, checks_sha=d.sha, checks_at=e.at,
                checks_failed_sha=d.sha if failed else o.checks_failed_sha,
                checks_said_ref=said or (o.checks_said_ref if failed else ""))
    return with_project(s, _objective(p, _sent_back(o) if failed_anew else o))


#: les relectures refusées d'affilée sur un objectif avant que la main revienne au propriétaire ; les relectures
#: parties pour un même commit sans conclure, au plus (ADR 0276)
REVIEW_REFUSALS_MAX = 2
REVIEW_TRIES_MAX = 2


def handed_over(o: Objective) -> bool:
    """Ses relectures l'ont-elles refusé autant de fois qu'il se peut (ADR 0276) ? La suivante n'a pas lieu : la
    main est au propriétaire."""
    return len(o.review_refused) >= REVIEW_REFUSALS_MAX


def rereads(p: Project, o: Objective) -> bool:
    """Le travail conclu de cet objectif passe-t-il par une relecture indépendante (ADR 0276) ? Avant de sortir :
    dès que le projet a un dépôt distant — une pull request, ou un envoi, en partira. À chaque « fait » : aussi pour
    un ponctuel d'un projet dont rien ne sort."""
    if p.reread not in (c.REREAD_OUT, c.REREAD_EACH):
        return False
    return bool(p.remote) or (p.reread == c.REREAD_EACH and o.kind == c.ONCE)


def unreviewed(p: Project, o: Objective) -> bool:
    """Le dernier commit de cet objectif attend-il encore un verdict favorable (ADR 0276) ? Sans commit, il n'y a
    rien à relire : une relecture relit un commit précis. Et ce qui est fusionné chez l'hôte est accepté : plus
    aucun verdict ne l'attend (ADR 0277)."""
    if by_pulls(p) and o.pull_state == PULL_MERGED and not o.unsent:
        return False
    return rereads(p, o) and bool(o.commit) and not review_holds(o, o.commit)


def review_waiting(p: Project) -> Objective | None:
    """L'objectif dont une relecture est à lancer (ADR 0276) : demandée pour un commit, pas encore partie autant de
    fois qu'il se peut, la main pas encore au propriétaire — le plus petit numéro d'abord."""
    if p.reread == c.REREAD_NEVER:
        return None
    return next((o for o in p.objectives if o.review_due and o.status != c.DROPPED
                 and o.review_tries < REVIEW_TRIES_MAX and not handed_over(o)), None)


def push_reviewed(p: Project, sha: str) -> bool:
    """Ce commit peut-il partir d'elle-même vers le dépôt distant (ADR 0276) ? Oui quand le projet ne demande
    aucune relecture, ou qu'un de ses objectifs a un verdict favorable pour ce commit-là — en flux direct comme
    pour une branche de travail (ADR 0277) : sans cela, un simple envoi mettait sous une pull request déjà ouverte
    un commit que personne n'avait relu."""
    if p.reread == c.REREAD_NEVER:
        return True
    return any(review_holds(o, sha) for o in p.objectives)


def review_holds(o: Objective, sha: str) -> bool:
    """Un verdict favorable vaut-il pour ce commit ? Pour lui seul : si la branche a bougé depuis, il ne vaut plus."""
    return bool(sha) and o.review_ok and o.reviewed == sha


@PROJECTS.reducer(REVIEW_ASKED)
def _review_asked(s: ProjectsState, e, cx) -> ProjectsState:
    """Une relecture est demandée pour un commit (ADR 0276). Jamais deux fois pour le même : ni un commit déjà jugé,
    ni celui qu'on attend déjà ; et plus aucune quand la main est au propriétaire. Total : un objectif inconnu ne
    change rien."""
    d = e.data
    p = s.projects.get(d.project)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or o is None or not d.sha or d.sha in (o.reviewed, o.review_due) or handed_over(o):
        return s
    return with_project(s, _objective(p, replace(o, review_due=d.sha, review_tries=0)))


@PROJECTS.reducer(REVIEWED)
def _reviewed(s: ProjectsState, e, cx) -> ProjectsState:
    """Le verdict d'une relecture indépendante (ADR 0276), pour le commit qu'elle attendait — un verdict pour un
    autre commit ne change rien. Bon : il vaut pour ce commit, et ses refus d'avant s'effacent. Sinon : ses constats
    reviennent à l'objectif, qui se rouvre comme lorsque l'hôte renvoie sa pull request ; au deuxième refus
    d'affilée il ne se rouvre pas — il va au propriétaire, avec les deux avis (un ponctuel bloque, un constant dit
    son besoin : dans les deux cas elle le lui dit, et sa réponse ou sa consigne rend la main)."""
    d = e.data
    p = s.projects.get(d.project)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or o is None or not d.sha or d.sha != o.review_due:
        return s
    run = s.running.get(e.correlation)
    if run is not None and run.project == p.id:
        s = replace(s, running=s.running.set(e.correlation, replace(run, reported=True)))
    ref = d.findings.ref or "" if d.findings is not None else ""
    o = replace(o, review_due="", review_tries=0, reviewed=d.sha, review_ok=d.good, review_at=e.at,
                review_by=d.by[:80], review_ref="" if d.good else ref)
    p = replace(p, failures=0)
    if d.good:
        # en flux direct, la relecture suivante lira ce qui a changé depuis ce commit-ci
        return with_project(s, _objective(p, replace(o, review_refused=(), since=o.since if by_pulls(p) else d.sha)))
    o = replace(o, review_refused=(*o.review_refused, ref)[-REVIEW_REFUSALS_MAX:])
    if not handed_over(o):
        return with_project(s, _objective(p, _sent_back(o)))
    if o.kind == c.ONCE and o.status in (c.DONE, c.OPEN):
        o = replace(o, status=c.BLOCKED, closed_at=e.at)
    return with_project(s, _objective(p, replace(o, need_ref=ref or o.need_ref, asked=False, ask_attempts=0, asked_at=0,
                                         answered_at=0, steered_at=0)))


def issue_move(p: Project, ticket: int, what: str, note: int = 0) -> IssueMove | None:
    """Ce qui part ou doit partir pour ce ticket, de cette sorte (une note : celle-là)."""
    return next((m for m in p.issue_moves if (m.ticket, m.what, m.note) == (ticket, what, note)), None)


def _moved_issue(p: Project, move: IssueMove | None, *, drop: IssueMove | None = None) -> Project:
    """Le projet avec ce départ posé (à la place de celui qu'il remplace) ou retiré. Borné : les plus anciens
    départs réglés tombent d'abord."""
    gone = drop if drop is not None else move
    kept = [m for m in p.issue_moves
            if gone is None or (m.ticket, m.what, m.note) != (gone.ticket, gone.what, gone.note)]
    if move is not None:
        kept.append(move)
    while len(kept) > MOVES_KEPT:
        settled = next((m for m in kept if not m.proposal and (m.sent_at or m.tries >= MOVE_TRIES_MAX)), kept[0])
        kept.remove(settled)
    return replace(p, issue_moves=tuple(kept))


def issue_settled(p: Project, ticket: int, *whats: str) -> Project:
    """Le fait attendu est arrivé (son issue a son numéro, son état a changé) : les départs de ces sortes qui ne
    sont plus en route pour ce ticket n'ont plus lieu d'être."""
    kept = tuple(m for m in p.issue_moves if not (m.ticket == ticket and m.what in whats and not m.proposal))
    return p if len(kept) == len(p.issue_moves) else replace(p, issue_moves=kept)


def reflected(p: Project) -> bool:
    """Ce projet reflète-t-il ses tickets en issues (ADR 0275) ? Il lui faut un dépôt distant, et son réglage."""
    return bool(p.remote) and p.issues in (c.ISSUES_ASK, c.ISSUES_ALWAYS) and p.status != c.ARCHIVED


@PROJECTS.reducer(ISSUE_ASKED)
def _issue_asked(s: ProjectsState, e, cx) -> ProjectsState:
    """Une publication demandée (ADR 0275) attend sa proposition (le processus ``projects.issues``). Total : un
    projet qui ne reflète rien, une sorte inconnue, un départ déjà en route ou déjà fait ne changent rien ; un
    départ refusé ou en échec repart de zéro — le redemander est un geste."""
    d = e.data
    p = s.projects.get(d.project)
    if p is None or not reflected(p) or d.what not in (MOVE_PUBLISH, MOVE_NOTE) or d.ticket <= 0:
        return s
    note = max(0, d.note) if d.what == MOVE_NOTE else 0
    if d.what == MOVE_NOTE and not note:
        return s
    old = issue_move(p, d.ticket, d.what, note)
    if old is not None and (old.proposal or old.sent_at):
        return s
    return with_project(s, _moved_issue(p, IssueMove(d.ticket, d.what, note, d.author, d.by, asked=e.seq, at=e.at)))


@PROJECTS.reducer(NETWORK_QUEUED)
def _network_queued(s: ProjectsState, e, cx) -> ProjectsState:
    p = s.projects.get(e.data.project)
    if p is None or p.status == c.ARCHIVED or not e.data.argv:
        return s
    entry = (e.seq, tuple(str(a) for a in e.data.argv), e.data.why.ref or "")
    return with_project(s, replace(p, network=(*p.network, entry)[-4:]))


def subject_of(project: int, objective: int) -> str:
    """Le sujet d'une exécution : le projet et l'objectif qu'elle vise."""
    return f"objective:{project}:{objective}"


def stall_subject(project: int) -> str:
    """Le sujet d'une initiative qui dit qu'un projet s'est arrêté (ADR 0143) : le projet, sans objectif."""
    return f"stalled:{project}"


def stall_of(subject: str | None) -> int | None:
    """Le projet d'un sujet ``stall_subject``, sinon ``None``."""
    return _numbered(subject, "stalled:")


def frame_subject(project: int) -> str:
    """Le sujet d'une séance de cadrage (ADR 0145) : le projet, sans objectif."""
    return f"frame:{project}"


def plan_subject(project: int) -> str:
    """Le sujet d'une initiative qui dit son plan à qui a demandé le projet (ADR 0145)."""
    return f"plan:{project}"


def review_subject(project: int, objective: int) -> str:
    """Le sujet d'une relecture indépendante (ADR 0276) : le projet et l'objectif dont elle relit le travail."""
    return f"review:{project}:{objective}"


def review_of(subject: str | None) -> tuple[int, int] | None:
    """``(projet, objectif)`` d'un sujet ``review_subject``, sinon ``None``."""
    if not subject or not subject.startswith("review:"):
        return None
    head, _, tail = subject[len("review:"):].partition(":")
    return (int(head), int(tail)) if head.isdigit() and tail.isdigit() else None


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
    """``(projet, objectif)`` d'un sujet d'exécution (ou d'un récit), sinon ``None`` — aussi quand c'est un réveil
    par API qui lance l'exécution en visant cet objectif : son sujet porte alors l'appel et ce qu'il vise (ADR
    0265, ``contracts.wakeup.aim_of``)."""
    subject = wakeup_c.aim_of(subject) or subject
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
        relu = review_of(d.subject)
        if relu is not None and relu[0] == p.id:
            # une relecture indépendante (ADR 0276) : elle compte dans les plafonds de l'heure et du jour et dans
            # l'espacement, comme toute exécution — mais l'objectif qu'elle relit n'a pas travaillé
            aimed = objective_at(p, relu[1])
            s = replace(s, running=s.running.set(e.correlation, Run(
                p.id, relu[1], "review", started=e.at, previous=p.last_run_at,
                reviewing=aimed.review_due if aimed is not None else "")),
                        runs_at=tuple(t for t in s.runs_at if e.at - t < HOUR) + (e.at,))
            return with_project(s, replace(p, runs=p.runs + 1, tried_at=e.at,
                                   runs_at=tuple(t for t in p.runs_at if e.at - t < DAY) + (e.at,)))
        got = objective_of(d.subject)
        oid = got[1] if got is not None and got[0] == p.id else 0
        o = objective_at(p, oid)
        purpose = "frame" if frame_of(d.subject) == p.id else "run"
        # ce qui a déclenché l'objectif visé part avec l'exécution, qui l'a sous les yeux (ADR 0265)
        run = Run(p.id, oid, purpose, started=e.at, previous=p.last_run_at,
                  previous_objective=o.last_run_at if o is not None else 0,
                  stirred=o.stirred if o is not None else (), stirred_at=o.stirred_at if o is not None else 0,
                  stirred_more=o.stirred_more if o is not None else 0)
        s = replace(s, running=s.running.set(e.correlation, run),
                    runs_at=tuple(t for t in s.runs_at if e.at - t < HOUR) + (e.at,))
        p = replace(p, runs=p.runs + 1, runs_at=tuple(t for t in p.runs_at if e.at - t < DAY) + (e.at,))
        if wakeup_c.call_of(d.subject) is None:
            # une exécution venue d'un réveil par API (ADR 0068) compte dans les plafonds, mais ne touche ni à
            # l'agenda ni à l'espacement : elle n'avale pas un « Lancer maintenant » en attente
            p = replace(p, last_run_at=e.at, tried_at=e.at)
        if o is not None:
            # une exécution de plus sans nouveau jalon atteint : un jalon atteint remettra ce compte à zéro (ADR 0273)
            p = _objective(p, _unstirred(replace(o, runs=o.runs + 1, worked=o.worked + 1, stale=o.stale + 1,
                                                 last_run_at=e.at)))
        return with_project(s, p)
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
        return with_project(s, replace(p, stall_asked=True))
    if run.purpose == "plan":
        # son plan est dit : s'il attend une réponse, c'est celle de cette personne-là ; dit une seconde fois, c'était
        # la relance
        s = replace(s, running=s.running.set(e.correlation, replace(run, reported=True)))
        if p.plan_asked:
            return with_project(s, replace(p, plan_reminded=True))
        person = (cx.facts.get(identity_c.PERSON(run.address)) or run.address) if run.address else ""
        return with_project(s, replace(p, plan_asked=True, plan_asked_at=e.at, plan_asked_to=person))
    o = objective_at(p, run.objective)
    if o is None:
        return s
    if run.purpose == "need":
        # « j'ai besoin de toi pour… » est dit : elle attend la réponse de cette personne-là, à partir de maintenant
        person = (cx.facts.get(identity_c.PERSON(run.address)) or run.address) if run.address else ""
        return with_project(s, _objective(p, replace(o, asked=True, asked_at=e.at, asked_to=person)))
    story = _story(p, run)
    return with_project(s, replace(p, objectives=tuple(
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
        return with_project(s, _objective(p, reopened(o, e.at)))
    if o.status != c.OPEN:
        return s
    # sa réponse est là : l'objectif n'attend plus (l'exécution suivante part dans l'espacement normal)
    return with_project(s, _objective(p, replace(o, waiting_until=0, answered_at=e.at)))


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
            return with_project(s, p)
        return with_project(s, replace(p, stall_attempts=p.stall_attempts + 1))
    if run.purpose == "plan":
        renounced = cx.facts.get(agency_c.RENOUNCED(e.data.target)) if e.data.target else 0
        if run.reported or not agency_c.tried(e.data.outcome, run.started, renounced):
            return with_project(s, p)  # dit (la parole l'a noté), ou pas vraiment tenté
        if p.plan_asked:  # la relance a été tentée sans être dite : elle n'insiste pas
            return with_project(s, replace(p, plan_reminded=True))
        return with_project(s, replace(p, plan_attempts=p.plan_attempts + 1))
    if run.purpose in ("share", "need"):
        renounced = cx.facts.get(agency_c.RENOUNCED(e.data.target)) if e.data.target else 0
        if o is None or not agency_c.tried(e.data.outcome, run.started, renounced):
            return with_project(s, p)
        still_untold = pass_untold(o) if o.kind == c.CONSTANT else not o.shared
        if run.purpose == "share" and still_untold:  # un essai pour tout ce que le récit couvrait
            story = _story(p, run)
            p = replace(p, objectives=tuple(replace(x, share_attempts=x.share_attempts + 1) if x.id in story else x
                                            for x in p.objectives))
        elif run.purpose == "need" and not o.asked:
            p = _objective(p, replace(o, ask_attempts=o.ask_attempts + 1))
        return with_project(s, p)
    if run.reported:
        return s
    if run.purpose == "review":
        if e.data.outcome in REFUND and e.data.outcome not in BROKEN:  # devancée : le plafond de l'heure la rend
            s = replace(s, runs_at=tuple(t for t in s.runs_at if t != run.started))
        return with_project(s, _review_ended(p, o, run, e))
    if run.purpose == "frame" and e.data.outcome not in REFUND:
        # une séance de cadrage qui n'a pas écrit de plan : comptée — d'affilée, elles arrêtent le projet, qui ne
        # recommence pas en boucle sans rien dire (ADR 0161)
        return with_project(s, replace(p, failures=0, frame_silent=p.frame_silent + 1))
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
            p = _objective(p, _handed_back(replace(o, runs=max(0, o.runs - 1), worked=max(0, o.worked - 1),
                                                   stale=max(0, o.stale - 1),
                                                   last_run_at=run.previous_objective), run))
        return with_project(s, p)
    if o is not None:  # le modèle a travaillé, mais n'a rien conclu
        p = _objective(p, replace(o, silent=o.silent + 1))
    return with_project(s, replace(p, failures=0))


def _review_ended(p: Project, o: Objective | None, run: Run, e: Any) -> Project:
    """Une relecture indépendante qui s'achève sans verdict (ADR 0276). En panne (le modèle n'a pas répondu), elle
    n'a pas eu lieu : son crédit du jour est rendu, la panne est comptée comme celle de toute exécution — trois
    d'affilée mettent le projet en pause —, et elle ne vaut jamais « bon ». Menée au bout sans conclure, elle est
    comptée sur le commit qu'elle relisait : ``REVIEW_TRIES_MAX`` au plus, puis ce commit n'est plus relu de
    lui-même."""
    if e.data.outcome in REFUND:
        broke = e.data.outcome in BROKEN
        p = replace(p, runs=max(0, p.runs - 1), failures=p.failures + (1 if broke else 0),
                    runs_at=tuple(t for t in p.runs_at if t != run.started))
        if broke:
            cause = e.data.detail or ("TimeoutError()" if e.data.outcome == "timeout" else "RuntimeError()")
            p = replace(p, last_failure=cause[:FAILURE_KEPT])
        return p
    if o is not None and o.review_due:
        o = replace(o, review_tries=o.review_tries + 1)
        if o.review_tries >= REVIEW_TRIES_MAX and o.kind == c.ONCE and o.status == c.DONE:
            # elle ne conclut pas : ce commit ne sera plus relu de lui-même, et le ponctuel va au propriétaire —
            # sans verdict, il n'est ni bon ni refusé
            o = replace(o, status=c.BLOCKED, closed_at=e.at, asked=False, ask_attempts=0, asked_at=0,
                        answered_at=0, steered_at=0)
        p = _objective(p, o)
    return replace(p, failures=0)


def _handed_back(o: Objective, run: Run) -> Objective:
    """Une exécution qui n'a pas eu lieu rend à l'objectif les causes qu'elle lui avait prises (ADR 0265), devant
    celles arrivées depuis : le passage qu'elles demandaient reste dû."""
    mine = tuple(x for x in run.stirred if x.key in o.on or triggers.asked(x.key)) if o.status == c.OPEN else ()
    if not mine:
        return o
    causes = (*mine, *o.stirred)
    over = max(0, len(causes) - STIRS_KEPT)
    return replace(o, stirred=causes[over:], stirred_at=run.stirred_at or mine[0].at,
                   stirred_more=run.stirred_more + o.stirred_more + over)


def hear_if_listening(s: ProjectsState, e: Any, key: str, detail: str = "", project: int = 0) -> ProjectsState:
    """Noter ce qui vient d'arriver, si un objectif l'attend (ADR 0265) — sans rien juger de ce qu'un lien donne :
    le processus ``projects.stirs`` le fera, devant ce qu'elle vit. ``project`` : où c'est arrivé, quand le
    réducteur le sait."""
    return with_heard(s, e, key, detail, project) if listening(s, key) else s


def with_heard(s: ProjectsState, e: Any, key: str, detail: str = "", project: int = 0) -> ProjectsState:
    """Une nouvelle de plus dans la file, à juger (``hear_if_listening`` ; la fermeture d'une demande, ADR 0271)."""
    return replace(s, heard=(*s.heard, Heard(e.seq, e.at, key, detail[:STIR_DETAIL], project))[-HEARD_KEPT:])


def asked_by(s: ProjectsState, target: int, key: str) -> tuple[Project, Ask] | None:
    """Le projet qui a ouvert ce ticket du projet ``target`` par une demande (ADR 0271), et sa demande ; ``None`` :
    ce ticket n'est pas une demande qu'un projet suit encore."""
    for p in s.projects.values():
        for ask in p.asks:
            if ask.target == target and ask.key == key:
                return p, ask
    return None


def answering(p: Project, o: Objective, key: str, detail: str) -> bool:
    """La fermeture d'une demande réveille-t-elle cet objectif (ADR 0271) ? Un objectif encore ouvert d'un projet
    vivant, qui a ouvert cette demande : la cause nomme le projet visé (``ask:<n>``) et le ticket (``#12``). Ce que
    le lien **donne** ne se sait pas ici : le processus qui écrit ``projects.stirred`` l'a relu."""
    target = triggers.asked(key)
    return bool(target) and live(p) and o.status == c.OPEN and any(
        a.target == target and a.objective == o.id and f"#{a.number}" == detail for a in p.asks)


def roused(o: Objective, cause: Stir) -> Objective:
    """L'objectif que réveille la fermeture d'une demande qu'il a ouverte : il n'attend plus ; constant, il devient
    dû par cette cause (seul un constant garde des causes)."""
    o = replace(o, waiting_until=0) if o.waiting_until else o
    return stir(o, cause) if o.kind == c.CONSTANT else o


@PROJECTS.reducer(forge_c.SIGNALED)
def _app_signaled(s: ProjectsState, e, cx) -> ProjectsState:
    """Le signal public d'une app (une panne, ce qu'elle a gardé en tête de sa file) : noté si un objectif attend
    cette app. À quel projet elle appartient ne se sait pas ici — le processus qui juge la nouvelle le lit."""
    return hear_if_listening(s, e, triggers.app_key(e.data.app), e.data.kind)


@PROJECTS.reducer(forge_c.RAISED)
def _app_raised(s: ProjectsState, e, cx) -> ProjectsState:
    """Une app d'un projet vient de mettre un signal dans sa file (ADR 0280) : noté si un objectif attend cette app
    — sans attendre que sa file soit triée, ni qu'elle tombe en panne. Le fait ne dit que son nom : le texte du
    signal reste à la Forge."""
    return hear_if_listening(s, e, triggers.app_key(e.data.app), forge_c.APP_QUEUED)


@PROJECTS.reducer(STIRRED)
def _stirred(s: ProjectsState, e, cx) -> ProjectsState:
    """Une nouvelle jugée quitte la file ; chaque objectif qu'elle éveille garde sa cause — s'il est encore un
    constant ouvert qui la déclare, le long d'un lien posé (``stirring``), ou l'objectif encore ouvert qui a ouvert la
    demande qu'elle dit fermée (``answering``, ADR 0271) : ce qui ne tient plus est ignoré."""
    d = e.data
    news = next((h for h in s.heard if h.seq == d.news and d.key in ("", h.key)), None)
    if news is None:
        return s
    s = replace(s, heard=tuple(h for h in s.heard if h is not news))
    cause = Stir(news.at, news.key, news.detail)
    for pid, oid in dict.fromkeys(tuple(x) for x in d.targets if len(x) == 2):
        p = s.projects.get(pid)
        o = objective_at(p, oid) if p is not None else None
        if p is None or o is None:
            continue
        if stirring(p, o, news.key):
            s = with_project(s, _objective(p, stir(o, cause)))
        elif answering(p, o, news.key, news.detail):
            s = with_project(s, _objective(p, roused(o, cause)))
    return s


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
    before = p.last_commit
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
        if d.summary.ref:  # ses comptes rendus à lui : sa mémoire ne dépend pas de ce que les autres ont fait depuis
            o = replace(o, reports=(*o.reports, (e.at, d.verdict, d.summary.ref))[-OBJECTIVE_REPORTS_KEPT:])
        if d.branch:
            # la branche où elle a travaillé, et si elle y laisse un commit que sa pull request n'a pas (ADR 0274)
            o = replace(o, branch=d.branch, unsent=o.unsent or bool(d.commit),
                        pull_tries=0 if d.commit else o.pull_tries)
        if d.commit:
            # ce qu'une relecture relira (ADR 0276) : ce commit, depuis celui d'avant son premier travail
            o = replace(o, commit=d.commit, since=o.since if o.since or o.commit else before)
        if d.commit and o.milestones:
            # le commit qui clôt l'exécution est celui des jalons qu'elle y a dits atteints, ou prêts (ADR 0273) :
            # ce qu'on montre au propriétaire, et ce qu'une relecture citera, contient son travail
            o = replace(o, milestones=tuple(
                replace(m, commit=d.commit) if m.status != c.DROPPED and max(m.reached_at, m.ready_at) >= began
                else m for m in o.milestones))
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
    if not d.commit or by_pulls(p):
        # en flux ``pr``, ce commit est sur une branche de travail : un projet lecteur ne le voit pas, et rien ne
        # s'éveille (ADR 0280) — sa base avancera à la fusion, par une récupération (``_base_seen``)
        return with_project(s, p)
    # en flux direct, le commit qu'elle laisse est sur la base : ce qu'attend peut-être un objectif d'un projet qui
    # lit celui-ci (ADR 0265)
    return _base_moved(with_project(s, p), e, p.id, d.commit)


def _base_moved(s: ProjectsState, e: Any, project: int, commit: str) -> ProjectsState:
    """La base de ce projet est à ce commit : s'il est nouveau, c'est ce qu'attend peut-être un objectif d'un projet
    qui lit celui-ci (``project:<n>:commit``, ADR 0265, 0280) — ce qu'un lecteur peut voir a changé."""
    p = s.projects.get(project)
    if p is None or not commit or commit == p.base_commit:
        return s
    return hear_if_listening(with_project(s, replace(p, base_commit=commit)), e, triggers.commit_key(p.id), commit, p.id)


@PROJECTS.reducer(BASE_SEEN)
def _base_seen(s: ProjectsState, e, cx) -> ProjectsState:
    """La base d'un atelier, relue après une récupération (ADR 0280) : la fusion acceptée d'une pull request, ou
    toute récupération qui ramène autre chose, fait avancer ce qu'un projet lecteur voit — c'est cela qui l'éveille,
    pas le commit d'une branche de travail. Une base qui n'a pas bougé n'éveille rien. Total : un projet inconnu ne
    change rien."""
    p = s.projects.get(e.data.project)
    if p is None:
        return s
    s = with_project(s, replace(p, base_unread=False)) if p.base_unread else s
    return _base_moved(s, e, p.id, e.data.commit)


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
    s = with_project(s, _objective(p, o))
    # un objectif abouti : ce qu'attend peut-être un objectif d'un projet qui lit celui-ci (ADR 0265)
    return hear_if_listening(s, e, triggers.done_key(p.id), str(o.id), p.id) if o.status == c.DONE else s


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
    if e.data.capability == PULL_REQUEST_CAPABILITY:  # la pull request de cet objectif est proposée (ADR 0274)
        aimed = objective_at(p, _request_of(e.data.args_json, "objective"))
        if aimed is not None:
            p = _objective(p, replace(aimed, pull_proposal=e.seq))
    if e.data.capability in ISSUE_CAPABILITIES:  # un départ vers ses issues est proposé (ADR 0275)
        ticket, what = _request_of(e.data.args_json, "ticket"), _word_of(e.data.args_json, "what")
        if ticket > 0 and what in MOVES:
            note = _request_of(e.data.args_json, "note") if what == MOVE_NOTE else 0
            old = issue_move(p, ticket, what, note)
            p = _moved_issue(p, replace(old, proposal=e.seq) if old is not None else
                             IssueMove(ticket, what, note, proposal=e.seq, at=e.at))
    awaiting = s.awaiting.set(e.seq, e.data.args_json) if e.data.approval else s.awaiting
    s = replace(with_project(s, p), proposals=s.proposals.set(e.seq, (pid, e.data.capability)), awaiting=awaiting)
    if e.data.capability == STEER_CAPABILITY:
        asked = _asked_of(e.data.args_json)
        if asked in s.steers:
            s = replace(s, steer_proposals=_kept(s.steer_proposals.set(e.seq, asked)))
    return s


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
    if capability == PUSH_CAPABILITY:
        return phrase("projects.effect.push")
    if capability == PULL_CAPABILITY:
        return phrase("projects.effect.pull")
    if capability == NETWORKED_CAPABILITY:
        return phrase("projects.effect.networked")
    if capability == STEER_CAPABILITY:
        return phrase("projects.effect.steer")
    if capability == PULL_REQUEST_CAPABILITY:
        return phrase("projects.effect.pull_request")
    if capability == ISSUE_CAPABILITY:
        return phrase("projects.effect.issue")
    if capability == ISSUE_STATE_CAPABILITY:
        return phrase("projects.effect.issue_state")
    if capability == ISSUE_NOTE_CAPABILITY:
        return phrase("projects.effect.issue_note")
    return default


def _word_of(args_json: str, key: str) -> str:
    """Un mot des arguments d'une proposition (vide : absent, ou autre chose qu'un mot)."""
    try:
        data = json.loads(args_json)
    except ValueError:
        return ""
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, str) else ""


def _issue_asked_by(p: Project, proposal: int) -> IssueMove | None:
    """Le départ vers ses issues que cette proposition porte."""
    return next((m for m in p.issue_moves if proposal and m.proposal == proposal), None)


def _request_of(args_json: str, key: str = "request") -> int:
    """La demande de l'opérateur qu'une proposition exécute (0 : aucune) ; ``key`` : un autre nombre de ses
    arguments (l'objectif dont elle ouvre la pull request)."""
    try:
        data = json.loads(args_json)
    except ValueError:
        return 0
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


#: une demande de récupérer la base après une fusion (``Project.requests``), à côté de « push » et « pull »
BASE_REQUEST = "base"


def _pull_asked(p: Project, proposal: int) -> Objective | None:
    """L'objectif dont cette proposition ouvre la pull request."""
    return next((o for o in p.objectives if proposal and o.pull_proposal == proposal), None)


@PROJECTS.reducer(rt.EFFECT_RESOLVED)
def _resolved(s: ProjectsState, e, cx) -> ProjectsState:
    got = s.proposals.get(e.data.proposal)
    if e.data.proposal in s.awaiting:
        s = replace(s, awaiting=s.awaiting.delete(e.data.proposal))
    if got is None or got[0] not in s.projects:
        return s
    p = s.projects[got[0]]
    if got[1] == STEER_CAPABILITY and not e.data.approved:  # refusée : elle ne s'appliquera jamais
        asked = s.steer_proposals.get(e.data.proposal, "")
        s = replace(s, steers=s.steers.delete(asked) if asked in s.steers else s.steers,
                    steer_proposals=s.steer_proposals.delete(e.data.proposal))
    if e.data.approved and got[1] != STEER_CAPABILITY:  # elle part : l'atelier est occupé jusqu'à ce qu'elle revienne
        return with_project(s, replace(p, outgoing=(*p.outgoing, (e.data.proposal, e.at))[-8:]))
    if e.data.approved:
        return s
    refused = _pull_asked(p, e.data.proposal) if got[1] == PULL_REQUEST_CAPABILITY else None
    if refused is not None:
        # sa pull request refusée ici même : elle ne se repropose pas d'elle-même (un nouveau commit, ou la console)
        p = _objective(p, replace(refused, pull_proposal=0, pull_tries=PULL_TRIES_MAX))
    unsent = _issue_asked_by(p, e.data.proposal) if got[1] in ISSUE_CAPABILITIES else None
    if unsent is not None:
        # refusé ici même : ce départ ne se repropose pas de lui-même (le redemander, ou le ticket qui change d'état)
        p = _moved_issue(p, replace(unsent, proposal=0, tries=MOVE_TRIES_MAX))
    # la note de qui refuse est gardée à part (l'oubli l'atteint) : seule celle d'un journal ancien est en clair
    note = f" : « {e.data.legacy_note[:200]} »" if e.data.legacy_note else ""
    if e.data.note is not None and e.data.note.ref:
        p = replace(p, refusals=(*p.refusals, (e.data.proposal, e.data.note.ref))[-EFFECTS_KEPT:])
    return with_project(s, _effect_line(p, f"#{e.data.proposal} {phrase('projects.effect.refused')}{note}"))


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
    if got[1] == NETWORKED_CAPABILITY:
        p = replace(p, network_out=result[:NETWORK_OUT_KEPT], network_out_at=e.at)
    if got[1] in (PUSH_CAPABILITY, PULL_CAPABILITY, PULL_REQUEST_CAPABILITY):
        p = replace(p, remote_at=e.at, remote_ok=e.data.ok,
                    remote_line=f"{effect_words(got[1], '')} : {result[:400]}")
    if got[1] == PULL_CAPABILITY and e.data.ok:
        # une récupération a abouti : la base a peut-être avancé — ``projects.pulls`` la relit dans l'atelier et pose
        # ce qu'il y trouve (``projects.base_seen``, ADR 0280) ; ce que la commande a rendu est un texte, rien ne
        # s'en déduit ici
        p = replace(p, base_unread=True)
    opened_for = _pull_asked(p, e.data.proposal) if got[1] == PULL_REQUEST_CAPABILITY else None
    if opened_for is not None:
        # ouverte chez l'hôte (son numéro et son état viendront de sa première lecture, ``projects.pull_seen``), ou
        # en échec : un essai de plus, et le processus réessaiera — ``PULL_TRIES_MAX`` fois au plus
        again = opened_for.pull_state == PULL_OPEN  # déjà ouverte : son envoi la met à jour, elle garde son numéro
        # ses vérifications sont celles d'un commit d'avant : elles se relisent avec elle (ADR 0275)
        after = replace(opened_for, pull_proposal=0, pull_state=PULL_OPEN, pull=opened_for.pull if again else 0,
                        pull_changes=opened_for.pull_changes and again, pull_at=0, unsent=False,
                        pull_tries=0, checks="") if e.data.ok else \
            replace(opened_for, pull_proposal=0, pull_tries=opened_for.pull_tries + 1)
        p = _objective(p, after)
    left = _issue_asked_by(p, e.data.proposal) if got[1] in ISSUE_CAPABILITIES else None
    if left is not None:
        # parti chez l'hôte (le fait — le numéro de l'issue, son état — viendra de sa lecture, ``projects.issues``),
        # ou en échec : un essai de plus, ``MOVE_TRIES_MAX`` au plus
        p = _moved_issue(p, replace(left, proposal=0, sent_at=e.at, tries=0) if e.data.ok else
                         replace(left, proposal=0, tries=left.tries + 1))
    asked = s.steer_proposals.get(e.data.proposal, "") if got[1] == STEER_CAPABILITY else ""
    if asked in s.steers:  # acceptée : son geste s'écrit (l'effet ``steer._steer_accepted``)
        s = replace(s, steers=s.steers.set(asked, replace(s.steers[asked], applied=True)))
    return with_project(s, p)


def _code_of(result: str) -> str:
    """Le code de sortie d'une commande, en mots : son statut, relu par ``run_status`` dans ce que l'atelier en a
    écrit (``ports/workshop.py``) ; rien pour un texte d'une autre forme."""
    status, code = run_status(result)
    if status == EXITED:
        return phrase("projects.effect.code", code=code)
    if status == TIMED_OUT:
        return phrase("projects.effect.timeout")
    if status == REFUSED:
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
        access=access_of(p)[0], default_access=access_of(p)[1], plan_state=p.plan_state, read_about=p.read_about)


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


@PROJECTS.fact(c.WAKE_AIM)
def _wake_aim(s: ProjectsState, cx, key: tuple) -> str:
    p = s.projects.get(key[0]) if len(key) == 2 else None
    o = wake_aim(p, str(key[1])) if p is not None else None
    return subject_of(p.id, o.id) if p is not None and o is not None else ""


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

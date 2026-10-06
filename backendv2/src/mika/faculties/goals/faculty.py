"""La faculté ``goals`` : sa tranche, ses réducteurs, ses faits, ce que ses
événements font ressentir.

- **Un pas se réserve au départ** (``episode.started``) : un pas qui tue le
  processus n'est pas rejoué à l'infini ; un pas qui échoue sans que le
  modèle ait répondu (panne, délai, supplantation) **rend son crédit**.
- **Un pas sans verdict** compte : trois de suite, et le but est bloqué.
- **« Fini » sans preuve** n'est pas fini : il est noté, le but continue (et le
  pas peut encore conclure). Noter ou chercher dans sa mémoire ne prouve rien ;
  une réflexion sur ce qu'on lui a confié se prouve en l'écrivant
  (``goal_reflect``), une curiosité en allant lire ailleurs.
- **Devenue un projet** (``projects.created`` qui en vient), une exploration se
  clôt sans émotion : elle continue là-bas.
- **L'envie** d'une exploration s'use (demi-vie de six heures).
- **Une curiosité** (un centre d'intérêt, un sujet) menée à bout garde ce
  qu'elle en a retenu — la dernière fois seulement : quand elle y revient,
  elle repart de là, pas d'une page blanche.
- **Un rappel** qui n'a pas pu être dit est retenté, espacé (5 min × n), au
  plus trois fois.
- **Suspendu** par un opérateur (``goals.paused``), un but est figé : aucun
  pas, aucun rappel, aucune clôture, et son envie ne s'use pas ; repris
  (``goals.resumed``), il repart d'où il en était. Une **consigne**
  (``goals.amended``) s'ajoute au but et se lit au pas suivant.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import agency as agency_c
from mika.contracts import goals as c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content, Payload
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict
from mika.vocab.affect import Appraisal, Emotion
from mika.vocab.episodes import Kind, goal_of
from mika.vocab.temperament import Temperament

KEEP_CLOSED = 32
NOTES_KEPT = 5
INSTRUCTIONS_KEPT = 5


class GoalsParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # l'envie d'une exploration
    desire_half_life_us: Annotated[int, Knob(
        label="Demi-vie de l'envie", group="L'envie d'une exploration", lo=HOUR, hi=3 * DAY,
        help="L'envie d'une exploration perd la moitié de sa force en ce temps (pas pendant une pause). Le "
             "tempérament la dérive de la persévérance.")] = 6 * HOUR
    abandon_below: Annotated[float, Knob(
        label="Abandon sous", group="L'envie d'une exploration", lo=0.0, hi=0.9, step=0.01,
        help="Quand l'envie d'une exploration passe sous ce seuil, elle y renonce (« l'envie s'est usée ») : "
             "renoncer n'est pas un échec.")] = 0.15
    # les pas
    step_spacing_us: Annotated[int, Knob(
        label="Espacement des séances (exploration)", group="Les séances", lo=MINUTE, hi=DAY,
        help="Entre deux séances d'une même exploration, au moins ce délai.")] = 30 * MINUTE
    steps_per_hour: Annotated[int, Knob(
        label="Séances par heure au plus", group="Les séances", lo=0, hi=30,
        help="Tous buts confondus : chaque séance est une boucle d'outils du modèle, silencieuse, hors du budget "
             "d'initiatives (0 : plus aucun travail).")] = 4
    exploration_steps: Annotated[int, Knob(
        label="Séances par exploration", group="Les séances", lo=1, hi=20,
        help="Le budget de séances d'une exploration qu'elle ouvre d'elle-même ; à bout de séances sans conclure, elle "
             "bloque. Le tempérament le dérive de la persévérance.")] = 4
    musing_steps: Annotated[int, Knob(
        label="Séances par rêverie", group="Les séances", lo=1, hi=10,
        help="Une rêverie (une curiosité sans endroit où chercher du neuf) se vit d'un trait : elle l'écrit, c'est "
             "tout. Plus de séances la font tourner en rond, et chaque séance est une boucle d'outils du "
             "modèle.")] = 1
    reflection_steps: Annotated[int, Knob(
        label="Séances par réflexion", group="Les séances", lo=1, hi=10,
        help="Repenser à ce qu'on lui a confié, ou à une croyance qu'elle a dû revoir, se fait en une séance, "
             "l'échange sous les yeux : elle écrit ce qu'elle en pense, c'est tout. Plus de séances en font une "
             "enquête qui tourne en rond et finit par inventer (sonde réelle du 2026-10-03).")] = 1
    silent_before_blocked: Annotated[int, Knob(
        label="Séances sans verdict avant blocage", group="Les séances", lo=1, hi=10,
        help="Après autant de séances de suite où le modèle a travaillé sans rien conclure, le but est bloqué.")] = 3
    failures_before_failed: Annotated[int, Knob(
        label="Pannes avant échec", group="Les séances", lo=1, hi=20,
        help="Une séance dont l'appel au modèle échoue (panne, délai) rend son crédit ; après autant de pannes "
             "d'affilée, le but est clos en échec.")] = 5
    wait_min_us: Annotated[int, Knob(
        label="Attente minimale", group="Les séances", lo=MINUTE, hi=DAY,
        help="Quand une séance conclut « attendre », le délai qu'elle demande est ramené au moins à cette "
             "durée.")] = 10 * MINUTE
    wait_max_us: Annotated[int, Knob(
        label="Attente maximale", group="Les séances", lo=HOUR, hi=30 * DAY,
        help="…et au plus à celle-ci ; une réponse de la personne attendue la libère plus tôt.")] = DAY
    # preuves (log-odds) : de l'envie au pas
    work_base: Annotated[float, Knob(
        label="Preuve de base d'une séance", group="Preuves", lo=0.0, hi=12.0, step=0.5,
        help="La preuve (log-odds) d'une séance d'exploration : cette base plus l'envie × le poids ci-dessous, "
             "plafonnée à 12, face au seuil des séances (8).")] = 4.0
    work_per_desire: Annotated[float, Knob(
        label="Poids de l'envie", group="Preuves", lo=0.0, hi=12.0, step=0.5,
        help="Ce que vaut une envie pleine (1) en preuve d'une séance ; par défaut, une envie à moitié usée amène "
             "juste au seuil.")] = 8.0
    priority_step: Annotated[float, Knob(
        label="Poids d'un cran de priorité", group="Preuves", lo=0.0, hi=4.0, step=0.25,
        help="Ce qu'un cran de priorité ajoute à la preuve d'une séance (basse : −1 cran, haute : +1, urgente : "
             "+2), plafonnée à 12 : entre deux buts dus, le plus prioritaire passe devant.")] = 1.0
    # rappels
    remind_evidence: Annotated[float, Knob(
        label="Preuve d'un rappel", group="Rappels", lo=0.0, hi=17.0, step=0.5,
        help="Au-dessus du seuil d'initiative (9) pour être dit à l'heure, sous la barre de réveil (15) pour "
             "attendre qu'elle se réveille ; un rappel urgent vaut 17.")] = 12.0
    remind_attempts: Annotated[int, Knob(
        label="Tentatives de rappel", group="Rappels", lo=1, hi=10,
        help="Un rappel qui n'a pas pu être dit est retenté ; après autant de tentatives, il échoue.")] = 3
    remind_retry_us: Annotated[int, Knob(
        label="Espacement des tentatives", group="Rappels", lo=MINUTE, hi=2 * HOUR,
        help="Une tentative ratée est retentée après ce délai multiplié par le nombre de tentatives déjà "
             "faites.")] = 5 * MINUTE
    remind_too_late_us: Annotated[int, Knob(
        label="Trop tard pour rappeler", group="Rappels", lo=HOUR, hi=7 * DAY,
        help="Passé ce délai après l'heure dite, un rappel non dit échoue (« trop tard pour le dire ») au lieu "
             "de tomber à contretemps.")] = 12 * HOUR
    # ouvrir de soi-même
    live_self_max: Annotated[int, Knob(
        label="Buts à elle en même temps", group="Entreprendre d'elle-même", lo=0, hi=10,
        help="Au plus autant de buts qu'elle a ouverts d'elle-même en cours ensemble (0 : elle n'entreprend "
             "plus rien seule).")] = 2
    seed_spacing_us: Annotated[int, Knob(
        label="Espacement des initiatives de travail", group="Entreprendre d'elle-même", lo=10 * MINUTE,
        hi=2 * DAY, help="Elle n'entreprend pas deux choses d'elle-même dans ce délai.")] = 2 * HOUR
    #: après un blocage, elle met plus longtemps à entreprendre autre chose
    discouraged_us: Annotated[int, Knob(
        label="Découragement après un blocage", group="Entreprendre d'elle-même", lo=0, hi=7 * DAY,
        help="Après avoir bloqué sur ce qu'elle avait entrepris, elle n'entreprend rien d'autre d'elle-même "
             "avant ce délai.")] = 6 * HOUR
    seed_thought_from: Annotated[float, Knob(
        label="Pensée qui fait entreprendre", group="Entreprendre d'elle-même", lo=0.0, hi=1.0, step=0.05,
        help="Une pensée (échange, croyance révisée, signal) qui la préoccupe ou l'intrigue, au moins aussi "
             "intense, peut devenir une exploration « y voir plus clair ».")] = 0.35
    seed_thought_age_us: Annotated[int, Knob(
        label="Âge d'une pensée avant d'entreprendre", group="Entreprendre d'elle-même", lo=0, hi=DAY,
        help="La pensée doit avoir tenu ce temps : ce qui passe vite ne vaut pas un chantier.")] = 30 * MINUTE
    seed_curiosity_from: Annotated[float, Knob(
        label="Curiosité qui fait explorer", group="Entreprendre d'elle-même", lo=0.0, hi=1.0, step=0.01,
        help="Dès que son besoin de curiosité atteint ce seuil, en journée, elle ouvre l'exploration d'un de ses "
             "centres d'intérêt. Le tempérament le dérive de la curiosité.")] = 0.7
    seed_day_start_min: Annotated[int, Knob(
        label="Début de la journée", group="Entreprendre d'elle-même", lo=0, hi=24 * 60,
        help="L'heure locale (depuis minuit) à partir de laquelle elle peut explorer un centre d'intérêt.")] = 9 * 60
    seed_day_end_min: Annotated[int, Knob(
        label="Fin de la journée", group="Entreprendre d'elle-même", lo=0, hi=24 * 60,
        help="L'heure locale (depuis minuit) après laquelle elle n'ouvre plus d'exploration d'un centre "
             "d'intérêt. Avant le début, la plage passe minuit.")] = 21 * 60
    seed_jitter_min: Annotated[int, Knob(
        label="Flottement du début de journée", group="Entreprendre d'elle-même", lo=0, hi=120,
        help="Le début de sa journée d'exploration varie d'un jour à l'autre, jusqu'à ce nombre de minutes avant "
             "ou après (le même jour donne toujours le même décalage : on peut le rejouer). Personne ne commence "
             "ses journées à la minute près.")] = 20
    no_reopen_us: Annotated[int, Knob(
        label="Ne pas rouvrir avant", group="Entreprendre d'elle-même", lo=HOUR, hi=30 * DAY,
        help="Un sujet qu'elle vient de clore (la même pensée, la même personne) ne se rouvre pas avant ce "
             "délai.")] = DAY
    interest_rest_us: Annotated[int, Knob(
        label="Repos d'un centre d'intérêt", group="Entreprendre d'elle-même", lo=HOUR, hi=90 * DAY,
        help="Un centre d'intérêt exploré n'est pas réexploré avant ce délai ; parmi les autres, elle va plus "
             "volontiers vers ceux qu'elle a délaissés, sans ordre fixe.")] = 3 * DAY
    musings_per_day: Annotated[int, Knob(
        label="Rêveries par jour, au plus", group="Entreprendre d'elle-même", lo=0, hi=12,
        help="Ce que sa curiosité lui fait ouvrir d'elle-même dans une journée — rêvasser autour d'un sujet, "
             "fouiller ses flux — ne dépasse pas ce nombre, étalé sur sa journée (deux : une le matin, une "
             "l'après-midi) : une personne ne rêvasse pas toutes les deux heures (sonde réelle du 2026-10-03 : "
             "quatre à cinq rêveries par jour). 0 : jamais.")] = 2
    talk_lookback_us: Annotated[int, Knob(
        label="Un sujet de conversation reste une graine pendant", group="Entreprendre d'elle-même", lo=HOUR,
        hi=14 * DAY,
        help="Ce dont on lui a parlé et qui l'a intéressée (ce qu'une amie lui a fait découvrir, un sujet qui l'a "
             "enthousiasmée) peut la faire rêvasser pendant ce délai — avant ses centres d'intérêt de "
             "toujours.")] = 2 * DAY
    # raconter ce qu'elle a mené à bout
    share_notable_from: Annotated[float, Knob(
        label="Notable à partir de", group="Raconter", lo=0.0, hi=1.0, step=0.05,
        help="Un but abouti que sa dernière séance juge au moins aussi notable se raconte à quelqu'un ; à qui et "
             "combien dépend du lien.")] = 0.4
    share_within_us: Annotated[int, Knob(
        label="Raconter dans les", group="Raconter", lo=HOUR, hi=7 * DAY,
        help="Passé ce délai après l'aboutissement, elle ne le raconte plus.")] = 12 * HOUR
    share_evidence: Annotated[float, Knob(
        label="Envie de raconter", group="Raconter", lo=0.0, hi=10.0, step=0.5,
        help="La preuve (log-odds) de l'initiative de le raconter, face au seuil d'initiative (9) ; "
             "l'arbitrage la plafonne à 10.")] = 10.0
    share_attempts: Annotated[int, Knob(
        label="Tentatives de raconter", group="Raconter", lo=1, hi=10,
        help="Après autant de tentatives qui n'ont pas abouti, elle n'essaie plus.")] = 2


def derive(t: Temperament, overrides: Any = None) -> GoalsParams:
    """La persévérance donne plus de pas et une envie plus tenace ; la
    curiosité ouvre une exploration plus tôt."""
    values: dict[str, Any] = {
        "exploration_steps": 3 + round(3 * t.perseverance),
        "desire_half_life_us": round((3 + 6 * t.perseverance) * HOUR),
        "seed_curiosity_from": round(0.85 - 0.3 * t.curiosity, 3),
    }
    values.update(dict(overrides or {}))
    return GoalsParams(**values)


#: les tâches d'un plan de travail, au plus
TASKS_KEPT = 40
DEPOSITS_KEPT = 5
#: les crans d'une priorité (``priority_step`` chacun)
PRIORITY_RANK = {c.LOW: -1, c.NORMAL: 0, c.HIGH: 1, c.URGENT: 2}


@dataclass(frozen=True, slots=True)
class Task:
    """Une tâche du plan de travail d'un but."""

    id: int
    text_ref: str
    status: str = c.TODO
    #: qui l'a posée : ``operator`` (demandée) ou ``self`` (elle)
    author: str = "self"
    #: son résultat, ou pourquoi elle bloque
    note_ref: str = ""
    at: int = 0


@dataclass(frozen=True, slots=True)
class Goal:
    id: int
    kind: str
    authority: str
    title_ref: str
    opened_at: int
    details_ref: str = ""
    owner: str | None = None
    address: str | None = None
    about: tuple[str, ...] = ()
    sensitivity: int = 1
    source: str = ""
    bundles: tuple[str, ...] = ()
    max_steps: int = 0
    due: int | None = None
    urgent: bool = False
    schedule: str = ""
    approval: bool = True
    status: str = c.ACTIVE
    desire: float = 0.0
    desire_at: int = 0
    # le travail
    steps: int = 0
    silent: int = 0
    unproven: int = 0
    failures: int = 0
    evidence: int = 0
    last_step_at: int = 0
    waiting_until: int = 0
    waiting_since: int = 0
    wait_for: str | None = None
    summary_ref: str = ""
    notes: tuple[str, ...] = ()  # références des notes de son carnet
    effects: tuple[str, ...] = ()  # ce que sont devenus ses effets externes (courtes lignes)
    #: suspendu par un opérateur depuis cet instant (0 : il ne l'est pas)
    paused_at: int = 0
    #: références des consignes d'un opérateur, les plus récentes en dernier
    instructions: tuple[str, ...] = ()
    priority: str = c.NORMAL
    #: son plan de travail, et le numéro de la dernière tâche posée
    tasks: tuple[Task, ...] = ()
    task_seq: int = 0
    #: « avancer maintenant » demandé à cet instant (sans effet une fois un pas parti)
    nudged_at: int = 0
    #: les fichiers déposés dans son atelier par un opérateur : (nom, octets, référence de la note)
    deposits: tuple[tuple[str, int, str], ...] = ()
    # les rappels
    delivered: bool = False
    attempts: int = 0
    retry_at: int = 0
    # clos
    closed_at: int = 0
    notable: float = 0.0
    result_ref: str = ""
    shared: bool = False
    share_attempts: int = 0
    #: une exploration : ce qui l'a fait naître (``exchange``, ``revision``, ``signal``, ``interest``) et quand
    origin: str = ""
    origin_at: int = 0
    #: le projet qu'elle est devenue (0 : aucun)
    became: int = 0


@dataclass(frozen=True, slots=True)
class Run:
    goal: int
    purpose: str  # "step" | "remind" | "share"
    reported: bool = False
    #: son départ (une initiative : pour reconnaître qu'elle s'est ravisée entre-temps)
    started: int = 0


@dataclass(frozen=True, slots=True)
class GoalsState:
    goals: FrozenDict[int, Goal] = field(default_factory=FrozenDict)
    running: FrozenDict[str, Run] = field(default_factory=FrozenDict)
    #: les pas de la dernière heure (plafond horaire)
    steps_at: tuple[int, ...] = ()
    #: sujet → fermeture : on ne rouvre pas sous 24 h ce qu'on vient de clore
    #: (une inquiétude redite est une autre pensée, mais le même sujet)
    closed_sources: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: centre d'intérêt → dernière exploration
    explored: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: curiosité (un centre d'intérêt, un sujet) → ce qu'elle en a retenu la dernière fois : (close le, référence du
    #: résultat, sensibilité). Seule une exploration menée à bout l'écrit : une rêverie dissipée n'efface pas la
    #: précédente
    kept_from: FrozenDict[str, tuple[int, str, int]] = field(default_factory=FrozenDict)
    #: proposition d'effet → but
    proposals: FrozenDict[int, int] = field(default_factory=FrozenDict)
    #: la dernière fois qu'elle a entrepris quelque chose d'elle-même
    self_opened_at: int = 0
    #: la dernière fois qu'elle a bloqué sur ce qu'elle avait entrepris
    self_stuck_at: int = 0


#: les lots qui ne touchent que sa tête (sa mémoire, ce qu'elle sait des autres, ses buts et ses projets) : ce
#: qu'ils font ne prouve pas qu'elle a mené quelque chose à bout
INNER_BUNDLES = frozenset({"goals", "memory", "identity", "self", "attention", "social", "projects"})


def musing(g: Goal) -> bool:
    """Une curiosité sans source où chercher du neuf : une rêverie — autour d'un de ses centres d'intérêt, ou de ce
    dont on lui a parlé et qui lui a plu."""
    return g.origin in c.MUSING_ORIGINS and not set(g.bundles) - INNER_BUNDLES


#: les sources d'une curiosité (un centre d'intérêt, un sujet de conversation) : ce qu'elle a déjà exploré
CURIOSITY_SOURCES = ("interest:", "talk:")


def curious_today(s: GoalsState, day: str, local_date: Any) -> int:
    """Combien de fois sa curiosité lui a fait ouvrir quelque chose ce jour-là (``local_date(t)`` : la date locale
    d'un instant, en AAAA-MM-JJ) — le plafond de ses rêveries."""
    return sum(1 for source, at in s.explored.items() if source.startswith(CURIOSITY_SOURCES)
               and local_date(at) == day)


def kept_before(s: GoalsState, g: Goal) -> tuple[int, str, int] | None:
    """Ce qu'elle avait retenu la dernière fois qu'elle a exploré la même curiosité que ce but (un centre d'intérêt,
    un sujet) : (close le, référence, sensibilité). Rien pour un autre but, ni une fois celui-ci clos (ce serait le
    sien)."""
    if g.status in c.CLOSED_STATUSES or not g.source.startswith(CURIOSITY_SOURCES):
        return None
    return s.kept_from.get(g.source)


#: v3 : un rappel, un récit devancés, interrompus ou dont elle s'est ravisée ne comptent plus comme essais.
#: v4 : ce qu'elle a retenu de sa dernière exploration d'une même curiosité (``kept_from``).
GOALS = Faculty("goals", state=GoalsState, init=lambda p: GoalsState(), params=GoalsParams, derive=derive,
                state_version=4,
                # les réglages des projets, quand ils étaient des buts (ADR 0031) : d'anciens journaux les portent
                retired_params=("project_spacing_us", "project_steps", "project_evidence"))
GOALS.declare(*c.ALL)


class Noted(Payload):
    """Une note de son carnet de travail (privée : personne d'autre ne la réduit)."""

    goal: int
    text: Content
    #: recopiés du but : une note peut citer ces personnes (l'oubli l'atteint)
    owner: str | None = None
    about: tuple[str, ...] = ()


NOTED = GOALS.event("noted", Noted, content=("text",), subjects=("owner", "about"))


class Awaited(Payload):
    """La personne qu'elle attendait a écrit : le but reprend."""

    goal: int
    person: str


AWAITED = GOALS.event("awaited", Awaited)


class Paused(Payload):
    """Un opérateur suspend ce but : ni pas, ni rappel, ni usure, jusqu'à reprise."""

    goal: int
    #: l'adresse de l'opérateur
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class Resumed(Payload):
    """Un opérateur reprend un but suspendu : il repart d'où il en était."""

    goal: int
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class Amended(Payload):
    """Une consigne d'un opérateur, ajoutée au but (elle la lit au pas suivant)."""

    goal: int
    instruction: Content
    by: str = ""
    #: recopiés du but : la consigne peut citer ces personnes (l'oubli l'atteint)
    owner: str | None = None
    about: tuple[str, ...] = ()


class Reframed(Payload):
    """Un opérateur change le cadre d'un but (le texte et l'heure d'un rappel ; la priorité de n'importe lequel ;
    les anciens projets, avant l'ADR 0031, changeaient aussi leur cadre). Seuls les champs donnés changent."""

    goal: int
    title: Content | None = None
    details: Content | None = None
    #: vider le cadre écrit (``details`` vide)
    clear_details: bool = False
    #: changer pour qui (``owner``/``about``/``address`` ci-dessous deviennent ceux du but)
    set_owner: bool = False
    address: str | None = None
    due: int | None = None
    clear_due: bool = False
    urgent: bool | None = None
    schedule: str | None = None
    max_steps: int | None = None
    approval: bool | None = None
    priority: str | None = None
    by: str = ""
    #: ceux du but après le changement : le cadre peut les citer (l'oubli l'atteint)
    owner: str | None = None
    about: tuple[str, ...] = ()


class Reopened(Payload):
    """Un opérateur rouvre un but clos (bloqué, abandonné, en échec, annulé) avec quelques pas de plus."""

    goal: int
    extra: int = 4
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class Nudged(Payload):
    """« Avancer maintenant » : le prochain pas n'attend ni l'agenda ni l'espacement."""

    goal: int
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class TaskAdded(Payload):
    goal: int
    task: int
    text: Content
    #: ``operator`` (demandée depuis la console) ou ``self`` (elle, pendant un pas)
    author: str = "self"
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class TaskChanged(Payload):
    goal: int
    task: int
    status: str | None = None
    text: Content | None = None
    #: son résultat, ou pourquoi elle bloque
    note: Content | None = None
    #: effacer la note (un champ vidé dans la console)
    clear_note: bool = False
    author: str = "self"
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class TaskRemoved(Payload):
    goal: int
    task: int
    author: str = "operator"
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


class Deposited(Payload):
    """Un fichier déposé dans l'atelier par un opérateur (elle le lit au pas suivant)."""

    goal: int
    name: str
    size: int = 0
    note: Content | None = None
    by: str = ""
    owner: str | None = None
    about: tuple[str, ...] = ()


GOAL_PAUSED = GOALS.event("paused", Paused, subjects=("owner", "about"))
GOAL_RESUMED = GOALS.event("resumed", Resumed, subjects=("owner", "about"))
#: les mots de l'opérateur : ses consignes s'oublient avec lui, et avec les personnes du but
GOAL_AMENDED = GOALS.event("amended", Amended, content=("instruction",), subjects=("owner", "about", "by"))
GOAL_REFRAMED = GOALS.event("reframed", Reframed, content=("title", "details"), subjects=("owner", "about", "by"))
GOAL_REOPENED = GOALS.event("reopened", Reopened, subjects=("owner", "about"))
GOAL_NUDGED = GOALS.event("nudged", Nudged, subjects=("owner", "about"))
TASK_ADDED = GOALS.event("task_added", TaskAdded, content=("text",), subjects=("owner", "about", "by"))
TASK_CHANGED = GOALS.event("task_changed", TaskChanged, content=("text", "note"), subjects=("owner", "about", "by"))
TASK_REMOVED = GOALS.event("task_removed", TaskRemoved, subjects=("owner", "about"))
GOAL_DEPOSITED = GOALS.event("deposited", Deposited, content=("note",), subjects=("owner", "about", "by"))
#: ce qu'un opérateur (ou elle, pour le plan) fait d'un but — la chronologie du carnet
OPERATIONS = (GOAL_PAUSED, GOAL_RESUMED, GOAL_REFRAMED, GOAL_REOPENED, GOAL_NUDGED, TASK_ADDED, TASK_CHANGED,
              TASK_REMOVED, GOAL_DEPOSITED)


def params(p: GoalsParams | None) -> GoalsParams:
    return p if p is not None else GoalsParams()


def budget(g: Goal, p: GoalsParams) -> int:
    """Combien de pas au plus : le sien, sinon la valeur par défaut de sa sorte (un rappel n'en fait pas ; un
    ancien projet, relu au rejeu, compte comme une exploration). Une seule lecture de ``max_steps == 0`` partout
    (le travail, la clôture, la fiche, le prompt)."""
    if g.max_steps:
        return g.max_steps
    return p.exploration_steps if g.kind in (c.EXPLORATION, c.PROJECT) else 0


def rank(g: Goal) -> int:
    return PRIORITY_RANK.get(g.priority, 0)


def task_at(g: Goal, task: int | str | None) -> Task | None:
    raw = str(task if task is not None else "").strip().lstrip("#")
    return next((t for t in g.tasks if str(t.id) == raw), None) if raw.isdigit() else None


def subject_key(source: str, about: tuple[str, ...]) -> str:
    """Ce sur quoi porte un but, pour ne pas le rouvrir : la personne dont
    parle la pensée d'où il vient, sinon sa source."""
    if source.startswith("thought:") and about:
        return f"about:{about[0]}"
    return source


def ready_to_undertake(s: GoalsState, p: GoalsParams) -> int:
    """À partir de quand elle peut entreprendre à nouveau quelque chose d'elle-même :
    pas deux choses dans la même heure, et plus lentement après un échec."""
    return max(s.self_opened_at + p.seed_spacing_us if s.self_opened_at else 0,
               s.self_stuck_at + p.discouraged_us if s.self_stuck_at else 0)


def desire(g: Goal, now: int, p: GoalsParams) -> float:
    """L'envie à l'instant ; suspendue, elle ne s'use pas (figée à la pause)."""
    if g.kind != c.EXPLORATION:
        return 1.0
    until = min(now, g.paused_at) if g.paused_at else now
    return g.desire * 0.5 ** (max(0, until - g.desire_at) / p.desire_half_life_us)


def status(g: Goal, now: int) -> str:
    """Le statut à l'instant : une attente échue redevient active ; un but
    suspendu (et pas clos) est « en pause »."""
    if g.status in c.CLOSED_STATUSES:
        return g.status
    if g.paused_at:
        return c.PAUSED
    if g.status == c.WAITING and g.waiting_until <= now:
        return c.ACTIVE
    return g.status


def live(g: Goal, now: int) -> bool:
    """Vivant : actif, en attente, ou suspendu (pas clos)."""
    return status(g, now) in c.LIVE_STATUSES


def workable(g: Goal, now: int) -> bool:
    """Vivant et pas suspendu : on peut y travailler, le rappeler, le clore."""
    return status(g, now) in (c.ACTIVE, c.WAITING)


def goal_at(s: GoalsState, key: str | int | None) -> Goal | None:
    """Le but d'une clé de fiche (``12``, ``"12"`` ou ``"#12"``), ou rien."""
    raw = str(key if key is not None else "").strip().lstrip("#")
    return s.goals.get(int(raw)) if raw.isdigit() else None


def _set(s: GoalsState, g: Goal) -> GoalsState:
    return replace(s, goals=s.goals.set(g.id, g))


def _prune(s: GoalsState, now: int) -> GoalsState:
    closed = sorted((g for g in s.goals.values() if g.status in c.CLOSED_STATUSES), key=lambda g: (g.closed_at, g.id))
    drop = [g.id for g in closed[:-KEEP_CLOSED]] + [g.id for g in closed if now - g.closed_at > 7 * DAY]
    goals = s.goals
    for gid in drop:
        goals = goals.delete(gid)
    sources = FrozenDict({k: v for k, v in s.closed_sources.items() if now - v <= 7 * DAY})
    proposals = FrozenDict({k: v for k, v in s.proposals.items() if v in goals})
    # un sujet de conversation passé l'horizon où il peut la faire rêvasser (au plus deux semaines) s'oublie ; ses
    # centres d'intérêt, eux, restent
    explored = FrozenDict({k: v for k, v in s.explored.items() if not k.startswith("talk:") or now - v <= 15 * DAY})
    # ce qu'elle en a retenu suit la même règle
    kept = FrozenDict({k: v for k, v in s.kept_from.items() if not k.startswith("talk:") or now - v[0] <= 15 * DAY})
    return replace(s, goals=goals, closed_sources=sources, proposals=proposals, explored=explored, kept_from=kept)


# ── Réducteurs ────────────────────────────────────────────────────────────


@GOALS.reducer(c.GOAL_OPENED)
def _opened(s: GoalsState, e, cx) -> GoalsState:
    d = e.data
    g = Goal(
        id=e.seq, kind=d.kind, authority=d.authority, title_ref=d.title.ref or "", opened_at=e.at,
        details_ref=d.details.ref or "" if d.details is not None else "", owner=d.owner, address=d.address,
        about=tuple(d.about), sensitivity=d.sensitivity, source=d.source, bundles=tuple(d.bundles),
        max_steps=d.max_steps, due=d.due, urgent=d.urgent, schedule=d.schedule, approval=d.approval,
        desire=d.desire, desire_at=e.at, priority=d.priority if d.priority in c.PRIORITIES else c.NORMAL,
        origin=d.origin, origin_at=d.origin_at,
    )
    s = _set(s, g)
    if d.source.startswith(CURIOSITY_SOURCES):
        s = replace(s, explored=s.explored.set(d.source, e.at))
    if d.authority == c.SELF:
        s = replace(s, self_opened_at=e.at)
    return s


@GOALS.reducer(rt.EPISODE_STARTED)
def _started(s: GoalsState, e, cx) -> GoalsState:
    d = e.data
    if d.kind == Kind.STEP:
        gid = goal_of(d.target)
        g = s.goals.get(gid) if gid is not None else None
        if g is None:
            return s
        s = replace(s, running=s.running.set(e.correlation, Run(g.id, "step")),
                    steps_at=tuple(t for t in s.steps_at if e.at - t < HOUR) + (e.at,))
        return _set(s, replace(g, steps=g.steps + 1, last_step_at=e.at))
    gid = goal_of(d.subject)
    if d.kind != Kind.INITIATIVE or gid is None or gid not in s.goals:
        return s
    reasons = d.reason.split(",")
    purpose = "remind" if c.REMIND in reasons else "share" if c.SHARE in reasons else ""
    if not purpose:
        return s
    return replace(s, running=s.running.set(e.correlation, Run(gid, purpose, started=e.at)))


@GOALS.reducer(rt.UTTERANCE)
def _uttered(s: GoalsState, e, cx) -> GoalsState:
    run = s.running.get(e.correlation)
    if run is None or run.goal not in s.goals:
        return s
    g = s.goals[run.goal]
    if run.purpose == "remind":
        return _set(s, replace(g, delivered=True))
    if run.purpose == "share":
        return _set(s, replace(g, shared=True))
    return s


#: Ce qui ne dit rien du pas : il n'a pas eu lieu, son crédit est rendu.
REFUND = frozenset({"failed", "timeout", "superseded", "preempted", "cancelled", "interrupted"})


@GOALS.reducer(rt.EPISODE_ENDED, reads=[agency_c.RENOUNCED])
def _ended(s: GoalsState, e, cx) -> GoalsState:
    run = s.running.get(e.correlation)
    if run is None:
        return s
    s = replace(s, running=s.running.delete(e.correlation))
    g = s.goals.get(run.goal)
    if g is None:
        return s
    p = params(cx.params)
    outcome = e.data.outcome
    if run.purpose == "step":
        if run.reported:
            return s
        if outcome in REFUND:
            broke = outcome in ("failed", "timeout")
            return _set(s, replace(g, steps=max(0, g.steps - 1), failures=g.failures + (1 if broke else 0)))
        return _set(s, replace(g, silent=g.silent + 1))  # le modèle a travaillé, mais n'a rien conclu
    renounced = cx.facts.get(agency_c.RENOUNCED(e.data.target)) if e.data.target else 0
    if run.purpose == "remind" and not g.delivered:
        if not agency_c.tried(outcome, run.started, renounced):
            return _set(s, replace(g, retry_at=e.at + p.remind_retry_us))
        n = g.attempts + 1
        return _set(s, replace(g, attempts=n, retry_at=e.at + p.remind_retry_us * n))
    if run.purpose == "share" and not g.shared and agency_c.tried(outcome, run.started, renounced):
        return _set(s, replace(g, share_attempts=g.share_attempts + 1))
    return s


@GOALS.reducer(c.STEP_REPORTED)
def _reported(s: GoalsState, e, cx) -> GoalsState:
    d = e.data
    g = s.goals.get(d.goal)
    if g is None:
        return s
    run = s.running.get(e.correlation)
    if run is not None and run.goal == g.id:
        s = replace(s, running=s.running.set(e.correlation, replace(run, reported=True)))
    p = params(cx.params)
    g = replace(g, silent=0, failures=0, summary_ref=d.summary.ref or g.summary_ref,
                evidence=g.evidence + len(d.tools))
    if d.verdict == c.WAIT:
        wait = max(p.wait_min_us, min(p.wait_max_us, d.wait_s * 1_000_000))
        g = replace(g, status=c.WAITING, waiting_until=e.at + wait, waiting_since=e.at, wait_for=d.wait_for)
    elif d.verdict == c.DONE and not d.proven:
        g = replace(g, unproven=g.unproven + 1)
    elif g.status == c.WAITING:
        g = replace(g, status=c.ACTIVE)
    return _set(s, g)


@GOALS.reducer(AWAITED)
def _awaited(s: GoalsState, e, cx) -> GoalsState:
    g = s.goals.get(e.data.goal)
    if g is None or g.status != c.WAITING:
        return s
    return _set(s, replace(g, status=c.ACTIVE, waiting_until=0, wait_for=None))


@GOALS.reducer(NOTED)
def _noted(s: GoalsState, e, cx) -> GoalsState:
    g = s.goals.get(e.data.goal)
    if g is None or not e.data.text.ref:
        return s
    return _set(s, replace(g, notes=(*g.notes, e.data.text.ref)[-NOTES_KEPT:]))


@GOALS.reducer(GOAL_PAUSED)
def _paused(s: GoalsState, e, cx) -> GoalsState:
    g = s.goals.get(e.data.goal)
    if g is None or g.status in c.CLOSED_STATUSES or g.paused_at:
        return s
    return _set(s, replace(g, paused_at=e.at))


@GOALS.reducer(GOAL_RESUMED)
def _resumed(s: GoalsState, e, cx) -> GoalsState:
    g = s.goals.get(e.data.goal)
    if g is None or g.status in c.CLOSED_STATUSES or not g.paused_at:
        return s
    # l'envie repart d'où elle était : la pause ne compte pas dans son usure
    return _set(s, replace(g, paused_at=0, desire_at=g.desire_at + max(0, e.at - g.paused_at)))


@GOALS.reducer(GOAL_AMENDED)
def _amended(s: GoalsState, e, cx) -> GoalsState:
    g = s.goals.get(e.data.goal)
    if g is None or g.status in c.CLOSED_STATUSES or not e.data.instruction.ref:
        return s
    return _set(s, replace(g, instructions=(*g.instructions, e.data.instruction.ref)[-INSTRUCTIONS_KEPT:]))


@GOALS.reducer(GOAL_REFRAMED)
def _reframed(s: GoalsState, e, cx) -> GoalsState:
    d = e.data
    g = s.goals.get(d.goal)
    if g is None or g.status in c.CLOSED_STATUSES:
        return s
    changes: dict[str, Any] = {}
    if d.title is not None and d.title.ref:
        changes["title_ref"] = d.title.ref
    if d.clear_details:
        changes["details_ref"] = ""
    elif d.details is not None and d.details.ref:
        changes["details_ref"] = d.details.ref
    if d.set_owner:
        changes.update(owner=d.owner, about=tuple(d.about), address=d.address)
    if d.clear_due:
        changes["due"] = None
    elif d.due is not None:
        changes["due"] = d.due
    if (d.due is not None or d.clear_due) and g.kind == c.REMINDER:
        changes.update(attempts=0, retry_at=0)  # une nouvelle heure : ses tentatives repartent de zéro
    if d.urgent is not None:
        changes["urgent"] = d.urgent
    if d.schedule is not None:
        changes["schedule"] = d.schedule
    if d.max_steps is not None:
        changes["max_steps"] = d.max_steps
    if d.approval is not None:
        changes["approval"] = d.approval
    if d.priority in c.PRIORITIES:
        changes["priority"] = d.priority
    return _set(s, replace(g, **changes)) if changes else s


@GOALS.reducer(GOAL_REOPENED)
def _reopened(s: GoalsState, e, cx) -> GoalsState:
    g = s.goals.get(e.data.goal)
    if g is None or g.status not in c.CLOSED_STATUSES or g.status == c.ACHIEVED:
        return s
    p = params(cx.params)
    extra = max(1, e.data.extra)
    g = replace(g, status=c.ACTIVE, closed_at=0, silent=0, failures=0, unproven=0, waiting_until=0,
                waiting_since=0, wait_for=None, max_steps=max(budget(g, p), g.steps + extra), notable=0.0,
                result_ref="", shared=False, share_attempts=0, paused_at=0,
                # une exploration rouverte repart avec l'envie qu'on lui redonne (sinon elle s'userait aussitôt)
                desire=max(g.desire, 0.6) if g.kind == c.EXPLORATION else g.desire, desire_at=e.at)
    s = _set(s, g)
    key = subject_key(g.source, g.about) if g.source else ""
    if key and key in s.closed_sources:
        s = replace(s, closed_sources=s.closed_sources.delete(key))
    return s


@GOALS.reducer(GOAL_NUDGED)
def _nudged(s: GoalsState, e, cx) -> GoalsState:
    g = s.goals.get(e.data.goal)
    if g is None or g.status in c.CLOSED_STATUSES:
        return s
    if g.status == c.WAITING:  # « maintenant » l'emporte sur l'attente
        g = replace(g, status=c.ACTIVE, waiting_until=0, waiting_since=0, wait_for=None)
    return _set(s, replace(g, nudged_at=e.at))


@GOALS.reducer(TASK_ADDED)
def _task_added(s: GoalsState, e, cx) -> GoalsState:
    d = e.data
    g = s.goals.get(d.goal)
    if g is None or not d.text.ref or len(g.tasks) >= TASKS_KEPT or task_at(g, d.task) is not None:
        return s
    task = Task(id=d.task, text_ref=d.text.ref, author=d.author, at=e.at)
    return _set(s, replace(g, tasks=(*g.tasks, task), task_seq=max(g.task_seq, d.task)))


@GOALS.reducer(TASK_CHANGED)
def _task_changed(s: GoalsState, e, cx) -> GoalsState:
    d = e.data
    g = s.goals.get(d.goal)
    t = task_at(g, d.task) if g is not None else None
    if g is None or t is None:
        return s
    changes: dict[str, Any] = {"at": e.at}
    if d.status in c.TASK_STATUSES:
        changes["status"] = d.status
    if d.text is not None and d.text.ref:
        changes["text_ref"] = d.text.ref
    if d.clear_note:
        changes["note_ref"] = ""
    elif d.note is not None and d.note.ref:
        changes["note_ref"] = d.note.ref
    new = replace(t, **changes)
    return _set(s, replace(g, tasks=tuple(new if x.id == t.id else x for x in g.tasks)))


@GOALS.reducer(TASK_REMOVED)
def _task_removed(s: GoalsState, e, cx) -> GoalsState:
    g = s.goals.get(e.data.goal)
    if g is None or task_at(g, e.data.task) is None:
        return s
    return _set(s, replace(g, tasks=tuple(t for t in g.tasks if t.id != e.data.task)))


@GOALS.reducer(GOAL_DEPOSITED)
def _deposited(s: GoalsState, e, cx) -> GoalsState:
    d = e.data
    g = s.goals.get(d.goal)
    if g is None:
        return s
    entry = (d.name, d.size, d.note.ref or "" if d.note is not None else "")
    return _set(s, replace(g, deposits=(*g.deposits, entry)[-DEPOSITS_KEPT:]))


@GOALS.reducer(projects_c.PROJECT_CREATED)
def _became_project(s: GoalsState, e, cx) -> GoalsState:
    """Une exploration qui s'avère plus grosse qu'une envie devient un projet (``start_project`` pendant une de
    ses séances) : elle continue là-bas, et se clôt ici (``goals.tend``)."""
    source = e.data.source or ""
    gid = int(source[len("goal:"):]) if source.startswith("goal:") and source[len("goal:"):].isdigit() else None
    g = s.goals.get(gid) if gid is not None else None
    if g is None or g.kind != c.EXPLORATION or g.status in c.CLOSED_STATUSES:
        return s
    return _set(s, replace(g, became=e.seq))


@GOALS.reducer(c.GOAL_CLOSED)
def _closed(s: GoalsState, e, cx) -> GoalsState:
    d = e.data
    g = s.goals.get(d.goal)
    if g is None or g.status in c.CLOSED_STATUSES:
        return s
    g = replace(g, status=d.status, closed_at=e.at, notable=d.notable, paused_at=0,
                result_ref=d.result.ref or "" if d.result is not None else "")
    s = _set(s, g)
    if g.source:
        s = replace(s, closed_sources=s.closed_sources.set(subject_key(g.source, g.about), e.at))
    if d.status == c.ACHIEVED and g.result_ref and g.source.startswith(CURIOSITY_SOURCES):
        # la prochaine fois qu'elle y reviendra, elle partira de là
        s = replace(s, kept_from=s.kept_from.set(g.source, (e.at, g.result_ref, g.sensitivity)))
    if d.status == c.STUCK and g.authority == c.SELF:
        s = replace(s, self_stuck_at=e.at)
    return _prune(s, e.at)


@GOALS.reducer(rt.EFFECT_PROPOSED)
def _proposed(s: GoalsState, e, cx) -> GoalsState:
    gid = goal_of(e.data.context)
    if e.data.owner != c.OWNER or gid is None or gid not in s.goals:
        return s
    g = s.goals[gid]
    line = f"#{e.seq} proposé ({e.data.capability})" + (" — en attente d'accord" if e.data.approval else "")
    return replace(_set(s, replace(g, effects=(*g.effects, line)[-NOTES_KEPT:])),
                   proposals=s.proposals.set(e.seq, gid))


@GOALS.reducer(rt.EFFECT_RESOLVED)
def _resolved(s: GoalsState, e, cx) -> GoalsState:
    gid = s.proposals.get(e.data.proposal)
    if gid is None or gid not in s.goals or e.data.approved:
        return s
    g = s.goals[gid]
    # la note de qui refuse est gardée à part (l'oubli l'atteint) : seule celle d'un journal ancien est en clair
    note = f" : « {e.data.legacy_note[:200]} »" if e.data.legacy_note else ""
    line = f"#{e.data.proposal} refusé{note}"
    return _set(s, replace(g, effects=(*g.effects, line)[-NOTES_KEPT:]))


@GOALS.reducer(rt.EFFECT_EXECUTED)
def _executed(s: GoalsState, e, cx) -> GoalsState:
    gid = s.proposals.get(e.data.proposal)
    if gid is None or gid not in s.goals:
        return s
    g = s.goals[gid]
    line = f"#{e.data.proposal} {'fait' if e.data.ok else 'échoué'} : {e.data.result[:300]}"
    return _set(s, replace(g, effects=(*g.effects, line)[-NOTES_KEPT:]))


# ── Faits ─────────────────────────────────────────────────────────────────


def view(g: Goal, now: int) -> c.GoalView:
    return c.GoalView(
        id=g.id, kind=g.kind, authority=g.authority, status=status(g, now), title_ref=g.title_ref, owner=g.owner,
        about=g.about, sensitivity=g.sensitivity, opened_at=g.opened_at, steps=g.steps, max_steps=g.max_steps,
        due=g.due, waiting_until=g.waiting_until if status(g, now) == c.WAITING else 0,
        last_summary_ref=g.summary_ref, schedule=g.schedule, priority=g.priority, tasks_total=len(g.tasks),
        tasks_done=sum(1 for t in g.tasks if t.status == c.TASK_DONE),
        tasks_blocked=sum(1 for t in g.tasks if t.status == c.TASK_BLOCKED), musing=musing(g),
    )


@GOALS.fact(c.LIVE)
def _live(s: GoalsState, cx) -> tuple[c.GoalView, ...]:
    return tuple(view(g, cx.now) for g in sorted(s.goals.values(), key=lambda g: g.id) if live(g, cx.now))


@GOALS.fact(c.STATUS)
def _status(s: GoalsState, cx, goal: int) -> str:
    g = s.goals.get(goal)
    return status(g, cx.now) if g is not None else ""


# ── Ce que ses événements font ressentir ──────────────────────────────────


@GOALS.appraisal(AWAITED)
def _awaited_felt(e, cx) -> Appraisal:
    """Enfin : ce qu'elle attendait est arrivé."""
    return Appraisal(Emotion.RELIEVED, 0.2, reason="attente comblée")


@GOALS.appraisal(c.GOAL_CLOSED)
def _closed_felt(e, cx) -> Appraisal | None:
    """Mener à bout rend fière ; bloquer frustre ; renoncer d'elle-même laisse
    une teinte de mélancolie. Un rappel dit n'est pas un exploit."""
    d = e.data
    if d.kind == c.REMINDER:
        return None
    if d.status == c.ACHIEVED and d.reason == c.MUSED:
        return Appraisal(Emotion.DREAMY, 0.2, reason="une rêverie écrite")
    if d.status == c.ACHIEVED:
        return Appraisal(Emotion.PROUD, 0.4, reason="abouti")
    if d.status == c.STUCK:
        return Appraisal(Emotion.FRUSTRATED, 0.35, reason="bloquée")
    if d.status == c.ABANDONED and d.reason in c.QUIET_ENDS:
        return None  # une rêverie qui s'efface, une réflexion sans suite : on n'a renoncé à rien
    if d.status == c.ABANDONED:
        return Appraisal(Emotion.MELANCHOLIC, 0.25, reason="abandon")
    return None

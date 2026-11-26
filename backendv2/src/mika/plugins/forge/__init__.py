"""Le plugin ``forge`` : les petites apps qu'elle écrit, et ce qu'elles lui font.

Ce module garde la vie d'une app : son état, ses événements et leurs réducteurs, ses tours (``Tick``, ``Events``,
``Discover``, ``outcomes``), et les aides que lisent les autres modules. Chaque contribution vit dans un module nommé
d'après ce qu'elle fait, importé en fin de fichier dans l'ordre de ses inscriptions.

- **Écrire** (outils ``forge_*``, ``tools.py``, à sa propriétaire ou quand elle travaille) : une app est relue à
  l'écriture ; une version refusée ne change rien. Elle la relit par morceaux numérotés (``forge_read``), cherche dans
  ses apps (``forge_search``), la retouche sans tout réécrire (``forge_edit``) et l'essaie tout de suite
  (``forge_test`` : tout ce qu'elle écrit, avec les délais et les arguments déclarés — ADR 0105).
- **La confiance d'un opérateur vaut pour l'app** : une app qui a des **secrets** sans avoir jamais été validée voit sa
  nouvelle version mise de côté et **proposée**, le manifeste et le code en diff (une version qui attend un accord,
  ``install.py``) ; validée une fois (une clé confiée, une version approuvée, une promotion), ses versions suivantes
  s'installent sans lui, ses secrets lisibles, sa promotion tenue (ADR 0105) ; « Ne plus lui faire confiance » la
  retire. Une app qu'un opérateur a arrêtée le reste, même réécrite.
- **Faire tourner** (ce module) : selon l'agenda de son manifeste, un tour à la fois, hors de son processus (l'hôte).
  Cinq échecs d'affilée ouvrent le disjoncteur : l'app s'arrête, et elle le **remarque** (« mon app ne marche
  plus ») — ce qui peut devenir une envie de la réparer.
- **Influence bornée** : ce qu'une app veut lui signaler passe par l'attention (dosé, habitué, un signal par app toutes
  les dix minutes au plus) ou par sa file de signaux, qu'elle lit dans une tâche (``signals.py``) ; son contexte est
  une section **citée**, en zone volatile, coupée en premier, et ce qu'une app d'un projet trouve pour quelqu'un, elle
  le lui dit (ce qu'elle en dit : ``prompt.py``).
- **Ses outils suivent son projet** (ADR 0133 ; ses outils d'app et leurs accès : ``access.py``) : ``<app>_<outil>``
  et ``<app>_pages`` sont offerts selon la ligne d'accès de son projet qui les concerne — lecture s'il le déclare
  (``lit``), action sinon ; une app sans projet a ses propres lignes d'accès, nées de son minimum vital
  (``APP_VITAL`` : toi et elle seule, ADR 0134). Sur accord, l'appel est proposé (``calls.py``) ; seule comme sur
  accord, ce qu'il rend porte ce qu'elle en garde (``vocab.access.KEEP_FLOORS``, ADR 0128). Une app qui a des secrets
  ne sert en conversation que promue.
- **La console** (``inspect.py``) : chaque app a sa fiche (type d'objet ``app``) — état, ses vues déclarées rendues
  depuis le bac à sable (``views.py`` ; jamais journalisées, jamais comptées par le disjoncteur), ses réglages typés,
  son code, son journal, son vécu — et les commandes d'un opérateur. Mika apprend à les écrire par ``forge_help`` (le
  mode d'emploi, ``guide.py``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import forge as c
from mika.contracts import identity as identity_c
from mika.contracts import projects as projects_c
from mika.kernel import schedule
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content, Origin, Payload
from mika.kernel.faculty import CatchUp, Faculty
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.ports.forge import AppInfo, SignalRules, ui_load
from mika.ports.forge_args import said_args
from mika.vocab.access import CLOSED_TOOLS, ToolRule
from mika.vocab.episodes import task_of
from mika.vocab.phrasebook import phrase

BUNDLE, APPS_BUNDLE = "forge", "forge_apps"


class ForgeParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tick_timeout_s: Annotated[float, Knob(
        label="Délai d'un battement", group="Ses apps", lo=0.5, hi=30, step=0.5,
        help="Le temps qu'une app a pour un battement, un service ou un événement, dans son bac à sable, quand son "
             "manifeste n'en déclare pas (« timeout », jusqu'à 120 s) ; au-delà, l'appel est tué et compte comme "
             "un échec.")] = 5.0
    context_timeout_s: Annotated[float, Knob(
        label="Délai du contexte", group="Ses apps", lo=0.2, hi=10, step=0.1,
        help="Le temps qu'une app a pour dire ce qu'elle apporte au prompt ; ce délai s'ajoute à la "
             "composition d'une réponse, d'où sa brièveté.")] = 1.5
    breaker: Annotated[int, Knob(
        label="Échecs avant disjonction", group="Ses apps", lo=1, hi=50,
        help="Autant d'échecs d'affilée (battements, événements) et l'app est mise hors service ; elle le "
             "ressent et peut la réparer. Une action d'opérateur n'est jamais comptée.")] = 5
    signal_calls_max: Annotated[int, Knob(
        label="Appels par jour, au plus, pour les signaux d'une app", group="Ses apps", lo=1, hi=200,
        help="Le quota qu'une app déclare (« signals: quota ») ne passe jamais ce plafond : chaque appel lit un lot "
             "de sa file et coûte un appel au modèle.")] = 48
    triage_evidence: Annotated[float, Knob(
        label="Envie de lire la file d'une app", group="Ses apps", lo=0.0, hi=12.0, step=0.5,
        help="La preuve (log-odds) qu'une file de signaux non lus apporte à la tâche de les lire, face au seuil des "
             "tâches (8).")] = 8.5
    context_chars: Annotated[int, Knob(
        label="Contexte par app (caractères)", group="Ses apps", lo=50, hi=4000,
        help="Ce qu'une app ajoute au prompt est coupé à cette longueur : chaque caractère est relu à "
             "chaque réponse.")] = 500
    news_within_us: Annotated[int, Knob(
        label="Dire une trouvaille dans les", group="Ce que ses apps trouvent", lo=10 * MINUTE, hi=2 * DAY,
        help="Ce qu'une app d'un projet lui signale fort (assez pour lui rester en tête) et qui concerne quelqu'un, "
             "elle le lui dit dans ce délai ; passé, elle ne le dit plus d'elle-même.")] = 6 * HOUR
    news_attempts: Annotated[int, Knob(
        label="Tentatives de dire une trouvaille", group="Ce que ses apps trouvent", lo=1, hi=10,
        help="Après autant d'essais qui n'ont rien dit, elle n'essaie plus.")] = 2
    news_evidence: Annotated[float, Knob(
        label="Envie de dire une trouvaille", group="Ce que ses apps trouvent", lo=0.0, hi=10.0, step=0.5,
        help="La preuve (log-odds) de l'initiative de dire à la personne ce qu'une app vient de trouver pour elle, "
             "face au seuil d'initiative (9). Elle prévient : ni la retenue envers qui ne répond pas, ni la période "
             "réfractaire allongée ne la retiennent.")] = 9.5


@dataclass(frozen=True, slots=True)
class App:
    title: str
    version: int
    schedule: str = "manual"
    context: bool = False
    enabled: bool = True
    broken: str = ""
    failures: int = 0
    promoted: bool = False
    #: arrêtée par un opérateur : elle le reste, même réécrite (seul un opérateur la relance)
    held: bool = False
    #: l'empreinte de la version en vigueur, et celle de la version qu'un opérateur a validée la première fois (en
    #: lui donnant un secret, en approuvant, en promouvant) : dès lors l'app a sa confiance, et ses versions
    #: suivantes lisent ses secrets sans repasser par lui (ADR 0105) ; vide : jamais validée, ou plus
    fingerprint: str = ""
    trusted: str = ""
    since: int = 0  # la version en vigueur depuis
    ticked_at: int = 0
    signaled_at: int = 0
    events: tuple[str, ...] = ()  # ce qu'elle veut recevoir (``on_event``)
    inbox: tuple[Delivery, ...] = ()  # ce qui l'attend (borné)
    #: sa surface déclarée (vues, actions, réglages, fonctions), en JSON canonique
    ui: str = ""
    #: l'épisode qui a écrit la version en vigueur : un essai réussi dans ce même épisode prouve qu'elle a produit
    #: une app qui marche (ADR 0104)
    written_in: str = ""
    #: la dernière version qu'un essai a prouvée, et l'épisode qui l'a relancée après une panne : un essai réussi
    #: prouve une version jamais prouvée de son projet, ou une app relancée dans l'épisode — pas une app qui marchait
    #: déjà (ADR 0161). Un essai qui prouve ne compte qu'une fois crédité par le compte rendu de son exécution : en
    #: attendant, l'épisode et la version (``trial_in``, ``trial_version``) ; une exécution qui n'aboutit pas ne
    #: consomme rien
    proven: int = 0
    revived_in: str = ""
    trial_in: str = ""
    trial_version: int = 0
    #: le projet où elle vit (0 : aucun) — écrite pendant une de ses exécutions, ou désignée ; il porte sa
    #: réparation, ses trouvailles et ses demandes (ADR 0104)
    project: int = 0
    #: un opérateur a refusé la dernière version proposée : elle le sait (effacé à la version suivante)
    install_refused: bool = False
    #: ses services (ADR 0104) : (nom, rythme) ; leur dernier passage, leurs échecs de suite, et ceux que le
    #: disjoncteur a arrêtés (nom → pourquoi) — un service cassé n'arrête pas les autres
    services: tuple[tuple[str, str], ...] = ()
    ran: FrozenDict[str, int] = field(default_factory=FrozenDict)
    svc_failures: FrozenDict[str, int] = field(default_factory=FrozenDict)
    broken_services: FrozenDict[str, str] = field(default_factory=FrozenDict)
    #: sa file de signaux (ADR 0105) : ce que l'app lui a signalé, pas encore lu ; ce qu'elle déclare (taille, par
    #: appel, quota par jour — vide : les défauts) et ce qu'elle doit en faire ; combien sont partis faute de place ;
    #: quand ses lectures ont eu lieu (le quota se compte sur vingt-quatre heures)
    queue: tuple[Queued, ...] = ()
    rules: tuple[int, int, int] = ()
    instructions: str = ""
    dropped: int = 0
    calls_at: tuple[int, ...] = ()
    #: ses lignes d'accès (ADR 0134), pour une app sans projet : réglées d'un coup (``access_set``) ; ``None`` :
    #: jamais réglées, son minimum vital vaut (``APP_VITAL``) ; une app d'un projet suit son projet
    access: tuple[ToolRule, ...] | None = None
    default_access: ToolRule = CLOSED_TOOLS


@dataclass(frozen=True, slots=True)
class Queued:
    """Un signal en attente dans la file d'une app."""

    seq: int
    at: int
    summary_ref: str
    pertinence: float
    emotion: str = ""
    level: int = 0


@dataclass(frozen=True, slots=True)
class Delivery:
    """Un événement à remettre à une app : l'enveloppe, et un résumé seulement
    s'il est anodin (une app peut appeler ses domaines : rien de personnel ne
    lui parvient)."""

    seq: int
    type: str
    at: int
    source: str = ""
    kind: str = ""
    summary_ref: str = ""
    #: ce qu'une autre app a émis (``api.emit``), en JSON
    data: str = ""


@dataclass(frozen=True, slots=True)
class ForgeState:
    apps: FrozenDict[str, App] = field(default_factory=FrozenDict)
    #: les propositions d'installer une version mise de côté : proposition → app
    installs: FrozenDict[int, str] = field(default_factory=FrozenDict)
    #: ce qu'une app d'un projet vient de lui signaler et qui concerne quelqu'un, à lui dire (ADR 0105) : app → la
    #: dernière trouvaille
    news: FrozenDict[str, News] = field(default_factory=FrozenDict)
    #: les initiatives parties pour dire une trouvaille : épisode → (départ, apps) — un essai qui ne dit rien compte
    openings: FrozenDict[str, tuple[int, tuple[str, ...]]] = field(default_factory=FrozenDict)
    #: les lectures de file en cours : épisode → (app, signaux lus, départ)
    sifting: FrozenDict[str, tuple[str, tuple[int, ...], int]] = field(default_factory=FrozenDict)
    #: les dernières trouvailles de chaque app vraiment dites (``SAID_KEPT`` au plus) : app → ((texte, quand, niveau),
    #: …) — une trouvaille pas encore dite peut en remplacer une autre, ce qui a été dit reste su (on ne le redit pas)
    said: FrozenDict[str, tuple[tuple[str, int, int], ...]] = field(default_factory=FrozenDict)
    #: les appels d'outils d'app qui attendaient un accord (ADR 0133), par proposition (``calls.py``)
    calls: FrozenDict[int, AppCall] = field(default_factory=FrozenDict)


@dataclass(frozen=True, slots=True)
class AppCall:
    """Un appel d'outil d'app qui demandait un accord, de la proposition à ce qu'elle en a dit (ADR 0133)."""

    proposal: int
    app: str
    #: l'outil tel qu'elle le nomme (``<app>_<outil>``, ``<app>_pages``)
    tool: str
    #: l'adresse de la personne de l'épisode (à qui le dire) ; vide en travail
    target: str
    approval: str
    at: int
    expires: int
    args_json: str = "{}"
    #: ce qu'elle garde de ce que l'app rendra (``keep`` de la ligne d'accès qui a permis la demande) ; vide pour une
    #: demande d'avant : gardé comme un souvenir personnel
    keep: str = ""
    status: str = "attend"
    by: str = ""
    done_at: int = 0
    text_ref: str = ""
    told: bool = False


@dataclass(frozen=True, slots=True)
class News:
    """Une trouvaille d'app à dire : le signal (son numéro, son instant, son texte), qui elle concerne et à quel
    niveau, sa pertinence, et ce qu'il en est (dite, combien d'essais)."""

    seq: int
    at: int
    about: tuple[str, ...]
    level: int
    summary_ref: str
    pertinence: float
    attempts: int = 0
    told: bool = False
    #: elle l'a jugée urgente : elle ouvre le dialogue même avec qui ne lui répond plus (``c.APP_ALERT``)
    urgent: bool = False


class Written(Payload):
    app: str
    version: int
    title: str
    schedule: str = "manual"
    context: bool = False
    events: tuple[str, ...] = ()
    #: ce que l'app déclare pour la console (``AppInfo.ui``) : ses formulaires se
    #: rendent sans relire le disque
    ui: str = ""
    #: l'empreinte de cette version (vide : un ancien journal)
    fingerprint: str = ""
    #: un opérateur l'a validée (il l'a approuvée, rechargée ou remise) : ses secrets lui sont lisibles
    vouched: bool = False
    #: le projet où elle vit (0 : celui d'avant, ou aucun — ADR 0104)
    project: int = 0
    #: ses services : (nom, rythme)
    services: tuple[tuple[str, str], ...] = ()
    #: sa file de signaux : (taille, par appel, quota par jour) et ce qu'elle doit en faire (vide : un ancien journal)
    signals: tuple[int, ...] = ()
    instructions: str = ""


class Handled(Payload):
    """Ce qui attendait une app lui a été remis (jusqu'à ``upto``)."""

    app: str
    upto: int
    ok: bool
    error: str = ""


class Switched(Payload):
    """Activée, arrêtée, cassée (disjoncteur), promue, effacée, stockage vidé, validée par un opérateur."""

    app: str
    #: "enabled" | "disabled" | "broken" | "promoted" | "demoted" | "erased" | "reset" | "trusted" | "untrusted"
    state: str
    reason: str = ""
    #: ``trusted`` : l'empreinte de la version validée
    fingerprint: str = ""
    #: ``broken`` d'un seul de ses services (les autres continuent, ADR 0104)
    service: str = ""


class Ticked(Payload):
    app: str
    ok: bool
    error: str = ""
    duration_ms: int = 0
    #: le service qui a tourné (vide : le rythme principal, ``tick``)
    service: str = ""


class Emitted(Payload):
    app: str
    type: str
    data: str


class Proved(Payload):
    """Un essai réussi prouve cette version (ADR 0161) : une fois le compte rendu de son exécution crédité de la
    preuve, un autre essai d'elle ne prouvera plus rien."""

    app: str
    version: int


class AppAccessSet(Payload):
    """Les lignes d'accès d'une app sans projet, réglées d'un coup par un opérateur (ADR 0134) : tout le tableau,
    dans son ordre, et la ligne par défaut."""

    app: str
    rows: tuple[ToolRule, ...] = ()
    default: ToolRule = CLOSED_TOOLS
    by: str = ""


#: v5 : ce qui a été dit de chaque app reste su (``said``), même quand une trouvaille nouvelle remplace la précédente.
#: v6 : une trouvaille sait si elle est urgente (``News.urgent``).
#: v7 : les appels d'outils d'app qui attendent un accord (``calls``, ADR 0133).
#: v8 : les lignes d'accès d'une app sans projet (``App.access``, ADR 0134).
#: v9 : la version prouvée et l'épisode qui l'a relancée (``App.proven``, ``App.revived_in`` : ADR 0161).
FORGE = Faculty("forge", state=ForgeState, init=lambda p: ForgeState(), params=ForgeParams, state_version=9,
               retired_params=("signal_spacing_us",))
FORGE.bundle(BUNDLE, phrase("forge.bundle"))
FORGE.declare(*c.ALL)
WRITTEN = FORGE.event("written", Written)
SWITCHED = FORGE.event("switched", Switched)
TICKED = FORGE.event("ticked", Ticked)
EMITTED = FORGE.event("emitted", Emitted)
PROVED = FORGE.event("proved", Proved)
HANDLED = FORGE.event("handled", Handled)
ACCESS_SET = FORGE.event("access_set", AppAccessSet, subjects=("by",))
INBOX_MAX = 16


def params(p: ForgeParams | None) -> ForgeParams:
    return p if p is not None else ForgeParams()


# ── Réducteurs ────────────────────────────────────────────────────────────


@FORGE.reducer(WRITTEN)
def _written(s: ForgeState, e, cx) -> ForgeState:
    d = e.data
    old = s.apps.get(d.app)
    print_ = d.fingerprint or (old.fingerprint if old is not None and old.version == d.version else "")
    if old is not None and old.version == d.version:  # la même version, relue : sa vie continue
        # une app d'avant les empreintes garde sa confiance pour la version qu'elle avait
        trusted = print_ if d.vouched or (not old.fingerprint and old.trusted == "") else old.trusted
        return replace(s, apps=s.apps.set(d.app, replace(old, title=d.title, schedule=d.schedule, context=d.context,
                                                         events=tuple(d.events), ui=d.ui, fingerprint=print_,
                                                         trusted=trusted, project=d.project or old.project,
                                                         services=tuple(d.services) or old.services,
                                                         rules=tuple(d.signals) or old.rules,
                                                         instructions=d.instructions if d.signals
                                                         else old.instructions)))
    if d.vouched and app_installs(s, d.app):  # installée après accord : la proposition est réglée
        s = replace(s, installs=FrozenDict({k: v for k, v in s.installs.items() if v != d.app}))
    held = old.held if old is not None else False
    # une nouvelle version repart (disjoncteur refermé), sauf si un opérateur l'a arrêtée ; elle garde la confiance
    # et la promotion de l'app (une validation vaut pour ses versions suivantes, ADR 0105)
    app = App(d.title, d.version, d.schedule, d.context, enabled=not held, since=e.at, held=held,
              promoted=old.promoted if old is not None else False,
              signaled_at=old.signaled_at if old else 0, events=tuple(d.events), ui=d.ui, fingerprint=print_,
              trusted=print_ if d.vouched else (old.trusted if old else ""), written_in=e.correlation,
              project=d.project or (old.project if old else 0), services=tuple(d.services),
              # un service gardé garde son dernier passage : la version suivante ne le relance pas aussitôt
              ran=FrozenDict({k: v for k, v in (old.ran if old else FrozenDict()).items()
                              if k in {name for name, _ in d.services}}),
              # sa file traverse les versions : ce qu'elle lui a signalé reste à lire
              queue=old.queue if old else (), dropped=old.dropped if old else 0,
              calls_at=old.calls_at if old else (), rules=tuple(d.signals), instructions=d.instructions,
              # ses lignes d'accès suivent l'app, pas sa version (ADR 0134) ; ce qui a été prouvé aussi (ADR 0161)
              access=old.access if old else None, default_access=old.default_access if old else CLOSED_TOOLS,
              proven=old.proven if old else 0)
    return replace(s, apps=s.apps.set(d.app, app))


@FORGE.reducer(ACCESS_SET)
def _access_set(s: ForgeState, e, cx) -> ForgeState:
    d = e.data
    app = s.apps.get(d.app)
    if app is None:
        return s
    return replace(s, apps=s.apps.set(d.app, replace(app, access=tuple(d.rows), default_access=d.default)))


@FORGE.reducer(SWITCHED)
def _switched(s: ForgeState, e, cx) -> ForgeState:
    d = e.data
    app = s.apps.get(d.app)
    if app is None:
        return s
    if d.state == "erased":
        return replace(s, apps=s.apps.delete(d.app), news=s.news.delete(d.app) if d.app in s.news else s.news)
    operator = e.origin == Origin.EXTERNAL  # une action d'opérateur (la console), pas elle
    if d.state == "broken" and d.service:  # un seul service s'arrête : les autres continuent
        return replace(s, apps=s.apps.set(d.app, replace(
            app, broken_services=app.broken_services.set(d.service, d.reason[:300]))))
    # relancée après une panne : un essai réussi dans cet épisode prouve sa réparation (ADR 0161)
    revived = e.correlation if app.broken or app.broken_services else app.revived_in
    change = {"enabled": {"enabled": True, "broken": "", "failures": 0, "held": False,
                          "broken_services": FrozenDict(), "svc_failures": FrozenDict(), "revived_in": revived},
              "disabled": {"enabled": False, "held": app.held or operator},
              "broken": {"enabled": False, "broken": d.reason[:300]}, "promoted": {"promoted": True},
              "demoted": {"promoted": False},
              "trusted": {"trusted": d.fingerprint or app.fingerprint},
              # un opérateur lui retire sa confiance : plus de secrets, plus de promotion ; sa version suivante
              # attendra de nouveau son accord
              "untrusted": {"trusted": "", "promoted": False}}.get(d.state)
    return replace(s, apps=s.apps.set(d.app, replace(app, **change))) if change else s


def app_installs(s: ForgeState, app: str) -> list[int]:
    """Les propositions d'installer une version de cette app, encore en route."""
    return [k for k, v in s.installs.items() if v == app]


def trusted(app: App | None) -> bool:
    """Ses secrets se lisent-ils ? Quand un opérateur a validé l'app une fois (ses versions suivantes comprises,
    ADR 0105), et ne lui a pas retiré sa confiance."""
    return app is not None and bool(app.trusted)


@FORGE.reducer(PROVED)
def _proved(s: ForgeState, e, cx) -> ForgeState:
    """L'essai qui prouve : en attente du compte rendu de son exécution (ADR 0161)."""
    app = s.apps.get(e.data.app)
    if app is None:
        return s
    return replace(s, apps=s.apps.set(e.data.app, replace(app, trial_in=e.correlation,
                                                          trial_version=e.data.version)))


@FORGE.reducer(projects_c.RUN_REPORTED)
def _credited(s: ForgeState, e, cx) -> ForgeState:
    """Le compte rendu d'une exécution crédité d'une preuve : les versions qu'elle a prouvées à l'essai le sont pour
    de bon (ADR 0161)."""
    if not e.data.proof:
        return s
    apps = s.apps
    for name, app in s.apps.items():
        if app.trial_in and app.trial_in == e.correlation:
            apps = apps.set(name, replace(app, proven=max(app.proven, app.trial_version), trial_in="",
                                          trial_version=0))
    return replace(s, apps=apps) if apps is not s.apps else s


@FORGE.reducer(TICKED)
def _ticked(s: ForgeState, e, cx) -> ForgeState:
    app = s.apps.get(e.data.app)
    if app is None:
        return s
    if e.data.service:
        name = e.data.service
        failures = 0 if e.data.ok else app.svc_failures.get(name, 0) + 1
        return replace(s, apps=s.apps.set(e.data.app, replace(app, ran=app.ran.set(name, e.at),
                                                               svc_failures=app.svc_failures.set(name, failures))))
    return replace(s, apps=s.apps.set(e.data.app, replace(app, ticked_at=e.at,
                                                           failures=0 if e.data.ok else app.failures + 1)))


@FORGE.reducer(c.SIGNALED)
def _signaled(s: ForgeState, e, cx) -> ForgeState:
    """Un signal de l'app est passé jusqu'à son attention (une panne, ou ce qu'elle a décidé de garder en tête)."""
    app = s.apps.get(e.data.app)
    return replace(s, apps=s.apps.set(e.data.app, replace(app, signaled_at=e.at))) if app else s


def rules_of(app: App) -> SignalRules:
    """Ce que l'app déclare de sa file (un ancien journal : les défauts)."""
    if len(app.rules) == 3:
        return SignalRules(app.rules[0], app.rules[1], app.rules[2], app.instructions)
    return SignalRules(instructions=app.instructions)


@FORGE.reducer(c.QUEUED)
def _queued(s: ForgeState, e, cx) -> ForgeState:
    """Un signal entre dans la file de son app ; pleine, la plus ancienne part — et c'est compté (ADR 0105)."""
    d = e.data
    app = s.apps.get(d.app)
    if app is None:
        return s
    queue = (*app.queue, Queued(e.seq, e.at, d.summary.ref or "", float(d.pertinence), d.emotion,
                                int(d.sensitivity)))
    size = rules_of(app).queue
    dropped = max(0, len(queue) - size)
    return replace(s, apps=s.apps.set(d.app, replace(app, queue=queue[dropped:], dropped=app.dropped + dropped,
                                                     signaled_at=e.at)))


@FORGE.reducer(c.JUDGED)
def _judged(s: ForgeState, e, cx) -> ForgeState:
    """Elle a lu un lot : il quitte la file ; ce qu'elle dira devient une trouvaille à dire à qui elle concerne."""
    d = e.data
    app = s.apps.get(d.app)
    if app is None:
        return s
    read = set(d.seqs)
    s = replace(s, apps=s.apps.set(d.app, replace(app, queue=tuple(q for q in app.queue if q.seq not in read))))
    if d.tell is not None and d.tell.ref and d.about:
        s = replace(s, news=s.news.set(d.app, News(e.seq, e.at, tuple(d.about), int(d.sensitivity), d.tell.ref, 1.0,
                                                   urgent=bool(d.urgent))))
    return replace(s, sifting=s.sifting.delete(e.correlation)) if e.correlation in s.sifting else s


def sifting_app(target: str | None) -> str:
    """L'app dont une tâche lit la file (vide : ce n'en est pas une)."""
    found = task_of(target)
    return found[1] if found is not None and found[0] == "forge" else ""


def wants(patterns: tuple[str, ...], type_name: str) -> bool:
    return any(type_name == p or (p.endswith(".*") and type_name.startswith(p[:-1])) for p in patterns)


def _queue(s: ForgeState, e: Any, delivery: Delivery, *, as_type: str = "") -> ForgeState:
    apps = s.apps
    wanted = as_type or e.type.name
    for name, app in s.apps.items():
        if not app.enabled or app.broken or not wants(app.events, wanted):
            continue
        if delivery.source == f"forge:{name}":
            continue  # jamais ses propres signaux : pas de boucle
        apps = apps.set(name, replace(app, inbox=(*app.inbox, delivery)[-INBOX_MAX:]))
    return replace(s, apps=apps)


@FORGE.reducer(EMITTED)
def _emitted_for_apps(s: ForgeState, e, cx) -> ForgeState:
    """Ce qu'une app émet (``api.emit``) parvient aux autres apps qui l'écoutent (``events: [forge.<app>.*]``) —
    jamais à son attention à elle, jamais à l'app qui l'émet (ADR 0104 : une émission n'arrivait nulle part)."""
    d = e.data
    if not any(a.events for a in s.apps.values()):
        return s
    return _queue(s, e, Delivery(e.seq, f"forge.{d.app}.{d.type}", e.at, f"forge:{d.app}", d.type, data=d.data[:4000]),
                  as_type=f"forge.{d.app}.{d.type}")


@FORGE.reducer(shapes=[attention_c.Signal])
def _signal_for_apps(s: ForgeState, e, cx) -> ForgeState:
    """Un signal anodin (un titre, un appareil, une autre app) peut intéresser une app ;
    un signal qui touche quelqu'un (un mail, la caméra) ne lui parvient jamais."""
    d = e.data
    if d.sensitivity > 0 or not any(a.events for a in s.apps.values()):
        return s
    return _queue(s, e, Delivery(e.seq, e.type.name, e.at, d.source, d.kind, d.summary.ref or ""))


@FORGE.reducer(body_c.FELL_ASLEEP, body_c.WOKE)
def _rhythm_for_apps(s: ForgeState, e, cx) -> ForgeState:
    if not any(a.events for a in s.apps.values()):
        return s
    return _queue(s, e, Delivery(e.seq, e.type.name, e.data.at))


@FORGE.reducer(HANDLED)
def _handled(s: ForgeState, e, cx) -> ForgeState:
    d = e.data
    app = s.apps.get(d.app)
    if app is None:
        return s
    inbox = tuple(x for x in app.inbox if x.seq > d.upto)
    return replace(s, apps=s.apps.set(d.app, replace(app, inbox=inbox, failures=0 if d.ok else app.failures + 1)))


@FORGE.fact(c.APPS)
def _apps(s: ForgeState, cx) -> tuple[c.AppView, ...]:
    pending = set(s.installs.values())
    return tuple(c.AppView(k, a.title, a.version, a.enabled, a.broken, a.failures, a.promoted, a.context, a.schedule,
                           project=a.project, held=a.held, pending=k in pending, refused=a.install_refused,
                           ticked_at=a.ticked_at, services=tuple(n for n, _ in a.services),
                           broken_services=tuple(sorted(a.broken_services.items())),
                           views=tuple(v.label for v in ui_load(a.ui).views))
                 for k, a in sorted(s.apps.items()))


# ── Faire tourner ─────────────────────────────────────────────────────────


#: le délai d'un outil d'app quand son manifeste n'en déclare pas : une réponse l'attend
TOOL_TIMEOUT_S = 10.0


def timeout_of(info: AppInfo | None, method: str, p: ForgeParams) -> float:
    """Le délai d'un appel (ADR 0105) : celui que son manifeste déclare — pour son battement et ses événements
    (``timeout``), un service, un outil —, sinon le défaut (un réglage pour ce qui tourne seul, 10 s pour un outil)."""
    if method.startswith("tool_"):
        tool = next((t for t in info.tools if t.name == method[5:]), None) if info is not None else None
        return tool.timeout if tool is not None and tool.timeout else TOOL_TIMEOUT_S
    declared = 0.0
    if info is not None and method.startswith("service_"):
        declared = next((x.timeout for x in info.services if x.name == method[8:]), 0.0)
    elif info is not None and method in ("tick", "on_event"):
        declared = info.timeout
    return declared or p.tick_timeout_s


def due_runs(a: App, tz: Any) -> list[tuple[int, str]]:
    """Quand tournera chacun de ses services : (instant, service) — ``""`` pour le rythme principal (``tick``) ;
    rien pour une app arrêtée ou cassée, ni pour un service que le disjoncteur a arrêté."""
    if not a.enabled or a.broken:
        return []
    out: list[tuple[int, str]] = []
    rule = schedule.read(a.schedule)
    if rule.kind != "manual":
        out.append((schedule.next_after(rule, a.ticked_at or a.since, tz), ""))
    for name, every in a.services:
        if name in a.broken_services:
            continue
        r = schedule.read(every)
        if r.kind != "manual":
            out.append((schedule.next_after(r, a.ran.get(name) or a.since, tz), name))
    return [(t, n) for t, n in out if t is not None]


def next_tick(a: App, tz: Any) -> int | None:
    runs = due_runs(a, tz)
    return min(t for t, _ in runs) if runs else None


def signal_draft(app: str, summary: str, pertinence: float, emotion: str, kind: str = c.APP_SIGNAL, *,
                 about: tuple[str, ...] = (), sensitivity: int = 0) -> Any:
    return c.SIGNALED.draft(source=f"forge:{app}", kind=kind, summary=Content.of(summary[:300], level=sensitivity),
                            pertinence=pertinence, emotion=emotion, intensity=0.15 if emotion else 0.0,
                            about=about, sensitivity=sensitivity, bundle=BUNDLE, app=app)


def concerns(frame: Frame, app: App | None) -> tuple[tuple[str, ...], int]:
    """Qui concerne ce qu'une app trouve : la personne pour qui son projet existe, au niveau du projet (ADR 0104) —
    une pensée née d'une trouvaille peut alors la pousser à le lui dire ; une app sans projet : personne."""
    if app is None or not app.project:
        return (), 0
    p = next((v for v in frame.get(projects_c.LIVE) if v.id == app.project), None)
    if p is None:
        return (), 0
    about = p.about or ((p.owner,) if p.owner else tuple(frame.get(identity_c.OWNERS)[:1]))
    return tuple(about), max(p.written, p.sensitivity) if about else 0


@FORGE.process("forge.tick", wake_on=[WRITTEN, SWITCHED, *body_c.ALL], catch_up=CatchUp.ONCE,
               max_quantum_s=3600, priority=85)
class Tick:
    def next_due(self, s: ForgeState, frame: Frame, last_run: int | None) -> int | None:
        tz = frame.env.tz_of(frame.root)
        times = [t for t in (next_tick(a, tz) for a in s.apps.values()) if t is not None]
        return max(frame.now, min(times)) if times else None

    async def run(self, ctx: Any) -> None:
        port = ctx.ports.get("forge")
        frame: Frame = ctx.frame
        if port is None:
            return
        p = params(frame.env.params_of("forge", frame.root))
        tz = frame.env.tz_of(frame.root)
        due = sorted((t, name, service) for name, a in ctx.state.apps.items()
                     for t, service in due_runs(a, tz) if t <= frame.now)
        if not due:
            return
        _, name, service = due[0]  # un appel à la fois : le plus en retard d'abord
        app = ctx.state.apps[name]
        method = f"service_{service}" if service else "tick"
        r = await port.call(name, method, timeout_s=timeout_of(port.info(name), method, p), secrets=trusted(app))
        if r.busy:
            return  # un autre appel tenait l'app : le passage reste dû, il se refera
        drafts: list[Any] = [TICKED.draft(app=name, ok=r.ok, error=r.error[:300], duration_ms=r.duration_ms,
                                          service=service)]
        await ctx.emit(*drafts, *outcomes(name, app, [r], frame.now, p, concern=concerns(frame, app),
                                          service=service))


def outcomes(name: str, app: App, results: list[Any], now: int, p: ForgeParams, *, breaker: bool = True,
             concern: tuple[tuple[str, ...], int] = ((), 0), service: str = "") -> list[Any]:
    """Ce qu'un ou plusieurs appels d'une app laissent : ses émissions, ses signaux — chacun dans sa file, qu'elle lira
    selon ce que l'app déclare (ADR 0105) —, le fait public qu'une app d'un projet a signalé (ADR 0280), et le
    disjoncteur si les échecs s'accumulent (``breaker=False`` : une
    action d'opérateur, qui n'est jamais comptée contre l'app)."""
    drafts: list[Any] = [EMITTED.draft(app=name, type=t, data=data) for r in results for t, data in r.emits]
    about, level = concern
    queued = [c.QUEUED.draft(app=name, summary=Content.of(said[:300], level=level), pertinence=pertinence,
                             emotion=emotion, about=about, sensitivity=level)
              for said, pertinence, emotion in (sig for r in results for sig in r.signals)]
    drafts += queued
    if queued and app.project:
        # une app d'un projet a signalé : le fait public, sans le texte (ADR 0280) — ce qu'attend l'objectif de son
        # projet qui l'écoute. Une fois par lot d'appels, quel que soit le nombre de signaux ; le tri de la file
        # reste ce qu'il est
        drafts.append(c.RAISED.draft(app=name))
    failed = [r for r in results if not r.ok]
    if breaker and failed and service:  # un service : son disjoncteur à lui
        if app.svc_failures.get(service, 0) + 1 >= p.breaker:
            drafts.append(SWITCHED.draft(app=name, state="broken", reason=failed[-1].error, service=service))
            drafts.append(signal_draft(name, phrase("forge.signal.service_broken", app=app.title, service=service,
                                                    error=failed[-1].error[:150]), 0.7, "frustrated", c.APP_BROKEN))
        return drafts
    if breaker and failed and app.failures + 1 >= p.breaker:
        drafts.append(SWITCHED.draft(app=name, state="broken", reason=failed[-1].error))
        drafts.append(signal_draft(name, phrase("forge.signal.broken", app=app.title, error=failed[-1].error[:150]),
                                   0.7, "frustrated", c.APP_BROKEN))
    return drafts


@FORGE.process("forge.events", wake_on=[HANDLED, WRITTEN, SWITCHED, *body_c.ALL], wake_on_shapes=[attention_c.Signal],
               catch_up=CatchUp.ONCE, max_quantum_s=3600, priority=86)
class Events:
    """Remettre à chaque app ce qu'elle attend, quelques événements à la fois."""

    def next_due(self, s: ForgeState, frame: Frame, last_run: int | None) -> int | None:
        waiting = any(a.inbox and a.enabled and not a.broken for a in s.apps.values())
        return frame.now if waiting else None

    async def run(self, ctx: Any) -> None:
        port, store = ctx.ports.get("forge"), ctx.ports.get("store")
        frame: Frame = ctx.frame
        ready = [(k, a) for k, a in sorted(ctx.state.apps.items()) if a.inbox and a.enabled and not a.broken]
        if port is None or not ready:
            return
        p = params(frame.env.params_of("forge", frame.root))
        name, app = ready[0]
        batch = app.inbox[:5]
        texts = store.content([d.summary_ref for d in batch if d.summary_ref]) if store is not None else {}
        results = []
        limit = timeout_of(port.info(name), "on_event", p)
        for d in batch:
            event = {"type": d.type, "at": d.at // 1_000_000, "source": d.source, "kind": d.kind,
                     "summary": texts.get(d.summary_ref, "")}
            if d.data:
                event["data"] = d.data
            r = await port.call(name, "on_event", event, timeout_s=limit, secrets=trusted(app))
            if r.busy:
                break  # un autre appel tenait l'app : ce qui reste du lot attend dans sa boîte
            results.append(r)
        if not results:
            return
        ok = all(r.ok for r in results)
        error = next((r.error for r in results if not r.ok), "")
        await ctx.emit(HANDLED.draft(app=name, upto=batch[len(results) - 1].seq, ok=ok, error=error[:300]),
                       *outcomes(name, app, results, frame.now, p, concern=concerns(frame, app)))


@FORGE.process("forge.discover", wake_on=[], catch_up=CatchUp.ONCE, max_quantum_s=0, priority=90)
class Discover:
    """Au démarrage : les apps posées sur le disque sans être passées par elle
    (restaurées d'une sauvegarde, écrites par un opérateur) entrent dans sa vie."""

    def __init__(self) -> None:
        self.done = False

    def next_due(self, s: ForgeState, frame: Frame, last_run: int | None) -> int | None:
        return None if self.done else frame.now

    async def run(self, ctx: Any) -> None:
        self.done = True
        port = ctx.ports.get("forge")
        if port is None:
            return
        known = ctx.state.apps
        drafts = [written_draft(i, dedupe=True) for i in port.apps() if stale(known.get(i.name), i)]
        if drafts:
            await ctx.emit(*drafts)


def stale(app: App | None, info: AppInfo) -> bool:
    """Ce que sa vie sait de l'app diffère-t-il du disque ?"""
    return app is None or app.version != info.version or app.ui != info.ui or app.title != info.title \
        or app.fingerprint != info.fingerprint


def written_draft(info: AppInfo, *, dedupe: bool = False, vouched: bool = False, project: int = 0) -> Any:
    """« Cette version de l'app est dans sa vie », avec ce qu'elle déclare (``vouched`` : un opérateur l'a
    validée)."""
    key = f"forge:{info.name}:{info.version}:{hashlib.sha256(info.ui.encode()).hexdigest()[:12]}:{info.fingerprint}" \
        if dedupe else None
    return WRITTEN.draft(app=info.name, version=info.version, title=info.title, schedule=info.schedule,
                         context=info.context, events=info.events, ui=info.ui, fingerprint=info.fingerprint,
                         vouched=vouched, project=project, services=tuple((x.name, x.schedule) for x in info.services),
                         signals=(info.signals.queue, info.signals.per_call, info.signals.quota),
                         instructions=info.signals.instructions, dedupe_key=key)


# ── Ce que lisent ses outils, ceux de ses apps et la console ──────────────


def caretaker(frame: Frame) -> str:
    """Qui s'occupe d'elle, par son prénom (jamais « ta propriétaire »)."""
    return identity_c.keepers(frame, quoted=True)


def bad_args(tool: Any, errors: Mapping[str, str]) -> str:
    """Pourquoi des arguments sont refusés, argument par argument, et ce que l'outil accepte."""
    said = "; ".join(f"{k} : {v}" for k, v in sorted(errors.items()))
    return phrase("forge.tools.call.bad_args", errors=said,
                  accepted=said_args(tool.args) or phrase("forge.tools.call.no_args"))


def forge_port(ctx: Any) -> Any:
    return ctx.ports.get("forge")


def has_secrets(ports: Mapping[str, Any], info: AppInfo | None) -> bool:
    """Un opérateur lui a-t-il donné un réglage secret (une clé d'API…) ?"""
    store = ports.get("forge_settings")
    if info is None or store is None:
        return False
    values = store.values(info.name) or {}
    return any(f.kind == "secret" and values.get(f.path) for f in info.config_fields)


def stopped(app: App | None) -> str:
    """Pourquoi une app ne tourne pas (vide : elle tourne)."""
    if app is None:
        return ""
    if app.held:
        return phrase("forge.tools.stopped.held")
    if app.broken:
        return phrase("forge.tools.stopped.broken", error=app.broken[:120])
    if not app.enabled:
        return phrase("forge.tools.stopped.disabled")
    return ""


# les contributions, dans l'ordre de leurs inscriptions sur FORGE, celui de l'ancien fichier unique (la console le
# montre) : ce qu'elle dit de ses apps (qui importe la file de signaux entre ses trouvailles et la section « apps ») ;
# une version qui attend un accord (qui importe ensuite ses appels sur accord) ; les outils de ses apps et leurs
# accès ; la console (qui importe d'abord ses outils)
# isort: off
from mika.plugins.forge import prompt as prompt  # noqa: E402
from mika.plugins.forge import signals as signals  # noqa: E402
from mika.plugins.forge import install as install  # noqa: E402
from mika.plugins.forge import calls as calls  # noqa: E402
from mika.plugins.forge import access as access  # noqa: E402
from mika.plugins.forge import inspect as inspect  # noqa: E402
from mika.plugins.forge import tools as tools  # noqa: E402
# isort: on

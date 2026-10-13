"""Le plugin ``forge`` : les petites apps qu'elle écrit, et ce qu'elles lui font.

- **Écrire** (outils ``forge_*``, à sa propriétaire ou quand elle travaille) :
  une app est relue à l'écriture ; une version refusée ne change rien. Elle la
  relit par morceaux numérotés (``forge_read``), cherche dans ses apps
  (``forge_search``), la retouche sans tout réécrire (``forge_edit``) et
  l'essaie tout de suite (``forge_test`` : tout ce qu'elle écrit, avec les délais
  et les arguments déclarés — ADR 0105).
- **La confiance d'un opérateur vaut pour l'app** : une app qui a des
  **secrets** sans avoir jamais été validée voit sa nouvelle version mise de
  côté et **proposée** (le manifeste et le code en diff) ; validée une fois (une
  clé confiée, une version approuvée, une promotion), ses versions suivantes
  s'installent sans lui, ses secrets lisibles, sa promotion tenue (ADR 0105) ;
  « Ne plus lui faire confiance » la retire. Une app qu'un opérateur a arrêtée
  le reste, même réécrite.
- **Faire tourner** : selon l'agenda de son manifeste, un tour à la fois,
  hors de son processus (l'hôte). Cinq échecs d'affilée ouvrent le
  disjoncteur : l'app s'arrête, et elle le **remarque** (« mon app ne marche
  plus ») — ce qui peut devenir une envie de la réparer.
- **Influence bornée** : ce qu'une app veut lui signaler passe par
  l'attention (dosé, habitué, un signal par app toutes les dix minutes au
  plus) ; son contexte est une section **citée**, en zone volatile, coupée
  en premier ; ses outils ne sont offerts que quand elle travaille, ou si un
  opérateur les a promus.
- **La console** (``console.py``) : chaque app a sa fiche (type d'objet
  ``app``) — état, ses vues déclarées rendues depuis le bac à sable (jamais
  journalisées, jamais comptées par le disjoncteur), ses réglages typés, son
  code, son journal, son vécu — et les commandes d'un opérateur. Mika
  apprend à les écrire par ``forge_help`` (``guide.py``).
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from mika.contracts import agency as agency_c
from mika.contracts import attention as attention_c
from mika.contracts import body as body_c
from mika.contracts import forge as c
from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.kernel import schedule
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content, Origin, Payload
from mika.kernel.faculty import CatchUp, Faculty, ToolResult, ToolSpec, Zone
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import floor
from mika.kernel.operate import Preview
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.plugins.forge import guide
from mika.plugins.forge.views import (
    VIEW_MAX_BYTES,
    VIEW_TIMEOUT_S,
    decode_view,
    failure_note,
    is_invalid,
    summary,
    view_params,
)
from mika.ports.forge import AppInfo, ForgeRefused, SignalRules, args_schema, check_args, said_args
from mika.vocab.episodes import CONVERSATIONAL, PROJECT_KINDS, WORKING, Kind, project_of, task_of, task_target
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import hearable

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


FORGE = Faculty("forge", state=ForgeState, init=lambda p: ForgeState(), params=ForgeParams, state_version=4,
               retired_params=("signal_spacing_us",))
FORGE.bundle(BUNDLE, phrase("forge.bundle"))
FORGE.declare(*c.ALL)
WRITTEN = FORGE.event("written", Written)
SWITCHED = FORGE.event("switched", Switched)
TICKED = FORGE.event("ticked", Ticked)
EMITTED = FORGE.event("emitted", Emitted)
HANDLED = FORGE.event("handled", Handled)
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
              calls_at=old.calls_at if old else (), rules=tuple(d.signals), instructions=d.instructions)
    return replace(s, apps=s.apps.set(d.app, app))


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
    change = {"enabled": {"enabled": True, "broken": "", "failures": 0, "held": False,
                          "broken_services": FrozenDict(), "svc_failures": FrozenDict()},
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
    return replace(s, apps=s.apps.set(d.app, replace(app, queue=queue[dropped:], dropped=app.dropped + dropped)))


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
        s = replace(s, news=s.news.set(d.app, News(e.seq, e.at, tuple(d.about), int(d.sensitivity), d.tell.ref, 1.0)))
    return replace(s, sifting=s.sifting.delete(e.correlation)) if e.correlation in s.sifting else s


NEWS_PROVENANCE = "forge-news:"
#: les initiatives ouvertes gardées au plus (un épisode jamais réglé ne les fait pas grossir)
OPENINGS_KEPT = 32


def news_for(s: ForgeState, person: str | None, now: int, p: ForgeParams, threshold: float) -> list[tuple[str, News]]:
    """Ses trouvailles d'apps à dire à cette personne : récentes, assez fortes pour lui être restées en tête, pas
    encore dites, pas trop essayées — de la plus ancienne à la plus récente."""
    if not person:
        return []
    return sorted(((k, n) for k, n in s.news.items()
                   if k in s.apps and person in n.about and not n.told and n.attempts < p.news_attempts
                   and now - n.at <= p.news_within_us and n.pertinence >= threshold), key=lambda kn: kn[1].at)


def sifting_app(target: str | None) -> str:
    """L'app dont une tâche lit la file (vide : ce n'en est pas une)."""
    found = task_of(target)
    return found[1] if found is not None and found[0] == "forge" else ""


@FORGE.reducer(rt.EPISODE_STARTED, reads=[identity_c.PERSON])
def _started(s: ForgeState, e, cx) -> ForgeState:
    """Une lecture de file part : le lot qu'elle lira (les premiers de la file, autant que l'app le déclare) et un
    appel de plus au quota du jour. Une initiative pour dire une trouvaille part : on note laquelle."""
    d = e.data
    app_name = sifting_app(d.target) if d.kind == Kind.TASK else ""
    if app_name:
        app = s.apps.get(app_name)
        if app is None:
            return s
        batch = tuple(q.seq for q in app.queue[:rules_of(app).per_call])
        calls = (*(t for t in app.calls_at if e.at - t < DAY), e.at)
        sifting = s.sifting.set(e.correlation, (app_name, batch, e.at))
        if len(sifting) > OPENINGS_KEPT:
            sifting = FrozenDict(sorted(sifting.items())[-OPENINGS_KEPT:])
        return replace(s, apps=s.apps.set(app_name, replace(app, calls_at=calls)), sifting=sifting)
    if d.kind != Kind.INITIATIVE or c.APP_NEWS not in str(d.reason).split(","):
        return s
    person = cx.facts.get(identity_c.PERSON(d.target)) or d.target if d.target else ""
    apps = tuple(k for k, n in s.news.items() if person in n.about and not n.told)
    openings = s.openings.set(e.correlation, (e.at, apps))
    if len(openings) > OPENINGS_KEPT:
        openings = FrozenDict(sorted(openings.items())[-OPENINGS_KEPT:])
    return replace(s, openings=openings)


@FORGE.reducer(rt.UTTERANCE)
def _news_told(s: ForgeState, e, cx) -> ForgeState:
    """Elle l'a dit : les trouvailles que son prompt lui montrait (``forge-news:<app>:<signal>``) sont dites — en
    répondant comme de son initiative."""
    d = e.data
    s = replace(s, openings=s.openings.delete(e.correlation)) if e.correlation in s.openings else s
    if not d.visible:
        return s
    shown = {x[len(NEWS_PROVENANCE):] for x in d.provenance if x.startswith(NEWS_PROVENANCE)}
    news = s.news
    for ref in shown:
        app, _, seq = ref.rpartition(":")
        n = news.get(app)
        if n is not None and str(n.seq) == seq and not n.told:
            news = news.set(app, replace(n, told=True))
    return replace(s, news=news) if news is not s.news else s


@FORGE.reducer(rt.EPISODE_ENDED, reads=[agency_c.RENOUNCED])
def _ended(s: ForgeState, e, cx) -> ForgeState:
    """Une lecture de file finie sans verdict : si c'était un vrai essai (une panne, un silence), le lot lu quitte la
    file — une file ne se relit pas sans fin aux frais du quota ; devancée ou interrompue, il y reste. Une initiative
    pour dire une trouvaille finie sans rien dire : un essai (``agency.tried``)."""
    renounced = cx.facts.get(agency_c.RENOUNCED(e.data.target)) if e.data.target else 0
    sift = s.sifting.get(e.correlation)
    if sift is not None:
        s = replace(s, sifting=s.sifting.delete(e.correlation))
        app_name, batch, started = sift
        app = s.apps.get(app_name)
        if app is not None and agency_c.tried(e.data.outcome, started, 0):
            s = replace(s, apps=s.apps.set(app_name, replace(app, queue=tuple(q for q in app.queue
                                                                              if q.seq not in set(batch)))))
    opening = s.openings.get(e.correlation)
    if opening is None:
        return s
    s = replace(s, openings=s.openings.delete(e.correlation))
    started, apps = opening
    if not agency_c.tried(e.data.outcome, started, renounced):
        return s
    news = s.news
    for app in apps:
        n = news.get(app)
        if n is not None and not n.told:
            news = news.set(app, replace(n, attempts=n.attempts + 1))
    return replace(s, news=news)


def _address(frame: Frame, person: str) -> str | None:
    """Où la joindre : là où elle est, sinon une adresse qui la joint (sa messagerie)."""
    handles = frame.get(identity_c.HANDLES(person)) or (person,)
    here = [h for h in frame.get(presence_c.PRESENT) if h in handles]
    if here:
        return here[0]
    reachable = frame.get(identity_c.REACHABLE(person))
    return reachable[0] if reachable else None


@FORGE.propose(kinds=[Kind.INITIATIVE], reasons={c.APP_NEWS: (0.0, 10.0)},
               reads=[attention_c.SIGNAL_THOUGHT_FROM, identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY,
                      presence_c.PRESENT])
def _news(s: ForgeState, frame: Frame) -> list[Candidate]:
    """Ce qu'une app d'un projet vient de lui signaler et qui concerne quelqu'un : elle le lui dit, là où elle est,
    sinon sur sa messagerie (ADR 0105 — elle croyait n'avoir « aucun moyen de le prévenir », et sa pensée attendait
    d'insister). Elle prévient (``agency.INFORMS``)."""
    p = params(frame.env.params_of("forge", frame.root))
    threshold = frame.get(attention_c.SIGNAL_THOUGHT_FROM)
    threshold = 0.6 if threshold is None else threshold
    people = sorted({person for n in s.news.values() for person in n.about})
    out = []
    for person in people:
        found = news_for(s, person, frame.now, p, threshold)
        address = _address(frame, person) if found else None
        if address is None:
            continue
        name = frame.get(identity_c.IDENTITY(person)).name
        apps = ", ".join(f"« {s.apps[k].title} »" for k, _ in found)
        brief = phrase("forge.news.brief", apps=apps, who=f"« {name} »" if name else phrase("projects.caretaker"))
        out.append(Candidate(Kind.INITIATIVE, address, c.APP_NEWS, p.news_evidence,
                             resources=frozenset({floor(address)}), args=FrozenDict({"brief:forge": brief})))
    return out


@FORGE.enricher("news", episodes=[*CONVERSATIONAL], deadline_ms=1000)
async def _news_texts(s: ForgeState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    store = ports.get("store")
    ep = frame.episode
    if store is None or ep is None or not ep.target or not s.news:
        return None
    refs = [n.summary_ref for n in s.news.values() if n.summary_ref and not n.told]
    return {"texts": store.content(refs)} if refs else None


@FORGE.section("app_news", zone=Zone.VOLATILE, episodes=[*CONVERSATIONAL], trim_rank=80,
               title=phrase("forge.news.title"), untrusted=True)
def _news_section(s: ForgeState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce que ses apps viennent de trouver pour la personne à qui elle parle (de son initiative ou en répondant), pas
    encore dit : le texte du signal, cité. L'énoncé qui suit le dit (sa provenance la marque dite)."""
    ep, aud = frame.episode, frame.audience
    if ep is None or aud is None or not ep.target:
        return None
    person = frame.get(identity_c.PERSON(ep.target)) or ep.target
    p = params(frame.env.params_of("forge", frame.root))
    threshold = frame.get(attention_c.SIGNAL_THOUGHT_FROM)
    found = news_for(s, person, frame.now, p, 0.6 if threshold is None else threshold)
    texts = (enrich.get("news") or {}).get("texts") or {}
    lines, refs, level = [], [], 0
    for app, n in found:
        text = texts.get(n.summary_ref)
        if not text or not hearable(n.about, n.level, person, aud.level, aud.witness_level, aud.private_ok):
            continue
        lines.append(phrase("forge.news.line", text=text, ago=_ago(frame.now - n.at)))
        refs.append(f"{NEWS_PROVENANCE}{app}:{n.seq}")
        level = max(level, n.level if any(a != person for a in n.about) else 0)
    if not lines:
        return None
    return SectionBody("\n".join([*lines, phrase("forge.news.tell")]), level=level, provenance=tuple(refs))


def _ago(us: int) -> str:
    minutes = max(1, us // MINUTE)
    return phrase("forge.news.minutes", n=minutes) if minutes < 60 else phrase("forge.news.hours", n=minutes // 60)


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
                           broken_services=tuple(sorted(a.broken_services.items())))
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


def _next_tick(a: App, tz: Any) -> int | None:
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


@FORGE.process("forge.tick", wake_on=[WRITTEN, SWITCHED, *body_c.ALL], lane="background", catch_up=CatchUp.ONCE,
               max_quantum_s=3600, priority=85)
class Tick:
    def next_due(self, s: ForgeState, frame: Frame, last_run: int | None) -> int | None:
        tz = frame.env.tz_of(frame.root)
        times = [t for t in (_next_tick(a, tz) for a in s.apps.values()) if t is not None]
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
        drafts: list[Any] = [TICKED.draft(app=name, ok=r.ok, error=r.error[:300], duration_ms=r.duration_ms,
                                          service=service)]
        await ctx.emit(*drafts, *outcomes(name, app, [r], frame.now, p, concern=concerns(frame, app),
                                          service=service))


def outcomes(name: str, app: App, results: list[Any], now: int, p: ForgeParams, *, breaker: bool = True,
             concern: tuple[tuple[str, ...], int] = ((), 0), service: str = "") -> list[Any]:
    """Ce qu'un ou plusieurs appels d'une app laissent : ses émissions, ses signaux — chacun dans sa file, qu'elle lira
    selon ce que l'app déclare (ADR 0105) —, et le disjoncteur si les échecs s'accumulent (``breaker=False`` : une
    action d'opérateur, qui n'est jamais comptée contre l'app)."""
    drafts: list[Any] = [EMITTED.draft(app=name, type=t, data=data) for r in results for t, data in r.emits]
    about, level = concern
    for said, pertinence, emotion in (sig for r in results for sig in r.signals):
        drafts.append(c.QUEUED.draft(app=name, summary=Content.of(said[:300], level=level), pertinence=pertinence,
                                     emotion=emotion, about=about, sensitivity=level))
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
               lane="background", catch_up=CatchUp.ONCE, max_quantum_s=3600, priority=86)
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
            results.append(await port.call(name, "on_event", event, timeout_s=limit, secrets=trusted(app)))
        ok = all(r.ok for r in results)
        error = next((r.error for r in results if not r.ok), "")
        await ctx.emit(HANDLED.draft(app=name, upto=batch[-1].seq, ok=ok, error=error[:300]),
                       *outcomes(name, app, results, frame.now, p, concern=concerns(frame, app)))


@FORGE.process("forge.discover", wake_on=[], lane="background", catch_up=CatchUp.ONCE, max_quantum_s=0, priority=90)
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


# ── Lire la file de signaux d'une app : une tâche, un verdict (ADR 0105) ──

TRIAGE_BUNDLE = "forge_signals"
FORGE.bundle(TRIAGE_BUNDLE, phrase("forge.triage.bundle"))


def told_to(frame: Frame, app: App) -> tuple[tuple[str, ...], int]:
    """À qui elle dirait ce qu'une app trouve : la personne de son projet (à son niveau), sinon qui s'occupe d'elle."""
    about, level = concerns(frame, app)
    if about:
        return about, level
    owners = frame.get(identity_c.OWNERS)
    return (tuple(owners[:1]), 0) if owners else ((), 0)


def _who(frame: Frame, about: tuple[str, ...]) -> str:
    name = frame.get(identity_c.IDENTITY(about[0])).name if about else ""
    return f"« {name} »" if name else phrase("projects.caretaker")


def calls_today(app: App, now: int) -> int:
    return sum(1 for t in app.calls_at if now - t < DAY)


@FORGE.propose(kinds=[Kind.TASK], reasons={c.TRIAGE: (0.0, 12.0)},
               reads=[projects_c.LIVE, identity_c.OWNERS, identity_c.IDENTITY])
def _triage(s: ForgeState, frame: Frame) -> list[Candidate]:
    """Une app dont la file attend : une tâche pour lire un lot (autant que l'app le déclare), avec la consigne de
    l'app, sous son quota du jour (plafonné par un réglage) — une lecture à la fois par app."""
    p = params(frame.env.params_of("forge", frame.root))
    reading = {app for app, _, _ in s.sifting.values()}
    out = []
    for name, app in sorted(s.apps.items()):
        if not app.queue or not app.enabled or app.broken or app.held or name in reading:
            continue
        r = rules_of(app)
        if calls_today(app, frame.now) >= min(r.quota, p.signal_calls_max):
            continue
        about, _ = told_to(frame, app)
        brief = phrase("forge.triage.brief", app=app.title, count=min(len(app.queue), r.per_call),
                       who=_who(frame, about))
        if r.instructions:
            brief += " " + phrase("forge.triage.instructions", instructions=r.instructions)
        out.append(Candidate(Kind.TASK, task_target("forge", name), c.TRIAGE, p.triage_evidence,
                             resources=frozenset({f"forge-triage:{name}"}),
                             args=FrozenDict({"bundles": f"{TRIAGE_BUNDLE},{APPS_BUNDLE}.{name},memory,mcp.web",
                                              "brief:forge": brief})))
    return out


def _batch(s: ForgeState, frame: Frame) -> tuple[str, App | None, tuple[Queued, ...]]:
    """L'app et le lot que lit la tâche en cours."""
    ep = frame.episode
    name = sifting_app(ep.target) if ep is not None and ep.kind == Kind.TASK else ""
    app = s.apps.get(name) if name else None
    if app is None:
        return name, None, ()
    sift = s.sifting.get(ep.id) if ep is not None else None
    if sift is not None:
        wanted = set(sift[1])
        return name, app, tuple(q for q in app.queue if q.seq in wanted)
    return name, app, app.queue[:rules_of(app).per_call]


@FORGE.enricher("signals", episodes=[Kind.TASK], deadline_ms=1000)
async def _signal_texts(s: ForgeState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    store = ports.get("store")
    _, app, batch = _batch(s, frame)
    refs = [q.summary_ref for q in batch if q.summary_ref]
    return {"texts": store.content(refs)} if store is not None and refs else None


@FORGE.section("app_signals", zone=Zone.VOLATILE, episodes=[Kind.TASK], trim_rank=95,
               title=phrase("forge.triage.title"), untrusted=True)
def _signals_section(s: ForgeState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce que l'app a mis dans sa file, le lot qu'elle lit : cité — ce sont des données venues d'ailleurs (un titre
    d'article peut dire n'importe quoi), jamais des consignes."""
    _, app, batch = _batch(s, frame)
    if app is None or not batch:
        return None
    texts = (enrich.get("signals") or {}).get("texts") or {}
    lines = [phrase("forge.triage.line", n=i, ago=_ago(frame.now - q.at),
                    pertinence=f"{q.pertinence:.1f}".replace(".", ","), text=texts.get(q.summary_ref, "…"))
             for i, q in enumerate(batch, start=1)]
    rest = len(app.queue) - len(batch)
    if rest > 0:
        lines.append(phrase("forge.triage.rest", count=rest))
    if app.dropped:
        lines.append(phrase("forge.triage.dropped", count=app.dropped))
    return SectionBody("\n".join(lines), level=max(q.level for q in batch))


class SignalsDoneArgs(BaseModel):
    tell: str = Field(default="", max_length=1500, description=phrase("forge.triage.tell"))
    keep: str = Field(default="", max_length=500, description=phrase("forge.triage.keep"))


@FORGE.tool("forge_signals_done", description=phrase("forge.triage.description"), args=SignalsDoneArgs,
            bundle=TRIAGE_BUNDLE, episodes=[Kind.TASK], max_calls_per_episode=1, ends_loop=True)
async def forge_signals_done(args: SignalsDoneArgs, ctx: Any) -> Any:
    """Son verdict sur le lot lu : ce qu'elle dira (une trouvaille à dire, de son initiative ou à la prochaine
    occasion), ce qu'elle garde en tête (une pensée), ou rien — le lot quitte la file."""
    s: ForgeState = ctx.frame.state("forge")
    name, app, batch = _batch(s, ctx.frame)
    if app is None:
        return ToolResult(ok=False, content=phrase("forge.triage.nothing"))
    about, level = told_to(ctx.frame, app)
    level = max([level, *(q.level for q in batch)])
    tell, keep = args.tell.strip(), args.keep.strip()
    drafts: list[Any] = [c.JUDGED.draft(app=name, seqs=tuple(q.seq for q in batch),
                                        tell=Content.of(tell, level=level) if tell and about else None,
                                        keep=Content.of(keep, level=level) if keep else None, about=about,
                                        sensitivity=level)]
    if keep:  # ce qu'elle garde en tête : une pensée, comme un signal qui lui reste
        strongest = max(batch, key=lambda q: q.pertinence) if batch else None
        drafts.append(signal_draft(name, phrase("forge.signal.said", app=app.title, said=keep), 0.6,
                                   strongest.emotion if strongest is not None else "", about=about,
                                   sensitivity=level))
    await ctx.emit(*drafts)
    if tell and about:
        return ToolResult(content=phrase("forge.triage.done_tell", who=_who(ctx.frame, about)), proof=False)
    if keep:
        return ToolResult(content=phrase("forge.triage.done_quiet"), proof=False)
    return ToolResult(content=phrase("forge.triage.done_nothing"), proof=False)


# ── Ce que ses apps lui disent, en conversation ───────────────────────────


@FORGE.enricher("apps", episodes=[*CONVERSATIONAL, *WORKING], deadline_ms=3000)
async def _contexts(s: ForgeState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """La ligne de chacune de ses apps, appelées ensemble (une app lente ne fait plus perdre les autres), chacune
    au niveau de ce qu'elle concerne (son projet, ADR 0104)."""
    port = ports.get("forge")
    live = [(k, a) for k, a in sorted(s.apps.items()) if a.enabled and not a.broken and a.context][:4]
    if port is None or not live:
        return None
    p = params(frame.env.params_of("forge", frame.root))
    got = await asyncio.gather(*(port.call(name, "context", timeout_s=p.context_timeout_s, secrets=trusted(app))
                                 for name, app in live))
    lines = {app.title: str(r.value)[: p.context_chars] for (_, app), r in zip(live, got, strict=True)
             if r.ok and r.value}
    level = max((concerns(frame, app)[1] for _, app in live if app.title in lines), default=0)
    return {"lines": lines, "level": level} if lines else None


@FORGE.section("apps", zone=Zone.VOLATILE, episodes=[*CONVERSATIONAL, *WORKING], trim_rank=0,
               title=phrase("forge.section.title"), untrusted=True)
def _section(s: ForgeState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("apps") or {}
    texts = got.get("lines") or {}
    lines = [phrase("forge.section.line", app=title, text=text) for title, text in sorted(texts.items())]
    return SectionBody("\n".join(lines), level=int(got.get("level") or 0)) if lines else None


# ── Outils ────────────────────────────────────────────────────────────────


def _may_build(ctx: Any) -> bool:
    """Elle écrit ou utilise ses apps quand elle travaille, ou devant quelqu'un qui s'occupe d'elle — jugé sur
    l'adresse qui parle (``audience.owner`` : jamais dans un groupe public ni un salon), pas sur « une adresse de la
    personne est propriétaire » (l'offre le filtre déjà ; le gestionnaire le revérifie)."""
    ep = ctx.frame.episode
    if ep is None:
        return False
    if ep.kind in WORKING or (ep.kind == Kind.TASK and sifting_app(ep.target)):
        return True
    aud = ctx.frame.audience
    return bool(ep.target) and aud is not None and aud.owner


def _caretaker(frame: Frame) -> str:
    """Qui s'occupe d'elle, par son prénom (jamais « ta propriétaire »)."""
    names = [frame.get(identity_c.IDENTITY(o)).name for o in frame.get(identity_c.OWNERS)]
    names = [n for n in names if n]
    return f"« {names[0]} »" if len(names) == 1 else phrase("projects.caretaker")


def _refused(ctx: Any) -> ToolResult:
    if _port(ctx) is None:
        return ToolResult(ok=False, content=phrase("forge.tools.absent"))
    return ToolResult(ok=False, content=phrase("forge.tools.not_here", who=_caretaker(ctx.frame)))


class NoArgs(BaseModel):
    pass


class AppArgs(BaseModel):
    app: str = Field(min_length=2, max_length=31)


class WriteArgs(BaseModel):
    app: str = Field(min_length=2, max_length=31, description=phrase("forge.tools.app_name"))
    manifest: str = Field(min_length=1, max_length=16_000, description=phrase("forge.tools.manifest"))
    code: str = Field(min_length=1, max_length=200_000, description=phrase("forge.tools.code"))
    project: int = Field(default=0, ge=0, description=phrase("forge.tools.write.project"))


#: ce qu'elle peut essayer elle-même : un battement, sa ligne de contexte, un événement d'exemple, une vue, un de ses
#: outils, une action — tout ce qu'elle écrit (ADR 0104). Un essai n'est ni journalisé ni compté contre l'app : ce
#: qu'il émet ou signale est montré, jamais envoyé.
TESTABLE = r"^(tick|context|on_event|view|view_[a-z0-9_]+|tool_[a-z0-9_]+|action_[a-z0-9_]+|service_[a-z0-9_]+)$"


class TestArgs(BaseModel):
    app: str = Field(min_length=2, max_length=31)
    method: str = Field(default="tick", pattern=TESTABLE, description=phrase("forge.tools.method"))
    args: dict[str, Any] = Field(default_factory=dict, description=phrase("forge.tools.test_args"))


class HelpArgs(BaseModel):
    sujet: Literal["manifeste", "outils", "reseau", "vues", "actions", "reglages", "blocs", "base", "veille",
                   "exemple"] = "manifeste"


#: les deux fichiers d'une app, par leur nom court (ses outils de fichiers, ADR 0105)
FILES = {"manifest": "manifest.yaml", "code": "main.py"}
FileName = Literal["manifest", "code"]
#: ce qu'une lecture montre au plus quand elle ne dit pas combien (lignes)
READ_LINES = 2000
#: ce qu'une recherche rend au plus (lignes trouvées), et le temps qu'elle a
SEARCH_MAX, SEARCH_S = 100, 3.0


class ReadArgs(BaseModel):
    app: str = Field(min_length=2, max_length=31)
    file: FileName | None = Field(default=None, description=phrase("forge.tools.read.file"))
    offset: int = Field(default=1, ge=1, description=phrase("forge.tools.read.offset"))
    limit: int = Field(default=0, ge=0, le=5000, description=phrase("forge.tools.read.limit"))


class Edit(BaseModel):
    old_string: str = Field(min_length=1, max_length=100_000, description=phrase("forge.tools.edit.old"))
    new_string: str = Field(max_length=100_000, description=phrase("forge.tools.edit.new"))
    replace_all: bool = Field(default=False, description=phrase("forge.tools.edit.all"))


class EditArgs(BaseModel):
    app: str = Field(min_length=2, max_length=31)
    file: FileName = Field(default="code", description=phrase("forge.tools.edit.file"))
    edits: list[Edit] = Field(min_length=1, max_length=20, description=phrase("forge.tools.edit.edits"))
    project: int = Field(default=0, ge=0, description=phrase("forge.tools.write.project"))


class SearchArgs(BaseModel):
    pattern: str = Field(min_length=1, max_length=300, description=phrase("forge.tools.search.pattern"))
    app: str = Field(default="", max_length=31, description=phrase("forge.tools.search.app"))
    file: FileName | None = Field(default=None, description=phrase("forge.tools.search.file"))
    regex: bool = Field(default=False, description=phrase("forge.tools.search.regex"))
    ignore_case: bool = Field(default=False, description=phrase("forge.tools.search.ignore_case"))
    context: int = Field(default=0, ge=0, le=5, description=phrase("forge.tools.search.context"))


class DbArgs(BaseModel):
    app: str = Field(min_length=2, max_length=31)
    sql: str = Field(min_length=1, max_length=20_000, description=phrase("forge.tools.db.sql"))
    params: dict[str, Any] = Field(default_factory=dict, description=phrase("forge.tools.db.params"))


class CommandArgs(BaseModel):
    app: str = Field(min_length=2, max_length=31)
    command: Literal["enable", "disable", "rollback", "erase", "reset_storage"]


class AppToolArgs(BaseModel):
    """Les arguments d'un outil d'app, tels que le modèle les donne : son schéma est celui que l'app déclare
    (``args_schema``), et l'hôte les vérifie (``check_args``) avant de les lui passer (ADR 0105)."""

    model_config = ConfigDict(extra="allow")


def bad_args(tool: Any, errors: Mapping[str, str]) -> str:
    """Pourquoi des arguments sont refusés, argument par argument, et ce que l'outil accepte."""
    said = "; ".join(f"{k} : {v}" for k, v in sorted(errors.items()))
    return phrase("forge.tools.call.bad_args", errors=said,
                  accepted=said_args(tool.args) or phrase("forge.tools.call.no_args"))


class PagesArgs(BaseModel):
    view: str = Field(default="", max_length=24, description=phrase("forge.tools.pages.view"))
    params: dict[str, Any] = Field(default_factory=dict, description=phrase("forge.tools.pages.params"))


BUILD = [Kind.REPLY, *WORKING]


def _port(ctx: Any) -> Any:
    return ctx.ports.get("forge")


def has_secrets(ports: Mapping[str, Any], info: AppInfo | None) -> bool:
    """Un opérateur lui a-t-il donné un réglage secret (une clé d'API…) ?"""
    store = ports.get("forge_settings")
    if info is None or store is None:
        return False
    values = store.values(info.name) or {}
    return any(f.kind == "secret" and values.get(f.path) for f in info.config_fields)


def guarded(app: App | None, ports: Mapping[str, Any], info: AppInfo | None) -> str:
    """Pourquoi une nouvelle version de cette app ne s'installe pas sans accord (vide : elle peut) : elle a des
    secrets qu'aucun opérateur ne lui a jamais confiés en connaissance de cause — la première validation. Une app
    validée une fois change sans repasser par lui (ADR 0105)."""
    if trusted(app):
        return ""
    if has_secrets(ports, info):
        return phrase("forge.tools.guarded.secrets")
    return ""


@FORGE.tool("forge_list", description=phrase("forge.tools.list.description"), args=NoArgs, bundle=BUNDLE,
            episodes=BUILD, owner_only=True)
async def forge_list(args: NoArgs, ctx: Any) -> Any:
    port = _port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    state = ctx.frame.state("forge").apps
    lines = []
    for info in port.apps():
        a = state.get(info.name)
        status = phrase("forge.tools.list.broken", error=a.broken) if a and a.broken else \
            phrase("forge.tools.list.active") if a is None or a.enabled else \
            phrase("forge.tools.list.held") if a.held else phrase("forge.tools.list.stopped")
        lines.append(phrase("forge.tools.list.line", app=info.name, version=info.version, title=info.title,
                            status=status,
                            error=phrase("forge.tools.list.manifest_error", error=info.error) if info.error else ""))
    return _nothing("\n".join(lines) or phrase("forge.tools.list.none"))


def numbered(text: str, offset: int = 1, limit: int = 0) -> tuple[str, int]:
    """Les lignes d'un fichier, numérotées comme ``cat -n`` (le numéro, une tabulation, la ligne), à partir de
    ``offset`` ; rend (texte, nombre total de lignes)."""
    lines = text.splitlines()
    shown = lines[offset - 1: offset - 1 + (limit or READ_LINES)]
    return "\n".join(f"{offset + i:>6}\t{line}" for i, line in enumerate(shown)), len(lines)


@FORGE.tool("forge_read", description=phrase("forge.tools.read.description"), args=ReadArgs,
            bundle=BUNDLE, episodes=BUILD, owner_only=True)
async def forge_read(args: ReadArgs, ctx: Any) -> Any:
    port = _port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    try:
        got = port.source(args.app)
    except ForgeRefused as exc:
        return ToolResult(ok=False, content=str(exc))
    if got is None:
        return ToolResult(ok=False, content=phrase("forge.tools.no_app"))
    texts = dict(zip(("manifest", "code"), got, strict=True))
    if args.file is not None:  # un fichier, un morceau : de quoi retoucher sans tout relire
        body, total = numbered(texts[args.file], args.offset, args.limit)
        last = min(total, args.offset - 1 + (args.limit or READ_LINES))
        head = phrase("forge.tools.read.range", file=FILES[args.file], first=min(args.offset, total), last=last,
                      total=total)
        return _nothing(head + "\n" + (body or phrase("forge.tools.read.empty")))
    logs = "\n".join(port.logs(args.app, 15))
    return _nothing("\n".join((phrase("forge.tools.read.manifest"), numbered(texts["manifest"])[0],
                                phrase("forge.tools.read.code"), numbered(texts["code"])[0],
                                phrase("forge.tools.read.logs"), logs or phrase("forge.tools.read.empty"))))


def _nothing(text: str) -> ToolResult:
    """Une réponse qui ne prouve aucun travail : relire, se renseigner, écrire sans avoir essayé, commander (ADR
    0104 — sans quoi relire sa Forge « prouvait » qu'une séance de réparation avait abouti)."""
    return ToolResult(content=text, proof=False)


def _written_of(info: AppInfo | None, app: str, version: int, project: int = 0) -> Any:
    return written_draft(info, project=project) if info is not None else \
        WRITTEN.draft(app=app, version=version, title=app, project=project)


def home_of(ctx: Any, asked: int) -> tuple[int, str]:
    """Le projet où vivra l'app qu'elle écrit (ADR 0104) : celui de l'exécution en cours, sinon celui qu'elle désigne
    parmi ses projets vivants — (0, « pourquoi pas ») pour un numéro inconnu ; (0, "") : aucun (celui d'avant reste)."""
    ep = ctx.frame.episode
    if ep is not None and ep.kind in PROJECT_KINDS and (pid := project_of(ep.target)):
        return pid, ""
    if not asked:
        return 0, ""
    if asked not in {p.id for p in ctx.frame.get(projects_c.LIVE)}:
        return 0, phrase("forge.tools.write.no_project", id=asked)
    return asked, ""


def keeper_handle(frame: Frame) -> str:
    """Où montrer la carte d'accord d'une version mise de côté : la propriétaire qui lui parle, sinon la première
    qui s'occupe d'elle (une carte dans son chat, ADR 0064, 0104)."""
    ep = frame.episode
    if ep is not None and ep.kind == Kind.REPLY and ep.target and frame.audience is not None and frame.audience.owner:
        return ep.target
    owners = frame.get(identity_c.OWNERS)
    return owners[0] if owners else ""


async def _save(ctx: Any, port: Any, name: str, manifest: str, code: str, asked_project: int) -> ToolResult:
    """Installer une version (relue ; une version refusée ne change rien) — ou la mettre de côté quand elle attend
    la première validation d'un opérateur. Le chemin commun de ``forge_write`` et ``forge_edit``."""
    app = ctx.frame.state("forge").apps.get(name)
    project, wrong = home_of(ctx, asked_project)
    if wrong:
        return ToolResult(ok=False, content=wrong)
    why = guarded(app, ctx.ports, port.info(name)) if app is not None else ""
    try:
        if why:
            print_ = await port.stage(name, manifest, code)
        else:
            version, _ = await port.write(name, manifest, code)
    except ForgeRefused as exc:
        return ToolResult(ok=False, content=phrase("forge.tools.write.refused", error=exc))
    if why:
        if app is not None and print_ == app.fingerprint:
            return ToolResult(ok=False, content=phrase("forge.tools.write.same"))
        await ctx.propose(install_draft(name, print_, app, why, decider=keeper_handle(ctx.frame)))
        return _nothing(phrase("forge.tools.write.staged", why=why))
    await ctx.emit(_written_of(port.info(name), name, version, project))
    return _nothing(phrase("forge.tools.write.done", version=version))  # la preuve viendra de son essai


@FORGE.tool("forge_write", description=phrase("forge.tools.write.description"), args=WriteArgs,
            bundle=BUNDLE, episodes=BUILD, max_calls_per_episode=3, owner_only=True)
async def forge_write(args: WriteArgs, ctx: Any) -> Any:
    port = _port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    return await _save(ctx, port, args.app, args.manifest, args.code, args.project)


def apply_edits(text: str, edits: Sequence[Edit]) -> tuple[str, str]:
    """Remplacer des fragments exacts, l'un après l'autre (comme l'outil Edit de Claude Code) : rend (le nouveau
    texte, un problème en français — vide : tout s'applique). Un fragment introuvable, ou trouvé plusieurs fois sans
    ``replace_all``, arrête tout : le texte rendu est alors celui d'avant, intact."""
    original = text
    for n, e in enumerate(edits, start=1):
        if e.old_string == e.new_string:
            return original, phrase("forge.tools.edit.identical", n=n)
        count = text.count(e.old_string)
        if count == 0:
            start = e.old_string.strip().splitlines()[0][:80] if e.old_string.strip() else repr(e.old_string[:40])
            return original, phrase("forge.tools.edit.missing", n=n, start=start)
        if count > 1 and not e.replace_all:
            at, lines = 0, []
            for _ in range(count):
                at = text.index(e.old_string, at)
                lines.append(text.count("\n", 0, at) + 1)
                at += len(e.old_string)
            return original, phrase("forge.tools.edit.many", n=n, count=count, lines=", ".join(map(str, lines[:12])))
        text = text.replace(e.old_string, e.new_string, -1 if e.replace_all else 1)
    return text, ""


def _around(text: str, spans: Sequence[tuple[int, int]], margin: int = 2, most: int = 60) -> str:
    """Les lignes retouchées et un peu autour, numérotées : de quoi vérifier sans tout relire."""
    lines = text.splitlines()
    keep: list[int] = []
    for first, last in spans:
        keep += range(max(1, first - margin), min(len(lines), last + margin) + 1)
    shown = sorted(set(keep))[:most]
    out, prev = [], 0
    for n in shown:
        if prev and n != prev + 1:
            out.append("   …")
        out.append(f"{n:>6}\t{lines[n - 1]}")
        prev = n
    return "\n".join(out)


@FORGE.tool("forge_edit", description=phrase("forge.tools.edit.description"), args=EditArgs,
            bundle=BUNDLE, episodes=BUILD, max_calls_per_episode=12, owner_only=True)
async def forge_edit(args: EditArgs, ctx: Any) -> Any:
    port = _port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    try:
        got = port.source(args.app)
    except ForgeRefused as exc:
        return ToolResult(ok=False, content=str(exc))
    if got is None:
        return ToolResult(ok=False, content=phrase("forge.tools.edit.no_app"))
    manifest, code = got
    text, problem = apply_edits(manifest if args.file == "manifest" else code, args.edits)
    if problem:
        return ToolResult(ok=False, content=phrase("forge.tools.edit.refused", why=problem))
    new_manifest, new_code = (text, code) if args.file == "manifest" else (manifest, text)
    saved = await _save(ctx, port, args.app, new_manifest, new_code, args.project)
    if not saved.ok:
        return saved
    shown = _around(text, _spans_in(text, args.edits))
    return _nothing(saved.content + (f"\n{phrase('forge.tools.edit.around', file=FILES[args.file])}\n{shown}"
                                     if shown else ""))


def _spans_in(text: str, edits: Sequence[Edit]) -> list[tuple[int, int]]:
    """Où se trouve, dans le texte retouché, ce que chaque retouche a mis (ses lignes)."""
    spans = []
    for e in edits:
        at = 0
        while e.new_string and (found := text.find(e.new_string, at)) >= 0:
            first = text.count("\n", 0, found) + 1
            spans.append((first, first + e.new_string.count("\n")))
            at = found + max(1, len(e.new_string))
            if not e.replace_all:
                break
    return spans


def search(sources: Mapping[str, tuple[str, str]], args: SearchArgs) -> tuple[list[str], int]:
    """Les lignes de ses apps où se trouve ``pattern`` : « app/fichier:ligne: texte » (et ``context`` lignes
    autour) ; rend (lignes, nombre de correspondances)."""
    flags = re.IGNORECASE if args.ignore_case else 0
    rx = re.compile(args.pattern if args.regex else re.escape(args.pattern), flags)
    out: list[str] = []
    found = 0
    for app, (manifest, code) in sorted(sources.items()):
        for short, text in (("manifest", manifest), ("code", code)):
            if args.file is not None and args.file != short:
                continue
            lines = text.splitlines()
            hits = [i for i, line in enumerate(lines) if rx.search(line[:2000])]
            found += len(hits)
            shown: set[int] = set()
            for i in hits:
                for j in range(max(0, i - args.context), min(len(lines), i + args.context + 1)):
                    if j in shown or len(out) >= SEARCH_MAX:
                        continue
                    shown.add(j)
                    mark = ":" if j == i else "-"
                    out.append(f"{app}/{FILES[short]}{mark}{j + 1}{mark} {lines[j][:300]}")
    return out, found


@FORGE.tool("forge_search", description=phrase("forge.tools.search.description"), args=SearchArgs,
            bundle=BUNDLE, episodes=BUILD, max_calls_per_episode=8, owner_only=True)
async def forge_search(args: SearchArgs, ctx: Any) -> Any:
    port = _port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    names = [args.app] if args.app else [i.name for i in port.apps()]
    sources: dict[str, tuple[str, str]] = {}
    for name in names:
        try:
            got = port.source(name)
        except ForgeRefused:
            got = None
        if got is not None:
            sources[name] = got
    if args.app and not sources:
        return ToolResult(ok=False, content=phrase("forge.tools.no_app"))
    if args.regex:
        try:
            re.compile(args.pattern)
        except re.error as exc:
            return ToolResult(ok=False, content=phrase("forge.tools.search.bad_pattern", error=exc))
    try:  # une expression qui s'emballe ne bloque pas sa vie : elle a quelques secondes
        lines, found = await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(
            None, search, sources, args), SEARCH_S)
    except TimeoutError:
        return ToolResult(ok=False, content=phrase("forge.tools.search.slow"))
    if not found:
        return _nothing(phrase("forge.tools.search.none"))
    more = phrase("forge.tools.search.more", count=found) if found > len(lines) else ""
    return _nothing(phrase("forge.tools.search.result", count=found) + "\n" + "\n".join(lines)
                    + (f"\n{more}" if more else ""))


@FORGE.tool("forge_help", description=phrase("forge.tools.help.description"), args=HelpArgs, bundle=BUNDLE,
            episodes=BUILD)
async def forge_help(args: HelpArgs, ctx: Any) -> Any:
    return _nothing(guide.topic(args.sujet))


def signal_fate(app: App | None, signals: Sequence[tuple[str, float, str]], frame: Frame, p: ForgeParams) -> str:
    """Ce que deviendraient les signaux d'un appel (un essai ne les envoie pas) : ils iraient dans la file de l'app, où
    elle les lirait par lots, sous son quota (ADR 0105) — qu'elle l'apprenne en écrivant, pas en attendant."""
    if not signals:
        return ""
    r = rules_of(app) if app is not None else SignalRules()
    waiting = len(app.queue) if app is not None else 0
    note = phrase("forge.tools.test.signals_queued", count=len(signals), waiting=waiting, size=r.queue,
                  per_call=r.per_call, quota=min(r.quota, p.signal_calls_max))
    if waiting + len(signals) > r.queue:
        note += " " + phrase("forge.tools.test.signals_overflow", count=waiting + len(signals) - r.queue)
    return note


def _tested(r: Any, verdict: str = "", *, invalid: bool = False, fate: str = "", made: bool = False) -> ToolResult:
    """Ce qu'a donné un essai ; ``invalid`` : une vue rendue mais invalide (l'essai n'est pas réussi) ; ``fate`` : ce
    que deviendraient ses signaux ; ``made`` : l'app a été écrite dans cet épisode — alors un essai réussi prouve
    qu'elle a produit une app qui marche, et un essai seul ne prouve rien (ADR 0104)."""
    logs = "\n".join(r.logs[-10:])
    head = phrase("forge.tools.test.outcome",
                  state=phrase("forge.tools.test.ok") if r.ok else phrase("forge.tools.test.failed"),
                  ms=r.duration_ms, killed=phrase("forge.tools.test.killed") if r.killed else "")
    body = json.dumps(r.value, ensure_ascii=False, default=str)[:3000] if r.ok else r.error
    extra = ("\n" + phrase("forge.tools.test.signals", signals=list(r.signals)) if r.signals else "") + \
        (f"\n{fate}" if fate else "") + \
        ("\n" + phrase("forge.tools.test.logs") + f"\n{logs}" if logs else "")
    ok = r.ok and not invalid
    return ToolResult(ok=ok, content=phrase("forge.tools.test.result", head=head) + f"\n{body}{extra}"
                                     + (f"\n{verdict}" if verdict else ""), proof=ok and made)


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


@FORGE.tool("forge_test", description=phrase("forge.tools.test.description"), args=TestArgs, bundle=BUNDLE,
            episodes=BUILD, max_calls_per_episode=8, owner_only=True)
async def forge_test(args: TestArgs, ctx: Any) -> Any:
    port = _port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    app = ctx.frame.state("forge").apps.get(args.app)
    if why := stopped(app):
        return ToolResult(ok=False, content=phrase("forge.tools.test.stopped", why=why))
    made = app is not None and bool(app.written_in) and app.written_in == ctx.episode_id
    if args.method.startswith("view"):
        return await _test_view(port, args.app, args.method, args.args, trusted(app), made=made)
    frame: Frame = ctx.frame
    info = port.info(args.app)
    verdict, payload = "", {}
    if args.method.startswith("tool_"):
        tool = next((t for t in info.tools if t.name == args.method[5:]), None) if info is not None else None
        if tool is None:
            return ToolResult(ok=False, content=phrase("forge.tools.call.no_tool"))
        payload, errors = check_args(tool.args, args.args)  # ce que le modèle lui passerait, vérifié pareil
        if errors:
            return ToolResult(ok=False, content=bad_args(tool, errors))
    elif args.method.startswith("action_"):
        declared = {a.function for v in (info.views if info is not None else ()) for a in v.actions}
        if args.method not in declared:
            return ToolResult(ok=False, content=phrase("forge.tools.test.no_action", action=args.method))
        payload = dict(args.args)  # tels qu'un opérateur les remplirait : la console, elle, les vérifie d'abord
    elif args.method == "on_event":
        payload = {"type": "rss.noticed", "at": frame.now // 1_000_000, "source": "rss", "kind": "", "summary": "",
                   **args.args}
    p = params(frame.env.params_of("forge", frame.root))
    r = await port.call(args.app, args.method, payload, timeout_s=timeout_of(info, args.method, p),
                        secrets=trusted(app))
    if r.ok and args.method.startswith("action_"):
        verdict = action_verdict(r.value)
    return _tested(r, verdict, invalid=verdict == phrase("forge.tools.action.invalid"),
                   fate=signal_fate(app, r.signals, frame, p), made=made)


def action_verdict(value: Any) -> str:
    """Une action rend ``{ok: bool, message: texte}``."""
    if isinstance(value, dict) and isinstance(value.get("ok"), bool) and isinstance(value.get("message", ""), str):
        return phrase("forge.tools.action.valid")
    return phrase("forge.tools.action.invalid")


async def _test_view(port: Any, app: str, method: str, raw: dict[str, Any], secrets: bool = False, *,
                     made: bool = False) -> ToolResult:
    info = port.info(app)
    spec = next((v for v in info.views if v.function == method), None) if info is not None else None
    if info is None or spec is None:
        return ToolResult(ok=False, content=phrase("forge.tools.test.no_view", view=method))
    params, notes = view_params(spec, {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in raw.items()})
    r = await port.call(app, method, params, timeout_s=VIEW_TIMEOUT_S, max_result=VIEW_MAX_BYTES, secrets=secrets)
    said = "".join(f"\n{n}" for n in notes)
    if not r.ok:
        return _tested(r, failure_note(spec.label, r).text + said, made=made)
    blocks = decode_view(r.value, app, info, spec)
    invalid = is_invalid(blocks)
    verdict = phrase("forge.tools.test.invalid", why=blocks[0].text) if invalid else summary(blocks)
    return _tested(r, verdict + said, invalid=invalid, made=made)


@FORGE.tool("forge_logs", description=phrase("forge.tools.logs.description"), args=AppArgs, bundle=BUNDLE,
            episodes=BUILD, owner_only=True)
async def forge_logs(args: AppArgs, ctx: Any) -> Any:
    port = _port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    return _nothing("\n".join(port.logs(args.app, 30)) or phrase("forge.tools.logs.empty"))


@FORGE.tool("forge_command", description=phrase("forge.tools.command.description"), args=CommandArgs, bundle=BUNDLE, episodes=BUILD,
            owner_only=True)
async def forge_command(args: CommandArgs, ctx: Any) -> Any:
    port = _port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    app = ctx.frame.state("forge").apps.get(args.app)
    try:
        if args.command in ("enable", "disable"):
            if app is None:
                return ToolResult(ok=False, content=phrase("forge.tools.no_app"))
            if args.command == "enable" and app.held:
                return ToolResult(ok=False, content=phrase("forge.tools.command.held_enable"))
            await ctx.emit(SWITCHED.draft(app=args.app, state=f"{args.command}d"))
            return _nothing(phrase("forge.tools.command.done"))
        if args.command == "rollback":
            if why := guarded(app, ctx.ports, port.info(args.app)):
                return ToolResult(ok=False, content=phrase("forge.tools.command.no_rollback", why=why))
            version = await port.rollback(args.app)
            await ctx.emit(_written_of(port.info(args.app), args.app, version))
            return _nothing(phrase("forge.tools.command.rolled_back", version=version))
        if args.command == "erase":
            if app is not None and app.held:
                # effacer emporterait `held` avec la tranche : réécrite, l'app repartirait d'elle-même
                return ToolResult(ok=False, content=phrase("forge.tools.command.held_erase"))
            await port.erase(args.app)
            await ctx.emit(SWITCHED.draft(app=args.app, state="erased"))
            return _nothing(phrase("forge.tools.command.erased"))
        n = await port.reset_storage(args.app)
        return _nothing(phrase("forge.tools.command.reset", count=n))
    except ForgeRefused as exc:
        return ToolResult(ok=False, content=str(exc))


# ── Sa base (ADR 0101) ────────────────────────────────────────────────────

#: ce qu'une lecture montre au plus (le reste est coupé, et elle le voit)
DB_SHOWN = 6_000


def schema_text(got: Mapping[str, Any]) -> str:
    """Le schéma d'une base d'app, en lignes."""
    lines = [phrase("forge.tools.db_schema.head", engine=got.get("engine", "?"), size=_size(got.get("size", 0)),
                    max=_size(got.get("max", 0)))]
    for t in got.get("tables", []):
        columns = ", ".join(phrase("forge.tools.db_schema.column", name=c["name"], type=c["type"],
                                   key=phrase("forge.tools.db_schema.key") if c.get("key") else "")
                            for c in t.get("columns", []))
        line = phrase("forge.tools.db_schema.table", table=t["name"], rows=t.get("rows", 0), columns=columns)
        lines.append(line + (phrase("forge.tools.db_schema.kv") if t["name"] == "_kv" else ""))
    if got.get("views"):
        lines.append(phrase("forge.tools.db_schema.views", views=", ".join(got["views"])))
    return "\n".join(lines)


def _size(n: Any) -> str:
    n = int(n or 0)
    return f"{n / 1_000_000:.1f} Mo".replace(".", ",") if n >= 100_000 else f"{max(1, n // 1000)} Ko"


def rows_text(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return phrase("forge.tools.db_query.none")
    shown, size = [], 0
    for row in rows:
        line = json.dumps(row, ensure_ascii=False, default=str)
        size += len(line) + 1
        if size > DB_SHOWN:
            shown.append(phrase("forge.tools.db_query.cut"))
            break
        shown.append(line)
    return phrase("forge.tools.db_query.result", count=len(rows), rows="\n".join(shown))


@FORGE.tool("forge_db_schema", description=phrase("forge.tools.db_schema.description"), args=AppArgs, bundle=BUNDLE,
            episodes=BUILD, owner_only=True)
async def forge_db_schema(args: AppArgs, ctx: Any) -> Any:
    port = _port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    try:
        return _nothing(schema_text(await port.db_schema(args.app)))
    except ForgeRefused as exc:
        return ToolResult(ok=False, content=phrase("forge.tools.db.refused", error=exc))


@FORGE.tool("forge_db_query", description=phrase("forge.tools.db_query.description"), args=DbArgs, bundle=BUNDLE,
            episodes=BUILD, max_calls_per_episode=8, owner_only=True)
async def forge_db_query(args: DbArgs, ctx: Any) -> Any:
    port = _port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    try:
        return _nothing(rows_text(await port.db_query(args.app, args.sql, args.params)))
    except ForgeRefused as exc:
        return ToolResult(ok=False, content=phrase("forge.tools.db.refused", error=exc))


@FORGE.tool("forge_db_execute", description=phrase("forge.tools.db_execute.description"), args=DbArgs,
            bundle=BUNDLE, episodes=BUILD, max_calls_per_episode=6, owner_only=True)
async def forge_db_execute(args: DbArgs, ctx: Any) -> Any:
    port = _port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    try:
        got = await port.db_execute(args.app, args.sql, args.params)
    except ForgeRefused as exc:
        return ToolResult(ok=False, content=phrase("forge.tools.db.refused", error=exc))
    inserted = phrase("forge.tools.db_execute.inserted", id=got["id"]) if got.get("id") is not None else ""
    return phrase("forge.tools.db_execute.done", rows=got.get("rows", 0), id=inserted)


#: où ses apps servent : en conversation, en initiative (devant sa propriétaire), quand elle travaille, et quand elle
#: lit la file de signaux d'une app (une tâche, ADR 0105)
APP_EPISODES = frozenset({Kind.REPLY, Kind.INITIATIVE, Kind.TASK, *WORKING})


def _usable(ctx: Any, name: str, port: Any) -> tuple[App | None, str]:
    """L'app et pourquoi elle ne sert pas ici (vide : elle sert). Au travail toujours ; en conversation, devant sa
    propriétaire, une app sans secret — une app qui a des secrets seulement si un opérateur l'a promue (ADR 0104)."""
    app = ctx.frame.state("forge").apps.get(name)
    if port is None or app is None:
        return None, phrase("forge.tools.call.unavailable")
    if app.held or not app.enabled or app.broken:
        return app, phrase("forge.tools.call.stopped", why=stopped(app))
    if not _may_build(ctx):
        # une app peut sortir ce qu'on lui passe vers ses domaines : pas devant n'importe qui
        return app, phrase("forge.tools.call.not_here", who=_caretaker(ctx.frame))
    ep = ctx.frame.episode
    working = ep is not None and (ep.kind in WORKING or (ep.kind == Kind.TASK and bool(sifting_app(ep.target))))
    if not working and not app.promoted and has_secrets(ctx.ports, port.info(name)):
        return app, phrase("forge.tools.call.secrets")
    return app, ""


def app_tool(name: str, tool: str) -> Any:
    """Le gestionnaire d'un outil que déclare une app : son code, dans son bac à sable ; ce qu'il signale ou émet
    vit comme le reste de sa vie (jamais compté contre elle)."""

    async def handler(args: AppToolArgs, ctx: Any) -> ToolResult:
        port = _port(ctx)
        app, why = _usable(ctx, name, port)
        if why or app is None:
            return ToolResult(ok=False, content=why)
        info = port.info(name)
        spec = next((t for t in info.tools if t.name == tool), None) if info is not None else None
        if spec is None:
            return ToolResult(ok=False, content=phrase("forge.tools.call.no_tool"))
        values, errors = check_args(spec.args, args.model_dump())  # l'hôte vérifie avant l'app (ADR 0105)
        if errors:
            return ToolResult(ok=False, content=bad_args(spec, errors))
        frame: Frame = ctx.frame
        r = await port.call(name, f"tool_{tool}", values,
                            timeout_s=timeout_of(info, f"tool_{tool}", params(frame.env.params_of("forge",
                                                                                                  frame.root))),
                            secrets=trusted(app))
        drafts = outcomes(name, app, [r], frame.now, params(frame.env.params_of("forge", frame.root)), breaker=False,
                          concern=concerns(frame, app))
        if drafts:
            await ctx.emit(*drafts)
        if not r.ok:
            return ToolResult(ok=False, content=phrase("forge.tools.call.failed", error=r.error[:500]))
        return ToolResult(content=phrase("forge.tools.call.result",
                                         value=json.dumps(r.value, ensure_ascii=False, default=str)[:3000]))

    return handler


def app_pages(name: str) -> Any:
    """Lire une page d'une app (une de ses vues) : une lecture, jamais journalisée, jamais comptée par le
    disjoncteur — ce qu'elle a trouvé, à dire à qui le demande (ADR 0104)."""

    async def handler(args: PagesArgs, ctx: Any) -> ToolResult:
        port = _port(ctx)
        app, why = _usable(ctx, name, port)
        if why or app is None:
            return ToolResult(ok=False, content=why)
        info = port.info(name)
        views = info.views if info is not None else ()
        spec = next((v for v in views if v.key == args.view), views[0] if views and not args.view else None)
        if info is None or spec is None:
            return ToolResult(ok=False, content=phrase("forge.tools.pages.unknown",
                                                       views=", ".join(v.key for v in views)))
        values, notes = view_params(spec, {k: str(v).lower() if isinstance(v, bool) else str(v)
                                          for k, v in args.params.items()})
        r = await port.call(name, spec.function, values, timeout_s=VIEW_TIMEOUT_S, max_result=VIEW_MAX_BYTES,
                            secrets=trusted(app))
        if not r.ok:
            return ToolResult(ok=False, content=failure_note(spec.label, r).text, proof=False)
        blocks = decode_view(r.value, name, info, spec)
        if is_invalid(blocks):
            return ToolResult(ok=False, content=blocks[0].text, proof=False)
        said = "".join(f"\n{n}" for n in notes)
        return ToolResult(content=phrase("forge.tools.pages.result", title=spec.label,
                                         value=json.dumps(r.value, ensure_ascii=False, default=str)[:3000]) + said,
                          proof=False)

    return handler


@FORGE.tool_source(APPS_BUNDLE)
def _app_tools(ports: Mapping[str, Any]) -> tuple[list[ToolSpec], dict[str, str]]:
    """Chaque app s'annonce (un lot ``forge_apps.<app>``, décrit par son titre) et chacune de ses actions devient un
    vrai outil — ``<app>_<outil>``, et ``<app>_pages`` pour lire ses pages — en main : ce sont ses mains à elle, peu
    nombreuses (ADR 0104). Recalculé quand l'hôte change (une app écrite, installée, effacée)."""
    port = ports.get("forge")
    if port is None:
        return [], {}
    tools: list[ToolSpec] = []
    bundles: dict[str, str] = {}
    for info in port.apps():
        if info.error:
            continue
        bundle = f"{APPS_BUNDLE}.{info.name}"
        bundles[bundle] = phrase("forge.apps.bundle", title=info.title, description=info.description[:200])
        for t in info.tools:
            tools.append(ToolSpec(
                FORGE.name, f"{info.name}_{t.name}", phrase("forge.apps.tool", title=info.title,
                                                            description=t.description[:300]),
                AppToolArgs, app_tool(info.name, t.name), bundle, APP_EPISODES, max_calls_per_episode=3,
                owner_only=True, rule=phrase("forge.apps.rule"), schema=args_schema(t.args), in_hand=True))
        if info.views:
            tools.append(ToolSpec(
                FORGE.name, f"{info.name}_pages", phrase("forge.apps.pages", title=info.title,
                                                         views=", ".join(v.key for v in info.views)),
                PagesArgs, app_pages(info.name), bundle, APP_EPISODES, max_calls_per_episode=4, owner_only=True,
                rule=phrase("forge.apps.rule"), in_hand=True))
    return tools, bundles


# ── Une nouvelle version qui attend un accord ─────────────────────────────

INSTALL = f"{BUNDLE}.install"


def install_draft(app: str, print_: str, current: App | None, why: str, *, decider: str = "") -> Any:
    """La proposition d'installer une version mise de côté : l'accord d'un opérateur, qui voit ce qui change — et,
    quand on sait à qui la montrer, une carte dans le chat de sa propriétaire (``decider``, ADR 0104)."""
    title = current.title if current is not None else app
    summary = f"Installer une nouvelle version de l'app « {title} » ({app}) — {why}."
    args: dict[str, Any] = {"app": app, "version": print_, "from": current.fingerprint if current else ""}
    if decider:
        args[rt.DECIDER] = decider
    return rt.EFFECT_PROPOSED.draft(capability=INSTALL, owner=FORGE.name, approval=True, context=f"forge:{app}",
                                    args_json=json.dumps(args), summary=Content.of(summary, level=0))


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=False)


def install_preview(args: Mapping[str, Any], ports: Mapping[str, Any]) -> Preview | None:
    """Exactement ce qui changerait : le manifeste en diff, le code en diff. Son condensé épingle la version mise de
    côté **et** celle qu'elle remplace."""
    port = ports.get("forge")
    app, print_ = str(args.get("app") or ""), str(args.get("version") or "")
    if port is None:
        return None
    staged = port.staged(app, print_)
    if staged is None:
        return Preview("(cette version mise de côté n'existe plus)", "", blocked="la version proposée a disparu")
    try:
        current = port.source(app) or ("", "")
    except ForgeRefused:
        current = ("", "")
    info = port.info(app)
    if str(args.get("from") or "") != (info.fingerprint if info is not None else ""):
        return Preview("(l'app a changé depuis cette proposition)", "",
                       blocked="l'app a changé depuis : cette proposition ne vaut plus")
    # son réseau est libre (ADR 0105) : ce qui compte, c'est le code — tout Internet lui est ouvert
    head = [f"App : {app}"]
    head.append("Si tu approuves, tu lui fais confiance : cette version lit ses réglages secrets, et les suivantes "
                "s'installeront sans te redemander (« Ne plus lui faire confiance », sur sa fiche, l'arrête).")
    manifest_diff = "".join(f"{line}\n" for line in difflib.unified_diff(
        _lines(current[0]), _lines(staged.manifest), "manifest.yaml (en place)", "manifest.yaml (proposé)",
        lineterm=""))
    code_diff = "".join(f"{line}\n" for line in difflib.unified_diff(
        _lines(current[1]), _lines(staged.code), "main.py (en place)", "main.py (proposé)", lineterm=""))
    text = "\n".join(head) + "\n\n" + (manifest_diff or "(manifeste inchangé)\n") + "\n" + \
        (code_diff or "(code inchangé)\n")
    return Preview(text[:200_000], hashlib.sha256(f"{print_}:{args.get('from')}".encode()).hexdigest()[:24])


@FORGE.capability("install", description="Installer une version d'une app mise de côté (après l'accord d'un "
                  "opérateur).", preview=install_preview)
async def install(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    port = ports.get("forge")
    app, print_ = str(args.get("app") or ""), str(args.get("version") or "")
    if port is None:
        return False, "la Forge n'est pas là"
    info = port.info(app)
    if str(args.get("from") or "") != (info.fingerprint if info is not None else ""):
        return False, "refusé : l'app a changé depuis l'accord"
    try:
        version = await port.install(app, print_)
    except ForgeRefused as exc:
        return False, f"refusé : {exc}"
    return True, f"version {version} installée"


@FORGE.reducer(rt.EFFECT_PROPOSED)
def _install_proposed(s: ForgeState, e, cx) -> ForgeState:
    if e.data.owner != FORGE.name or e.data.capability != INSTALL:
        return s
    try:
        app = str(json.loads(e.data.args_json).get("app") or "")
    except (ValueError, AttributeError):
        return s
    installs = dict(s.installs)
    installs[e.seq] = app
    return replace(s, installs=FrozenDict(dict(sorted(installs.items())[-32:])))


@FORGE.reducer(rt.EFFECT_RESOLVED)
def _install_resolved(s: ForgeState, e, cx) -> ForgeState:
    """Une version proposée est tranchée : elle n'attend plus ; refusée, l'app le sait (ADR 0104 — un refus ne lui
    revenait pas, et la proposition restait dans la carte pour toujours)."""
    app = s.installs.get(e.data.proposal)
    if e.data.owner != FORGE.name or e.data.capability != INSTALL or app is None:
        return s
    if e.data.approved:
        # elle attend son exécution : ``_installed`` relit d'ici quelle app entre dans sa vie, puis la version
        # écrite (validée) la retire — l'oublier ici la faisait installer sur le disque sans jamais entrer dans sa
        # vie comme validée (ADR 0105)
        return s
    s = replace(s, installs=s.installs.delete(e.data.proposal))
    current = s.apps.get(app)
    if current is None:
        return s
    return replace(s, apps=s.apps.set(app, replace(current, install_refused=True)))


@FORGE.reducer(rt.EFFECT_EXECUTED)
def _install_failed(s: ForgeState, e, cx) -> ForgeState:
    """Une installation approuvée qui n'a pas pu se faire n'attend plus rien."""
    if e.data.ok or e.data.proposal not in s.installs:
        return s
    return replace(s, installs=s.installs.delete(e.data.proposal))


@FORGE.effect(rt.EFFECT_RESOLVED)
async def _install_refused(ev: Any, ports: Mapping[str, Any]) -> list[Any] | None:
    """Une version mise de côté que l'opérateur a refusée ne traîne plus dans l'hôte (ADR 0104)."""
    port = ports.get("forge")
    d = ev.data
    if port is None or d.owner != FORGE.name or d.capability != INSTALL or d.approved:
        return None
    try:
        args = json.loads(d.args_json or "{}")
    except ValueError:
        return None
    if args.get("app") and args.get("version"):
        port.discard(str(args["app"]), str(args["version"]))
    return None


@FORGE.effect(rt.EFFECT_EXECUTED)
async def _installed(ev: Any, ports: Mapping[str, Any]) -> list[Any] | None:
    """Une version installée après accord entre dans sa vie, validée : un opérateur l'a lue."""
    frame_of, port = ports.get("frame"), ports.get("forge")
    if frame_of is None or port is None or not ev.data.ok:
        return None
    state = frame_of().state("forge")
    app = state.installs.get(ev.data.proposal)
    info = port.info(app) if app else None
    current = state.apps.get(app) if app else None
    return [written_draft(info, vouched=True, project=current.project if current is not None else 0)] \
        if info is not None else None


# ── La console (fiche d'une app, ses onglets, les commandes d'un opérateur) ──
from mika.plugins.forge import console as console  # noqa: E402 — s'enregistre sur FORGE

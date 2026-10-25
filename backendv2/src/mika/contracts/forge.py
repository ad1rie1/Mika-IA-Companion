"""Contrat du plugin ``forge`` : les apps qu'elle écrit elle-même.

Ce qu'une app veut porter à son attention est un **signal** (dosé, habitué,
cité) ; une app cassée aussi (« mon app ne marche plus »), qui peut devenir
une envie de la réparer. Le code et les données des apps vivent hors du
journal (le monde) ; le journal garde ce qu'elle a fait : écrire, activer,
et ce que ses apps lui ont signalé.
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.contracts.attention import Signal
from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey

OWNER = "forge"
APP_SIGNAL, APP_BROKEN = "app", "broken"
#: la raison d'une initiative : dire à la personne que son projet concerne ce qu'une de ses apps vient de lui signaler
#: (ADR 0105) — elle prévient (``agency.INFORMS``) : la personne attend qu'on la prévienne, ce n'est pas une relance
APP_NEWS = "app_news"
#: … ce qu'elle a jugé urgent (un danger, une alerte, ce qui le touche de près, maintenant) : ça ouvre le dialogue même
#: avec qui ne lui répond plus (``agency.INFORMS``, sans attendre de réponse — 2026-10-19). Une trouvaille ordinaire
#: (une nouvelle, une curiosité), elle, attend qu'il ait répondu à ce qu'elle lui a déjà écrit
#: (``agency.WAITS_FOR_AN_ANSWER``).
APP_ALERT = "app_alert"


#: la raison d'une tâche : lire ce qu'une app a mis dans sa file de signaux, juger, et prévenir (ADR 0105)
TRIAGE = "app_triage"
#: appeler un outil d'app après un accord (ADR 0133), et la raison de l'initiative due qui dit ce qu'il a rendu, à qui
#: l'avait demandé (comme un service extérieur, ``mcp.ANSWERED_REASON``)
CALL = "forge.call"
ANSWERED_REASON = "app_answered"
#: un appel d'app sur accord dont l'issue n'est pas encore dite (par proposition)
UNTOLD = FactFamily("forge.untold", arg=int, type=bool, doc="l'issue d'un appel d'app sur accord pas encore dite")


class AppSignaled(Signal):
    app: str


class SignalQueued(Payload):
    """Un signal d'une app entre dans sa file (ADR 0105) : il y attend qu'elle le lise, seul ou en lot, selon ce que
    l'app déclare (``signals`` de son manifeste)."""

    app: str
    summary: Content
    pertinence: float
    emotion: str = ""
    #: qui il concerne (la personne du projet où vit l'app), à son niveau
    about: tuple[str, ...] = ()
    sensitivity: int = 1


class SignalsJudged(Payload):
    """Ce qu'elle a fait d'un lot de la file : ce qu'elle dira à la personne (``tell``), ce qu'elle garde en tête
    (``keep``), ou rien — les signaux lus (``seqs``) quittent la file."""

    app: str
    seqs: tuple[int, ...]
    tell: Content | None = None
    keep: Content | None = None
    about: tuple[str, ...] = ()
    sensitivity: int = 1
    #: ce qu'elle dira ne peut pas attendre qu'il lui réponde (``APP_ALERT``)
    urgent: bool = False


class AppAnswered(Payload):
    """Ce qu'un appel d'outil d'app fait après accord a rendu : un contenu (l'oubli l'atteint), pour qu'elle le dise à
    qui l'avait demandé."""

    proposal: int
    ok: bool
    text: Content
    about: tuple[str, ...] = ()


SIGNALED = event_type("forge.signaled", OWNER, AppSignaled, public=True, content=("summary",))
QUEUED = event_type("forge.queued", OWNER, SignalQueued, content=("summary",), subjects=("about",))
JUDGED = event_type("forge.judged", OWNER, SignalsJudged, content=("tell", "keep"), subjects=("about",))
ANSWERED = event_type("forge.answered", OWNER, AppAnswered, content=("text",), subjects=("about",))
ALL = (SIGNALED, QUEUED, JUDGED, ANSWERED)


@dataclass(frozen=True, slots=True)
class AppView:
    name: str
    title: str
    version: int
    enabled: bool
    broken: str
    failures: int
    promoted: bool
    context: bool
    schedule: str
    #: le projet où elle vit (0 : aucun), ce qui attend un opérateur, son dernier battement (ADR 0104)
    project: int = 0
    held: bool = False
    pending: bool = False
    refused: bool = False
    ticked_at: int = 0
    #: ses services, et ceux que le disjoncteur a arrêtés : (nom, pourquoi) — l'app tourne encore (ADR 0104)
    services: tuple[str, ...] = ()
    broken_services: tuple[tuple[str, str], ...] = ()


def failure(app: AppView) -> str:
    """Ce qui ne marche plus dans une app (vide : rien) : elle entière, sinon ses services arrêtés (ADR 0104)."""
    if app.broken:
        return app.broken
    return " ; ".join(f"{name} : {why}" for name, why in app.broken_services)


#: Ses apps, par nom.
APPS = FactKey("forge.apps", type=tuple)

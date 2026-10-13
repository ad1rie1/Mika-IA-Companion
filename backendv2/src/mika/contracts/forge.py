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
from mika.kernel.facts import FactKey

OWNER = "forge"
APP_SIGNAL, APP_BROKEN = "app", "broken"
#: la raison d'une initiative : dire à la personne que son projet concerne ce qu'une de ses apps vient de lui signaler
#: (ADR 0105) — elle prévient (``agency.INFORMS``) : la personne attend qu'on la prévienne, ce n'est pas une relance
APP_NEWS = "app_news"


#: la raison d'une tâche : lire ce qu'une app a mis dans sa file de signaux, juger, et prévenir (ADR 0105)
TRIAGE = "app_triage"


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


SIGNALED = event_type("forge.signaled", OWNER, AppSignaled, public=True, content=("summary",))
QUEUED = event_type("forge.queued", OWNER, SignalQueued, content=("summary",), subjects=("about",))
JUDGED = event_type("forge.judged", OWNER, SignalsJudged, content=("tell", "keep"), subjects=("about",))
ALL = (SIGNALED, QUEUED, JUDGED)


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

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
from mika.kernel.events import event_type
from mika.kernel.facts import FactKey

OWNER = "forge"
APP_SIGNAL, APP_BROKEN = "app", "broken"


class AppSignaled(Signal):
    app: str


SIGNALED = event_type("forge.signaled", OWNER, AppSignaled, public=True, content=("summary",))
ALL = (SIGNALED,)


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

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


#: Ses apps, par nom.
APPS = FactKey("forge.apps", type=tuple)

"""La faculté du noyau : démarrages, arrêts, baux, paramètres journalisés, sélections.

Les paramètres d'une faculté sont des événements (``kernel.params_changed``) :
un réducteur reçoit toujours les paramètres *en vigueur à l'instant de
l'événement*, rejeu compris.

**Ses absences** : un démarrage relève l'instant du dernier événement du journal
(``Boot.last_at``) — après un arrêt propre, ``kernel.stopped`` ; après un arrêt
brutal, la dernière chose vécue. De là à son retour, elle n'était pas là : le
noyau garde les dernières de ces absences (``kernel.absences``), à partir d'une
durée qui écarte les redémarrages de quelques secondes. Chaque faculté décide de
ce qu'elle en fait.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Annotated

from pydantic import BaseModel, ConfigDict

from mika.kernel.clock import DAY, MINUTE
from mika.kernel.events import Payload
from mika.kernel.facts import FactFamily, FactKey
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict


class KernelParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tz: Annotated[str, Knob(label="Fuseau horaire", help="Celui de sa persona (un réglage, jamais une surcharge) : "
                                                         "ses heures, ses nuits, ses rappels se lisent dans ce "
                                                         "fuseau.")] = "UTC"
    absence_min_us: Annotated[int, Knob(
        label="Une absence à partir de", lo=MINUTE, hi=DAY,
        help="Un arrêt du serveur au moins aussi long compte comme une absence : elle sait qu'elle n'était pas là, "
             "de quand à quand. Plus court (un redémarrage), il ne laisse aucune trace.")] = 20 * MINUTE


@dataclass(frozen=True, slots=True)
class Lease:
    holder: str
    until: int


@dataclass(frozen=True, slots=True)
class ParamsRecord:
    version: int
    data: str  # JSON canonique des paramètres


@dataclass(frozen=True, slots=True)
class Absence:
    """Un temps où elle n'était pas là : de son dernier instant vécu (``since``) à son retour (``until``)."""

    since: int
    until: int


#: au plus tant d'absences gardées (les plus récentes)
ABSENCES_KEPT = 8


@dataclass(frozen=True, slots=True)
class KernelState:
    boots: int = 0
    leases: FrozenDict[str, Lease] = field(default_factory=FrozenDict)
    params: FrozenDict[str, ParamsRecord] = field(default_factory=FrozenDict)
    selections: int = 0
    #: ses dernières absences, de la plus ancienne à la plus récente
    absences: tuple[Absence, ...] = ()


class Boot(Payload):
    """Un démarrage. Les champs ajoutés après coup ont un défaut : un journal plus ancien se relit tel quel."""

    code: str = ""
    #: l'instant du dernier événement du journal au démarrage (0 : inconnu, ou sa première vie)
    last_at: int = 0


class Stopped(Payload):
    """Un arrêt propre : son absence commence là (après un arrêt brutal, au dernier événement vécu)."""


class LeaseAcquired(Payload):
    resource: str
    holder: str
    until: int


class LeaseReleased(Payload):
    resource: str
    holder: str


class ParamsChanged(Payload):
    owner: str
    data: str


class RowRecord(Payload):
    """Une ligne de la table d'arbitrage : ``score = Σ parts + shift + aging − threshold``.

    Les champs ajoutés après coup ont un défaut : un journal plus ancien se
    relit tel quel (ses lignes y valent 0)."""

    kind: str
    target: str
    parts: tuple[tuple[str, str, float], ...]
    shift: float
    vetoes: tuple[tuple[str, str], ...]
    score: float
    hazard: float
    #: le seuil du type d'épisode, soustrait au score
    threshold: float = 0.0
    #: ce qu'a ajouté l'attente de la ligne (vieillissement)
    aging: float = 0.0
    #: le décalage de chaque modulateur (par propriétaire) ; leur somme est ``shift``
    shifts: tuple[tuple[str, float], ...] = ()


class Selected(Payload):
    """Une occurrence acceptée : les premières lignes de la table (et toujours
    celle qui a été choisie), la borne d'amincissement et l'intensité totale."""

    rows: tuple[RowRecord, ...]
    fired: tuple[str, ...]
    draw: float
    #: le nombre de lignes de la table entière (``rows`` n'en garde que le haut)
    candidates: int = 0
    #: la borne de l'amincissement (occurrence acceptée si ``draw · bound < total``)
    bound: float = 0.0
    #: l'intensité totale Σλ au moment du tirage
    total: float = 0.0


KERNEL = Faculty(
    "kernel",
    state=KernelState,
    init=lambda p: KernelState(),
    params=KernelParams,
)

BOOT = KERNEL.event("kernel.boot", Boot, public=True)
STOPPED = KERNEL.event("kernel.stopped", Stopped, public=True)
LEASE_ACQUIRED = KERNEL.event("kernel.lease_acquired", LeaseAcquired, public=True)
LEASE_RELEASED = KERNEL.event("kernel.lease_released", LeaseReleased, public=True)
PARAMS_CHANGED = KERNEL.event("kernel.params_changed", ParamsChanged, public=True)
SELECTED = KERNEL.event("kernel.selected", Selected, public=True)

LEASE = FactFamily(
    "kernel.lease", arg=str, type=Lease, time_varying=True,
    doc="Le bail en cours (non expiré) sur une ressource, ou None.",
)
BOOTS = FactKey("kernel.boots", type=int)
ABSENCES = FactKey(
    "kernel.absences", type=tuple,
    doc="Ses dernières absences (``Absence`` : de son dernier instant vécu à son retour), de la plus ancienne à la "
        "plus récente ; seulement celles d'au moins ``absence_min_us``.",
)


@KERNEL.reducer(BOOT)
def _boot(s: KernelState, e, cx) -> KernelState:
    """Un démarrage : les baux d'avant tombent ; s'il revient d'un arrêt assez long (le dernier instant vécu est
    connu), c'est une absence."""
    s = replace(s, boots=s.boots + 1, leases=FrozenDict())
    p: KernelParams = cx.params if cx.params is not None else KernelParams()
    since = e.data.last_at
    if not since or e.at - since < p.absence_min_us:
        return s
    return replace(s, absences=(*s.absences, Absence(since, e.at))[-ABSENCES_KEPT:])


@KERNEL.reducer(LEASE_ACQUIRED)
def _lease_acquired(s: KernelState, e, cx) -> KernelState:
    current = s.leases.get(e.data.resource)
    if current is not None and current.holder != e.data.holder and current.until > e.at:
        return s  # transition illégale : sans effet (la garde aurait dû la refuser)
    return replace(s, leases=s.leases.set(e.data.resource, Lease(e.data.holder, e.data.until)))


@KERNEL.reducer(LEASE_RELEASED)
def _lease_released(s: KernelState, e, cx) -> KernelState:
    current = s.leases.get(e.data.resource)
    if current is None or current.holder != e.data.holder:
        return s
    return replace(s, leases=s.leases.delete(e.data.resource))


@KERNEL.reducer(PARAMS_CHANGED)
def _params_changed(s: KernelState, e, cx) -> KernelState:
    previous = s.params.get(e.data.owner)
    version = 1 if previous is None else previous.version + 1
    return replace(s, params=s.params.set(e.data.owner, ParamsRecord(version, e.data.data)))


@KERNEL.reducer(SELECTED)
def _selected(s: KernelState, e, cx) -> KernelState:
    return replace(s, selections=s.selections + 1)


@KERNEL.fact(LEASE)
def _lease(s: KernelState, cx, resource: str) -> Lease | None:
    lease = s.leases.get(resource)
    if lease is None or lease.until <= cx.now:
        return None
    return lease


@KERNEL.fact(BOOTS)
def _boots(s: KernelState, cx) -> int:
    return s.boots


@KERNEL.fact(ABSENCES)
def _absences(s: KernelState, cx) -> tuple[Absence, ...]:
    return s.absences

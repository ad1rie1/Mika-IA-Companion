"""Le ``Frame`` : une vue épinglée sur une racine d'état, à un instant.

Rien de ce qu'on lit à travers un frame ne change sous lui. Il porte aussi,
pendant un épisode, l'audience résolue au bord et le contexte d'épisode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from mika.kernel.clock import local as to_local
from mika.kernel.facts import FactEnv, FactRef, FactView
from mika.kernel.state import FrozenDict, Root


@dataclass(frozen=True, slots=True)
class Audience:
    """Qui entend, résolu une fois au bord de l'épisode.

    ``level`` est le niveau de sensibilité maximal qu'on peut dire devant elle
    sur autrui (les niveaux sont nommés dans ``vocab``), ``witness_level``
    celui d'un contenu où l'interlocuteur figure lui-même, ``private_ok`` la
    porte de sa propre fiche. Toute panne de résolution doit donner
    l'audience fermée (niveaux 0, publique, fiche fermée).
    """

    persons: tuple[str, ...] = ()
    channel: str = ""
    room: str | None = None
    public: bool = True
    level: int = 0
    trust: str = ""
    witness_level: int = 0
    private_ok: bool = False
    certainty: float = 0.0
    name: str = ""
    #: l'interlocuteur est l'un de ses propriétaires (ou personne n'écoute :
    #: elle travaille pour elle) — ouvre les outils ``owner_only``
    owner: bool = False


CLOSED = Audience()


@dataclass(frozen=True, slots=True)
class EpisodeRef:
    id: str
    kind: str
    target: str | None = None
    muted_tags: frozenset[str] = frozenset()
    attrs: FrozenDict[str, Any] = field(default_factory=FrozenDict)


class Frame:
    __slots__ = ("root", "now", "env", "audience", "episode", "_view")

    def __init__(
        self,
        root: Root,
        now: int,
        env: FactEnv,
        audience: Audience | None = None,
        episode: EpisodeRef | None = None,
    ) -> None:
        self.root = root
        self.now = now
        self.env = env
        self.audience = audience
        self.episode = episode
        self._view = FactView(root, now, env)

    @property
    def seq(self) -> int:
        return self.root.seq

    @property
    def view(self) -> FactView:
        return self._view

    def get(self, ref: FactRef) -> Any:
        return self._view.get(ref)

    def fingerprint(self, ref: FactRef) -> str:
        return self._view.fingerprint(ref)

    def state(self, owner: str) -> Any:
        return self.root.slices[owner]

    def at(self, now: int) -> Frame:
        return Frame(self.root, now, self.env, self.audience, self.episode)

    def with_episode(self, episode: EpisodeRef | None, audience: Audience | None) -> Frame:
        return Frame(self.root, self.now, self.env, audience, episode)

    def local(self, t: int | None = None) -> datetime:
        return to_local(self.now if t is None else t, self.env.tz_of(self.root))

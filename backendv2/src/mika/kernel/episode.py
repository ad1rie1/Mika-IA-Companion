"""Épisodes : un pipeline fixe, des politiques par type.

Phases, dans cet ordre et jamais un autre : admission → identification (au
bord) → enrichissement (en parallèle, avec échéances) → composition → appel →
analyse → commit (gardé) → livraison (file de sortie) → règlement. Une
politique choisit *quelles* phases tournent, pas leur ordre.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mika.kernel.frame import Audience, Frame
from mika.kernel.guards import Guard


class Phase(enum.StrEnum):
    ADMIT = "admit"
    IDENTIFY = "identify"
    ENRICH = "enrich"
    COMPOSE = "compose"
    CALL = "call"
    PARSE = "parse"
    COMMIT = "commit"
    DELIVER = "deliver"
    SETTLE = "settle"


ALL_PHASES = frozenset(Phase)


class Outcome(enum.StrEnum):
    DONE = "done"
    ABSTAINED = "abstained"
    SUPERSEDED = "superseded"
    TIMEOUT = "timeout"
    FAILED = "failed"
    PREEMPTED = "preempted"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


GuardFactory = Callable[[Frame, str | None, Audience | None], Guard | None]
#: Le message final d'un épisode que personne n'a demandé (initiative, pas,
#: murmure) : la consigne « c'est toi qui prends la parole, et pourquoi ».
Brief = Callable[[Frame, Any], str]


@dataclass(frozen=True, slots=True)
class Prelude:
    """Un épisode sans destinataire qui en précède un autre (un murmure).

    ``instead`` : il le remplace — elle y pense, puis se ravise. Il passe alors
    juste après le départ gardé de l'épisode principal, qui se règle sans être
    composé (rien ne part, aucun appel de modèle perdu). Sinon, il passe une
    fois la réponse de l'épisode principal prête, juste avant son énoncé."""

    kind: str
    message: str
    reason: str = ""
    instead: bool = False


@dataclass(frozen=True, slots=True)
class EpisodePolicy:
    kind: str
    role: str | None  # rôle LLM ; None = pas d'appel de modèle
    voice: bool = True  # un rôle voix exige la persona
    persona_depth: str = "full"  # "full" | "compact"
    visible: bool = True  # écrit dans le fil de conversation
    delivered: bool = True
    lane: str = "conversation"
    priority: int = 1  # 0 = premier plan
    max_tool_turns: int = 8
    max_tokens: int = 1024
    deadline_s: float = 180.0
    tool_bundles: frozenset[str] = frozenset()
    #: les lots « en main » ; les autres lots offerts sont à la demande (le modèle
    #: les cherche quand il en a besoin). None : tout est en main.
    core_bundles: frozenset[str] | None = None
    muted_tags: frozenset[str] = frozenset()
    guard: GuardFactory | None = None
    brief: Brief | None = None
    phases: frozenset[Phase] = ALL_PHASES

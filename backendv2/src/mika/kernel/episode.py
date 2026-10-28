"""Épisodes : un pipeline fixe, des politiques par type.

Phases, dans cet ordre et jamais un autre : admission → identification (au
bord) → enrichissement (en parallèle, avec échéances) → composition → appel →
analyse → commit (gardé) → livraison (file de sortie) → règlement. Une
politique choisit *quelles* phases tournent, pas leur ordre.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass, replace
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
#: au-delà, le résultat d'un outil venu d'ailleurs (``ToolSpec.outside``) est coupé dans le fil, cité, à une frontière
#: (caractères) : au-dessus de ce qu'une page lue rend (``plugins/web`` : 20 000), pour que la borne de l'outil reste
#: celle qui compte ; un mode qui travaille sur des fichiers (le mode pro) la relève (``EpisodeMode.outside_chars``)
OUTSIDE_CHARS = 24_000
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
    persona_depth: str = "full"  # "full" | "compact" | un mode (``EpisodeMode.persona_depth``)
    visible: bool = True  # écrit dans le fil de conversation
    delivered: bool = True
    lane: str = "conversation"
    priority: int = 1  # 0 = premier plan
    max_tool_turns: int = 8
    max_tokens: int = 1024
    deadline_s: float = 180.0
    #: au plus tant de paragraphes gardés de son texte (0 : tous) — une pensée à mi-voix tient en un souffle ; ce
    #: qui suit (un message entier qu'elle rédigerait) n'est pas sa pensée
    max_paragraphs: int = 0
    #: au-delà, ce qu'un outil venu d'ailleurs rend est coupé dans le fil (``OUTSIDE_CHARS``)
    outside_chars: int = OUTSIDE_CHARS
    tool_bundles: frozenset[str] = frozenset()
    #: les lots « en main » ; les autres lots offerts sont à la demande (le modèle
    #: les cherche quand il en a besoin). None : tout est en main.
    core_bundles: frozenset[str] | None = None
    muted_tags: frozenset[str] = frozenset()
    guard: GuardFactory | None = None
    brief: Brief | None = None
    phases: frozenset[Phase] = ALL_PHASES


@dataclass(frozen=True, slots=True)
class EpisodeMode:
    """Une façon de répondre que la personne choisit pour un message (``EpisodeRequest.mode``), jamais l'arbitre :
    ce qu'elle change à la politique des épisodes de ``kinds``. Ce qu'elle laisse à ``None`` reste celui de la
    politique ; ses étiquettes coupées s'ajoutent aux siennes."""

    kinds: frozenset[str]
    #: un autre rôle de modèle (qui a son repli, comme tout rôle)
    role: str | None = None
    #: une autre profondeur de persona : le fournisseur de persona la reconnaît
    persona_depth: str | None = None
    max_tool_turns: int | None = None
    max_tokens: int | None = None
    deadline_s: float | None = None
    #: une autre borne pour ce qu'un outil venu d'ailleurs rend (un mode qui lit des fichiers entiers)
    outside_chars: int | None = None
    muted_tags: frozenset[str] = frozenset()
    #: sa parole passée une seconde fois (``polishers``), comme d'ordinaire
    polished: bool = True
    #: ses outils montrés à la personne pendant qu'elle travaille (le port ``activity``)
    live: bool = False
    #: sa réponse est du Markdown : ses blocs de code, son code en ligne et l'indentation de ses lignes passent
    #: l'analyse tels quels (elle range une parole de chat : espaces resserrés, jetons entre crochets retirés)
    markdown: bool = False
    #: la consigne du mode, à la suite de celle de ses outils
    instruction: Callable[[], str] | None = None

    def applied(self, policy: EpisodePolicy) -> EpisodePolicy:
        """La politique de l'épisode dans ce mode."""
        return replace(
            policy,
            role=self.role if self.role is not None and policy.role is not None else policy.role,
            persona_depth=self.persona_depth or policy.persona_depth,
            max_tool_turns=self.max_tool_turns if self.max_tool_turns is not None else policy.max_tool_turns,
            max_tokens=self.max_tokens if self.max_tokens is not None else policy.max_tokens,
            deadline_s=self.deadline_s if self.deadline_s is not None else policy.deadline_s,
            outside_chars=self.outside_chars if self.outside_chars is not None else policy.outside_chars,
            muted_tags=policy.muted_tags | self.muted_tags,
        )

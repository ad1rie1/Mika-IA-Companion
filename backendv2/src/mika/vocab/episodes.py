"""Types d'épisodes, rôles de modèle, étiquettes de sections.

Un **rôle voix** est un rôle où c'est elle qui écrit (répondre, prendre la
parole, travailler, murmurer, écrire son journal, rêver, se raconter) : la
passerelle exige la persona. Les **rôles utilitaires** (extraire, valider,
décrire une image…) ne parlent pas en son nom.
"""

from __future__ import annotations

import enum


class Kind(enum.StrEnum):
    REPLY = "REPLY"
    INITIATIVE = "INITIATIVE"
    STEP = "STEP"
    MURMUR = "MURMUR"
    JOURNAL = "JOURNAL"
    DREAM = "DREAM"
    NARRATIVE = "NARRATIVE"
    DECISION = "DECISION"
    #: une tâche silencieuse qu'une faculté lui confie (préparer un brouillon de réponse) : pour elle seule
    TASK = "TASK"
    #: une exécution de travail sur un projet, dans son mode à elle (sa voix, son humeur, ses avis)
    WORK = "WORK"
    #: une exécution de travail sur un projet en mode impersonnel (sans persona, sans affect)
    JOB = "JOB"
    #: un réveil par API (ADR 0068), dans son mode à elle : ce qu'un appel lui demande, pour elle seule
    WAKE = "WAKE"
    #: un réveil par API en mode impersonnel (sans persona, sans affect)
    WAKE_JOB = "WAKE_JOB"


#: Les épisodes où elle s'adresse à quelqu'un, dans le fil de conversation.
CONVERSATIONAL = frozenset({Kind.REPLY, Kind.INITIATIVE})
#: Les épisodes de travail, que personne n'écoute : une séance sur un but, une exécution sur un projet, un réveil.
WORKING = frozenset({Kind.STEP, Kind.WORK, Kind.JOB, Kind.WAKE, Kind.WAKE_JOB})
#: Les exécutions d'un projet (ses deux modes).
PROJECT_KINDS = frozenset({Kind.WORK, Kind.JOB})
#: Les réveils par API sans projet (ses deux modes, ADR 0068) : leurs outils sont ceux que le réveil a choisis.
WAKE_KINDS = frozenset({Kind.WAKE, Kind.WAKE_JOB})

#: La cible d'un épisode qui ne s'adresse à personne mais porte sur un but
#: (un pas de travail) : ``goal:12``. Personne ne l'écoute.
GOAL_PREFIX = "goal:"


def goal_target(goal: int) -> str:
    return f"{GOAL_PREFIX}{goal}"


#: La cible d'une tâche (``Kind.TASK``) : ``task:<faculté>:<objet>`` (``task:email:perso:<id@x>``).
#: Personne ne l'écoute non plus.
TASK_PREFIX = "task:"


def task_target(owner: str, key: str) -> str:
    return f"{TASK_PREFIX}{owner}:{key}"


def task_of(target: str | None) -> tuple[str, str] | None:
    """``(faculté, objet)`` d'une cible de tâche, sinon ``None``."""
    if not target or not target.startswith(TASK_PREFIX):
        return None
    owner, _, key = target[len(TASK_PREFIX):].partition(":")
    return (owner, key) if owner and key else None


def is_work_target(target: str | None) -> bool:
    """Un but, un projet ou une tâche : une cible qui n'est pas quelqu'un."""
    return goal_of(target) is not None or project_of(target) is not None or task_of(target) is not None


def goal_of(target: str | None) -> int | None:
    if not target or not target.startswith(GOAL_PREFIX):
        return None
    try:
        return int(target[len(GOAL_PREFIX):])
    except ValueError:
        return None


#: La cible d'une exécution sur un projet : ``project:7``. Personne ne l'écoute.
PROJECT_PREFIX = "project:"


def project_target(project: int) -> str:
    return f"{PROJECT_PREFIX}{project}"


def project_of(target: str | None) -> int | None:
    if not target or not target.startswith(PROJECT_PREFIX):
        return None
    try:
        return int(target[len(PROJECT_PREFIX):])
    except ValueError:
        return None


class Role(enum.StrEnum):
    # voix
    REPLY = "reply"
    INITIATIVE = "initiative"
    STEP = "step"
    MURMUR = "murmur"
    JOURNAL = "journal"
    DREAM = "dream"
    NARRATIVE = "narrative"
    #: travailler sur un projet, dans son mode à elle
    PROJECT = "project"
    # utilitaires
    #: travailler sur un projet en mode impersonnel (sans persona)
    JOB = "job"
    EXTRACT = "extract"
    VALIDATE = "validate"
    PROFILE = "profile"
    INTERPRET = "interpret"
    TRIAGE = "triage"
    CAPTION = "caption"
    COMPACT = "compact"
    PLAN = "plan"


VOICE_ROLES = frozenset({Role.REPLY, Role.INITIATIVE, Role.STEP, Role.MURMUR, Role.JOURNAL, Role.DREAM,
                         Role.NARRATIVE, Role.PROJECT})
#: Replis quand un rôle n'a pas de modèle : tout ce qui parle retombe sur la
#: réponse (le seul rôle qu'une installation neuve configure forcément).
FALLBACKS = {
    Role.INITIATIVE: Role.REPLY, Role.STEP: Role.REPLY, Role.MURMUR: Role.REPLY, Role.JOURNAL: Role.REPLY,
    Role.DREAM: Role.REPLY, Role.NARRATIVE: Role.REPLY,
    # un projet travaille d'abord avec le modèle de ses séances ; l'impersonnel, avec celui de ses projets
    Role.PROJECT: Role.STEP, Role.JOB: Role.PROJECT,
    Role.VALIDATE: Role.EXTRACT, Role.PROFILE: Role.EXTRACT, Role.INTERPRET: Role.EXTRACT,
    Role.TRIAGE: Role.EXTRACT, Role.COMPACT: Role.EXTRACT, Role.PLAN: Role.EXTRACT,
    # un seul modèle déclaré suffit : les utilitaires retombent sur celui qui répond
    Role.EXTRACT: Role.REPLY, Role.CAPTION: Role.REPLY,
}


class Tag(enum.StrEnum):
    #: Coupé en mode travail (un projet confié la veut professionnelle).
    AFFECTIVE = "affective"
    #: Ne concerne que la vie intérieure (coupé dans les voix compactes).
    INNER = "inner"

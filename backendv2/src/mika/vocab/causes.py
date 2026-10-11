"""Pourquoi elle ressent ce qu'elle ressent : un code par cause (ADR 0095).

Une évaluation (``Appraisal.reason``) porte un de ces codes ; son humeur en garde la trace (``Mark.cause``) pour
pouvoir dire d'où elle vient, par la phrase ``affect.cause.<code>`` de ``persona/voix.yaml``. Jamais un texte libre :
une raison écrite en français que la table des phrases ne connaissait pas se taisait sans que rien ne le dise
(« c'est toujours elle qui écrit », la contagion, un lien qui change, le rêve de la nuit, un projet abandonné…).

Les origines d'une pensée (``contracts.attention`` : ``exchange``, ``revision``…) et les sources d'un signal (``email``,
``rss``, ``world``…) sont aussi des causes, sous leurs propres codes ; quelques-unes se disent par la phrase d'une autre
(``ALIASES``). ``tests/architecture/test_causes_are_said.py`` vérifie que chacune a sa phrase.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

# ── Ce qui lui arrive avec les autres ─────────────────────────────────────
CAME_BACK = "came_back"  # quelqu'un qui lui manquait est revenu
ANSWERED = "answered"  # une réponse qu'elle attendait
UNANSWERED = "unanswered"  # un message resté sans réponse
BROKEN_PROMISE = "broken_promise"  # une promesse qu'elle n'a pas tenue à temps
SURPRISED = "surprised"  # quelqu'un l'a surprise
WORRIED = "worried"  # elle s'inquiète pour quelqu'un
CONTAGION = "contagion"  # l'humeur de quelqu'un avec qui elle a parlé
COMPANY = "company"  # quelqu'un est venu lui parler après un moment creux
ONE_SIDED = "one_sided"  # c'est toujours elle qui écrit la première
BOND_WARMING = "bond_warming"  # un lien qui s'approfondit
BOND_COOLING = "bond_cooling"  # un lien qui se refroidit
#: ce qu'elle a déclaré en parlant : dit selon qu'elle parle à la même personne (``talk_here``, ``talk_elsewhere``)
TALK = "talk"

# ── Ce qu'elle mène ───────────────────────────────────────────────────────
AWAITED = "awaited"  # une attente enfin comblée
ACHIEVED = "achieved"  # quelque chose qu'elle a mené à bout
STUCK = "stuck"  # quelque chose sur quoi elle bloque
GAVE_UP = "gave_up"  # quelque chose qu'elle a laissé tomber
DAYDREAM = "daydream"  # un moment où elle a laissé son esprit vagabonder
REFLECTED = "reflected"  # avoir pris le temps de repenser à ce qui pesait (une réflexion menée au bout)
OBJECTIVE_ACHIEVED = "objective_achieved"
OBJECTIVE_STUCK = "objective_stuck"
PROJECT_CLOSED = "project_closed"  # un projet refermé : il avait fait son temps
PROJECT_ABANDONED = "project_abandoned"

# ── Ce qui vient d'elle ───────────────────────────────────────────────────
THOUGHT_BACK = "thought_back"  # une pensée qui lui revient
DREAM = "dream"  # le rêve de cette nuit, dont elle se souvient
DREAM_FORGOTTEN = "dream_forgotten"  # un rêve dont il ne lui reste qu'une couleur
DIGESTION = "digestion"  # la nuit a apaisé ce qui pesait

# ── Ce qu'elle attend (ADR 0086) ──────────────────────────────────────────
TURNED_OUT = "turned_out"  # un moment qui n'a pas tourné comme elle l'attendait
LET_DOWN = "let_down"  # un moment attendu avec joie, qui n'aura pas lieu
FEAR_LIFTED = "fear_lifted"  # un moment redouté, qui n'aura pas lieu
LOOKING_FORWARD = "looking_forward"
DREADING = "dreading"

#: une de ses apps : ``forge:<app>``
FORGE_PREFIX = "forge:"
#: des codes nés ailleurs (les origines d'une pensée) qui se disent par la phrase d'une autre cause
ALIASES: Mapping[str, str] = MappingProxyType({"concern": WORRIED, "blocked": STUCK})
#: les phrases sous ``affect.cause`` qui ne sont pas des causes : ce que devient ``TALK``, une app, l'inconnu
NOT_CAUSES = frozenset({"talk_here", "talk_elsewhere", "forge", "unknown"})


def said_as(cause: str) -> str:
    """Le nom de la phrase (sous ``affect.cause``) qui dit cette cause : elle-même, sauf un alias ; une app se dit
    ``forge`` ; ``TALK`` se dit selon la personne (``affect`` le tranche)."""
    if cause.startswith(FORGE_PREFIX):
        return "forge"
    return ALIASES.get(cause, cause)

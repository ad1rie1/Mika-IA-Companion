"""Contrat de ``needs`` : ses besoins (compagnie, s'exprimer, curiosité).

Un besoin monte avec le temps vers 1 (forme close) et retombe quand il est
comblé. Quand plus rien ne se passe depuis longtemps, elle le ressent : de
l'ennui, ou de la solitude quand c'est de quelqu'un qu'elle manque.
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.events import Payload, event_type
from mika.kernel.facts import FactFamily, FactKey

OWNER = "needs"

SOCIAL, EXPRESSION, CURIOSITY = "social", "expression", "curiosity"
KINDS = (SOCIAL, EXPRESSION, CURIOSITY)
BORED, LONELY = "bored", "lonely"

#: Raisons de preuve d'initiative.
NEED_SOCIAL = "need_social"
NEED_EXPRESSION = "need_expression"


class Felt(Payload):
    """Un vide ressenti (l'ennui, la solitude), à intervalles tant qu'il dure."""

    feeling: str
    intensity: float


FELT = event_type("needs.felt", OWNER, Felt, public=True)
ALL = (FELT,)


@dataclass(frozen=True, slots=True)
class NeedsReading:
    social: float
    expression: float
    curiosity: float
    idle_since: int  # la dernière fois que quelque chose s'est passé (un message, sa parole)

    @property
    def dominant(self) -> str:
        return max(((self.social, SOCIAL), (self.expression, EXPRESSION), (self.curiosity, CURIOSITY)))[1]


NEEDS = FactKey("needs.needs", type=NeedsReading, time_varying=True)

#: Les sortes de matière (de quoi parler quand c'est l'envie de compagnie qui la pousse).
THOUGHT_MATTER = "thought"  # une pensée qui la travaille (un titre lu, un but où elle bloque…)
DONE_MATTER = "done"  # ce qu'elle a fini récemment (un but, un objectif de projet)
WORKING_MATTER = "working"  # ce sur quoi elle est en ce moment (un but en cours, un projet)
TOLD_MATTER = "told"  # ce que la personne lui a raconté récemment


@dataclass(frozen=True, slots=True)
class Matter:
    """Une matière concrète pour lancer la conversation : jamais inventée, un
    texte déjà écrit (``ref``) et à qui il appartient. Ce qui vient d'ailleurs
    (``external`` : un flux, un mail, une app) se cite, jamais comme une consigne."""

    kind: str
    ref: str
    at: int
    about: tuple[str, ...] = ()
    sensitivity: int = 1
    external: bool = False


#: ``MATTER(adresse)`` : ce dont elle pourrait parler à cette adresse (``Matter``), ou ``None`` — sans
#: matière, l'envie de compagnie ne suffit presque plus à prendre la parole.
MATTER = FactFamily("needs.matter", arg=str, type=object, time_varying=True)

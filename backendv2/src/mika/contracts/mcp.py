"""Contrat du plugin ``mcp`` : les outils venus d'ailleurs (ADR 0064).

Un appel qui demande un accord est un effet proposé (``mcp.call``) ; quand il a été exécuté, ce que le service a
rendu revient comme ``mcp.answered`` — un **contenu** (l'oubli l'atteint : il peut parler de la personne), jamais le
champ brut du résultat de l'effet. Tant qu'elle ne l'a pas dit à la personne, ``mcp.untold`` le dit vrai et une
initiative due peut partir (``service_answered``), comme un dessin prêt.
"""

from __future__ import annotations

from mika.contracts import memory as memory_c
from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily

OWNER = "mcp"
#: le lot de ses outils du web (le serveur système « web » du plugin ``web``, ADR 0066) : chercher, lire une page. Ses
#: projets et ses explorations l'ont en main comme ses autres outils (ADR 0105)
WEB_BUNDLE = "mcp.web"
#: la capacité : appeler un outil d'un serveur, après accord
CALL = "mcp.call"
#: la raison de l'initiative due : ce qu'un service a rendu (ou un accord refusé, expiré) est à dire
ANSWERED_REASON = "service_answered"
#: une réponse pas encore dite à la personne (la garde de l'initiative due)
UNTOLD = FactFamily("mcp.untold", arg=int, type=bool, doc="une réponse d'un service extérieur pas encore dite")


class Answered(Payload):
    """Ce qu'un service extérieur a rendu après accord (ou son échec)."""

    proposal: int
    ok: bool
    text: Content
    about: tuple[str, ...] = ()


ANSWERED = event_type("mcp.answered", OWNER, Answered, content=("text",), subjects=("about",))
#: ce qu'elle a consulté pendant qu'elle travaillait (ADR 0085) : un outil en lecture seule ouvert sur le monde
#: (une recherche, une page) — la forme commune des lectures, l'extrait borné et inerte ; jamais en conversation
CONSULTED = event_type("mcp.consulted", OWNER, memory_c.Reading, public=True, content=("title", "excerpt"))
ALL = (ANSWERED, CONSULTED)

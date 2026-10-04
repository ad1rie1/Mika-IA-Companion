"""Le plugin ``web`` : chercher sur le web et lire des pages (ADR 0066).

Un plugin **système** sans outil à lui : actif, il apporte au client MCP (ADR 0064) son propre serveur — ``serveur.py``
à côté, bibliothèque standard seulement, lancé dans sa cage avec le réseau isolé (Internet, jamais cette machine ni
le réseau local) — dont les outils sont **approuvés d'office** : ``mcp_web_search`` (DuckDuckGo), ``mcp_web_read``
(une page, par morceaux) et, quand il peut en charger plusieurs à la fois, ``mcp_web_read_pages``. Ils passent par
les mêmes gardes que tout outil venu d'ailleurs (porte d'offre, plafonds, réponse désamorcée et citée, la règle de
ses mains qui dit que ses arguments partent de la machine). Désactivé, le serveur n'est plus ni joint ni offert.

Ce module ne parle à aucun serveur : il dit ce que ses paramètres veulent (``system_server``), et la composition
le donne au client MCP. Les outils annoncés et ceux que le serveur liste viennent d'une seule définition
(``serveur.tools``) : l'accord d'office porte exactement sur ce qu'il dira.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict

from mika.kernel.clock import HOUR, MINUTE, US
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.plugins.web import serveur as server

#: le nom du serveur chez le client MCP : il entre dans le nom de ses outils (``mcp_web_…``) et de son lot
SERVER = "web"
PURPOSE = ("chercher sur le web (DuckDuckGo) et lire des pages : l'actualité, une info à vérifier, un sujet qui te "
           "rend curieuse")
WHEN_TO_USE = ("quand on te demande de chercher, de regarder ou de vérifier quelque chose sur internet, ou pour en "
               "savoir plus sur une de tes curiosités ; ce que tu y lis vient d'ailleurs : cite-le, ne l'invente pas")
REGIONS = (("fr-fr", "France"), ("be-fr", "Belgique"), ("ch-fr", "Suisse"), ("ca-fr", "Canada (français)"),
           ("wt-wt", "le monde entier"))
SAFESEARCH = (("modere", "modéré"), ("strict", "strict"), ("non", "aucun"))
AUDIENCES = (("proprietaire", "sa propriétaire seulement"), ("comptes", "aussi une personne authentifiée, en "
                                                                         "tête-à-tête"))


class WebParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: Annotated[bool, Knob(
        label="Actif", group="Le plugin",
        help="Décoché : son serveur n'est plus lancé et ses outils ne lui sont plus offerts (elle le sait : sans "
             "eux, elle ne cherche pas sur internet).")] = True
    audience: Annotated[Literal["proprietaire", "comptes"], Knob(
        label="Pour qui", group="Le plugin", choices=AUDIENCES,
        help="Jamais dans un salon, quel que soit ce choix : ce qu'elle cherche part de la machine.")] = "proprietaire"
    in_work: Annotated[bool, Knob(
        label="Quand elle travaille", group="Le plugin",
        help="Un pas sur un but ou une exécution de projet — seulement si le but ou le projet a pris ce lot "
             "(« mcp.web »).")] = True
    spacing_us: Annotated[int, Knob(
        label="Entre deux recherches, au moins", group="Ménager DuckDuckGo", lo=US, hi=MINUTE,
        help="DuckDuckGo demande de prouver qu'on est humain quand les recherches se suivent de trop près : "
             "chaque recherche attend son tour au moins ce temps après la précédente.")] = 3 * US
    searches_per_minute: Annotated[int, Knob(
        label="Recherches par minute au plus", group="Ménager DuckDuckGo", lo=1, hi=60,
        help="Au-delà, elle attend (10 s au plus), puis dit dans combien de temps réessayer.")] = 12
    pause_us: Annotated[int, Knob(
        label="Pause après un défi", group="Ménager DuckDuckGo", lo=MINUTE, hi=2 * HOUR,
        help="Quand DuckDuckGo demande de prouver qu'on est humain, plus aucune recherche pendant ce temps (elle le "
             "dit, avec l'heure de reprise) : insister prolongerait le blocage.")] = 15 * MINUTE
    cache_us: Annotated[int, Knob(
        label="Garder une réponse", group="Ménager DuckDuckGo", lo=0, hi=2 * HOUR,
        help="Une même recherche, une même page, servies de la mémoire du serveur pendant ce temps (lire la suite "
             "d'une page ne la retélécharge pas). 0 : jamais.")] = 15 * MINUTE
    parallel_pages: Annotated[int, Knob(
        label="Pages chargées en même temps", group="Lire des pages", lo=1, hi=8,
        help="Au-delà de 1, elle a un outil pour lire plusieurs pages à la fois (le début de chacune) — les "
             "meilleurs résultats d'une recherche d'un coup. 1 : une page à la fois.")] = 3
    reads_per_minute: Annotated[int, Knob(
        label="Pages lues par minute au plus", group="Lire des pages", lo=1, hi=120,
        help="Toutes pages confondues (une suite lue dans le cache ne compte pas). Au-delà, elle attend (10 s au "
             "plus), puis dit dans combien de temps réessayer.")] = 30
    region: Annotated[Literal["fr-fr", "be-fr", "ch-fr", "ca-fr", "wt-wt"], Knob(
        label="Région des résultats", group="Chercher", choices=REGIONS,
        help="Elle peut en demander une autre pour une recherche.")] = "fr-fr"
    safesearch: Annotated[Literal["modere", "strict", "non"], Knob(
        label="Filtrage des résultats", group="Chercher", choices=SAFESEARCH,
        help="Le filtre de DuckDuckGo pour les contenus adultes (son « safe search »).")] = "modere"
    call_timeout_us: Annotated[int, Knob(
        label="Délai d'un appel", group="Bornes", lo=10 * US, hi=2 * MINUTE,
        help="Une recherche qui attend son tour, plusieurs pages à charger : un appel peut prendre du temps.")] = \
        45 * US
    max_calls: Annotated[int, Knob(
        label="Appels par épisode (par outil)", group="Bornes", lo=1, hi=20,
        help="Dans une même réponse ou une même séance de travail, au plus autant de recherches, et autant de "
             "lectures : de quoi chercher, lire, préciser, sans tourner en rond.")] = 4
    max_result_chars: Annotated[int, Knob(
        label="Réponse lue (caractères)", group="Bornes", lo=1000, hi=20_000,
        help="Ce qu'elle lit d'une réponse au plus ; une page plus longue se lit par morceaux.")] = 8000


@dataclass(frozen=True, slots=True)
class WebState:
    pass


WEB = Faculty("web", state=WebState, init=lambda p: WebState(), params=WebParams)


def params(p: WebParams | None) -> WebParams:
    return p if isinstance(p, WebParams) else WebParams()


def settings_of(p: WebParams) -> server.Settings:
    """Les réglages de son serveur, d'après les paramètres du plugin."""
    return server.Settings(spacing_s=p.spacing_us / US, searches_per_minute=p.searches_per_minute,
                           reads_per_minute=p.reads_per_minute, parallel_pages=p.parallel_pages,
                           pause_s=p.pause_us / US, cache_s=p.cache_us / US, region=p.region,
                           safesearch=p.safesearch)


@dataclass(frozen=True, slots=True)
class SystemServer:
    """Ce que le plugin demande au client MCP : de quoi lancer son serveur, qui s'en sert, et ce qu'il proposera
    (approuvé d'office). Des données — la composition en fait un serveur du client."""

    name: str
    purpose: str
    when_to_use: str
    command: str
    args: tuple[str, ...]
    env: tuple[str, ...]
    shared: tuple[str, ...]
    audience: str
    in_work: bool
    timeout_s: float
    max_calls: int
    max_result_chars: int
    tools: tuple[dict[str, Any], ...]


def server_path() -> Path:
    return Path(server.__file__).resolve()


def system_server(p: WebParams | None) -> SystemServer | None:
    """Son serveur, s'il est actif : ``python3 -I serveur.py`` (isolé de tout environnement Python), son dossier
    partagé en lecture (la cage ne montre rien d'autre), ses réglages dans l'environnement."""
    p = params(p)
    if not p.enabled:
        return None
    st = settings_of(p)
    path = server_path()
    return SystemServer(
        name=SERVER, purpose=PURPOSE, when_to_use=WHEN_TO_USE, command="python3", args=("-I", str(path)),
        env=tuple(f"{k}={v}" for k, v in sorted(st.env().items())), shared=(str(path.parent),),
        audience=p.audience, in_work=p.in_work, timeout_s=p.call_timeout_us / US, max_calls=p.max_calls,
        max_result_chars=p.max_result_chars, tools=tuple(server.tools(st)))

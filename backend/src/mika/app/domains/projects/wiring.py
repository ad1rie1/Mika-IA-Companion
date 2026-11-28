"""Le câblage des projets (ADR 0031, 0183, 0289, 0310) : l'atelier de chaque projet (le port ``workshop`` : ses
dossiers sous ``ateliers/``, leur git, qu'il signe de son nom, et le jeton de leurs dépôts distants, lu dans leurs
réglages), l'hôte de leurs dépôts distants (le port ``repo_host`` : GitHub, lu par la console seulement) et les
images de leur documentation (le port ``project_docs`` : leurs octets hors du journal, sous ``documentation/``). Une
fois le noyau construit, le point MCP de leur documentation (``/mcp/moi``), pour qui présente un jeton de compte
(``bind``).
"""

from __future__ import annotations

from starlette.routing import Mount

from mika.adapters.shares import DiskShares
from mika.adapters.workshop import BwrapWorkshop
from mika.adapters.workshop.github import GitHubRepos
from mika.app.domains.projects.docs_mcp import PREFIX as DOCS_MCP_PREFIX
from mika.app.domains.projects.docs_mcp import DocsPoint
from mika.app.domains.projects.settings import ProjectsSettings
from mika.app.wiring import Wiring
from mika.faculties.projects.docs import PORT as PROJECT_DOCS_PORT


def wire(w: Wiring) -> None:
    """Avant le noyau : l'atelier, l'hôte des dépôts distants, les images de la documentation."""
    settings = w.settings.of(ProjectsSettings)
    w.ports["workshop"] = BwrapWorkshop(w.data / "ateliers", credentials=settings.git, author=w.her)
    # l'hôte GitHub d'un dépôt distant, lu par la console seulement (ADR 0183)
    w.ports["repo_host"] = GitHubRepos(settings.git)
    # les images de la documentation de ses projets (ADR 0289) : leurs octets hors du journal, sauvegardés de même
    w.ports[PROJECT_DOCS_PORT] = DiskShares(w.data / "documentation")


def bind(w: Wiring) -> None:
    """Une fois le noyau construit : la documentation de ses projets, par MCP, pour qui présente un jeton de compte
    (ADR 0289)."""
    w.routes.append(Mount(DOCS_MCP_PREFIX, app=DocsPoint(w.port.kernel, w.live.accounts).app()))

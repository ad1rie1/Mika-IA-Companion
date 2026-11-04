"""L'aperçu de la console : le dépôt git d'un projet face à son dépôt distant (ADR 0183), sans réseau.

Le projet reçoit un dépôt distant GitHub fictif et trois commits dans son atelier, dont le dernier n'est pas encore
poussé ; un hôte de démonstration tient lieu de GitHub (la tête de la branche, deux issues, deux pull requests). La
page se voit pleine, et rien ne sort de la machine."""

from __future__ import annotations

from typing import Any

from mika.ports.workshop import Commit, Hosted, Ticket
from mika.runtime.operations import perform

URL = "https://github.com/exemple/outils-reseau.git"
PAGE = "https://github.com/exemple/outils-reseau"
#: ce qu'elle écrit dans l'atelier, un commit chacun (le dernier reste à pousser)
WORK = (("README.md", "# Outils réseau\n\nUn petit outillage d'administration.\n", "exécution 1 · objectif n° 1"),
        ("rdp/module.py", "def connect(host: str) -> None:\n    ...\n", "exécution 2 · objectif n° 1"),
        ("docs/rdp.md", "# Le module RDP\n\nComment s'en servir.\n", "exécution 3 · objectif n° 2"))
HOUR = 3_600_000_000


class DemoHost:
    """Un hôte de démonstration (le port ``RepoHost``) : il rend toujours la même lecture."""

    def __init__(self, hosted: Hosted) -> None:
        self.hosted = hosted

    def handles(self, url: str) -> bool:
        return url == URL

    async def read(self, url: str, branch: str, *, fresh: bool = False, since: int = 0) -> Hosted:
        return self.hosted

    async def compare(self, url: str, base: str, head: str) -> tuple[int, int] | None:
        return None


async def repository(kernel: Any, key: str, now: int) -> None:
    """Le dépôt distant du projet, son travail enregistré, et l'hôte qui le montre."""
    port = kernel.ports.get("workshop")
    if not key or port is None:
        return
    await perform(kernel, "projects.depot_distant", {"_champs": ["remote", "branch", "auto_push"], "remote": [URL],
                                                     "branch": ["main"]}, by="user_1", subject=key,
                  nonce="apercu-depot")
    pid = int(key)
    for path, text, message in WORK:
        await port.write(pid, path, text)
        await port.commit(pid, message)
    local = await port.commits(pid, 10)
    pushed = local[1:]  # le distant a tout, sauf le dernier
    if not pushed:
        return
    hosted = Hosted(
        name="exemple/outils-reseau", url=PAGE, branch="main", about="Un petit outillage d'administration.",
        head=pushed[0].sha, read_at=now - 2 * 60_000_000,
        commits=tuple(Commit(k.sha, k.at, k.title, "mika-atelier") for k in pushed),
        issues=(Ticket(14, "Le module RDP ne gère pas les écrans multiples", f"{PAGE}/issues/14", "adrien",
                       now - 3 * HOUR, ("bug", "rdp"), 2),
                Ticket(9, "Documenter les options de connexion", f"{PAGE}/issues/9", "bea", now - 50 * HOUR,
                       ("documentation",), 0)),
        pulls=(Ticket(15, "Écrans multiples pour le module RDP", f"{PAGE}/pull/15", "adrien", now - HOUR, (), 0,
                      "rdp-ecrans", "main", draft=True),
               Ticket(12, "Exemples dans la documentation", f"{PAGE}/pull/12", "bea", now - 26 * HOUR,
                      ("documentation",), 0, "docs-exemples", "main")),
        open_issues=2, open_pulls=2)
    kernel.ports["repo_host"] = DemoHost(hosted)

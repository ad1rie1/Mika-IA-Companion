"""Réglages › Connexions extérieures : ses dépôts Git."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, field_validator

from mika.app.settings_sections.common import tolerant
from mika.inspector.catalog import SettingsPage, SettingsSection
from mika.inspector.ui import PREFIX
from mika.kernel.forms import Knob
from mika.kernel.inspect import Ref

if TYPE_CHECKING:
    from mika.app.server import Live

#: un hôte seul (github.com, git.exemple.org:8443) : ni schéma, ni chemin, ni espace
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+(?::[0-9]{1,5})?")


class GitSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    token: Annotated[str, Knob(label="Jeton", help="Un jeton d'accès personnel (GitHub : « fine-grained », droits "
                                                   "« Contents : Read and write » sur les dépôts de ses projets). "
                               "Chiffré, jamais réaffiché, jamais dans le journal ni dans ce qu'elle lit. Vide : "
                               "inchangé.", secret=True, advanced=False, order=10)] = ""
    hosts: Annotated[tuple[str, ...], Knob(
        label="Hôtes autorisés", help="Un hôte par ligne (github.com). Le jeton n'est montré qu'à eux : un projet "
                                      "réglé sur un autre hôte ne l'envoie pas.", advanced=False, order=15)] = \
        ("github.com",)
    user: Annotated[str, Knob(label="Utilisateur", help="Le nom qui accompagne le jeton ; « x-access-token » convient "
                                                        "à GitHub.", order=20)] = "x-access-token"

    @field_validator("hosts")
    @classmethod
    def _hosts(cls, hosts: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(dict.fromkeys(h.strip().lower() for h in hosts if h.strip()))
        bad = [h for h in cleaned if not _HOST.fullmatch(h)]
        if bad:
            raise ValueError(f"« {bad[0][:80]} » n'est pas un hôte : écris-le seul, sans « https:// » ni chemin "
                             "(github.com)")
        return cleaned

    @field_validator("user")
    @classmethod
    def _user(cls, user: str) -> str:
        user = user.strip()
        if not user or any(c.isspace() or c in ":@/" for c in user):
            raise ValueError("un nom sans espace ni « : @ / » (« x-access-token » pour GitHub)")
        return user


def sections(live: Live) -> tuple[SettingsSection, ...]:
    settings = live.settings

    def git() -> GitSettings:
        got = settings.git()
        return tolerant(GitSettings, token=got["token"], user=got["user"], hosts=tuple(got["hosts"]))

    async def save_git(cfg: GitSettings) -> list[str]:
        await settings.save_git(cfg.token, cfg.user, list(cfg.hosts))
        return []

    return (
        # joint par Connexions extérieures, où son lien est dans le menu (ADR 0197)
        SettingsSection("depots", "Dépôts Git", "connexions", GitSettings, git, save_git,
                        description="Le jeton avec lequel ses projets poussent vers leur dépôt distant.",
                        facts=lambda: [("Jeton", "défini" if settings.git()["token"] else "aucun"),
                                       ("L'adresse de chaque dépôt", Ref("local", f"{PREFIX}/projets",
                                                                         "sur la fiche de son projet"))],
                        pages=(SettingsPage("depots", "Dépôts Git", description=(
                            "Le jeton avec lequel l'atelier d'un projet pousse vers son dépôt distant (GitHub ou un "
                            "autre hôte https) et en récupère l'histoire ; l'adresse du dépôt se règle sur la fiche "
                            "du projet. Le jeton ne passe que par l'environnement de git, limité à l'hôte du "
                            "dépôt.")),)),
    )

"""Ce que Teams partage (ADR 0188, 0310) : ses comptes — sa part des partages (``app/me/sharing.py``).

Un compte partagé est rangé avec sa ressource (``TeamsAccount.shares``) et journalisé avec ses paramètres
(``shares``) : sa règle s'étend à la personne, au niveau donné (lire ; lire et préparer ; s'en servir). Seul son
propriétaire le partage ; l'opérateur qui retire un partage dans Réglages › Droits › Partages le range par la même
écriture (``write``, ADR 0210).

Un compte est une ressource rangée dans les réglages avec ses partages (``app/me/sharing.py::kept_in_settings``) :
ce module ne dit que ses mots, comment lire et récrire ses comptes, à qui en est un, et qui le partage.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mika.adapters.teams import TeamsAccount, TeamsConfig
from mika.app.domains.teams import api as teams_me
from mika.app.me.sharing import Shared, kept_in_settings
from mika.plugins import teams as teams_p


def _config(settings: Any) -> TeamsConfig:
    """Ses comptes, tels que les réglages les tiennent (avec le reste de ce qui est réglé de Teams)."""
    return settings.named("teams").teams()


async def _save(settings: Any, cfg: TeamsConfig, accounts: dict[str, TeamsAccount]) -> None:
    """Ses comptes récrits, un changé, le reste de ce qui est réglé de Teams gardé tel quel."""
    await settings.named("teams").save_teams(cfg.model_copy(update={"accounts": accounts}))


def sharer(frame: Any, s: Shared, name: Callable[[str], str]) -> str:
    """Qui partage un compte Teams : qui y écrit."""
    return teams_p.writer_of(frame, s.key)


SHARING = kept_in_settings("teams", word="compte Teams", article="le ", config=_config, account=TeamsAccount, save=_save,
                           owned=teams_me.owned, sharer=sharer)

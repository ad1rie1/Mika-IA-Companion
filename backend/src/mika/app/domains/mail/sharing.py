"""Ce que le courrier partage (ADR 0188, 0310) : ses boîtes — sa part des partages (``app/me/sharing.py``).

Une boîte partagée est rangée avec sa ressource (``MailAccount.shares``) et journalisée avec ses paramètres
(``shares``) : sa règle s'étend à la personne, au niveau donné (lire ; lire et préparer ; s'en servir). Seul son
propriétaire la partage ; l'opérateur qui retire un partage dans Réglages › Droits › Partages le range par la même
écriture (``write``, ADR 0210).

Une boîte est une ressource rangée dans les réglages avec ses partages (``app/me/sharing.py::kept_in_settings``) :
ce module ne dit que ses mots, comment lire et récrire ses boîtes, à qui en est une, et qui la partage.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mika.adapters.mail.config import MailAccount, MailConfig
from mika.app.domains.mail import api as mail_me
from mika.app.me.sharing import Shared, kept_in_settings
from mika.plugins import email as email_p


def _config(settings: Any) -> MailConfig:
    """Ses boîtes, telles que les réglages les tiennent."""
    return settings.named("mail").email()


async def _save(settings: Any, cfg: MailConfig, accounts: dict[str, MailAccount]) -> None:
    """Ses boîtes récrites, une changée (``MailSettings.save_email`` : l'application Microsoft, gardée à part, ne s'y
    lit ni ne s'y écrit)."""
    await settings.named("mail").save_email(MailConfig(accounts=accounts))


def sharer(frame: Any, s: Shared, name: Callable[[str], str]) -> str:
    """Qui partage une boîte : qui en décide."""
    return email_p.approver_name(frame, s.key)


SHARING = kept_in_settings("mail", word="boîte", article="la ", config=_config, account=MailAccount, save=_save,
                           owned=mail_me.owned, sharer=sharer)

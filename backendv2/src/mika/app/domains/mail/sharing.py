"""Ce que le courrier partage (ADR 0188, 0310) : ses boîtes — sa part des partages (``app/me/sharing.py``).

Une boîte partagée est rangée avec sa ressource (``MailAccount.shares``) et journalisée avec ses paramètres
(``shares``) : sa règle s'étend à la personne, au niveau donné (lire ; lire et préparer ; s'en servir). Seul son
propriétaire la partage ; l'opérateur qui retire un partage dans Réglages › Droits › Partages le range par la même
écriture (``write``, ADR 0210).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import ValidationError

from mika.adapters.mail.config import MailAccount, MailConfig
from mika.app.domains.domain import SharingPart
from mika.app.domains.mail import api as mail_me
from mika.app.me.api import Call, missing, refused
from mika.app.me.sharing import Shared, not_hers_already
from mika.plugins import email as email_p
from mika.vocab.access import PERSON


def every(settings: Any, names: Mapping[str, str] | None = None) -> list[Shared]:
    """Ses partages, boîte par boîte : ceux rangés avec chacune."""
    out: list[Shared] = []
    for key, spec in sorted(settings.named("mail").email().accounts.items()):
        out += [Shared("mail", key, spec.label or key, spec.owner, who[len(PERSON):], level)
                for who, level in sorted(spec.shares.items())]
    return out


async def share(call: Call, settings: Any, key: str, person: str, level: str) -> None:
    """Son propriétaire partage une de ses boîtes : elle est à lui, et pas déjà à cette personne — jugé sur sa fiche
    relue sous le verrou des réglages."""
    def hers(spec: Any) -> None:
        mail_me.owned(call, key)
        not_hers_already(call, spec.owner, person, level)

    await write(settings, call.api.reconfigure, key, person, level, hers)


async def write(settings: Any, reconfigure: Callable[[], Awaitable[Any]] | None, key: str, person: str, level: str,
                check: Callable[[Any], None] | None = None) -> None:
    """Le partage d'une boîte à cette personne, à ce niveau (vide : retiré). Relus puis réécrits d'un seul tenant
    (``Settings.writing``), avec ce qui en dérive (``shares``, rejournalisé : sa règle s'étend) : un partage retiré
    ailleurs entre-temps ne revient pas. ``check`` juge la fiche relue, sous le verrou : qui a le droit, c'est à qui
    appelle de le dire."""
    async with settings.writing:
        cfg = settings.named("mail").email()
        spec = cfg.accounts.get(key)
        if spec is None:
            raise missing()
        if check is not None:
            check(spec)
        who = PERSON + person
        shares = {k: v for k, v in spec.shares.items() if k != who} | ({who: level} if level else {})
        try:
            await settings.named("mail").save_email(MailConfig(accounts={**cfg.accounts, key: MailAccount.model_validate(
                {**spec.model_dump(), "shares": shares})}))
        except ValidationError as exc:
            raise refused(exc) from None
        if reconfigure is not None:
            await reconfigure()


def sharer(frame: Any, s: Shared, name: Callable[[str], str]) -> str:
    """Qui partage une boîte : qui en décide."""
    return email_p.approver_name(frame, s.key)


SHARING = SharingPart("mail", every=every, share=share, write=write, sharer=sharer, word="boîte", article="la ")

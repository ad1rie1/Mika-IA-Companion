"""Ce que Teams partage (ADR 0188, 0310) : ses comptes — sa part des partages (``app/me/sharing.py``).

Un compte partagé est rangé avec sa ressource (``TeamsAccount.shares``) et journalisé avec ses paramètres
(``shares``) : sa règle s'étend à la personne, au niveau donné (lire ; lire et préparer ; s'en servir). Seul son
propriétaire le partage ; l'opérateur qui retire un partage dans Réglages › Droits › Partages le range par la même
écriture (``write``, ADR 0210).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import ValidationError

from mika.adapters.teams import TeamsAccount
from mika.app.domains.domain import SharingPart
from mika.app.domains.teams import api as teams_me
from mika.app.me.api import Call, missing, refused
from mika.app.me.sharing import Shared, not_hers_already
from mika.plugins import teams as teams_p
from mika.vocab.access import PERSON


def every(settings: Any, names: Mapping[str, str] | None = None) -> list[Shared]:
    """Ses partages, compte par compte : ceux rangés avec chacun."""
    out: list[Shared] = []
    for key, spec in sorted(settings.named("teams").teams().accounts.items()):
        out += [Shared("teams", key, spec.label or key, spec.owner, who[len(PERSON):], level)
                for who, level in sorted(spec.shares.items())]
    return out


async def share(call: Call, settings: Any, key: str, person: str, level: str) -> None:
    """Son propriétaire partage un de ses comptes : il est à lui, et pas déjà à cette personne — jugé sur sa fiche
    relue sous le verrou des réglages."""
    def hers(spec: Any) -> None:
        teams_me.owned(call, key)
        not_hers_already(call, spec.owner, person, level)

    await write(settings, call.api.reconfigure, key, person, level, hers)


async def write(settings: Any, reconfigure: Callable[[], Awaitable[Any]] | None, key: str, person: str, level: str,
                check: Callable[[Any], None] | None = None) -> None:
    """Le partage d'un compte Teams à cette personne, à ce niveau (vide : retiré). Relus puis réécrits d'un seul tenant
    (``Settings.writing``), avec ce qui en dérive (``shares``, rejournalisé : sa règle s'étend) : un partage retiré
    ailleurs entre-temps ne revient pas. ``check`` juge la fiche relue, sous le verrou : qui a le droit, c'est à qui
    appelle de le dire."""
    async with settings.writing:
        cfg = settings.named("teams").teams()
        spec = cfg.accounts.get(key)
        if spec is None:
            raise missing()
        if check is not None:
            check(spec)
        who = PERSON + person
        shares = {k: v for k, v in spec.shares.items() if k != who} | ({who: level} if level else {})
        try:
            account = TeamsAccount.model_validate({**spec.model_dump(), "shares": shares})
            await settings.named("teams").save_teams(cfg.model_copy(update={"accounts": {**cfg.accounts, key: account}}))
        except ValidationError as exc:
            raise refused(exc) from None
        if reconfigure is not None:
            await reconfigure()


def sharer(frame: Any, s: Shared, name: Callable[[str], str]) -> str:
    """Qui partage un compte Teams : qui y écrit."""
    return teams_p.writer_of(frame, s.key)


SHARING = SharingPart("teams", every=every, share=share, write=write, sharer=sharer, word="compte Teams")

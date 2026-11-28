"""Ce que l'agenda partage (ADR 0188, 0309, 0310) : ses agendas — sa part des partages (``app/me/sharing.py``).

Un agenda partagé est rangé avec son agenda (``AgendaSettings.share_calendar``) et journalisé avec les paramètres du
plugin ``agenda`` ; son tableau de droits reçoit ou perd la ligne de la personne. Seul son propriétaire le partage ;
l'opérateur qui retire un partage dans Réglages › Droits › Partages le range par la même écriture (``write``). Son
nom est celui que dit la base de l'agenda (``names_of``), lu avant ses partages ; sinon, sa clé courte.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import ValidationError

from mika.app.domains.agenda.reach import calendar_names, holder_person, mine
from mika.app.domains.domain import SharingPart
from mika.app.me.api import Call, Denied, missing, refused
from mika.app.me.sharing import Shared, not_hers_already
from mika.contracts import identity as identity_c
from mika.plugins import agenda as agenda_p
from mika.ports.agenda import split_calendar_key, system_person
from mika.vocab.access import PERSON
from mika.vocab.ownership import OWNED


def names_of(port: Callable[[str], Any]) -> dict[str, str]:
    """Le nom de chaque agenda, tel que sa base le dit (``port`` : un port du noyau, par son nom)."""
    return calendar_names(port("agenda"))


def every(settings: Any, names: Mapping[str, str] | None = None) -> list[Shared]:
    """Ses partages, agenda par agenda, compte par compte (``names`` : leur nom, tel que la base de l'agenda le dit,
    ``names_of`` ; sinon sa clé courte)."""
    out: list[Shared] = []
    for account, spec in sorted(settings.named("agenda").agenda().accounts.items()):
        holder = PERSON + system_person(account) if system_person(account) else spec.owner
        for local, setting in sorted(spec.calendars.items()):
            calendar = f"{account}~{local}"
            out += [Shared("agenda", calendar, (names or {}).get(calendar) or local, holder, who[len(PERSON):], level)
                    for who, level in sorted(setting.shares.items())]
    return out


async def share(call: Call, settings: Any, key: str, person: str, level: str) -> None:
    """Son propriétaire partage un de ses agendas : il est à lui, et pas déjà à cette personne."""
    cal, held_level = mine(call).get(key) or (None, "")
    if cal is None:
        raise missing()
    if held_level != OWNED:
        raise Denied(403, "Seul son propriétaire partage cet agenda.")  # comme une boîte qu'on te partage
    holder = holder_person(agenda_p.params_of(call.frame), key)

    def calendar_hers(spec: Any) -> None:
        not_hers_already(call, holder, person, level)

    await write(settings, call.api.reconfigure, key, person, level, calendar_hers)


async def write(settings: Any, reconfigure: Callable[[], Awaitable[Any]] | None, calendar: str, person: str,
                level: str, check: Callable[[Any], None] | None) -> None:
    """Le partage d'un agenda à cette personne (vide : retiré), rangé avec l'agenda (``AgendaSettings.share_calendar`` : son
    tableau suit), relu puis réécrit sous ``Settings.writing`` ; ``check`` juge son réglage relu (``CalendarSetting``),
    sous le verrou."""
    account, local = split_calendar_key(calendar)
    async with settings.writing:
        found = settings.named("agenda").agenda().account(account) if account else None
        if found is None:
            raise missing()
        if check is not None:
            check(found.setting(local))
        try:
            await settings.named("agenda").share_calendar(calendar, PERSON + person, level or None)
        except (ValidationError, ValueError) as exc:
            raise refused(exc) from None
        if reconfigure is not None:
            await reconfigure()


def sharer(frame: Any, s: Shared, name: Callable[[str], str]) -> str:
    """Qui partage un agenda : ses propriétaires, pour un agenda « à toi » ; sinon son propriétaire, par son nom."""
    if not s.owner:
        return identity_c.keepers(frame)
    return name(s.owner.removeprefix(PERSON))


SHARING = SharingPart("agenda", every=every, share=share, write=write, sharer=sharer, key_limit=200, names=names_of,
                      word="agenda", article="l'")

"""Ce que la console change d'un compte d'agenda dans les réglages (ADR 0309, lot 5) : le port ``agenda_desk``
(``ports/agenda.py::AgendaDesk``), que les actions du plugin ``agenda`` appellent depuis la fiche d'un agenda.

- **Décocher, recocher un compte** (``enable``) : décoché, il ne se synchronise plus et Mika ne s'en sert plus ; ce
  qui est gardé reste, figé (« Déconnecter » un compte CalDAV ou un abonnement).
- **Suivre ou ne plus suivre un agenda** (``follow``) : ne plus le suivre retire sa copie de Mika, rien chez son
  fournisseur (« Supprimer de Mika ») ; ``None`` revient à ce que le fournisseur coche.
- **Oublier la connexion** d'un compte Google ou Microsoft (``disconnect``) : retirée chez Google, oubliée ici ; le
  compte reste, « à reconnecter » (« Déconnecter », le geste du lot 4 dans l'espace de la personne).

Jamais une écriture dans un agenda : la console ne crée, ne modifie ni ne répond à la place de personne. Chaque
changement s'écrit sous le verrou des réglages, puis les paramètres du plugin se rejournalisent (``reconfigure``,
posé par le serveur une fois l'état vivant construit) : ce que Mika en fait se relit tel qu'il était.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from mika.adapters.agenda import AgendaConfig
from mika.ports.agenda import GOOGLE, MICROSOFT, AgendaError, split_calendar_key

log = logging.getLogger("mika.agenda")


class AgendaSettingsDesk:
    """Le port ``agenda_desk`` : les réglages des comptes d'agenda, et les fournisseurs (leurs connexions)."""

    def __init__(self, settings: Any, providers: Any) -> None:
        self.settings = settings
        self.providers = providers
        #: rejournalise les paramètres des facultés (``Live.reconfigure``), posé par le serveur
        self.reconfigure: Callable[[], Awaitable[Any]] | None = None

    async def _save(self, cfg: AgendaConfig) -> None:
        await self.settings.save_agenda(cfg)
        if self.reconfigure is not None:
            await self.reconfigure()

    async def enable(self, account: str, enabled: bool) -> bool:
        async with self.settings.writing:
            cfg = self.settings.agenda()
            found = cfg.accounts.get(account)
            if found is None:
                raise ValueError(f"compte d'agenda inconnu : « {account[:60]} »")
            if found.enabled == enabled:
                return False
            await self._save(cfg.model_copy(update={"accounts": {
                **cfg.accounts, account: found.model_copy(update={"enabled": enabled})}}))
        return True

    async def follow(self, calendar: str, followed: bool | None) -> bool:
        account, local = split_calendar_key(calendar)
        async with self.settings.writing:
            cfg = self.settings.agenda()
            found = cfg.accounts.get(account) if account else None
            if found is None:
                raise ValueError(f"agenda inconnu : « {calendar[:60]} »")
            setting = found.setting(local)
            if setting.followed == followed:
                return False
            changed = found.model_copy(update={"calendars": {
                **found.calendars, local: setting.model_copy(update={"followed": followed})}})
            await self._save(cfg.model_copy(update={"accounts": {**cfg.accounts, account: changed}}))
        return True

    async def disconnect(self, account: str) -> bool:
        found = self.settings.agenda().accounts.get(account)
        if found is None or found.kind not in (GOOGLE, MICROSOFT):
            raise ValueError(f"pas un compte Google ou Microsoft : « {account[:60]} »")
        signin = getattr(self.providers.of(found.kind), "signin", None)
        if signin is not None:
            if found.kind == GOOGLE:
                try:
                    await signin.revoke(account)
                except (AgendaError, OSError, RuntimeError, ValueError) as exc:
                    log.info("agenda : la connexion Google de %s n'a pas pu être retirée chez Google : %s",
                             account[:60], exc)
            signin.drop(account)
        return bool(await self.settings.drop_agenda_grant(account))


__all__ = ["AgendaSettingsDesk"]
